"""
Simple "agentic" news workflow: perceive (RSS) → select (top stories) → act (LLM) → deliver (HTML).

Configuration:
- Preferred: config/settings.json (create from config/settings.example.json) — feeds, prompts, provider.
- Secrets: .env — OPENAI_API_KEY, ANTHROPIC_API_KEY (never store keys in JSON).

Run CLI: python news_agent.py
Run web:  python web_app.py
"""

from __future__ import annotations

import html
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import feedparser
from dotenv import load_dotenv
from openai import NotFoundError, OpenAI


# ---------------------------------------------------------------------------
# Paths & defaults
# ---------------------------------------------------------------------------

DEFAULT_RSS_FEEDS = [
    "http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/front_page/rss.xml",
    "http://rss.cnn.com/rss/cnn_topstories.rss",
]

TOP_N_STORIES = 8
DEFAULT_OUTPUT_HTML = "output/briefing.html"
SETTINGS_PATH = Path(os.getenv("NEWS_AGENT_SETTINGS", "config/settings.json"))
SETTINGS_EXAMPLE_PATH = Path("config/settings.example.json")

OLLAMA_OPENAI_BASE_URL = "http://localhost:11434/v1"
OLLAMA_DEFAULT_MODEL = "llama3"
OLLAMA_PLACEHOLDER_API_KEY = "ollama"

DEFAULT_SYSTEM_PROMPT = (
    "You are a careful news assistant. Be factual; do not invent events. "
    "If the snippets are thin, say what is unknown."
)

DEFAULT_USER_PROMPT_TEMPLATE = (
    "Here are the latest headlines with links and short blurbs from RSS.\n"
    "Write a concise briefing: bullet list of themes, 2–3 sentences per major theme,\n"
    "mention which story/link supports each point when useful.\n\n"
    "{stories}"
)


def _env_truthy(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _llm_provider_from_env() -> str:
    p = os.getenv("LLM_PROVIDER", "").strip().lower()
    if p in ("openai", "ollama", "claude"):
        return p
    backend = os.getenv("LLM_BACKEND", "").strip().lower()
    if backend == "ollama":
        return "ollama"
    if backend == "claude":
        return "claude"
    if backend == "openai":
        return "openai"
    if backend:
        raise ValueError(f"Unknown LLM_BACKEND={backend!r}; use openai, ollama, or claude.")
    if _env_truthy("USE_OLLAMA"):
        return "ollama"
    return "openai"


@dataclass(frozen=True)
class Settings:
    rss_urls: list[str]
    top_n: int
    llm_provider: str
    model: str
    openai_api_key: str
    openai_base_url: str | None
    anthropic_api_key: str
    output_html: str
    system_prompt: str
    user_prompt_template: str


def _load_json_settings() -> dict[str, Any] | None:
    if not SETTINGS_PATH.is_file():
        return None
    raw = SETTINGS_PATH.read_text(encoding="utf-8")
    return json.loads(raw)


def default_settings_dict() -> dict[str, Any]:
    """Defaults for new installs and the web UI."""
    return {
        "llm_provider": "openai",
        "model": "gpt-4o-mini",
        "openai_base_url": "",
        "rss_feeds": list(DEFAULT_RSS_FEEDS),
        "top_n": TOP_N_STORIES,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "user_prompt_template": DEFAULT_USER_PROMPT_TEMPLATE,
        "output_html": DEFAULT_OUTPUT_HTML,
    }


def merge_settings_dict(base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for k, v in overlay.items():
        if v is not None:
            out[k] = v
    return out


def _env_settings_overlay() -> dict[str, Any]:
    """When no settings.json exists, mirror legacy .env configuration."""
    overlay: dict[str, Any] = {"llm_provider": _llm_provider_from_env()}
    feeds = os.getenv("RSS_FEEDS", "").strip()
    if feeds:
        overlay["rss_feeds"] = [u.strip() for u in feeds.split(",") if u.strip()]
    if os.getenv("TOP_N_STORIES", "").strip():
        overlay["top_n"] = int(os.getenv("TOP_N_STORIES", "8"))
    if os.getenv("OPENAI_MODEL", "").strip():
        overlay["model"] = os.getenv("OPENAI_MODEL", "").strip()
    if os.getenv("OPENAI_BASE_URL", "").strip():
        overlay["openai_base_url"] = os.getenv("OPENAI_BASE_URL", "").strip()
    if os.getenv("OUTPUT_HTML", "").strip():
        overlay["output_html"] = os.getenv("OUTPUT_HTML", "").strip()
    if os.getenv("SYSTEM_PROMPT", "").strip():
        overlay["system_prompt"] = os.getenv("SYSTEM_PROMPT", "").strip()
    if os.getenv("USER_PROMPT_TEMPLATE", "").strip():
        overlay["user_prompt_template"] = os.getenv("USER_PROMPT_TEMPLATE", "").strip()
    return overlay


def load_settings() -> Settings:
    """Load config/settings.json if present; merge with .env for API keys and env-only overrides."""
    load_dotenv()
    data = default_settings_dict()
    file_data = _load_json_settings()
    if file_data:
        data = merge_settings_dict(data, file_data)
    else:
        data = merge_settings_dict(data, _env_settings_overlay())

    rss = data.get("rss_feeds") or list(DEFAULT_RSS_FEEDS)
    if isinstance(rss, str):
        rss = [u.strip() for u in rss.replace(",", "\n").splitlines() if u.strip()]
    else:
        rss = [str(u).strip() for u in rss if str(u).strip()]

    top_n = int(data.get("top_n", TOP_N_STORIES))
    output_html = str(data.get("output_html", DEFAULT_OUTPUT_HTML)).strip() or DEFAULT_OUTPUT_HTML
    system_prompt = str(data.get("system_prompt", DEFAULT_SYSTEM_PROMPT)).strip() or DEFAULT_SYSTEM_PROMPT
    user_prompt_template = (
        str(data.get("user_prompt_template", DEFAULT_USER_PROMPT_TEMPLATE)).strip() or DEFAULT_USER_PROMPT_TEMPLATE
    )

    provider = str(data.get("llm_provider", _llm_provider_from_env())).strip().lower()
    if provider not in ("openai", "ollama", "claude"):
        raise ValueError(f"Unknown llm_provider={provider!r}; use openai, ollama, or claude.")

    model_raw = str(data.get("model", "")).strip()
    openai_base_raw = str(data.get("openai_base_url", "")).strip()

    openai_key = os.getenv("OPENAI_API_KEY", "").strip()
    anthropic_key = os.getenv("ANTHROPIC_API_KEY", "").strip()

    if provider == "ollama":
        model = model_raw or OLLAMA_DEFAULT_MODEL
        base_url = openai_base_raw or OLLAMA_OPENAI_BASE_URL
        api_key = openai_key or OLLAMA_PLACEHOLDER_API_KEY
    elif provider == "openai":
        model = model_raw or "gpt-4o-mini"
        base_url = openai_base_raw or None
        api_key = openai_key
    else:
        model = model_raw or "claude-3-5-haiku-20241022"
        base_url = None
        api_key = openai_key

    return Settings(
        rss_urls=rss,
        top_n=top_n,
        llm_provider=provider,
        model=model,
        openai_api_key=api_key,
        openai_base_url=base_url,
        anthropic_api_key=anthropic_key,
        output_html=output_html,
        system_prompt=system_prompt,
        user_prompt_template=user_prompt_template,
    )


def settings_dict_for_ui() -> dict[str, Any]:
    """Data for the web form (no secrets)."""
    base = default_settings_dict()
    file_data = _load_json_settings()
    if file_data:
        return merge_settings_dict(base, file_data)
    return merge_settings_dict(base, _env_settings_overlay())


# ---------------------------------------------------------------------------
# Step 1 — RSS
# ---------------------------------------------------------------------------


@dataclass
class Story:
    title: str
    link: str
    summary: str
    published: datetime | None


def _parse_published(entry: Any) -> datetime | None:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        t = entry.published_parsed
        try:
            return datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    if hasattr(entry, "updated_parsed") and entry.updated_parsed:
        t = entry.updated_parsed
        try:
            return datetime(t.tm_year, t.tm_mon, t.tm_mday, t.tm_hour, t.tm_min, t.tm_sec, tzinfo=timezone.utc)
        except (TypeError, ValueError):
            pass
    return None


def fetch_stories_from_feed(url: str) -> list[Story]:
    parsed = feedparser.parse(url)
    if not parsed.entries:
        exc = getattr(parsed, "bozo_exception", None)
        detail = f" ({exc})" if exc else ""
        raise RuntimeError(f"No entries from feed {url!r}{detail}")

    out: list[Story] = []
    for entry in parsed.entries:
        title = (entry.get("title") or "").strip()
        link = (entry.get("link") or "").strip()
        summary = (entry.get("summary") or entry.get("description") or "").strip()
        summary = summary.replace("<![CDATA[", "").replace("]]>", "")
        if not title:
            continue
        out.append(Story(title=title, link=link, summary=summary, published=_parse_published(entry)))
    return out


def fetch_all_stories(urls: list[str]) -> list[Story]:
    all_stories: list[Story] = []
    for url in urls:
        try:
            all_stories.extend(fetch_stories_from_feed(url))
        except RuntimeError as err:
            print(f"Warning: {err}", file=sys.stderr)
    return all_stories


# ---------------------------------------------------------------------------
# Step 2 — Select
# ---------------------------------------------------------------------------


def select_top_stories(stories: list[Story], n: int) -> list[Story]:
    def sort_key(s: Story) -> datetime:
        return s.published or datetime.min.replace(tzinfo=timezone.utc)

    sorted_stories = sorted(stories, key=sort_key, reverse=True)
    return sorted_stories[:n]


# ---------------------------------------------------------------------------
# Step 3 — Prompts & LLM
# ---------------------------------------------------------------------------


def format_stories_block(stories: list[Story]) -> str:
    """Numbered list of stories for the user message."""
    lines: list[str] = []
    for i, s in enumerate(stories, start=1):
        when = s.published.isoformat() if s.published else "unknown date"
        lines.append(f"{i}. {s.title}")
        lines.append(f"   Link: {s.link}")
        lines.append(f"   Date: {when}")
        if s.summary:
            snippet = s.summary[:800] + ("…" if len(s.summary) > 800 else "")
            lines.append(f"   Snippet: {snippet}")
        lines.append("")
    return "\n".join(lines).rstrip()


def build_user_content(stories: list[Story], user_prompt_template: str) -> str:
    block = format_stories_block(stories)
    tpl = user_prompt_template.strip()
    if "{stories}" in tpl:
        return tpl.replace("{stories}", block)
    return tpl.rstrip() + "\n\n" + block


def summarize_openai_compatible(
    *,
    api_key: str,
    base_url: str | None,
    model: str,
    system_prompt: str,
    user_content: str,
    temperature: float = 0.4,
) -> str:
    kwargs: dict[str, Any] = {"api_key": api_key}
    if base_url:
        kwargs["base_url"] = base_url
    client = OpenAI(**kwargs)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=temperature,
    )
    choice = response.choices[0].message.content
    return (choice or "").strip()


def summarize_claude(
    *,
    api_key: str,
    model: str,
    system_prompt: str,
    user_content: str,
) -> str:
    from anthropic import Anthropic

    client = Anthropic(api_key=api_key)
    msg = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
    )
    parts: list[str] = []
    for block in msg.content:
        if getattr(block, "type", None) == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def summarize_with_settings(settings: Settings, stories: list[Story]) -> str:
    user_content = build_user_content(stories, settings.user_prompt_template)
    if settings.llm_provider == "claude":
        return summarize_claude(
            api_key=settings.anthropic_api_key,
            model=settings.model,
            system_prompt=settings.system_prompt,
            user_content=user_content,
        )
    return summarize_openai_compatible(
        api_key=settings.openai_api_key,
        base_url=settings.openai_base_url,
        model=settings.model,
        system_prompt=settings.system_prompt,
        user_content=user_content,
    )


# ---------------------------------------------------------------------------
# Step 4 — HTML file
# ---------------------------------------------------------------------------


def write_briefing_html(path: str, summary: str, stories: list[Story], model: str, provider: str) -> None:
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    esc_summary = html.escape(summary, quote=False)

    items: list[str] = []
    for s in stories:
        title = html.escape(s.title, quote=True)
        when = html.escape(s.published.isoformat() if s.published else "unknown date", quote=True)
        if s.link:
            href = html.escape(s.link, quote=True)
            items.append(f'<li><a href="{href}" target="_blank" rel="noopener noreferrer">{title}</a> — {when}</li>')
        else:
            items.append(f"<li>{title} — {when}</li>")

    stories_html = "\n    ".join(items) if items else "<li>(no stories)</li>"
    meta_model = html.escape(f"{provider} · {model}", quote=True)

    doc = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>News briefing</title>
  <style>
    :root {{ font-family: system-ui, Segoe UI, Roboto, sans-serif; line-height: 1.5; }}
    body {{ max-width: 52rem; margin: 2rem auto; padding: 0 1rem; color: #1a1a1a; }}
    h1 {{ font-size: 1.35rem; }}
    .meta {{ color: #555; font-size: 0.9rem; margin-bottom: 1.5rem; }}
    .summary {{ white-space: pre-wrap; background: #f6f8fa; padding: 1rem 1.25rem; border-radius: 8px; }}
    h2 {{ font-size: 1.1rem; margin-top: 2rem; }}
    ul {{ padding-left: 1.25rem; }}
    a {{ color: #0969da; }}
  </style>
</head>
<body>
  <h1>News briefing</h1>
  <p class="meta">Generated {html.escape(generated, quote=True)} · {meta_model}</p>
  <h2>Summary</h2>
  <div class="summary">{esc_summary}</div>
  <h2>Sources (top stories sent to the model)</h2>
  <ul>
    {stories_html}
  </ul>
</body>
</html>
"""
    out = Path(path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")


# ---------------------------------------------------------------------------
# Pipeline (CLI + web)
# ---------------------------------------------------------------------------


def validate_settings_for_run(settings: Settings) -> str | None:
    if settings.llm_provider == "openai" and not settings.openai_api_key:
        return "Missing OPENAI_API_KEY in .env (required for OpenAI)."
    if settings.llm_provider == "claude" and not settings.anthropic_api_key:
        return "Missing ANTHROPIC_API_KEY in .env (required for Claude)."
    if not settings.rss_urls:
        return "Add at least one RSS feed URL."
    return None


def run_pipeline(settings: Settings, *, verbose: bool = True) -> tuple[int, str | None, str | None]:
    """
    Returns (exit_code, summary_text_or_none, error_message_or_none).
    On success exit_code 0 and summary is set; on failure exit_code non-zero and error_message is set.
    """
    err = validate_settings_for_run(settings)
    if err:
        return 1, None, err

    if verbose:
        print("Step 1 — Fetching RSS feeds…")
    stories = fetch_all_stories(settings.rss_urls)
    if not stories:
        return 1, None, "No stories fetched. Check RSS URLs and your network."

    if verbose:
        print(f"         Collected {len(stories)} raw entries from {len(settings.rss_urls)} feed(s).")
        print("Step 2 — Selecting top stories by date…")
    top = select_top_stories(stories, settings.top_n)
    if verbose:
        print(f"         Keeping top {len(top)} for the LLM.")
        print(f"Step 3 — Calling LLM ({settings.llm_provider})…")

    try:
        summary = summarize_with_settings(settings, top)
    except NotFoundError:
        if settings.llm_provider == "ollama":
            return (
                1,
                None,
                f"Ollama has no model {settings.model!r}. Run: ollama pull {settings.model}  (see also: ollama list)",
            )
        return 1, None, "Model not found (404). Check the model id for your provider."
    except Exception as e:
        return 1, None, f"{type(e).__name__}: {e}"

    if verbose:
        print("Step 4 — Writing HTML briefing…")
    write_briefing_html(settings.output_html, summary, top, settings.model, settings.llm_provider)
    if verbose:
        print(f"         Saved: {settings.output_html}")
        print("\n--- Briefing ---\n")
        print(summary)
        print("\n--- End ---")

    return 0, summary, None


def ensure_settings_file() -> None:
    """Copy example JSON if no settings file exists."""
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not SETTINGS_PATH.is_file() and SETTINGS_EXAMPLE_PATH.is_file():
        SETTINGS_PATH.write_text(SETTINGS_EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")


def main() -> int:
    try:
        settings = load_settings()
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Invalid JSON in {SETTINGS_PATH}: {e}", file=sys.stderr)
        return 1

    code, _summary, err = run_pipeline(settings, verbose=True)
    if err:
        print(err, file=sys.stderr)
    return code


if __name__ == "__main__":
    raise SystemExit(main())

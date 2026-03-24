"""
Simple "agentic" news workflow in one script (easy to read top-to-bottom).

What is "agentic" here?
-----------------------
We chain explicit steps: perceive (RSS) → select (top stories) → act (call LLM).
There is no tool loop yet; the point is to see the pipeline clearly. You can
later swap the LLM step for a planner that calls tools (search, email, etc.).

Run:
    python -m venv .venv
    .venv\\Scripts\\activate   # Windows
    pip install -r requirements.txt
    copy .env.example .env     # then edit .env
    python news_agent.py
"""

from __future__ import annotations

import html
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
# Step 0 — Configuration (environment + defaults)
# ---------------------------------------------------------------------------

DEFAULT_RSS_FEEDS = [
    "http://newsrss.bbc.co.uk/rss/newsonline_uk_edition/front_page/rss.xml",
    "http://rss.cnn.com/rss/cnn_topstories.rss",
]

# How many items to keep after merging all feeds (by recency).
TOP_N_STORIES = 8

# Where the HTML briefing is written (override with OUTPUT_HTML in .env).
DEFAULT_OUTPUT_HTML = "output/briefing.html"

# Ollama serves an OpenAI-compatible API (see https://github.com/ollama/ollama/blob/main/docs/openai.md ).
OLLAMA_OPENAI_BASE_URL = "http://localhost:11434/v1"
# Default only if OPENAI_MODEL is unset; must match `ollama list` (e.g. llama3, llama3:latest).
OLLAMA_DEFAULT_MODEL = "llama3"
# The Python SDK requires a non-empty key; Ollama ignores it locally.
OLLAMA_PLACEHOLDER_API_KEY = "ollama"


def _env_truthy(name: str) -> bool:
    v = os.getenv(name, "").strip().lower()
    return v in ("1", "true", "yes", "on")


def _use_ollama_backend() -> bool:
    backend = os.getenv("LLM_BACKEND", "").strip().lower()
    if backend == "ollama":
        return True
    if backend == "openai":
        return False
    if backend == "":
        return _env_truthy("USE_OLLAMA")
    raise ValueError(f"Unknown LLM_BACKEND={backend!r}; use 'openai' or 'ollama'.")


@dataclass(frozen=True)
class Settings:
    """All runtime settings in one place."""

    rss_urls: list[str]
    top_n: int
    openai_api_key: str
    openai_base_url: str | None
    model: str
    output_html: str
    llm_backend: str


def load_settings() -> Settings:
    load_dotenv()
    feeds_env = os.getenv("RSS_FEEDS")
    if feeds_env:
        rss_urls = [u.strip() for u in feeds_env.split(",") if u.strip()]
    else:
        rss_urls = list(DEFAULT_RSS_FEEDS)

    top_n = int(os.getenv("TOP_N_STORIES", str(TOP_N_STORIES)))
    output_html = os.getenv("OUTPUT_HTML", DEFAULT_OUTPUT_HTML).strip()

    use_ollama = _use_ollama_backend()
    if use_ollama:
        # Same env names as OpenAI path so one .env can switch backends easily.
        base_raw = os.getenv("OPENAI_BASE_URL", OLLAMA_OPENAI_BASE_URL).strip()
        base_url = base_raw or OLLAMA_OPENAI_BASE_URL
        api_key = os.getenv("OPENAI_API_KEY", OLLAMA_PLACEHOLDER_API_KEY).strip() or OLLAMA_PLACEHOLDER_API_KEY
        model = os.getenv("OPENAI_MODEL", OLLAMA_DEFAULT_MODEL).strip() or OLLAMA_DEFAULT_MODEL
        llm_backend = "ollama"
    else:
        api_key = os.getenv("OPENAI_API_KEY", "").strip()
        base_url = os.getenv("OPENAI_BASE_URL", "").strip() or None
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini").strip()
        llm_backend = "openai"

    return Settings(
        rss_urls=rss_urls,
        top_n=top_n,
        openai_api_key=api_key,
        openai_base_url=base_url,
        model=model,
        output_html=output_html,
        llm_backend=llm_backend,
    )


# ---------------------------------------------------------------------------
# Step 1 — Perceive: fetch and parse RSS
# ---------------------------------------------------------------------------


@dataclass
class Story:
    """One news item we can summarize."""

    title: str
    link: str
    summary: str
    published: datetime | None


def _parse_published(entry: Any) -> datetime | None:
    """Best-effort parse of RSS/Atom date fields."""
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
    """Download one feed and normalize entries to Story objects."""
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
        # Strip basic HTML noise from some feeds (keep it simple).
        summary = summary.replace("<![CDATA[", "").replace("]]>", "")
        if not title:
            continue
        out.append(Story(title=title, link=link, summary=summary, published=_parse_published(entry)))
    return out


def fetch_all_stories(urls: list[str]) -> list[Story]:
    """Step 1 (full): aggregate stories from every configured feed."""
    all_stories: list[Story] = []
    for url in urls:
        try:
            all_stories.extend(fetch_stories_from_feed(url))
        except RuntimeError as err:
            print(f"Warning: {err}", file=sys.stderr)
    return all_stories


# ---------------------------------------------------------------------------
# Step 2 — Select: rank and take top N (by publication time)
# ---------------------------------------------------------------------------


def select_top_stories(stories: list[Story], n: int) -> list[Story]:
    """
    Step 2: choose the N most recent items.

    Real agents might use relevance scoring, deduplication, or user prefs here.
    """
    # None dates sort last
    def sort_key(s: Story) -> datetime:
        return s.published or datetime.min.replace(tzinfo=timezone.utc)

    sorted_stories = sorted(stories, key=sort_key, reverse=True)
    return sorted_stories[:n]


# ---------------------------------------------------------------------------
# Step 3 — Act: send a prompt to the LLM and get a summary
# ---------------------------------------------------------------------------


def build_user_prompt(stories: list[Story]) -> str:
    """Turn structured stories into one user message for the model."""
    lines: list[str] = [
        "Here are the latest headlines with links and short blurbs from RSS.",
        "Write a concise briefing: bullet list of themes, 2–3 sentences per major theme,",
        "mention which story/link supports each point when useful.",
        "",
    ]
    for i, s in enumerate(stories, start=1):
        when = s.published.isoformat() if s.published else "unknown date"
        lines.append(f"{i}. {s.title}")
        lines.append(f"   Link: {s.link}")
        lines.append(f"   Date: {when}")
        if s.summary:
            # Truncate very long HTML summaries
            snippet = s.summary[:800] + ("…" if len(s.summary) > 800 else "")
            lines.append(f"   Snippet: {snippet}")
        lines.append("")
    return "\n".join(lines)


def summarize_with_llm(client: OpenAI, model: str, stories: list[Story]) -> str:
    """Step 3: one chat completion — the 'agent action' for this demo."""
    user_content = build_user_prompt(stories)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": (
                    "You are a careful news assistant. Be factual; do not invent events. "
                    "If the snippets are thin, say what is unknown."
                ),
            },
            {"role": "user", "content": user_content},
        ],
        temperature=0.4,
    )
    choice = response.choices[0].message.content
    return (choice or "").strip()


# ---------------------------------------------------------------------------
# Step 4 — Deliver: write a local HTML file (easy to open in a browser)
# ---------------------------------------------------------------------------


def write_briefing_html(
    path: str,
    summary: str,
    stories: list[Story],
    model: str,
) -> None:
    """
    Build a single self-contained HTML page.

    The LLM text is escaped so arbitrary model output cannot inject HTML/JS.
    Story titles and links are escaped; links use a safe attribute.
    """
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
  <p class="meta">Generated {html.escape(generated, quote=True)} · Model {html.escape(model, quote=True)}</p>
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
# Main — orchestrates the workflow
# ---------------------------------------------------------------------------


def main() -> int:
    try:
        settings = load_settings()
    except ValueError as err:
        print(str(err), file=sys.stderr)
        return 1

    if settings.llm_backend == "openai" and not settings.openai_api_key:
        print(
            "Missing OPENAI_API_KEY. Copy .env.example to .env and set your key from "
            "https://platform.openai.com/api-keys — or set USE_OLLAMA=1 for local Ollama.",
            file=sys.stderr,
        )
        return 1

    print("Step 1 — Fetching RSS feeds…")
    stories = fetch_all_stories(settings.rss_urls)
    if not stories:
        print(
            "No stories fetched. Check RSS URLs and your network.\n"
            "Set RSS_FEEDS in .env to comma-separated feed URLs.",
            file=sys.stderr,
        )
        return 1
    print(f"         Collected {len(stories)} raw entries from {len(settings.rss_urls)} feed(s).")

    print("Step 2 — Selecting top stories by date…")
    top = select_top_stories(stories, settings.top_n)
    print(f"         Keeping top {len(top)} for the LLM.")

    print(f"Step 3 — Calling LLM for summary ({settings.llm_backend})…")
    client_kwargs: dict[str, Any] = {"api_key": settings.openai_api_key}
    if settings.openai_base_url:
        client_kwargs["base_url"] = settings.openai_base_url
    client = OpenAI(**client_kwargs)

    try:
        summary = summarize_with_llm(client, settings.model, top)
    except NotFoundError as err:
        if settings.llm_backend == "ollama":
            print(
                f"Ollama does not have model {settings.model!r} (404).\n"
                f"  Install:  ollama pull {settings.model}\n"
                f"  Or pick a name from:  ollama list\n"
                f"Then set OPENAI_MODEL in .env to that exact name.",
                file=sys.stderr,
            )
        else:
            print(f"Model not found: {err}", file=sys.stderr)
        return 1

    print("Step 4 — Writing HTML briefing…")
    write_briefing_html(settings.output_html, summary, top, settings.model)
    print(f"         Saved: {settings.output_html}")

    print("\n--- Briefing (same as in HTML) ---\n")
    print(summary)
    print("\n--- End ---")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

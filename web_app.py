"""
Local web UI for News Agent: edit LLM provider, RSS feeds, and prompts; save JSON; run briefing.

Usage:
    pip install -r requirements.txt
    copy config\\settings.example.json config\\settings.json   # first time
    python web_app.py

Open http://127.0.0.1:5000 — API keys stay in .env only (OPENAI_API_KEY, ANTHROPIC_API_KEY).
"""

from __future__ import annotations

import json
import os
import traceback
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, flash, redirect, render_template, request, url_for

from news_agent import (
    SETTINGS_PATH,
    default_settings_dict,
    ensure_settings_file,
    load_settings,
    merge_settings_dict,
    run_pipeline,
    settings_dict_for_ui,
)

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-key-change-for-production")


def _parse_form() -> dict:
    feeds_raw = request.form.get("rss_feeds", "")
    feeds = [ln.strip() for ln in feeds_raw.replace("\r\n", "\n").split("\n") if ln.strip()]
    try:
        top_n = int(request.form.get("top_n", "8") or "8")
    except ValueError:
        top_n = 8
    top_n = max(1, min(top_n, 50))

    return {
        "llm_provider": (request.form.get("llm_provider") or "openai").strip().lower(),
        "model": (request.form.get("model") or "").strip(),
        "openai_base_url": (request.form.get("openai_base_url") or "").strip(),
        "rss_feeds": feeds,
        "top_n": top_n,
        "system_prompt": request.form.get("system_prompt") or "",
        "user_prompt_template": request.form.get("user_prompt_template") or "",
        "output_html": (request.form.get("output_html") or "").strip() or "output/briefing.html",
    }


def _save_settings(data: dict) -> None:
    SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SETTINGS_PATH.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        ensure_settings_file()
        data = settings_dict_for_ui()
        return render_template(
            "index.html",
            settings=data,
            settings_path=str(SETTINGS_PATH.resolve()),
            has_openai_key=bool(os.getenv("OPENAI_API_KEY", "").strip()),
            has_anthropic_key=bool(os.getenv("ANTHROPIC_API_KEY", "").strip()),
        )

    action = (request.form.get("action") or "").strip().lower()
    data = _parse_form()
    if data["llm_provider"] not in ("openai", "ollama", "claude"):
        flash("Invalid LLM provider.", "error")
        return redirect(url_for("index"))

    base = default_settings_dict()
    merged = merge_settings_dict(base, data)
    _save_settings(merged)

    if action == "save":
        flash("Configuration saved.", "ok")
        return redirect(url_for("index"))

    if action == "run":
        try:
            settings = load_settings()
        except ValueError as e:
            flash(str(e), "error")
            return redirect(url_for("index"))
        except json.JSONDecodeError as e:
            flash(f"Invalid settings JSON: {e}", "error")
            return redirect(url_for("index"))

        _code, summary, err = run_pipeline(settings, verbose=False)
        if err:
            flash(err, "error")
            app.logger.warning("run_pipeline failed: %s", err)
            return redirect(url_for("index"))
        flash(f"Briefing written to {settings.output_html}", "ok")
        return render_template(
            "result.html",
            summary=summary or "",
            output_path=settings.output_html,
            provider=settings.llm_provider,
            model=settings.model,
        )

    flash("Unknown action.", "error")
    return redirect(url_for("index"))


@app.errorhandler(500)
def server_error(e):
    return render_template("error.html", detail=traceback.format_exc()), 500


if __name__ == "__main__":
    ensure_settings_file()
    port = int(os.environ.get("PORT", "5000"))
    app.run(host="127.0.0.1", port=port, debug=os.environ.get("FLASK_DEBUG") == "1")

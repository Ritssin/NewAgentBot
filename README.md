# News Agent (RSS → LLM → HTML)

A **small, readable Python script** that demonstrates a linear **agentic workflow**:

1. **Perceive** — download and parse RSS feeds.  
2. **Select** — merge items and keep the most recent *N* stories.  
3. **Act** — send those stories to an LLM and receive a briefing (**OpenAI** or **local Ollama**).  
4. **Deliver** — write a self-contained **HTML file** you can open in a browser (summary + source links).

Upstream repo: [github.com/Ritssin/NewAgentBot](https://github.com/Ritssin/NewAgentBot)

There is no multi-step “tool loop” here on purpose: the full pipeline lives in `news_agent.py`.

## Prerequisites

- Python 3.10+ recommended  
- Either:
  - **[Ollama](https://ollama.com)** running locally (recommended for offline / no API key), or  
  - An [OpenAI API key](https://platform.openai.com/api-keys)

## Setup

```powershell
cd path\to\NewsAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` (see below).

## Ollama (local)

1. Install and start [Ollama](https://ollama.com).  
2. Pull a model, e.g. `ollama pull llama3.2`.  
3. In `.env` set **`USE_OLLAMA=1`** and **`OPENAI_MODEL`** to that model name (default in code is `llama3.2`).

Ollama exposes an [OpenAI-compatible API](https://github.com/ollama/ollama/blob/main/docs/openai.md) at `http://localhost:11434/v1`. This project uses the same `openai` Python package with `base_url` pointing there.

## OpenAI (cloud)

In `.env` remove **`USE_OLLAMA`** (or set **`USE_OLLAMA=0`**) and set **`OPENAI_API_KEY`**.

## Run

```powershell
python news_agent.py
```

By default this writes **`output/briefing.html`** (the `output/` folder is gitignored).

## Configuration (environment variables)

| Variable | Purpose |
|----------|---------|
| `USE_OLLAMA` | `1` / `true` to use local Ollama (defaults: base URL `http://localhost:11434/v1`, placeholder API key, model `llama3.2`). |
| `LLM_BACKEND` | Optional explicit `ollama` or `openai` (overrides `USE_OLLAMA` when set to `openai`). |
| `OPENAI_API_KEY` | Required for OpenAI; optional for Ollama (defaults to `ollama`). |
| `OPENAI_BASE_URL` | Ollama: override host/port if needed. OpenAI: only for non-default endpoints. |
| `OPENAI_MODEL` | Model name (`llama3.2`, `gpt-4o-mini`, etc.). |
| `OUTPUT_HTML` | Path for the HTML report (default: `output/briefing.html`). |
| `RSS_FEEDS` | Comma-separated RSS URLs (overrides built-in defaults). |
| `TOP_N_STORIES` | How many recent items to send to the model (default: 8). |

## Syncing with GitHub

```powershell
git remote add origin https://github.com/Ritssin/NewAgentBot.git
git push -u origin main
```

If `origin` already exists, use `git remote set-url origin https://github.com/Ritssin/NewAgentBot.git`.

**Security:** `.env` is in `.gitignore` — never commit secrets.

## License

Use and modify freely for learning.

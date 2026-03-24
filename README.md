# News Agent (RSS → LLM → HTML)

Linear **agentic workflow**: fetch RSS → pick top stories → call an LLM → write an HTML briefing.

Upstream repo: [github.com/Ritssin/NewAgentBot](https://github.com/Ritssin/NewAgentBot)

## Features

- **LLMs:** [OpenAI](https://platform.openai.com/), local **[Ollama](https://ollama.com)** (OpenAI-compatible API), **[Claude](https://www.anthropic.com/)** (Anthropic).
- **Config:** `config/settings.json` — RSS list, provider, model, base URL, **system prompt**, **user prompt** (use `{stories}` where the headline list goes). Copy from `config/settings.example.json`.
- **Secrets:** only in `.env` — `OPENAI_API_KEY`, `ANTHROPIC_API_KEY` (never commit).
- **CLI:** `python news_agent.py`
- **Web UI:** `python web_app.py` → [http://127.0.0.1:5000](http://127.0.0.1:5000) — edit feeds/prompts/provider, save, run briefing.

## Setup

```powershell
cd path\to\NewsAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env` with API keys. For the web UI or file-based config:

```powershell
copy config\settings.example.json config\settings.json
```

## Run (CLI)

If `config/settings.json` is **missing**, the CLI uses `.env` (see `.env.example`) plus built-in defaults.

```powershell
python news_agent.py
```

## Run (web)

```powershell
python web_app.py
```

Open **http://127.0.0.1:5000** . The first visit can create `config/settings.json` from the example if the file is absent.

## Prompts

- **System prompt:** instructions for the model (role, tone, factuality).
- **User prompt:** your task text; include **`{stories}`** where the numbered RSS excerpts should appear. If `{stories}` is omitted, the story block is appended after your text.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | OpenAI and Ollama client (Ollama may use a placeholder like `ollama` if unset when using settings JSON with provider Ollama — CLI env-mode still sets this). |
| `ANTHROPIC_API_KEY` | Required for Claude. |
| `NEWS_AGENT_SETTINGS` | Path to JSON settings file (default `config/settings.json`). |
| `USE_OLLAMA` / `LLM_BACKEND` / `LLM_PROVIDER` | Used when **no** `settings.json` (see `news_agent.py`). |
| `FLASK_SECRET_KEY` / `PORT` / `FLASK_DEBUG` | Web app. |

## Syncing with GitHub

```powershell
git remote set-url origin https://github.com/Ritssin/NewAgentBot.git
git push -u origin main
```

**Security:** `.env` and `config/settings.json` are gitignored (example JSON is committed).

## License

Use and modify freely for learning.

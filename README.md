# News Agent (RSS → LLM)

A **small, readable Python script** that demonstrates a linear **agentic workflow**:

1. **Perceive** — download and parse RSS feeds.  
2. **Select** — merge items and keep the most recent *N* stories.  
3. **Act** — send those stories to an LLM and print a structured briefing.

There is no multi-step “tool loop” here on purpose: you can see the full pipeline in one file (`news_agent.py`). Later you can replace the LLM call with a planner that chooses tools (search, email, calendar, etc.).

## Prerequisites

- Python 3.10+ recommended  
- An **API key** for an OpenAI-compatible chat API (see questions below)

## Setup

```powershell
cd path\to\NewsAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`: set `OPENAI_API_KEY` and, if needed, `OPENAI_BASE_URL` and `OPENAI_MODEL`.

## Run

```powershell
python news_agent.py
```

## Configuration (environment variables)

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Required for the default client. |
| `OPENAI_BASE_URL` | Optional. Use for Azure OpenAI, Ollama (`http://localhost:11434/v1`), LM Studio, etc. |
| `OPENAI_MODEL` | Model id (provider-specific). |
| `RSS_FEEDS` | Comma-separated RSS URLs (overrides built-in defaults). |
| `TOP_N_STORIES` | How many recent items to send to the LLM (default: 8). |

## Syncing with GitHub

1. Create a **new empty repository** on GitHub (no README/license if you already have files locally).  
2. In this folder:

```powershell
git init
git add .
git commit -m "Initial commit: RSS news agent with LLM summary"
git branch -M main
git remote add origin https://github.com/YOUR_USER/YOUR_REPO.git
git push -u origin main
```

Use SSH if you prefer: `git@github.com:YOUR_USER/YOUR_REPO.git`.

**Security:** `.env` is in `.gitignore` — never commit secrets.

## Questions to decide before you scale this up

1. **Which LLM?** OpenAI, Azure OpenAI, Anthropic, Google, or a **local** model (Ollama)? This repo uses the `openai` Python SDK with an optional `base_url` so one code path covers many providers.  
2. **Which feeds?** Set `RSS_FEEDS` or edit `DEFAULT_RSS_FEEDS` in `news_agent.py`.  
3. **How many stories?** `TOP_N_STORIES` trades context size vs. coverage.  
4. **Output destination?** Today the result prints to stdout; you could add email, Slack, or a file.  
5. **“Real” agent next step?** Add tool definitions and let the model call `fetch_rss` or `web_search` in a loop — same perceive → decide → act pattern, repeated.

## License

Use and modify freely for learning.

# News Agent (RSS → OpenAI → HTML)

A **small, readable Python script** that demonstrates a linear **agentic workflow**:

1. **Perceive** — download and parse RSS feeds.  
2. **Select** — merge items and keep the most recent *N* stories.  
3. **Act** — send those stories to **OpenAI** and receive a briefing.  
4. **Deliver** — write a self-contained **HTML file** you can open in a browser (summary + source links).

Upstream repo: [github.com/Ritssin/NewAgentBot](https://github.com/Ritssin/NewAgentBot)

There is no multi-step “tool loop” here on purpose: the full pipeline lives in `news_agent.py`.

## Prerequisites

- Python 3.10+ recommended  
- An [OpenAI API key](https://platform.openai.com/api-keys)

## Setup

```powershell
cd path\to\NewsAgent
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
```

Edit `.env`: set `OPENAI_API_KEY` and optionally `OPENAI_MODEL`, `OUTPUT_HTML`, `RSS_FEEDS`, `TOP_N_STORIES`.

## Run

```powershell
python news_agent.py
```

By default this writes **`output/briefing.html`** (the `output/` folder is gitignored so generated pages are not committed by mistake).

## Configuration (environment variables)

| Variable | Purpose |
|----------|---------|
| `OPENAI_API_KEY` | Required. |
| `OPENAI_MODEL` | OpenAI model id (default: `gpt-4o-mini`). |
| `OUTPUT_HTML` | Path for the HTML report (default: `output/briefing.html`). |
| `RSS_FEEDS` | Comma-separated RSS URLs (overrides built-in defaults). |
| `TOP_N_STORIES` | How many recent items to send to the model (default: 8). |
| `OPENAI_BASE_URL` | Rarely needed; only if you use a non-default OpenAI API endpoint. |

## Syncing with GitHub

```powershell
git remote add origin https://github.com/Ritssin/NewAgentBot.git
git push -u origin main
```

If `origin` already exists, use `git remote set-url origin https://github.com/Ritssin/NewAgentBot.git`.

**Security:** `.env` is in `.gitignore` — never commit secrets.

## License

Use and modify freely for learning.

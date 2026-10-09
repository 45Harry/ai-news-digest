# AI News Digest

Checks AI news sources on a schedule and emails you **one daily digest at 9:10 AM**
focused on **new AI technology** — model releases, launches, research, products,
tools, chips, and big lab news. It covers yesterday plus today, drops anything
you've already seen, and never sends duplicates or empty emails.

---

## How it works (simple version)

Each day the bot:
- Pulls from AI lab blogs (OpenAI, Google, DeepMind, Mistral, Meta, HuggingFace)
  plus Google News searches that catch new model launches across the industry
  (Anthropic, DeepSeek, Qwen, Kimi, Grok, GLM, MiniMax, Cohere, NVIDIA, and
  general "new AI model" releases)
- Drops anything you've already seen and anything older than the window
- Uses an LLM to keep **only new AI tech**: it drops opinion pieces, listicles,
  "AI will change everything" fluff, adoption surveys, funding/valuation chatter
  and stock commentary
- Writes a short "what's notable today" summary and emails it

Before anything gets emailed, an LLM checks it:
- Merges duplicate coverage of the same story (only the best version survives)
- Drops junk or off-topic items
- Fact-checks the summary against the real headlines (no made-up facts)
- Makes sure no HTML/code/markdown leaks into the email

If the LLM says something looks wrong, it regenerates up to 3 times. If all attempts fail, a clean default summary goes out instead.

Set `MODEL_FOCUS=0` in `.env` to turn off the new-tech filter and keep everything.

---

## The LLM providers

The bot uses LLMs for two jobs: **verify** (dedup + junk removal + fact-checking) and **overview** (the summary). Both try providers in this order — first one that answers wins:

| Order | Provider | Model | Status |
|---|---|---|---|
| 1st | Anthropic (Claude) | claude-sonnet-5 | Add `ANTHROPIC_API_KEY` to enable |
| 2nd | Groq | openai/gpt-oss-120b | **Working** |
| 3rd | NVIDIA NIM | deepseek-v4-flash | **Free**, no credit card — add `NIM_API_KEY` from build.nvidia.com |
| 4th | Cerebras | gpt-oss-120b | Key valid, needs billing on account |
| 5th | Google Gemini | gemini-3.8-flash | **Working** (quota: 20/day, resets daily) |
| 6th | HuggingFace | Llama-3.3-70B-Instruct | Credits depleted |
| 7th | OpenAI | gpt-4o-mini | Add `OPENAI_API_KEY` to enable |
| 8th | OpenCode Zen | big-pickle | Console-only, not usable via API |
| Last | Ollama (local) | llama3.1 | **Working** (free, private, no key needed) |

Right now the bot uses **Groq** for both tasks (Gemini is quota-exhausted today, Ollama picks up if Groq also fails). When the Gemini quota resets tomorrow it'll be available again. When you add a Claude key it moves to first position.

Each task runs its own independent chain, so you can use a cheap model for verify and a stronger model for overview — set `VERIFY_LLM_PROVIDERS` and `OVERVIEW_LLM_PROVIDERS` in `.env`.

---

## Setup

### What you need

- Python 3.9+
- A Gmail account with 2-Step Verification turned on
- At least one working LLM key (Groq is already set up)

### Install

```bash
cd ai-news-digest
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then fill in your keys
```

### Gmail setup

1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords
3. Put your Gmail address and that 16-character password into `.env` (`GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD`)

### Test it

```bash
.venv/bin/python run.py --check-llm     # shows which LLM providers work
.venv/bin/python run.py --test-email    # sends a test email via Gmail
.venv/bin/python run.py --once          # runs the full pipeline once
```

---

## Running it on a schedule

**One daily email at 9:10 AM** (cron, Asia/Kathmandu local time). It covers the
previous day's news plus today's so far (`FILTER_TODAY_ONLY=1` +
`RECENCY_DAYS=1`). No real-time BREAKING alerts (`BREAKING_ALERTS=0`) — big
stories are simply included in the single morning digest, so you get one tidy
email each day, no duplicates, nothing re-sent.

Install the cron job:

```bash
crontab -e
```

```
10 9 * * * cd /full/path/to/ai-news-digest && /full/path/to/.venv/bin/python run.py --once >> logs/run.log 2>&1
```

Run it right now: `.venv/bin/python run.py --once`

Want real-time alerts again? Set `BREAKING_ALERTS=1` in `.env` and start the
24/7 watcher (`nohup .venv/bin/python run.py >> logs/run.log 2>&1 &`), and it
will email big stories the moment they appear, on top of the daily digest.

---

## Customizing

Edit `src/config.py` to change what gets watched:

- `GENERAL_AI_FEEDS` — direct RSS feeds (TechCrunch, VentureBeat, The Verge, GitHub)
- `POLICY_QUERIES` — Google News searches for policy/regulation/politics stories
- `LAB_AI_FEEDS` / `LAB_ANNOUNCE_QUERIES` — AI lab blogs + the model-launch
  searches (this is the section that catches new model releases)
- `AI_TWITTER_ACCOUNTS` — official lab X/Twitter accounts (needs a working RSSHub instance)

---

## Project layout

```
ai-news-digest/
  run.py              # entry point
  requirements.txt
  .env.example        # copy to .env and fill in
  .env                # your keys (gitignored)
  src/
    config.py         # settings + source lists
    providers.py      # LLM provider chain + failover
    sources.py        # RSS feed fetchers
    priority.py       # big/unique story detection
    seen_store.py     # remembers already-emailed links
    mailer.py         # email formatting + sending
    graph.py          # the pipeline
    main.py           # run helpers
  data/seen.json      # runtime state (auto-created)
  logs/
```

---

## Tuning

- `MODEL_FOCUS` (default 1) — keep only new AI tech (models/launches/research/products). Set to 0 to keep all feed items.
- `RECENCY_DAYS` (default 1) — how far back the digest reaches. 1 = yesterday + today.
- `FILTER_TODAY_ONLY` (default 1) — only emails articles within the recency window. Set to 0 to email anything in the feeds.
- `BREAKING_ALERTS` (default 0) — 1 = also email big stories instantly (needs the 24/7 watcher running).
- `HOT_THRESHOLD` (default 65) — how "big" a story must be to count as breaking when alerts are on.
- `MAX_ARTICLES_PER_RUN` (default 20) — cap per category per email. Lower if emails feel long.
- `RUN_INTERVAL_SECONDS` (default 300) — how often the watcher checks for new stories.

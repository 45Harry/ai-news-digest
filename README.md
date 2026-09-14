# AI News Digest

Checks AI news sources on a schedule and emails you two things:

1. **Real-time BREAKING alerts** the moment a big story appears.
2. **One nightly digest** at 11:30 PM with everything else published that day.

No duplicates, no spam, no empty emails. Stories you already got as breaking alerts are never repeated in the digest.

---

## How it works (simple version)

Every few minutes, the bot:
- Pulls stories from AI news sites (TechCrunch, The Verge, OpenAI blog, Google News for policy/regulation stories, etc.)
- Drops anything you've already seen
- Flags big/unique stories (court cases, new models, regulation, funding) and emails them to you **instantly**
- At 11:30 PM, sends one tidy recap of the rest of the day's news

Before anything gets emailed, an LLM checks it:
- Merges duplicate coverage of the same story (only the best version survives)
- Drops junk or off-topic items
- Writes a short "what's notable today" summary
- Fact-checks the summary against the real headlines (no made-up facts)
- Makes sure no HTML/code/markdown leaks into the email

If the LLM says something looks wrong, it regenerates up to 3 times. If all attempts fail, a clean default summary goes out instead.

---

## The LLM providers

The bot uses LLMs for two jobs: **verify** (dedup + junk removal + fact-checking) and **overview** (the summary). Both try providers in this order — first one that answers wins:

| Order | Provider | Model | Status |
|---|---|---|---|
| 1st | Anthropic (Claude) | claude-sonnet-5 | Add `ANTHROPIC_API_KEY` to enable |
| 2nd | Groq | openai/gpt-oss-120b | **Working** |
| 3rd | Cerebras | gpt-oss-120b | Key valid, needs billing on account |
| 4th | Google Gemini | gemini-3.8-flash | **Working** (quota: 20/day, resets daily) |
| 5th | HuggingFace | Llama-3.3-70B-Instruct | Credits depleted |
| 6th | OpenAI | gpt-4o-mini | Add `OPENAI_API_KEY` to enable |
| 7th | OpenCode Zen | big-pickle | Console-only, not usable via API |
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

## Running it 24/7

Two things run at the same time:

**1. Real-time watcher (runs in background, checks every 5 minutes)**
Emails big stories the moment they appear. Survives reboots via `@reboot` in crontab.

```bash
nohup .venv/bin/python run.py >> logs/run.log 2>&1 &
```

**2. Nightly digest (cron at 11:30 PM)**
One email with everything else published that day.

```
30 23 * * * cd /path/to/ai-news-digest && /path/to/.venv/bin/python run.py --once >> logs/run.log 2>&1
```

---

## Customizing

Edit `src/config.py` to change what gets watched:

- `GENERAL_AI_FEEDS` — direct RSS feeds (TechCrunch, VentureBeat, The Verge, GitHub)
- `POLICY_QUERIES` — Google News searches for policy/regulation/politics stories
- `LAB_AI_FEEDS` / `LAB_ANNOUNCE_QUERIES` — AI lab blogs + announcement searches
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

- `HOT_THRESHOLD` (default 65) — how "big" a story has to be before it triggers a real-time alert. Higher = fewer alerts.
- `MAX_ARTICLES_PER_RUN` (default 20) — cap per category per email. Lower if emails feel long.
- `FILTER_TODAY_ONLY` (default 1) — only emails articles published today. Set to 0 to email anything in the feeds.
- `RUN_INTERVAL_SECONDS` (default 300) — how often the watcher checks for new stories.

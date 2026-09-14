# AI News Digest

A small multi-agent pipeline (built with LangGraph) that checks authorized AI
news sources on a schedule and emails you a digest of what's new -- general
AI/product news plus AI policy & political news -- since the last time it ran.

## What it does

```
              -> fetch_general ->\
START ->                            >-> merge -> prioritize -> send_breaking ->\
              -> fetch_policy  ->/                       |                       -> summarize -> send_digest -> END
              -> fetch_tweets  ->/    -> END (nothing new)  -> END (no hot news)   / -> END (no regular news)
              -> fetch_labs    ->/
```

- **fetch_general / fetch_policy / fetch_tweets / fetch_labs** (in parallel) pull
  raw items from RSS feeds -- general AI news, policy/politics, AI lab tweets,
  and official lab blogs + announcement searches. See `src/config.py` for the
  lists.
- **merge** de-dupes, drops anything already emailed before (tracked in
  `data/seen.json`), and caps volume per run.
- **prioritize** flags **big / unique** stories (regulation, court cases, model
  launches, funding rounds, the same story covered by multiple outlets, ...).
  Hot stories are emailed **immediately as a BREAKING alert** -- real time.
- **summarize** asks an LLM for a short 3-5 sentence "here's what's notable"
  overview. This is the *only* place a model touches the content -- every
  headline, link, and source in the email is taken straight from the feed
  and can never be garbled by the model.
- **send** emails the digest via Gmail SMTP and records the sent links so they
  won't be repeated next run.
- If nothing new was found, the graph skips straight to END -- no wasted LLM
  call, no empty email.

## Multiple LLM providers with automatic failover

The overview only needs *a* working model, so you can enable several providers
in `.env` (`LLM_PROVIDERS`). Each run tries them in order and uses the first
that answers:

```
LLM_PROVIDERS=ollama,opencode_zen,gemini,huggingface,openai,anthropic
```

If a provider throws an error (bad key, quota, outage), it's logged and the
next provider is tried automatically -- the email always goes out. Enabled
providers with a key in `.env` are picked up automatically; add whichever
keys you have and drop the rest.

## Project layout

```
ai-news-digest/
  run.py              # entry point (--once, scheduler loop, --check-llm, --test-email)
  requirements.txt
  .env.example        # copy to .env and fill in
  .env                # your keys (gitignored, never commit)
  src/
    config.py         # all settings + the RSS source lists
    providers.py      # LLM provider registry + failover chain
    llm.py            # thin re-export shim for providers.py
    sources.py        # RSS/Atom fetchers
    priority.py       # big/unique ("hot") news detection
    seen_store.py     # remembers already-emailed links
    mailer.py         # BREAKING alert + digest emails (Gmail SMTP)
    graph.py          # the LangGraph pipeline
    main.py           # run_once / check_llm helpers
  data/seen.json      # runtime state (auto-created)
  logs/               # optional, for cron/nohup output
```

## Setup

```bash
cd ai-news-digest
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env       # then edit .env
```

### 1. Pick summarizers (`LLM_PROVIDERS` + keys)

| Provider | Enable by setting | Notes |
|---|---|---|
| `ollama` (default first) | `OLLAMA_BASE_URL` / `OLLAMA_MODEL` | `ollama pull llama3.1`, then `ollama serve`. No key needed. |
| `opencode_zen` | `OPENCODE_API_KEY` | Key from https://opencode.ai/auth. Free-tier models: `big-pickle`, `deepseek-v4-flash-free`, `mimo-v2.5-free`, `nemotron-3-super-free`. |
| `gemini` | `GEMINI_API_KEY` | Key from https://aistudio.google.com/apikey. |
| `huggingface` | `HUGGINGFACE_API_KEY` (or `HF_API_KEY`) | Key from https://huggingface.co/settings/tokens. |
| `openai` | `OPENAI_API_KEY` | |
| `anthropic` | `ANTHROPIC_API_KEY` | |

You only need one working provider to start; the rest are failover.

### 2. Gmail SMTP

1. Turn on 2-Step Verification: https://myaccount.google.com/security
2. Create an App Password: https://myaccount.google.com/apppasswords
3. Put your Gmail address + that 16-character app password (not your normal
   password) into `GMAIL_ADDRESS` / `GMAIL_APP_PASSWORD`.

### 3. Test the pieces

```bash
.venv/bin/python run.py --check-llm     # confirms which LLM providers work
.venv/bin/python run.py --test-email    # sends a test email via Gmail
.venv/bin/python run.py --once          # run the pipeline once
```

First real run will likely email you everything currently in the feeds
(nothing's been marked "seen" yet). After that, each run only sends what's new
-- instant BREAKING emails for big/unique stories, and a digest for the rest.

## Running it on a schedule (real-time)

**Option A -- long-running loop (recommended):**

```bash
mkdir -p logs
nohup .venv/bin/python run.py >> logs/run.log 2>&1 &
```

Change how often it checks feeds with `RUN_INTERVAL_SECONDS` in `.env`
(default 300 = every 5 minutes). Lower it for tighter "real-time" alerts.

**Option B -- cron (if you prefer):**

```bash
crontab -e
```

Add (adjust the path to your venv):

```
* * * * * cd /full/path/to/ai-news-digest && /full/path/to/.venv/bin/python run.py --once >> logs/run.log 2>&1
```

## Customizing sources

Edit the lists in `src/config.py`:

- `GENERAL_AI_FEEDS` -- direct RSS feeds (TechCrunch AI, VentureBeat AI, The
  Verge AI, GitHub's generative-AI blog by default). Add any publisher's own
  RSS feed here.
- `POLICY_QUERIES` -- plain-language queries turned into Google News RSS
  searches, so policy/political coverage draws from many authorized outlets at
  once. Edit the query strings to steer coverage.
- `LAB_AI_FEEDS` / `LAB_ANNOUNCE_QUERIES` -- the **AI Lab Updates** section:
  official lab blogs (OpenAI, Google AI, DeepMind, Mistral, Meta, HuggingFace)
  plus announcement searches covering labs without public RSS (Anthropic,
  DeepSeek, Qwen, Moonshot/xAI/Zhipu).
- `AI_TWITTER_ACCOUNTS` (also settable via `AI_TWITTER_ACCOUNTS` in `.env`) --
  the **AI Lab Tweets** section: official X accounts, read as RSS through
  `TWITTER_RSS_TEMPLATE` (RSSHub by default). X blocks anonymous readers and
  public RSSHub instances are usually overloaded, so this section is skipped
  (logged to stdout) unless you point `TWITTER_RSS_TEMPLATE` at a working,
  e.g. self-hosted, RSSHub/Nitter instance.

A feed that's down or slow is skipped for that run (logged to stdout) rather
than breaking the whole pipeline.

## Notes / things you may want to tune

- `HOT_THRESHOLD` (in `.env`, default 65) is the heat score at which a story is
  considered "big/unique" and triggers an instant BREAKING email. Higher = fewer
  alerts. Tune in `src/priority.py` (keyword weights) if stories feel over- or
  under-triggered.
- `MAX_ARTICLES_PER_RUN` caps how many items per category go into one email --
  turn it down if emails feel long.
- `SEEN_TTL_DAYS` controls how long a link is remembered before it could
  theoretically be re-sent.
- Emails are sent as HTML + a plain-text fallback, so they render in any client.
- This is a personal single-user tool -- `data/seen.json` just needs to persist
  between runs, so keep it on the same machine/disk you're running from.
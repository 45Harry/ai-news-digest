# AI News Digest

A small multi-agent pipeline (built with LangGraph) that checks authorized AI
news sources on a schedule and emails you a digest of what's new -- general
AI/product news plus AI policy & political news -- since the last time it ran.

## What it does

```
              -> fetch_general ->\
START ->                            >-> merge -> prioritize -> verify -> send_breaking ->\
              -> fetch_policy  ->/                                                  |       -> summarize -> send_digest -> END
              -> fetch_tweets  ->/           -> END (nothing new)                   |      /  -> END (no regular news)
              -> fetch_labs    ->/                                    -> END (no hot news)
```

- **fetch_general / fetch_policy / fetch_tweets / fetch_labs** (in parallel) pull
  raw items from RSS feeds -- general AI news, policy/politics, AI lab tweets,
  and official lab blogs + announcement searches. See `src/config.py` for the
  lists.
- **merge** de-dupes exact duplicates, drops anything already emailed before
  (tracked in `data/seen.json`), keeps the cap per category, and -- with
  `FILTER_TODAY_ONLY=1` (default) -- only keeps articles **published today**.
  Yesterday's news is never re-sent, so each run is a clean "what's new today".
- **prioritize** flags **big / unique** stories (regulation, court cases, model
  launches, funding rounds, the same story covered by multiple outlets, ...).
- **verify** (LLM) guards what gets mailed, twice:
  1. it merges *near-duplicate* coverage of the same story -- same story on
     several feeds is emailed once, the hottest version wins -- and drops junk
     (off-topic, spam, placeholders). It never rewrites a headline/link/source;
     it only decides which original feed items survive. If the model can't
     answer, everything passes through.
  2. after the overview is generated, the verify model **fact-checks** it
     against the source headlines (no invented facts/numbers) and confirms the
     format check passed (no HTML/markdown/code).
  Hot stories are emailed **immediately as a BREAKING alert** -- real time.
- **summarize** asks the generate model for a structured overview (headline +
  3-5 sentence summary + top themes) as JSON with a *fixed schema*. The verify
  model then validates it (format + hallucination check); anything unclean is
  **regenerated** (up to 3 tries) and only a clean answer is emailed -- if none
  arrives, a fixed plain-text notice goes out. Because the output schema and
  email template are fixed, the email renders **identically no matter which
  LLM/provider wrote it** (gemini, ollama, openai, ...). Every headline, link,
  and source in the email is still taken straight from the feed and can never
  be garbled by the model.
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

### One model per task

Each LLM task has its **own** chain, so you can pair the right model to the job:

```
VERIFY_LLM_PROVIDERS=ollama,gemini    # verify/dedup task -- cheap & fast
OVERVIEW_LLM_PROVIDERS=gemini,ollama  # summary task -- your best writer
```

Tasks with `name@model` syntax can pin a specific model of a provider (e.g.
`ollama@llama3.2`). A task left set to a provider that's down still falls back
within *its own* list. The tasks:

- **verify** (`VERIFY_LLM_PROVIDERS`) -- merges near-duplicate stories and
  drops junk. Suggestion: a small/cheap local model.
- **overview** (`OVERVIEW_LLM_PROVIDERS`) -- writes the structured headline +
  summary + themes. Suggestion: your strongest writing model.

If a task's whole chain fails, that task falls back to a fixed default (no
email is ever blocked). `run.py --check-llm` prints each task's assignment.

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

## Running it on a schedule

The intended setup is **two jobs working together**:

1. **24/7 watcher (already running on this machine) -- real-time BREAKING alerts.**
   A background process checks the feeds every `RUN_INTERVAL_SECONDS` (default
   5 min) and emails **big/unique stories instantly** as they appear. It never
   sends the regular digest -- that's the nightly job's job.

   ```bash
   mkdir -p logs
   nohup .venv/bin/python run.py >> logs/run.log 2>&1 &
   ```

   It survives reboots via `@reboot` in `crontab -e`. Hot stories already
   alerted are recorded in `data/seen.json`, so the nightly digest never
   repeats them.

2. **Nightly digest (cron, 23:30 local / Asia-Kathmandu) -- one email a night.**
   `run.py --once` sends everything published **that day** that you haven't
   already received as a BREAKING alert, in a single email:

   ```
   30 23 * * * cd /full/path/to/ai-news-digest && /full/path/to/.venv/bin/python run.py --once >> logs/run.log 2>&1
   ```

   So: big news hits your inbox the moment it happens, and every evening at
   11:30pm you get one tidy digest of the rest of that day's AI news.
   Duplicates are impossible -- anything already emailed is never re-sent
   (see `FILTER_TODAY_ONLY` + `data/seen.json`).

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
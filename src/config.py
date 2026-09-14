"""Central configuration for the AI News Digest bot.

Everything here is either a hard-coded default (safe to edit directly) or
pulled from environment variables / a local .env file (see .env.example).
"""

import os
from urllib.parse import quote

# ---------------------------------------------------------------------------
# LLM provider chain (used only to write the short overview paragraph at the
# top of each email). Providers are tried in order; the first one that answers
# wins, so a provider that errors (bad key / quota / outage) is skipped and
# the next one gets a chance. See providers.py for the registry.
# ---------------------------------------------------------------------------
DEFAULT_PROVIDER_CHAIN = "ollama,opencode_zen,gemini,huggingface,openai,anthropic"
LLM_PROVIDER = (os.getenv("LLM_PROVIDER") or "").strip().lower()  # optional single-provider override
LLM_PROVIDERS = os.getenv("LLM_PROVIDERS", DEFAULT_PROVIDER_CHAIN)
PROVIDER_CHAIN = [p.strip().lower() for p in LLM_PROVIDERS.split(",") if p.strip()]
if LLM_PROVIDER:
    PROVIDER_CHAIN = [LLM_PROVIDER]

# Ollama -- usually local (http://localhost:11434). Set OLLAMA_API_KEY only if
# your Ollama instance requires auth (e.g. a remote box).
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.1")
OLLAMA_API_KEY = os.getenv("OLLAMA_API_KEY", "")

# OpenCode Zen: OpenAI-compatible endpoint, get a key at https://opencode.ai/auth
OPENCODE_API_KEY = os.getenv("OPENCODE_API_KEY", "")
OPENCODE_BASE_URL = os.getenv("OPENCODE_BASE_URL", "https://opencode.ai/zen/v1")
OPENCODE_MODEL = os.getenv("OPENCODE_MODEL", "big-pickle")  # free tier model; see README for others

# Google Gemini, via its OpenAI-compatible endpoint.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_BASE_URL = os.getenv("GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta/openai")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

# Hugging Face Inference Providers (OpenAI-compatible router).
# Key may be given as HUGGINGFACE_API_KEY or the shorter HF_API_KEY.
HUGGINGFACE_API_KEY = os.getenv("HUGGINGFACE_API_KEY", "") or os.getenv("HF_API_KEY", "")
HUGGINGFACE_BASE_URL = os.getenv("HUGGINGFACE_BASE_URL", "https://router.huggingface.co/v1")
HUGGINGFACE_MODEL = os.getenv("HUGGINGFACE_MODEL", "meta-llama/Llama-3.1-8B-Instruct")

# OpenAI and Anthropic -- only used if their key is set and they are in the chain.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-5")

# ---------------------------------------------------------------------------
# Email (Gmail SMTP)
# ---------------------------------------------------------------------------
GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS", "")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "")
MAIL_TO = os.getenv("MAIL_TO", GMAIL_ADDRESS)

# ---------------------------------------------------------------------------
# Behavior
# ---------------------------------------------------------------------------
RUN_INTERVAL_SECONDS = int(os.getenv("RUN_INTERVAL_SECONDS", "300"))  # how often the loop checks feeds
MAX_ARTICLES_PER_RUN = int(os.getenv("MAX_ARTICLES_PER_RUN", "20"))  # cap per category, per run
SEEN_TTL_DAYS = int(os.getenv("SEEN_TTL_DAYS", "14"))  # how long we remember a link to avoid re-sending it
HOT_THRESHOLD = int(os.getenv("HOT_THRESHOLD", "65"))  # score above which a story is "big/unique" and alerts you
REQUEST_TIMEOUT = 10  # seconds, per feed fetch

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SEEN_STORE_PATH = os.getenv(
    "SEEN_STORE_PATH", os.path.join(_PROJECT_ROOT, "data", "seen.json")
)


def _google_news_rss(query: str) -> str:
    return f"https://news.google.com/rss/search?q={quote(query)}&hl=en-US&gl=US&ceid=US:en"


# ---------------------------------------------------------------------------
# Sources -- edit freely. Anything that returns a standard RSS/Atom feed works.
# ---------------------------------------------------------------------------

# Direct, curated feeds for general AI/product/research news
GENERAL_AI_FEEDS = [
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://venturebeat.com/category/ai/feed/",
    "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "https://github.blog/ai-and-ml/generative-ai/feed/",
]

# Google News search feeds for AI policy / politics / regulation / geopolitics.
# This pulls from many authorized outlets at once and stays fresh without you
# having to track down each publisher's own RSS path.
POLICY_QUERIES = [
    'artificial intelligence regulation OR "AI policy"',
    'artificial intelligence government OR congress OR "white house" OR EU OR law',
    'artificial intelligence geopolitics OR "export controls" OR sanctions OR chips act',
]
POLICY_AI_FEEDS = [_google_news_rss(q) for q in POLICY_QUERIES]

# ---------------------------------------------------------------------------
# AI Lab Updates -- official lab blogs plus announcement searches.
# The most reliable substitute for (and complement to) the labs' tweets; the
# Google-News queries cover labs with no public RSS (Anthropic, DeepSeek, xAI,
# Qwen, Zhipu, Moonshot, ...).
# ---------------------------------------------------------------------------
LAB_AI_FEEDS = [
    "https://openai.com/news/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://deepmind.google/blog/rss.xml",
    "https://mistral.ai/rss.xml",
    "https://about.fb.com/news/feed/",
    "https://huggingface.co/blog/feed.xml",
]
LAB_ANNOUNCE_QUERIES = [
    '"Anthropic" Claude release announcement',
    '"DeepSeek" model release',
    '"Alibaba Qwen" model release',
    '"Moonshot AI" Kimi',
    '"xAI" Grok update',
    '"Zhipu AI" GLM',
]
LAB_ANNOUNCE_FEEDS = [_google_news_rss(q) for q in LAB_ANNOUNCE_QUERIES]
LAB_AI_FEEDS += LAB_ANNOUNCE_FEEDS

# Official X/Twitter accounts of the AI labs we watch. Tweets come in as RSS
# via TWITTER_RSS_TEMPLATE (RSSHub by default) and land in the "AI Lab Tweets"
# section of the email. Comma-separated env override, or edit the default list.
# Note: public RSSHub instances are frequently overloaded and X itself blocks
# anonymous readers, so this section only fills in when you point
# TWITTER_RSS_TEMPLATE at a working (e.g. self-hosted) RSSHub/Nitter instance;
# otherwise it is skipped and the "AI Lab Updates" section above covers the labs.
_DEFAULT_TWITTER_ACCOUNTS = [
    "OpenAI",
    "AnthropicAI",
    "GoogleDeepMind",
    "GoogleAI",
    "GeminiApp",
    "deepseek_ai",
    "Alibaba_Qwen",
    "MoonshotAI",
    "zhipu_ai",
    "MistralAI",
    "xai",
    "AIatMeta",
]
AI_TWITTER_ACCOUNTS = [
    u.strip() for u in os.getenv("AI_TWITTER_ACCOUNTS", ",".join(_DEFAULT_TWITTER_ACCOUNTS)).split(",") if u.strip()
]
TWITTER_RSS_TEMPLATE = os.getenv("TWITTER_RSS_TEMPLATE", "https://rsshub.app/twitter/user/{user}")
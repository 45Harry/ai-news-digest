"""Run a single pipeline pass (fetch -> filter -> alert -> digest)."""

from dotenv import load_dotenv

load_dotenv()

from src.config import LLM_OVERVIEW_PROVIDERS, PROVIDER_CHAIN, LLM_VERIFY_PROVIDERS  # noqa: E402
from src.graph import build_graph  # noqa: E402
from src.mailer import send_test_email  # noqa: E402
from src.providers import check_providers  # noqa: E402


def run_once() -> dict:
    app = build_graph()
    initial_state = {
        "raw_general": [],
        "raw_policy": [],
        "raw_tweets": [],
        "raw_labs": [],
        "new_general": [],
        "new_policy": [],
        "new_tweets": [],
        "new_labs": [],
        "hot_general": [],
        "hot_policy": [],
        "hot_tweets": [],
        "hot_labs": [],
        "normal_general": [],
        "normal_policy": [],
        "normal_tweets": [],
        "normal_labs": [],
        "overview": "",
        "sent": False,
    }
    result = app.invoke(initial_state)

    total_new = (
        len(result.get("new_general", []))
        + len(result.get("new_policy", []))
        + len(result.get("new_tweets", []))
        + len(result.get("new_labs", []))
    )
    total_sent = (
        len(result.get("hot_general", []))
        + len(result.get("hot_policy", []))
        + len(result.get("hot_tweets", []))
        + len(result.get("hot_labs", []))
        + len(result.get("normal_general", []))
        + len(result.get("normal_policy", []))
        + len(result.get("normal_tweets", []))
        + len(result.get("normal_labs", []))
    )
    hot_count = (
        len(result.get("hot_general", []))
        + len(result.get("hot_policy", []))
        + len(result.get("hot_tweets", []))
        + len(result.get("hot_labs", []))
    )
    if result.get("sent"):
        print(f"[main] sent {total_sent} article(s) ({hot_count} breaking) out of {total_new} new.")
    else:
        print("[main] nothing new since last run - no email sent.")
    return result


def check_llm() -> None:
    print(f"[main] provider chain: {', '.join(PROVIDER_CHAIN)}")
    print(f"[main]   verify   task -> {' ,'.join(LLM_VERIFY_PROVIDERS)}")
    print(f"[main]   overview task -> {' ,'.join(LLM_OVERVIEW_PROVIDERS)}")
    results = check_providers()
    if not results:
        print("[main] no providers configured - add keys to .env or start Ollama, then re-run.")
        return
    for r in results:
        status = "OK " if r["ok"] else "FAIL"
        detail = "" if r["ok"] else f" - {r['error']}"
        print(f"[main]   {status} {r['provider']}{detail}")
    if any(r["ok"] for r in results):
        print("[main] at least one working provider - the email overview will be written.")
    else:
        print("[main] NO provider succeeded - emails will use the default overview until fixed.")

    print("Note: the overview chooses the FIRST provider in the chain that answers; a failing")
    print("provider is skipped and the next one is tried automatically.")
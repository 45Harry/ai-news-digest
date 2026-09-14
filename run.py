"""Entry point for the AI News Digest bot.

Usage:
    python run.py --once                # run the pipeline once and exit
    python run.py                       # keep running every RUN_INTERVAL_SECONDS
    python run.py --interval 120        # ... every 2 minutes (real-time-ish)
    python run.py --check-llm           # test every configured LLM provider
    python run.py --test-email          # send a test email to confirm Gmail SMTP

Add your API keys / Gmail credentials to .env (see .env.example) first.
"""

import argparse
import sys
import time
import traceback

from dotenv import load_dotenv

load_dotenv()

from src.config import RUN_INTERVAL_SECONDS  # noqa: E402  (after dotenv)
from src.main import check_llm, run_once, send_test_email  # noqa: E402


def _scheduler(interval: int) -> None:
    print(f"[scheduler] starting; checking feeds every {interval}s (Ctrl+C to stop)")
    while True:
        try:
            run_once()
        except Exception:  # noqa: BLE001 -- keep the loop alive across bad runs
            traceback.print_exc()
        time.sleep(interval)


def _parse_args(argv) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="run.py", description="AI News Digest bot")
    parser.add_argument("--once", action="store_true", help="run the pipeline once, then exit")
    parser.add_argument("--interval", type=int, default=RUN_INTERVAL_SECONDS, help="seconds between runs")
    parser.add_argument("--check-llm", action="store_true", help="test every configured LLM provider")
    parser.add_argument("--test-email", action="store_true", help="send a test email via Gmail SMTP")
    return parser.parse_args(argv)


def main(argv=None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])

    if args.check_llm and args.test_email:
        print("--check-llm and --test-email cannot be combined.")
        return 2
    if args.check_llm:
        check_llm()
        return 0
    if args.test_email:
        send_test_email()
        print("[run] test email sent - check your inbox.")
        return 0
    if args.once:
        run_once()
        return 0

    _scheduler(args.interval)
    return 0


if __name__ == "__main__":
    sys.exit(main())
"""GitHub Actionsとローカル確認用の入口。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from regional_cashless_monitor.monitor import JsonlAuditLog, run_monitor
from regional_cashless_monitor.providers import default_providers
from regional_cashless_monitor.services.calendar import GoogleCalendarWriter
from regional_cashless_monitor.services.discord import DiscordNotifier
from regional_cashless_monitor.state import load_state

JST = ZoneInfo("Asia/Tokyo")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="地域キャッシュレス還元キャンペーン監視")
    parser.add_argument(
        "--mode",
        choices=("auto", "baseline", "run", "dry-run"),
        default=os.getenv("RUN_MODE", "auto"),
        help="autoは初回だけ無通知baseline、その後は通常監視",
    )
    return parser


def main() -> int:
    args = _parser().parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    state_path = Path(os.getenv("STATE_FILE", "state/state.json"))
    log_dir = Path(os.getenv("LOG_DIR", "logs"))
    now = datetime.now(JST)
    audit = JsonlAuditLog(log_dir / f"audit-{now:%Y%m%d-%H%M%S}.jsonl")

    try:
        state = load_state(state_path)
        summary = run_monitor(
            mode=args.mode,
            state=state,
            state_path=state_path,
            providers=default_providers(
                contact=os.getenv("MONITOR_USER_AGENT_CONTACT") or None
            ),
            notifier=DiscordNotifier(os.getenv("DISCORD_WEBHOOK_URL") or None),
            calendar=GoogleCalendarWriter(
                os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or None,
                os.getenv("GOOGLE_CALENDAR_ID") or None,
            ),
            audit=audit,
            now=now,
        )
        print(json.dumps(summary.as_dict(), ensure_ascii=False, indent=2))
        return 1 if summary.errors else 0
    except Exception as exc:
        audit.write("fatal_error", error=repr(exc))
        print(json.dumps({"fatal_error": repr(exc)}, ensure_ascii=False, indent=2))
        return 1


if __name__ == "__main__":
    sys.exit(main())

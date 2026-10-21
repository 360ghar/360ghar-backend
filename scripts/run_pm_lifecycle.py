"""Run the daily PM lifecycle once (overdue charges, late fees, lease expiry).

Use this as a Railway cron job when SERVERLESS_ENABLED=true, because the in-process
scheduler does not run then. Schedule it daily at 19:00 UTC (00:30 IST).

    python -m scripts.run_pm_lifecycle
"""

from __future__ import annotations

import asyncio
import json

from app.services.pm_scheduler import run_pm_daily_lifecycle


def main() -> None:
    print(json.dumps(asyncio.run(run_pm_daily_lifecycle())))


if __name__ == "__main__":
    main()

"""Import the frozen setup D forward test (AMM - APP research/festx_d/results/forward/) into the Trading tab's read-only robot results.

  cd backend && .venv/bin/python -m app.festx_robot_import                 # newest report, shared cloud database
  cd backend && .venv/bin/python -m app.festx_robot_import --sqlite        # local SQLite file instead (testing)

Writes ONLY the festx.robot_trades / festx.robot_meta tables (created if missing; the signals table is never touched). Opens one short connection,
commits each statement, and closes it -- no idle-in-transaction session is left behind. Sends no orders; nothing here touches MT5.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
from pathlib import Path

from dotenv import load_dotenv

from app import festx_signals as fx

FORWARD_DIR = Path.home() / "Desktop" / "AMM - APP" / "research" / "festx_d" / "results" / "forward"


def newest_report(folder: Path) -> tuple[dict, list[dict], Path]:
    reports = sorted(folder.glob("forward_20*.json"))
    if not reports:
        raise SystemExit(f"No forward report in {folder} -- run research/scripts/run_festx_d_forward.py first.")
    rp = reports[-1]
    tp = folder / rp.name.replace("forward_", "forward_trades_").replace(".json", ".csv")
    trades = list(csv.DictReader(tp.open())) if tp.exists() and tp.stat().st_size > 1 else []
    return json.loads(rp.read_text()), trades, rp


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default=str(FORWARD_DIR))
    ap.add_argument("--sqlite", action="store_true")
    args = ap.parse_args()
    report, trades, path = newest_report(Path(args.folder))
    print(f"report {path.name}: verdict {report.get('verdict')!r}, {len(trades)} forward trade rows")
    if args.sqlite:
        out = await fx.import_robot_report("D", report, trades, None)
    else:
        import psycopg
        load_dotenv(Path(__file__).parent.parent / ".env")
        dsn = os.environ.get("CLOUD_POSTGRES_DSN")
        if not dsn:
            raise SystemExit("CLOUD_POSTGRES_DSN is not set in backend/.env")
        async with await psycopg.AsyncConnection.connect(dsn, connect_timeout=20) as conn:
            out = await fx.import_robot_report("D", report, trades, conn)
    d = out.get("D", {})
    print(f"stored: verdict {d.get('verdict')!r}, forward {d.get('forward')}, recent {len(d.get('recent', []))}")


if __name__ == "__main__":
    asyncio.run(main())

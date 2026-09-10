"""Entrypoint: backup -> replicate -> verify against one Postgres target.

    uv run python -m app.migration.run_all \\
        --dsn postgresql://joshuapeters@localhost:5432/pcorp_migration_test
"""

import argparse
import sys
from pathlib import Path

from dotenv import load_dotenv

from app.migration import backup, replicate, verify
from app.migration.replicate import require_local_or_confirmed, resolve_dsn


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Back up, replicate, and verify all SQLite databases against Postgres"
    )
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--confirm-remote", action="store_true")
    args = parser.parse_args()

    load_dotenv(Path(__file__).parent.parent.parent / ".env")
    dsn = resolve_dsn(args.dsn)
    require_local_or_confirmed(dsn, args.confirm_remote)

    manifest_path = backup.run()
    replicate.run(dsn, manifest_path)
    passed = verify.run(dsn, manifest_path)

    print("\nAll domains verified successfully." if passed else "\nVerification FAILED for one or more tables.")
    sys.exit(0 if passed else 1)


if __name__ == "__main__":
    main()

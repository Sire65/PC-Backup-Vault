from __future__ import annotations

import argparse
import json
import sys

from .job_runner import run_job


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PC Backup Vault ProjektFinder Runner")
    parser.add_argument("--profile", required=True, help="Pfad zum Analyseprofil")
    args = parser.parse_args(argv)
    try:
        summary = run_job(args.profile)
        print(json.dumps(summary, ensure_ascii=False))
        return 0
    except Exception as exc:
        print(f"JOB_FAILED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

from __future__ import annotations

import argparse

from .job_runner import run_profile


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PC Backup Vault ProjektFinder Runner")
    parser.add_argument("--profile", required=True, help="Pfad zum Analyseprofil")
    args = parser.parse_args(argv)
    run_profile(args.profile)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""CLI entrypoint for the minimal worker process."""

from __future__ import annotations

import argparse

from backend.config import load_settings
from backend.worker.worker_process import WorkerProcess


def main() -> None:
    parser = argparse.ArgumentParser(description="Run worker process")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one poll cycle and exit",
    )
    args = parser.parse_args()

    worker = WorkerProcess(load_settings())
    if args.once:
        worker.run_once()
        return
    worker.run_forever()


if __name__ == "__main__":
    main()

"""Serve the read-only dashboard on localhost.

Usage:
    uv run --no-sync python scripts/run_dashboard.py [port]
"""

import sys

import uvicorn


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    uvicorn.run("artha.dashboard.app:app", host="127.0.0.1", port=port)


if __name__ == "__main__":
    main()

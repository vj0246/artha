"""Kite Connect morning login: request token -> access token (Track B B2).

Access tokens expire daily. The browser step is manual by design
(automating the login is a Kite ToS question, deliberately not
attempted).

Usage:
    1. uv run --no-sync python scripts/kite_login.py
       Prints the login URL. Open it, log in, and copy the
       ``request_token`` query parameter from the redirect URL.
    2. uv run --no-sync python scripts/kite_login.py <request_token>
       Exchanges it and prints the setx line for KITE_ACCESS_TOKEN.

Requires KITE_API_KEY and KITE_API_SECRET in the environment. The token
value is printed once for you to set; it is never written to disk.
"""

import os
import sys


def main() -> int:
    api_key = os.environ.get("KITE_API_KEY", "")
    api_secret = os.environ.get("KITE_API_SECRET", "")
    if not api_key:
        print("KITE_API_KEY not set; nothing to do", file=sys.stderr)
        return 1

    if len(sys.argv) < 2:
        print(f"login url: https://kite.zerodha.com/connect/login?v=3&api_key={api_key}")
        print("open it, log in, then rerun with the request_token from the redirect url")
        return 0

    if not api_secret:
        print("KITE_API_SECRET not set; cannot exchange the request token", file=sys.stderr)
        return 1
    try:
        from kiteconnect import KiteConnect  # type: ignore[import-not-found]
    except ImportError:
        print("pip install kiteconnect first", file=sys.stderr)
        return 1

    kite = KiteConnect(api_key=api_key)
    session = kite.generate_session(sys.argv[1], api_secret=api_secret)
    token = session["access_token"]
    print("access token obtained. Set it for today's session:")
    print(f'  setx KITE_ACCESS_TOKEN "{token}"')
    print("(new shells only; for the scheduled task, update its environment)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

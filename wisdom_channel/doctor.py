"""`wisdom-channel doctor` — connectivity & config check."""

from __future__ import annotations

import asyncio
import sys


async def _check() -> int:
    # Import lazily so that `--help` etc. doesn't pull in httpx / loguru noise.
    import httpx

    from wisdom_channel.config import WISDOM_API_TOKEN, WISDOM_API_URL, WISDOM_WS_URL

    print(f"WISDOM_API_URL = {WISDOM_API_URL}")
    print(f"WISDOM_API_TOKEN = {'***' + WISDOM_API_TOKEN[-4:] if WISDOM_API_TOKEN else '(empty)'}")
    print(f"WISDOM_WS_URL = {WISDOM_WS_URL.split('?')[0]}")
    print()

    ok = True

    if not WISDOM_API_TOKEN:
        print("FAIL: WISDOM_API_TOKEN is empty. Run `wisdom-channel init` first.")
        ok = False

    # Probe the REST endpoint. /health is the conventional liveness path; fall
    # back to / if /health 404s so we still pick up wrong-host errors.
    try:
        async with httpx.AsyncClient(timeout=10.0) as c:
            for path in ("/health", "/"):
                url = f"{WISDOM_API_URL.rstrip('/')}{path}"
                try:
                    r = await c.get(url)
                except httpx.HTTPError as e:
                    print(f"FAIL: HTTP error on {url}: {e}")
                    ok = False
                    break
                if r.status_code < 500:
                    print(f"OK: {url} -> {r.status_code}")
                    break
            else:
                print("FAIL: no responsive REST endpoint")
                ok = False
    except Exception as e:
        print(f"FAIL: unexpected error: {e}")
        ok = False

    print()
    print("doctor:", "all green" if ok else "issues detected")
    return 0 if ok else 1


def run() -> int:
    return asyncio.run(_check())


if __name__ == "__main__":
    sys.exit(run())

"""Entry point: python -m wisdom_channel [init|doctor|--test]"""

import asyncio
import sys


def _main() -> None:
    argv = sys.argv[1:]
    cmd = argv[0] if argv else ""

    if cmd == "init":
        from wisdom_channel.init import run

        sys.exit(run())
    if cmd == "doctor":
        from wisdom_channel.doctor import run

        sys.exit(run())
    if cmd in ("-h", "--help", "help"):
        print("Usage: wisdom-channel [init|doctor|--test]")
        print()
        print("  (no args)   Run the MCP channel server (stdio transport)")
        print("  init        Interactively configure WISDOM_API_URL / WISDOM_API_TOKEN")
        print("  doctor      Verify configuration and connectivity to the Wisdom API")
        print("  --test      Run a one-off connectivity smoke test against the WS endpoint")
        sys.exit(0)

    if "--test" in argv:
        from wisdom_channel.server import test_standalone

        asyncio.run(test_standalone())
    else:
        from wisdom_channel.server import main

        asyncio.run(main())


if __name__ == "__main__":
    _main()

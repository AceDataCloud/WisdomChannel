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
    if cmd == "access":
        from wisdom_channel.access_cli import run

        sys.exit(run(argv[1:]))
    if cmd == "bridge":
        from wisdom_channel.bridge import run_bridge

        has_model = "--model" in argv and argv.index("--model") + 1 < len(argv)
        model = argv[argv.index("--model") + 1] if has_model else "sonnet"
        sys.exit(asyncio.run(run_bridge(model)) or 0)
    if cmd in ("-h", "--help", "help"):
        print("Usage: wisdom-channel [init|doctor|access|bridge|--test]")
        print()
        print("  (no args)   Run the MCP channel server (stdio transport)")
        print("  init        Interactively configure connection + access allowlist")
        print("  doctor      Verify configuration and connectivity to the Wisdom API")
        print("  access      View/edit access policy from the local terminal")
        print("  bridge      Headless auto-reply loop (Wisdom WS -> claude -p -> reply);")
        print("              for hosts with no persistent interactive Claude Code session")
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

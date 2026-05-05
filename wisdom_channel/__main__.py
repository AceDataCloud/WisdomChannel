"""Entry point: python -m wisdom_channel [--test]"""

import asyncio
import sys


def _main() -> None:
    if "--test" in sys.argv:
        from wisdom_channel.server import test_standalone

        asyncio.run(test_standalone())
    else:
        from wisdom_channel.server import main

        asyncio.run(main())


if __name__ == "__main__":
    _main()

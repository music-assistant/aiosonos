"""Example script for the package."""

from __future__ import annotations

import argparse
import asyncio
import logging
from typing import Final

from aiohttp import ClientSession

from aiosonos import SonosLocalApiClient
from aiosonos.const import LOG_LEVEL_VERBOSE

logging.basicConfig(level=logging.DEBUG)

FORMAT_DATE: Final = "%Y-%m-%d"
FORMAT_TIME: Final = "%H:%M:%S"
FORMAT_DATETIME: Final = f"{FORMAT_DATE} {FORMAT_TIME}"

# Get parsed passed in arguments.
parser = argparse.ArgumentParser(description="AIOSonos Client Example.")
parser.add_argument(
    "player_ip",
    type=str,
    help="IP address of the Sonos player.",
)
parser.add_argument(
    "--log-level",
    type=str,
    default="info",
    help="Provide logging level. Example --log-level debug, default=info, "
    "possible=(critical, error, warning, info, debug, verbose)",
)

args = parser.parse_args()


if __name__ == "__main__":
    # configure basic logging
    log_fmt = "%(asctime)s.%(msecs)03d %(levelname)s (%(threadName)s) [%(name)s] %(message)s"
    logging.addLevelName(LOG_LEVEL_VERBOSE, "VERBOSE")
    logging.basicConfig(format=log_fmt, datefmt=FORMAT_DATETIME, level=args.log_level.upper())
    logging.getLogger("asyncio").setLevel(logging.INFO)

    logger = logging.getLogger(__name__)

    def on_event(event: dict) -> None:
        """Handle event."""
        logger.debug("Event: %s", event)

    async def run_client() -> None:
        """Run the SonosApi client."""
        # run the client
        async with ClientSession() as session, SonosLocalApiClient(
            args.player_ip,
            session,
        ) as client:
            # subscribe to all events to simply log them
            client.subscribe(on_event)
            # start listening
            await client.start_listening()

    # run the server
    asyncio.run(run_client(), debug=args.log_level.upper() == "DEBUG")

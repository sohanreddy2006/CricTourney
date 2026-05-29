from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import discord
from discord.ext import commands

from config import configure_logging, load_settings
from database.connection import close_db, init_db


LOGGER = logging.getLogger(__name__)
BASE_DIR = Path(__file__).resolve().parent


class CricketGuruBot(commands.Bot):
    def __init__(self, settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

        super().__init__(
            command_prefix=settings.prefix,
            intents=intents,
            help_command=None,
        )
        self.settings = settings
        self._synced_commands = False

    async def setup_hook(self) -> None:
        await init_db(self.settings.database_url)
        await self._load_cogs()

    async def _load_cogs(self) -> None:
        cogs_dir = BASE_DIR / "cogs"
        if not cogs_dir.exists():
            LOGGER.warning("Cogs directory not found: %s", cogs_dir)
            return

        for cog_file in sorted(cogs_dir.glob("*.py")):
            if cog_file.name.startswith("_") or cog_file.stem == "__init__":
                continue

            extension = f"cogs.{cog_file.stem}"
            await self.load_extension(extension)
            LOGGER.info("Loaded cog: %s", extension)

    async def on_ready(self) -> None:
        if not self._synced_commands:
            synced = await self.tree.sync()
            self._synced_commands = True
            LOGGER.info("Synced %s slash commands", len(synced))

        if self.user:
            LOGGER.info("Cricket Guru is online as %s (%s)", self.user, self.user.id)

    async def close(self) -> None:
        await close_db()
        await super().close()


async def main() -> None:
    settings = load_settings()
    configure_logging(settings.log_level)

    bot = CricketGuruBot(settings)
    await bot.start(settings.discord_token)


if __name__ == "__main__":
    asyncio.run(main())

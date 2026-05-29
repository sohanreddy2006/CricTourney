from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timezone

import discord


BRAND_COLOR = discord.Color(0x1A237E)
BRAND_NAME = "Cricket Guru"


def cricket_embed(
    *,
    title: str,
    description: str | None = None,
    fields: Iterable[tuple[str, str, bool]] | None = None,
    color: discord.Color = BRAND_COLOR,
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc),
    )
    embed.set_footer(text=BRAND_NAME)

    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)

    return embed


def error_embed(message: str) -> discord.Embed:
    return cricket_embed(title="Action Failed", description=message, color=discord.Color.red())


def success_embed(title: str, message: str) -> discord.Embed:
    return cricket_embed(title=title, description=message, color=discord.Color.green())

from __future__ import annotations

import discord
from discord.ext import commands

from database.queries import get_organizer_role_id


DEFAULT_ORGANIZER_ROLE_NAME = "Organizer"


async def is_organizer(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True

    organizer_role_id = await get_organizer_role_id(member.guild.id)
    if organizer_role_id is not None:
        return any(role.id == organizer_role_id for role in member.roles)

    return any(role.name == DEFAULT_ORGANIZER_ROLE_NAME for role in member.roles)


def organizer_only() -> commands.Check:
    async def predicate(ctx: commands.Context) -> bool:
        if ctx.guild is None or not isinstance(ctx.author, discord.Member):
            return False
        return await is_organizer(ctx.author)

    return commands.check(predicate)

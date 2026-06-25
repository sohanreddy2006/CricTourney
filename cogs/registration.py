from __future__ import annotations

import importlib
import logging
from collections.abc import Iterable
from typing import Any

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

from database import queries
from utils.embeds import cricket_embed, error_embed, success_embed


LOGGER = logging.getLogger(__name__)

FORMAT_LABELS = {
    "single_elimination": "Single Elimination",
    "round_robin": "Round Robin",
    "group_knockout": "Group Stage -> Knockout",
}


def format_label(value: str) -> str:
    return FORMAT_LABELS.get(value, value.replace("_", " ").title())


def participant_line(index: int, participant: Any) -> str:
    group = participant["group_name"]
    suffix = f" — Group {group}" if group else ""
    return f"{index}. {participant['username']} — OVR {participant['ovr']}{suffix}"


def chunk_lines(lines: Iterable[str], *, max_chars: int = 950) -> list[str]:
    chunks: list[str] = []
    current: list[str] = []
    current_size = 0

    for line in lines:
        line_size = len(line) + 1
        if current and current_size + line_size > max_chars:
            chunks.append("\n".join(current))
            current = []
            current_size = 0

        current.append(line)
        current_size += line_size

    if current:
        chunks.append("\n".join(current))

    return chunks


async def call_matchup_generator(
    bot: commands.Bot,
    guild: discord.Guild,
    tournament: Any,
    source_channel: discord.abc.Messageable,
) -> None:
    try:
        module = importlib.import_module("cogs.matchups")
        generator = getattr(module, "generate_matchups_for_tournament")
    except (ImportError, AttributeError):
        await source_channel.send(
            embed=cricket_embed(
                title="Matchups Pending",
                description=(
                    "Registration is full. The matchup generator will be available after the matchups stage is added."
                ),
            )
        )
        return

    try:
        await generator(bot, guild, tournament)
    except Exception:
        LOGGER.exception("Automatic matchup generation failed")
        await source_channel.send(embed=error_embed("Automatic matchup generation failed."))


class RegistrationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def current_tournament_for_display(self, guild_id: int):
        return await queries.get_active_tournament(guild_id)

    @commands.hybrid_command(name="register", description="Register for the active Cricket Guru tournament.")
    @app_commands.describe(username="Your tournament display name.", ovr="Your team/player OVR rating.")
    async def register(self, ctx: commands.Context, username: str, ovr: int) -> None:
        if ctx.guild is None:
            await ctx.send(embed=error_embed("This command can only be used in a server."))
            return

        tournament = await queries.get_registration_tournament(ctx.guild.id)
        if tournament is None:
            active = await queries.get_active_tournament(ctx.guild.id)
            if active is None:
                await ctx.send(embed=error_embed("There is no tournament open for registration."))
            else:
                await ctx.send(embed=error_embed("Registrations are closed for the current tournament."))
            return

        if ovr < tournament["ovr_min"]:
            await ctx.send(
                embed=error_embed(
                    f"Your OVR ({ovr}) is below the minimum required ({tournament['ovr_min']}) for this tournament."
                )
            )
            return

        existing = await queries.get_participant_by_discord_id(tournament["id"], ctx.author.id)
        if existing is not None:
            await ctx.send(embed=error_embed("You are already registered for this tournament."))
            return

        current_count = await queries.count_participants(tournament["id"])
        if current_count >= tournament["participant_cap"]:
            await ctx.send(embed=error_embed("This tournament is already full."))
            return

        try:
            await queries.add_participant(
                tournament_id=tournament["id"],
                discord_id=ctx.author.id,
                username=username,
                ovr=ovr,
            )
        except asyncpg.UniqueViolationError:
            await ctx.send(embed=error_embed("You are already registered for this tournament."))
            return

        new_count = await queries.count_participants(tournament["id"])
        await ctx.send(
            embed=success_embed(
                "Registration Confirmed",
                f"{username} is registered with OVR {ovr}.\nSlot: {new_count}/{tournament['participant_cap']}",
            )
        )

        if new_count >= tournament["participant_cap"]:
            registration_channel = ctx.guild.get_channel(tournament["registration_channel_id"])
            if isinstance(registration_channel, discord.TextChannel):
                close_embed = cricket_embed(
                    title="Registrations Closed",
                    description=(
                        f"**🔒 Registrations are now CLOSED! "
                        f"{new_count} players have joined the tournament.**"
                    ),
                )
                await registration_channel.send(embed=close_embed)
                await call_matchup_generator(self.bot, ctx.guild, tournament, registration_channel)
            else:
                await call_matchup_generator(self.bot, ctx.guild, tournament, ctx.channel)

    @commands.hybrid_command(name="view-participants", description="View registered tournament participants.")
    async def view_participants(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send(embed=error_embed("This command can only be used in a server."))
            return

        tournament = await self.current_tournament_for_display(ctx.guild.id)
        if tournament is None:
            await ctx.send(embed=error_embed("There is no active tournament."))
            return

        participants = await queries.list_participants(tournament["id"])
        count = len(participants)
        title = f"Registered Participants ({count}/{tournament['participant_cap']})"

        if not participants:
            await ctx.send(embed=cricket_embed(title=title, description="No players have registered yet."))
            return

        lines = [participant_line(index, participant) for index, participant in enumerate(participants, start=1)]
        chunks = chunk_lines(lines)
        embed = cricket_embed(title=title)

        for index, chunk in enumerate(chunks, start=1):
            field_name = "Players" if index == 1 else f"Players {index}"
            embed.add_field(name=field_name, value=chunk, inline=False)

        await ctx.send(embed=embed)

    @commands.hybrid_command(name="tournament-info", description="Show the current Cricket Guru tournament details.")
    async def tournament_info(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send(embed=error_embed("This command can only be used in a server."))
            return

        tournament = await self.current_tournament_for_display(ctx.guild.id)
        if tournament is None:
            await ctx.send(embed=error_embed("There is no active tournament."))
            return

        registered_count = await queries.count_participants(tournament["id"])
        current_round = str(tournament["current_round"]) if tournament["status"] == "active" else "Not started"
        fields = [
            ("Name", tournament["name"], False),
            ("Format", format_label(tournament["format"]), True),
            ("Status", tournament["status"].title(), True),
            ("OVR Min", f"{tournament['ovr_min']}+", True),
            ("Cap", str(tournament["participant_cap"]), True),
            ("Registered", f"{registered_count}/{tournament['participant_cap']}", True),
            ("Current Round", current_round, True),
        ]

        await ctx.send(embed=cricket_embed(title="Tournament Info", fields=fields))

    @commands.hybrid_command(name="my-match", description="Show your current tournament match.")
    async def my_match(self, ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send(embed=error_embed("This command can only be used in a server."))
            return

        tournament = await self.current_tournament_for_display(ctx.guild.id)
        if tournament is None:
            await ctx.send(embed=error_embed("There is no active tournament."))
            return

        participant = await queries.get_participant_by_discord_id(tournament["id"], ctx.author.id)
        if participant is None:
            await ctx.send(embed=error_embed("You are not registered for this tournament."))
            return

        match = await queries.get_pending_match_for_participant(tournament["id"], participant["id"])
        if match is None:
            await ctx.send(embed=cricket_embed(title="My Match", description="You have no active match in this tournament."))
            return

        opponent_id = match["participant_2"] if match["participant_1"] == participant["id"] else match["participant_1"]
        opponent = await queries.get_participant(opponent_id) if opponent_id is not None else None
        if opponent is None:
            await ctx.send(embed=cricket_embed(title="My Match", description="You have no active match in this tournament."))
            return

        await ctx.send(
            embed=cricket_embed(
                title="My Match",
                description=(
                    f"Your match: #{match['match_id']} vs {opponent['username']} "
                    f"(OVR {opponent['ovr']}) — {match['round_name']}"
                ),
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RegistrationCog(bot))

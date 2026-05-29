from __future__ import annotations

from collections.abc import Callable, Awaitable
from typing import TypeVar

import asyncpg
import discord
from discord import app_commands
from discord.ext import commands

from database import queries
from utils.checks import is_organizer, organizer_only
from utils.embeds import cricket_embed, error_embed, success_embed


T = TypeVar("T")

FORMAT_LABELS = {
    "single_elimination": "Single Elimination",
    "round_robin": "Round Robin",
    "group_knockout": "Group Stage -> Knockout",
}


class SetupCancelled(Exception):
    pass


def format_label(value: str) -> str:
    return FORMAT_LABELS.get(value, value.replace("_", " ").title())


def build_registration_announcement(name: str, tournament_format: str, ovr_min: int, cap: int) -> discord.Embed:
    return cricket_embed(
        title="Registrations Open",
        description=(
            f"🏏 {name} is now open for registration!\n"
            f"Format: {format_label(tournament_format)} | OVR Min: {ovr_min}+ | Cap: {cap}\n"
            "Use /register username:<your_name> ovr:<your_rating> to join!"
        ),
    )


class OwnedView(discord.ui.View):
    def __init__(self, owner_id: int, *, timeout: float = 60.0) -> None:
        super().__init__(timeout=timeout)
        self.owner_id = owner_id
        self.message: discord.Message | None = None

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id == self.owner_id:
            return True

        await interaction.response.send_message(
            "Only the organizer who started this action can use these buttons.",
            ephemeral=True,
        )
        return False

    async def on_timeout(self) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        if self.message is not None:
            await self.message.edit(view=self)


class CancelCurrentTournamentView(OwnedView):
    @discord.ui.button(label="Cancel current tournament", style=discord.ButtonStyle.danger)
    async def cancel_current(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if interaction.guild is None or not isinstance(interaction.user, discord.Member):
            await interaction.response.send_message("This button can only be used in a server.", ephemeral=True)
            return

        if not await is_organizer(interaction.user):
            await interaction.response.send_message("You do not have permission to cancel tournaments.", ephemeral=True)
            return

        cancelled = await queries.cancel_active_tournament(interaction.guild.id)
        if cancelled is None:
            embed = error_embed("There is no active tournament to cancel.")
        else:
            embed = success_embed(
                "Tournament Cancelled",
                f"`{cancelled['name']}` has been cancelled.",
            )

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        await interaction.response.edit_message(embed=embed, view=self)


class ConfirmTournamentView(OwnedView):
    def __init__(
        self,
        owner_id: int,
        payload: dict,
        registration_channel: discord.TextChannel,
    ) -> None:
        super().__init__(owner_id)
        self.payload = payload
        self.registration_channel = registration_channel

    @discord.ui.button(label="✅ Confirm", style=discord.ButtonStyle.success)
    async def confirm(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        if interaction.guild is None:
            await interaction.response.send_message("This command can only be used in a server.", ephemeral=True)
            return

        await interaction.response.defer()

        active = await queries.get_active_tournament(interaction.guild.id)
        if active is not None:
            embed = error_embed(f"`{active['name']}` is already active for this server.")
            view = CancelCurrentTournamentView(interaction.user.id)
            await interaction.message.edit(embed=embed, view=view)
            view.message = interaction.message
            return

        try:
            tournament = await queries.create_tournament(**self.payload)
        except asyncpg.UniqueViolationError:
            embed = error_embed("Another tournament is already active for this server.")
            view = CancelCurrentTournamentView(interaction.user.id)
            await interaction.message.edit(embed=embed, view=view)
            view.message = interaction.message
            return

        announcement = build_registration_announcement(
            tournament["name"],
            tournament["format"],
            tournament["ovr_min"],
            tournament["participant_cap"],
        )
        await self.registration_channel.send(embed=announcement)

        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        embed = success_embed(
            "Tournament Created",
            f"`{tournament['name']}` is now open for registration in {self.registration_channel.mention}.",
        )
        await interaction.message.edit(embed=embed, view=self)

    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(
        self,
        interaction: discord.Interaction,
        _button: discord.ui.Button,
    ) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = True

        await interaction.response.edit_message(
            embed=error_embed("Tournament creation cancelled."),
            view=self,
        )


class SetupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def ask(
        self,
        ctx: commands.Context,
        title: str,
        prompt: str,
        parser: Callable[[str], Awaitable[T]],
        *,
        timeout: float = 120.0,
    ) -> T:
        await ctx.send(
            embed=cricket_embed(
                title=title,
                description=f"{prompt}\n\nType `cancel` to stop setup.",
            )
        )

        def check(message: discord.Message) -> bool:
            return (
                message.author.id == ctx.author.id
                and message.channel.id == ctx.channel.id
                and not message.author.bot
            )

        while True:
            try:
                message = await self.bot.wait_for("message", timeout=timeout, check=check)
            except TimeoutError as exc:
                raise SetupCancelled("Tournament setup timed out.") from exc

            content = message.content.strip()
            if content.lower() == "cancel":
                raise SetupCancelled("Tournament setup cancelled.")

            try:
                return await parser(content)
            except ValueError as exc:
                await ctx.send(embed=error_embed(str(exc)))

    async def parse_int(self, content: str, *, minimum: int | None = None, maximum: int | None = None) -> int:
        try:
            value = int(content)
        except ValueError as exc:
            raise ValueError("Please enter a whole number.") from exc

        if minimum is not None and value < minimum:
            raise ValueError(f"Please enter a number at least {minimum}.")
        if maximum is not None and value > maximum:
            raise ValueError(f"Please enter a number no higher than {maximum}.")

        return value

    async def parse_bool(self, content: str) -> bool:
        lowered = content.lower()
        if lowered in {"yes", "y", "true", "1"}:
            return True
        if lowered in {"no", "n", "false", "0"}:
            return False
        raise ValueError("Please reply with `yes` or `no`.")

    async def parse_channel(self, ctx: commands.Context, content: str) -> discord.TextChannel:
        if content.lower() in {"here", "current"}:
            if isinstance(ctx.channel, discord.TextChannel):
                return ctx.channel
            raise ValueError("The current channel is not a text channel.")

        converter = commands.TextChannelConverter()
        try:
            return await converter.convert(ctx, content)
        except commands.BadArgument as exc:
            raise ValueError("Please mention a text channel, like #tournament-registration.") from exc

    @commands.hybrid_command(name="create-tournament", description="Start the Cricket Guru tournament setup wizard.")
    @app_commands.describe(
        name="Tournament name.",
        format="Tournament format.",
        cap="Maximum number of players.",
    )
    @app_commands.choices(
        format=[
            app_commands.Choice(name="Single Elimination", value="single_elimination"),
            app_commands.Choice(name="Round Robin", value="round_robin"),
            app_commands.Choice(name="Group Stage -> Knockout", value="group_knockout"),
        ]
    )
    @organizer_only()
    async def create_tournament(
        self,
        ctx: commands.Context,
        name: str,
        format: str,
        cap: int,
    ) -> None:
        if ctx.guild is None:
            await ctx.send(embed=error_embed("This command can only be used in a server."))
            return

        if format not in FORMAT_LABELS:
            await ctx.send(embed=error_embed("Choose one of: single_elimination, round_robin, group_knockout."))
            return

        if cap < 2:
            await ctx.send(embed=error_embed("cap must be at least 2."))
            return

        active = await queries.get_active_tournament(ctx.guild.id)
        if active is not None:
            view = CancelCurrentTournamentView(ctx.author.id)
            message = await ctx.send(
                embed=error_embed(f"`{active['name']}` is already active for this server."),
                view=view,
            )
            view.message = message
            return

        await ctx.send(
            embed=cricket_embed(
                title="Tournament Setup Started",
                description=(
                    f"Name: `{name}`\n"
                    f"Format: `{format_label(format)}`\n"
                    f"Cap: `{cap}`\n\n"
                    "I will ask the remaining setup questions one by one."
                ),
            )
        )

        try:
            ovr_min = await self.ask(
                ctx,
                "Step 1: OVR Minimum",
                "Enter the minimum OVR required to register. Use `0` for no restriction.",
                lambda value: self.parse_int(value, minimum=0),
            )

            use_groups = False
            group_size: int | None = None
            group_advance_count = 2
            rr_advance_count = 2

            if format == "round_robin":
                rr_advance_count = await self.ask(
                    ctx,
                    "Step 2: Round Robin Advance Count",
                    "How many players should advance after round robin? Enter `1`, `2`, or `3`.",
                    lambda value: self.parse_int(value, minimum=1, maximum=3),
                )

            if format == "group_knockout":
                use_groups = await self.ask(
                    ctx,
                    "Step 2: Groups",
                    "Use groups for the group stage? Reply `yes` or `no`.",
                    self.parse_bool,
                )
                if use_groups:
                    group_size = await self.ask(
                        ctx,
                        "Step 3: Group Size",
                        "Enter the maximum number of players per group.",
                        lambda value: self.parse_int(value, minimum=2),
                    )
                group_advance_count = await self.ask(
                    ctx,
                    "Step 4: Group Advance Count",
                    "How many players advance from each group? Enter at least `1`.",
                    lambda value: self.parse_int(value, minimum=1),
                )

            registration_channel = await self.ask(
                ctx,
                "Channels: Registration",
                "Mention the registration channel, or type `here` to use this channel.",
                lambda value: self.parse_channel(ctx, value),
            )
            matchups_channel = await self.ask(
                ctx,
                "Channels: Matchups",
                "Mention the matchups channel, or type `here` to use this channel.",
                lambda value: self.parse_channel(ctx, value),
            )
            results_channel = await self.ask(
                ctx,
                "Channels: Results",
                "Mention the results channel, or type `here` to use this channel.",
                lambda value: self.parse_channel(ctx, value),
            )
            bracket_channel = await self.ask(
                ctx,
                "Channels: Bracket",
                "Mention the bracket channel, or type `here` to use this channel.",
                lambda value: self.parse_channel(ctx, value),
            )
        except SetupCancelled as exc:
            await ctx.send(embed=error_embed(str(exc)))
            return

        stage = "group" if format == "group_knockout" else "knockout"
        fields = [
            ("Name", name, False),
            ("Format", format_label(format), True),
            ("Cap", str(cap), True),
            ("OVR Min", f"{ovr_min}+", True),
            ("Registration", registration_channel.mention, True),
            ("Matchups", matchups_channel.mention, True),
            ("Results", results_channel.mention, True),
            ("Bracket", bracket_channel.mention, True),
            ("Use Groups", "Yes" if use_groups else "No", True),
            ("Group Size", str(group_size) if group_size else "N/A", True),
            ("Group Advance Count", str(group_advance_count), True),
            ("Round Robin Advance Count", str(rr_advance_count), True),
        ]
        embed = cricket_embed(
            title="Confirm Tournament",
            description="Review the tournament settings below before creating it.",
            fields=fields,
        )

        payload = {
            "guild_id": ctx.guild.id,
            "name": name,
            "tournament_format": format,
            "participant_cap": cap,
            "created_by": ctx.author.id,
            "registration_channel_id": registration_channel.id,
            "matchups_channel_id": matchups_channel.id,
            "results_channel_id": results_channel.id,
            "bracket_channel_id": bracket_channel.id,
            "ovr_min": ovr_min,
            "use_groups": use_groups,
            "group_size": group_size,
            "group_advance_count": group_advance_count,
            "rr_advance_count": rr_advance_count,
            "stage": stage,
        }

        view = ConfirmTournamentView(ctx.author.id, payload, registration_channel)
        message = await ctx.send(embed=embed, view=view)
        view.message = message

    @commands.hybrid_command(name="set-organizer-role", description="Set the role that can manage tournaments.")
    @app_commands.describe(role="Role allowed to run organizer commands.")
    @app_commands.default_permissions(administrator=True)
    @commands.has_guild_permissions(administrator=True)
    async def set_organizer_role(self, ctx: commands.Context, role: discord.Role) -> None:
        if ctx.guild is None:
            await ctx.send(embed=error_embed("This command can only be used in a server."))
            return

        await queries.set_organizer_role(ctx.guild.id, role.id)
        await ctx.send(
            embed=success_embed(
                "Organizer Role Updated",
                f"{role.mention} can now run Cricket Guru organizer commands.",
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SetupCog(bot))

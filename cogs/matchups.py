from __future__ import annotations

import io
import math
import random
from collections import defaultdict
from typing import Any

import discord
from discord.ext import commands

from database import queries
from utils.bracket_renderer import render_bracket, render_standings
from utils.checks import organizer_only
from utils.embeds import cricket_embed, error_embed, success_embed


ROUND_NAMES = {
    1: "Final",
    2: "Semi Finals",
    3: "Quarter Finals",
}


def round_name_for_knockout(total_rounds: int, round_number: int) -> str:
    remaining = total_rounds - round_number + 1
    return ROUND_NAMES.get(remaining, f"Round {round_number}")


def mention(participant: Any) -> str:
    return f"<@{participant['discord_id']}>"


def participant_label(participant: Any) -> str:
    return f"{participant['username']} (OVR {participant['ovr']})"


def next_power_of_two(value: int) -> int:
    if value <= 1:
        return 1
    return 2 ** math.ceil(math.log2(value))


def pair_adjacent(participants: list[Any]) -> tuple[list[tuple[Any, Any]], Any | None]:
    pairs = []
    bye = None
    for index in range(0, len(participants), 2):
        if index + 1 >= len(participants):
            bye = participants[index]
        else:
            pairs.append((participants[index], participants[index + 1]))
    return pairs, bye


def group_names() -> list[str]:
    return [chr(code) for code in range(ord("A"), ord("Z") + 1)]


async def assign_groups(tournament: Any, participants: list[Any]) -> list[Any]:
    if tournament["format"] != "group_knockout" or not tournament["use_groups"]:
        return participants

    shuffled = participants[:]
    random.shuffle(shuffled)
    size = tournament["group_size"] or max(len(shuffled), 1)
    assignments = []
    names = group_names()

    for index, participant in enumerate(shuffled):
        group_name = names[index // size]
        assignments.append((participant["id"], group_name))

    await queries.set_participant_groups(assignments)
    return await queries.list_participants(tournament["id"])


def first_round_robin_pairs(participants: list[Any]) -> list[tuple[Any, Any]]:
    shuffled = participants[:]
    random.shuffle(shuffled)
    pairs, _bye = pair_adjacent(shuffled)
    return pairs


def build_match_render_rows(matches: list[Any], participants_by_id: dict[int, Any]) -> list[dict]:
    rows = []
    for match in matches:
        p1 = participants_by_id.get(match["participant_1"])
        p2 = participants_by_id.get(match["participant_2"]) if match["participant_2"] is not None else None
        winner = participants_by_id.get(match["winner_id"]) if match["winner_id"] is not None else None
        rows.append(
            {
                "match_id": match["match_id"],
                "p1_username": p1["username"] if p1 else "TBD",
                "p1_ovr": p1["ovr"] if p1 else None,
                "p2_username": p2["username"] if p2 else None,
                "p2_ovr": p2["ovr"] if p2 else None,
                "winner_username": winner["username"] if winner else None,
                "status": match["status"],
            }
        )
    return rows


def build_standing_rows(participants: list[Any]) -> list[dict]:
    return [
        {
            "username": (
                f"{participant['group_name']}: {participant['username']}"
                if participant["group_name"]
                else participant["username"]
            ),
            "ovr": participant["ovr"],
            "wins": 0,
            "losses": 0,
            "points": 0,
        }
        for participant in participants
    ]


async def send_matchup_embed(
    channel: discord.TextChannel,
    *,
    title: str,
    matches: list[Any],
    participants_by_id: dict[int, Any],
    group_name: str | None = None,
) -> None:
    lines = []
    pings = []
    for match in matches:
        p1 = participants_by_id.get(match["participant_1"])
        p2 = participants_by_id.get(match["participant_2"]) if match["participant_2"] is not None else None
        if p1 is None:
            continue

        if match["status"] == "bye" or p2 is None:
            lines.append(f"#{match['match_id']}  {participant_label(p1)} has a BYE")
            pings.append(mention(p1))
            continue

        lines.append(f"#{match['match_id']}  {participant_label(p1)} vs {participant_label(p2)}")
        pings.extend([mention(p1), mention(p2)])

    if not lines:
        lines.append("No playable matches in this round.")

    description = "\n".join(lines)
    if pings:
        description += "\n\n" + " ".join(pings)
    description += "\n\nUse /my-match to see your match details."
    description += "\nPost results using /post-result match_id:<number> winner:<@player>"

    embed_title = title if group_name is None else f"{title} - Group {group_name}"
    await channel.send(embed=cricket_embed(title=embed_title, description=description))


async def post_bracket_image(
    channel: discord.TextChannel,
    *,
    tournament: Any,
    round_name: str,
    matches: list[Any],
    participants: list[Any],
    group_name: str | None = None,
) -> discord.Message:
    participants_by_id = {participant["id"]: participant for participant in participants}
    if tournament["format"] in {"round_robin", "group_knockout"}:
        image_bytes = await render_standings(build_standing_rows(participants), group_name)
        filename = "standings.png"
    else:
        image_bytes = await render_bracket(
            build_match_render_rows(matches, participants_by_id),
            round_name,
            tournament["name"],
        )
        filename = "bracket.png"

    file = discord.File(io.BytesIO(image_bytes), filename=filename)
    return await channel.send(file=file)


async def generate_single_elimination(
    tournament: Any,
    participants: list[Any],
) -> tuple[list[Any], list[Any], int, str]:
    shuffled = participants[:]
    random.shuffle(shuffled)
    total_rounds = math.ceil(math.log2(max(len(shuffled), 2)))
    round_name = round_name_for_knockout(total_rounds, 1)
    round_row = await queries.create_round(
        tournament_id=tournament["id"],
        round_number=1,
        round_name=round_name,
    )

    pairs, bye = pair_adjacent(shuffled)
    rows = []
    match_id = 1
    for p1, p2 in pairs:
        rows.append(
            {
                "tournament_id": tournament["id"],
                "round_id": round_row["id"],
                "match_id": match_id,
                "participant_1": p1["id"],
                "participant_2": p2["id"],
                "status": "pending",
            }
        )
        match_id += 1

    if bye is not None:
        rows.append(
            {
                "tournament_id": tournament["id"],
                "round_id": round_row["id"],
                "match_id": match_id,
                "participant_1": bye["id"],
                "participant_2": None,
                "status": "bye",
                "winner_id": bye["id"],
            }
        )
        match_id += 1

    matches = await queries.create_matches(rows)
    return [round_row], matches, total_rounds, round_name


async def generate_round_robin(
    tournament: Any,
    participants: list[Any],
) -> tuple[list[Any], list[Any], int, str]:
    total_rounds = len(participants) - 1 if len(participants) % 2 == 0 else len(participants)
    round_name = "Round 1"
    round_row = await queries.create_round(
        tournament_id=tournament["id"],
        round_number=1,
        round_name=round_name,
    )

    rows = []
    for match_id, (p1, p2) in enumerate(first_round_robin_pairs(participants), start=1):
        rows.append(
            {
                "tournament_id": tournament["id"],
                "round_id": round_row["id"],
                "match_id": match_id,
                "participant_1": p1["id"],
                "participant_2": p2["id"],
                "status": "pending",
            }
        )

    matches = await queries.create_matches(rows)
    return [round_row], matches, total_rounds, round_name


async def generate_group_knockout(
    tournament: Any,
    participants: list[Any],
) -> tuple[list[Any], list[Any], int, str]:
    grouped: dict[str, list[Any]] = defaultdict(list)
    for participant in participants:
        grouped[participant["group_name"] or "A"].append(participant)

    rounds = []
    all_matches = []
    match_id = 1
    round_name = "Round 1"

    for group_name in sorted(grouped):
        group_participants = grouped[group_name]
        round_row = await queries.create_round(
            tournament_id=tournament["id"],
            round_number=1,
            round_name=round_name,
            group_name=group_name,
        )
        rounds.append(round_row)

        rows = []
        for p1, p2 in first_round_robin_pairs(group_participants):
            rows.append(
                {
                    "tournament_id": tournament["id"],
                    "round_id": round_row["id"],
                    "match_id": match_id,
                    "participant_1": p1["id"],
                    "participant_2": p2["id"],
                    "status": "pending",
                }
            )
            match_id += 1

        if rows:
            all_matches.extend(await queries.create_matches(rows))

    largest_group = max((len(group) for group in grouped.values()), default=0)
    total_rounds = largest_group - 1 if largest_group % 2 == 0 else largest_group
    return rounds, all_matches, max(total_rounds, 1), round_name


async def generate_matchups_for_tournament(
    bot: commands.Bot,
    guild: discord.Guild,
    tournament: Any,
) -> None:
    fresh_tournament = await queries.get_tournament(tournament["id"])
    if fresh_tournament is None or fresh_tournament["status"] != "registration":
        return

    participants = await queries.list_participants(fresh_tournament["id"])
    if len(participants) < 2:
        channel = guild.get_channel(fresh_tournament["matchups_channel_id"])
        if isinstance(channel, discord.TextChannel):
            await channel.send(embed=error_embed("Not enough players registered (minimum 2 required)."))
        return

    participants = await assign_groups(fresh_tournament, participants)
    if fresh_tournament["format"] == "single_elimination":
        rounds, matches, total_rounds, round_name = await generate_single_elimination(fresh_tournament, participants)
        stage = "knockout"
    elif fresh_tournament["format"] == "round_robin":
        rounds, matches, total_rounds, round_name = await generate_round_robin(fresh_tournament, participants)
        stage = "group"
    else:
        rounds, matches, total_rounds, round_name = await generate_group_knockout(fresh_tournament, participants)
        stage = "group"

    updated_tournament = await queries.mark_tournament_matchups_generated(
        fresh_tournament["id"],
        total_rounds=total_rounds,
        match_counter=max((match["match_id"] for match in matches), default=0),
        stage=stage,
    )
    if updated_tournament is None:
        return

    matchups_channel = guild.get_channel(updated_tournament["matchups_channel_id"])
    bracket_channel = guild.get_channel(updated_tournament["bracket_channel_id"])
    if not isinstance(matchups_channel, discord.TextChannel) or not isinstance(bracket_channel, discord.TextChannel):
        return

    participants_by_id = {participant["id"]: participant for participant in participants}
    if updated_tournament["format"] == "group_knockout":
        grouped_matches: dict[str, list[Any]] = defaultdict(list)
        for match in matches:
            p1 = participants_by_id.get(match["participant_1"])
            group_name = p1["group_name"] if p1 else None
            grouped_matches[group_name or "A"].append(match)

        for group_name in sorted(grouped_matches):
            await send_matchup_embed(
                matchups_channel,
                title="Round 1 Matchups",
                matches=grouped_matches[group_name],
                participants_by_id=participants_by_id,
                group_name=group_name,
            )
    else:
        await send_matchup_embed(
            matchups_channel,
            title=f"{round_name} Matchups",
            matches=matches,
            participants_by_id=participants_by_id,
        )

    bracket_message = await post_bracket_image(
        bracket_channel,
        tournament=updated_tournament,
        round_name=round_name,
        matches=matches,
        participants=participants,
    )
    await queries.set_bracket_message_id(updated_tournament["id"], bracket_message.id)


class MatchupsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.hybrid_command(name="generate-matchups", description="Generate the first round of tournament matchups.")
    @organizer_only()
    async def generate_matchups(self, ctx: commands.Context) -> None:
        await ctx.defer()

        if ctx.guild is None:
            await ctx.send(embed=error_embed("This command can only be used in a server."))
            return

        tournament = await queries.get_active_tournament(ctx.guild.id)
        if tournament is None:
            await ctx.send(embed=error_embed("There is no active tournament."))
            return

        if tournament["status"] != "registration":
            await ctx.send(embed=error_embed("Matchups have already been generated for this tournament."))
            return

        count = await queries.count_participants(tournament["id"])
        if count < 2:
            await ctx.send(embed=error_embed("Not enough players registered (minimum 2 required)."))
            return

        await generate_matchups_for_tournament(self.bot, ctx.guild, tournament)
        await ctx.send(embed=success_embed("Matchups Generated", "Round 1 matchups have been posted."))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MatchupsCog(bot))

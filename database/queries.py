from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import asyncpg

from database.connection import acquire


Record = asyncpg.Record


async def get_guild_config(guild_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            "SELECT * FROM guild_config WHERE guild_id = $1",
            guild_id,
        )


async def ensure_guild_config(guild_id: int) -> Record:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            INSERT INTO guild_config (guild_id)
            VALUES ($1)
            ON CONFLICT (guild_id) DO UPDATE
                SET guild_id = EXCLUDED.guild_id
            RETURNING *
            """,
            guild_id,
        )


async def get_organizer_role_id(guild_id: int) -> int | None:
    config = await get_guild_config(guild_id)
    if config is None:
        return None
    return config["organizer_role"]


async def set_organizer_role(guild_id: int, role_id: int) -> Record:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            INSERT INTO guild_config (guild_id, organizer_role)
            VALUES ($1, $2)
            ON CONFLICT (guild_id) DO UPDATE
                SET organizer_role = EXCLUDED.organizer_role
            RETURNING *
            """,
            guild_id,
            role_id,
        )


async def create_tournament(
    *,
    guild_id: int,
    name: str,
    tournament_format: str,
    participant_cap: int,
    created_by: int,
    registration_channel_id: int,
    matchups_channel_id: int,
    results_channel_id: int,
    bracket_channel_id: int,
    ovr_min: int = 0,
    use_groups: bool = False,
    group_size: int | None = None,
    group_advance_count: int = 2,
    rr_advance_count: int = 2,
    stage: str = "group",
) -> Record:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            INSERT INTO tournaments (
                guild_id,
                name,
                format,
                ovr_min,
                participant_cap,
                use_groups,
                group_size,
                group_advance_count,
                rr_advance_count,
                registration_channel_id,
                matchups_channel_id,
                results_channel_id,
                bracket_channel_id,
                stage,
                created_by
            )
            VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9,
                $10, $11, $12, $13, $14, $15
            )
            RETURNING *
            """,
            guild_id,
            name,
            tournament_format,
            ovr_min,
            participant_cap,
            use_groups,
            group_size,
            group_advance_count,
            rr_advance_count,
            registration_channel_id,
            matchups_channel_id,
            results_channel_id,
            bracket_channel_id,
            stage,
            created_by,
        )


async def get_tournament(tournament_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            "SELECT * FROM tournaments WHERE id = $1",
            tournament_id,
        )


async def get_active_tournament(guild_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            SELECT *
            FROM tournaments
            WHERE guild_id = $1
              AND status IN ('registration', 'active')
            ORDER BY created_at DESC
            LIMIT 1
            """,
            guild_id,
        )


async def get_registration_tournament(guild_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            SELECT *
            FROM tournaments
            WHERE guild_id = $1
              AND status = 'registration'
            ORDER BY created_at DESC
            LIMIT 1
            """,
            guild_id,
        )


async def update_tournament_status(tournament_id: int, status: str) -> Record | None:
    ended_clause = ", ended_at = NOW()" if status in {"completed", "cancelled"} else ""
    async with acquire() as connection:
        return await connection.fetchrow(
            f"""
            UPDATE tournaments
            SET status = $2
                {ended_clause}
            WHERE id = $1
            RETURNING *
            """,
            tournament_id,
            status,
        )


async def set_tournament_active(tournament_id: int) -> Record | None:
    return await update_tournament_status(tournament_id, "active")


async def cancel_active_tournament(guild_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            UPDATE tournaments
            SET status = 'cancelled',
                ended_at = NOW()
            WHERE guild_id = $1
              AND status IN ('registration', 'active')
            RETURNING *
            """,
            guild_id,
        )


async def update_tournament_round(
    tournament_id: int,
    *,
    current_round: int | None = None,
    total_rounds: int | None = None,
    stage: str | None = None,
) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            UPDATE tournaments
            SET current_round = COALESCE($2, current_round),
                total_rounds = COALESCE($3, total_rounds),
                stage = COALESCE($4, stage)
            WHERE id = $1
            RETURNING *
            """,
            tournament_id,
            current_round,
            total_rounds,
            stage,
        )


async def set_bracket_message_id(tournament_id: int, message_id: int | None) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            UPDATE tournaments
            SET bracket_message_id = $2
            WHERE id = $1
            RETURNING *
            """,
            tournament_id,
            message_id,
        )


async def increment_match_counter(tournament_id: int, amount: int = 1) -> int:
    async with acquire() as connection:
        return await connection.fetchval(
            """
            UPDATE tournaments
            SET match_counter = match_counter + $2
            WHERE id = $1
            RETURNING match_counter
            """,
            tournament_id,
            amount,
        )


async def add_participant(
    *,
    tournament_id: int,
    discord_id: int,
    username: str,
    ovr: int,
    group_name: str | None = None,
) -> Record:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            INSERT INTO participants (
                tournament_id,
                discord_id,
                username,
                ovr,
                group_name
            )
            VALUES ($1, $2, $3, $4, $5)
            RETURNING *
            """,
            tournament_id,
            discord_id,
            username,
            ovr,
            group_name,
        )


async def get_participant(participant_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            "SELECT * FROM participants WHERE id = $1",
            participant_id,
        )


async def get_participant_by_discord_id(tournament_id: int, discord_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            SELECT *
            FROM participants
            WHERE tournament_id = $1
              AND discord_id = $2
            """,
            tournament_id,
            discord_id,
        )


async def list_participants(tournament_id: int) -> list[Record]:
    async with acquire() as connection:
        return list(
            await connection.fetch(
                """
                SELECT *
                FROM participants
                WHERE tournament_id = $1
                ORDER BY registered_at ASC, id ASC
                """,
                tournament_id,
            )
        )


async def count_participants(tournament_id: int) -> int:
    async with acquire() as connection:
        return await connection.fetchval(
            "SELECT COUNT(*) FROM participants WHERE tournament_id = $1",
            tournament_id,
        )


async def set_participant_group(participant_id: int, group_name: str | None) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            UPDATE participants
            SET group_name = $2
            WHERE id = $1
            RETURNING *
            """,
            participant_id,
            group_name,
        )


async def set_participant_groups(assignments: Iterable[tuple[int, str | None]]) -> None:
    async with acquire() as connection:
        await connection.executemany(
            """
            UPDATE participants
            SET group_name = $2
            WHERE id = $1
            """,
            list(assignments),
        )


async def create_round(
    *,
    tournament_id: int,
    round_number: int,
    round_name: str,
    group_name: str | None = None,
) -> Record:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            INSERT INTO rounds (
                tournament_id,
                round_number,
                round_name,
                group_name
            )
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (tournament_id, round_number, group_name) DO UPDATE
                SET round_name = EXCLUDED.round_name
            RETURNING *
            """,
            tournament_id,
            round_number,
            round_name,
            group_name,
        )


async def get_round(round_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            "SELECT * FROM rounds WHERE id = $1",
            round_id,
        )


async def list_rounds(tournament_id: int) -> list[Record]:
    async with acquire() as connection:
        return list(
            await connection.fetch(
                """
                SELECT *
                FROM rounds
                WHERE tournament_id = $1
                ORDER BY round_number ASC, group_name NULLS LAST
                """,
                tournament_id,
            )
        )


async def list_active_rounds(tournament_id: int) -> list[Record]:
    async with acquire() as connection:
        return list(
            await connection.fetch(
                """
                SELECT *
                FROM rounds
                WHERE tournament_id = $1
                  AND status = 'active'
                ORDER BY round_number ASC, group_name NULLS LAST
                """,
                tournament_id,
            )
        )


async def complete_round(round_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            UPDATE rounds
            SET status = 'completed'
            WHERE id = $1
            RETURNING *
            """,
            round_id,
        )


async def create_match(
    *,
    tournament_id: int,
    round_id: int,
    match_id: int,
    participant_1: int | None,
    participant_2: int | None,
    status: str = "pending",
    winner_id: int | None = None,
) -> Record:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            INSERT INTO matches (
                tournament_id,
                round_id,
                match_id,
                participant_1,
                participant_2,
                status,
                winner_id,
                posted_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, CASE WHEN $6 IN ('completed', 'bye') THEN NOW() ELSE NULL END)
            RETURNING *
            """,
            tournament_id,
            round_id,
            match_id,
            participant_1,
            participant_2,
            status,
            winner_id,
        )


async def create_matches(matches: Sequence[dict[str, Any]]) -> list[Record]:
    created: list[Record] = []
    async with acquire() as connection:
        async with connection.transaction():
            for match in matches:
                created.append(
                    await connection.fetchrow(
                        """
                        INSERT INTO matches (
                            tournament_id,
                            round_id,
                            match_id,
                            participant_1,
                            participant_2,
                            status,
                            winner_id,
                            posted_at
                        )
                        VALUES ($1, $2, $3, $4, $5, $6, $7, CASE WHEN $6 IN ('completed', 'bye') THEN NOW() ELSE NULL END)
                        RETURNING *
                        """,
                        match["tournament_id"],
                        match["round_id"],
                        match["match_id"],
                        match.get("participant_1"),
                        match.get("participant_2"),
                        match.get("status", "pending"),
                        match.get("winner_id"),
                    )
                )
    return created


async def get_match_by_display_id(tournament_id: int, match_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            SELECT
                m.*,
                r.round_number,
                r.round_name,
                r.group_name
            FROM matches m
            JOIN rounds r ON r.id = m.round_id
            WHERE m.tournament_id = $1
              AND m.match_id = $2
            """,
            tournament_id,
            match_id,
        )


async def list_matches_for_round(round_id: int) -> list[Record]:
    async with acquire() as connection:
        return list(
            await connection.fetch(
                """
                SELECT *
                FROM matches
                WHERE round_id = $1
                ORDER BY match_id ASC
                """,
                round_id,
            )
        )


async def list_matches_for_tournament(tournament_id: int) -> list[Record]:
    async with acquire() as connection:
        return list(
            await connection.fetch(
                """
                SELECT
                    m.*,
                    r.round_number,
                    r.round_name,
                    r.group_name
                FROM matches m
                JOIN rounds r ON r.id = m.round_id
                WHERE m.tournament_id = $1
                ORDER BY r.round_number ASC, m.match_id ASC
                """,
                tournament_id,
            )
        )


async def get_pending_match_for_participant(tournament_id: int, participant_id: int) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            SELECT
                m.*,
                r.round_name,
                r.group_name
            FROM matches m
            JOIN rounds r ON r.id = m.round_id
            WHERE m.tournament_id = $1
              AND m.status = 'pending'
              AND (m.participant_1 = $2 OR m.participant_2 = $2)
            ORDER BY r.round_number ASC, m.match_id ASC
            LIMIT 1
            """,
            tournament_id,
            participant_id,
        )


async def record_match_result(
    *,
    tournament_id: int,
    match_id: int,
    winner_id: int,
    result_image_url: str | None = None,
) -> Record | None:
    async with acquire() as connection:
        return await connection.fetchrow(
            """
            UPDATE matches
            SET winner_id = $3,
                result_image_url = $4,
                status = 'completed',
                posted_at = NOW()
            WHERE tournament_id = $1
              AND match_id = $2
              AND status = 'pending'
            RETURNING *
            """,
            tournament_id,
            match_id,
            winner_id,
            result_image_url,
        )


async def round_is_complete(round_id: int) -> bool:
    async with acquire() as connection:
        pending = await connection.fetchval(
            """
            SELECT COUNT(*)
            FROM matches
            WHERE round_id = $1
              AND status = 'pending'
            """,
            round_id,
        )
    return pending == 0


async def list_round_winners(round_id: int) -> list[Record]:
    async with acquire() as connection:
        return list(
            await connection.fetch(
                """
                SELECT p.*
                FROM matches m
                JOIN participants p ON p.id = m.winner_id
                WHERE m.round_id = $1
                  AND m.winner_id IS NOT NULL
                ORDER BY m.match_id ASC
                """,
                round_id,
            )
        )


async def get_standings(tournament_id: int, group_name: str | None = None) -> list[Record]:
    async with acquire() as connection:
        return list(
            await connection.fetch(
                """
                SELECT
                    p.*,
                    COUNT(m.id) FILTER (WHERE m.winner_id = p.id) AS wins,
                    COUNT(m.id) FILTER (
                        WHERE m.status IN ('completed', 'bye')
                          AND (m.participant_1 = p.id OR m.participant_2 = p.id)
                    ) AS played
                FROM participants p
                LEFT JOIN matches m
                    ON m.tournament_id = p.tournament_id
                   AND (m.participant_1 = p.id OR m.participant_2 = p.id)
                WHERE p.tournament_id = $1
                  AND ($2::TEXT IS NULL OR p.group_name = $2)
                GROUP BY p.id
                ORDER BY wins DESC, played ASC, p.ovr DESC, p.registered_at ASC
                """,
                tournament_id,
                group_name,
            )
        )

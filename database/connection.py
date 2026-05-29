from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import asyncpg


_pool: asyncpg.Pool | None = None


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS guild_config (
    guild_id        BIGINT PRIMARY KEY,
    organizer_role  BIGINT,
    created_at      TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tournaments (
    id                  SERIAL PRIMARY KEY,
    guild_id            BIGINT NOT NULL,
    name                TEXT NOT NULL,
    format              TEXT NOT NULL CHECK (format IN ('single_elimination', 'round_robin', 'group_knockout')),
    status              TEXT NOT NULL DEFAULT 'registration'
                          CHECK (status IN ('registration', 'active', 'completed', 'cancelled')),
    ovr_min             INT NOT NULL DEFAULT 0,
    participant_cap     INT NOT NULL,
    use_groups          BOOLEAN NOT NULL DEFAULT FALSE,
    group_size          INT,
    group_advance_count INT NOT NULL DEFAULT 2,
    rr_advance_count    INT NOT NULL DEFAULT 2,
    registration_channel_id   BIGINT NOT NULL,
    matchups_channel_id       BIGINT NOT NULL,
    results_channel_id        BIGINT NOT NULL,
    bracket_channel_id        BIGINT NOT NULL,
    bracket_message_id        BIGINT,
    current_round             INT NOT NULL DEFAULT 1,
    total_rounds              INT,
    match_counter             INT NOT NULL DEFAULT 0,
    stage                     TEXT NOT NULL DEFAULT 'group'
                                CHECK (stage IN ('group', 'knockout')),
    created_by        BIGINT NOT NULL,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    ended_at          TIMESTAMPTZ
);

CREATE UNIQUE INDEX IF NOT EXISTS one_active_tournament
    ON tournaments(guild_id)
    WHERE status IN ('registration', 'active');

CREATE TABLE IF NOT EXISTS participants (
    id              SERIAL PRIMARY KEY,
    tournament_id   INT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    discord_id      BIGINT NOT NULL,
    username        TEXT NOT NULL,
    ovr             INT NOT NULL,
    group_name      TEXT,
    registered_at   TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tournament_id, discord_id)
);

CREATE INDEX IF NOT EXISTS participants_tournament_idx
    ON participants(tournament_id);

CREATE TABLE IF NOT EXISTS rounds (
    id              SERIAL PRIMARY KEY,
    tournament_id   INT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    round_number    INT NOT NULL,
    round_name      TEXT NOT NULL,
    group_name      TEXT,
    status          TEXT NOT NULL DEFAULT 'active'
                      CHECK (status IN ('active', 'completed')),
    created_at      TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(tournament_id, round_number, group_name)
);

CREATE TABLE IF NOT EXISTS matches (
    id              SERIAL PRIMARY KEY,
    tournament_id   INT NOT NULL REFERENCES tournaments(id) ON DELETE CASCADE,
    round_id        INT NOT NULL REFERENCES rounds(id) ON DELETE CASCADE,
    match_id        INT NOT NULL,
    participant_1   INT REFERENCES participants(id),
    participant_2   INT REFERENCES participants(id),
    winner_id       INT REFERENCES participants(id),
    result_image_url TEXT,
    status          TEXT NOT NULL DEFAULT 'pending'
                      CHECK (status IN ('pending', 'completed', 'bye')),
    posted_at       TIMESTAMPTZ,
    UNIQUE(tournament_id, match_id)
);

CREATE INDEX IF NOT EXISTS matches_round_idx
    ON matches(round_id);

CREATE INDEX IF NOT EXISTS matches_tournament_status
    ON matches(tournament_id, status);
"""


async def init_db(database_url: str) -> asyncpg.Pool:
    global _pool

    if _pool is None:
        _pool = await asyncpg.create_pool(database_url)
        async with _pool.acquire() as connection:
            await connection.execute(SCHEMA_SQL)

    return _pool


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool has not been initialized")
    return _pool


@asynccontextmanager
async def acquire() -> AsyncIterator[asyncpg.Connection]:
    pool = get_pool()
    async with pool.acquire() as connection:
        yield connection


async def close_db() -> None:
    global _pool

    if _pool is not None:
        await _pool.close()
        _pool = None

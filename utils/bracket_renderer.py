from __future__ import annotations

import io
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont


BASE_DIR = Path(__file__).resolve().parent.parent
FONT_PATH = BASE_DIR / "assets" / "fonts" / "bold.ttf"
SYSTEM_MONO_FONTS = (
    Path("C:/Windows/Fonts/consolab.ttf"),
    Path("C:/Windows/Fonts/consola.ttf"),
    Path("C:/Windows/Fonts/courbd.ttf"),
    Path("C:/Windows/Fonts/cour.ttf"),
)

WIDTH = 1200
PADDING = 40
HEADER_HEIGHT = 84
CARD_PADDING = 32
LINE_HEIGHT = 34

BACKGROUND = "#0d1b2a"
CARD_BG = "#181818"
CARD_BORDER = "#242424"
WHITE = "#ffffff"
GOLD = "#FFD700"
GRAY = "#8a94a6"
GREEN = "#00e676"
LOSER = "#6f7785"


def load_font(size: int) -> ImageFont.ImageFont:
    if FONT_PATH.exists():
        return ImageFont.truetype(str(FONT_PATH), size=size)
    for font_path in SYSTEM_MONO_FONTS:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size=size)
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def text_size(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> tuple[int, int]:
    box = draw.textbbox((0, 0), text, font=font)
    return box[2] - box[0], box[3] - box[1]


def image_to_png_bytes(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def normalize_match(match: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": match.get("match_id", 0),
        "p1_username": match.get("p1_username") or "TBD",
        "p1_ovr": match.get("p1_ovr"),
        "p2_username": match.get("p2_username"),
        "p2_ovr": match.get("p2_ovr"),
        "winner_username": match.get("winner_username"),
        "status": match.get("status", "pending"),
    }


def truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    if limit <= 3:
        return value[:limit]
    return value[: limit - 3] + "..."


def player_label(username: str | None, ovr: int | None, *, width: int = 28) -> str:
    if username is None:
        username = "BYE"

    suffix = "" if ovr is None else f" [{ovr}]"
    available = max(width - len(suffix), 4)
    return f"{truncate(username, available)}{suffix}".ljust(width)


def draw_text_line(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    text: str,
    font: ImageFont.ImageFont,
    fill: str,
    *,
    strike: bool = False,
) -> None:
    draw.text((x, y), text, font=font, fill=fill)
    if strike:
        width, height = text_size(draw, text.rstrip(), font)
        draw.line((x, y + height // 2 + 2, x + width, y + height // 2 + 2), fill=fill, width=2)


def match_result_label(match: dict[str, Any]) -> str:
    status = match["status"]
    winner = match["winner_username"]
    if status == "bye":
        return f"Advances: {winner or match['p1_username']}"
    if status == "completed" and winner:
        return f"Winner: {winner}"
    return "Pending"


def draw_player_branch(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    label: str,
    font: ImageFont.ImageFont,
    fill: str,
    *,
    strike: bool = False,
) -> None:
    draw_text_line(draw, x, y, label.rstrip(), font, fill, strike=strike)
    connector_x = x + text_size(draw, "M" * 28, font)[0]
    draw_text_line(draw, connector_x, y, " --+", font, fill)


def draw_match_block(
    draw: ImageDraw.ImageDraw,
    x: int,
    y: int,
    match: dict[str, Any],
    font: ImageFont.ImageFont,
) -> int:
    status = match["status"]
    winner = match["winner_username"]
    p1 = match["p1_username"]
    p2 = match["p2_username"] or "BYE"
    p1_won = winner == p1 or status == "bye"
    p2_won = winner == p2

    result_text = f"{' ' * 31}+-- {match_result_label(match)}"

    draw_text_line(draw, x, y, f"#{match['match_id']}", font, GRAY)
    y += LINE_HEIGHT

    draw_player_branch(
        draw,
        x,
        y,
        player_label(p1, match["p1_ovr"]),
        font,
        GREEN if status in {"completed", "bye"} and p1_won else WHITE,
        strike=status == "completed" and not p1_won,
    )
    y += LINE_HEIGHT

    draw_text_line(
        draw,
        x,
        y,
        result_text,
        font,
        GREEN if status in {"completed", "bye"} else GRAY,
    )
    y += LINE_HEIGHT

    draw_player_branch(
        draw,
        x,
        y,
        player_label(p2, match["p2_ovr"]),
        font,
        GREEN if status == "completed" and p2_won else LOSER if status == "completed" else WHITE,
        strike=status == "completed" and not p2_won,
    )
    y += LINE_HEIGHT

    return y + (LINE_HEIGHT // 2)


def draw_card(draw: ImageDraw.ImageDraw, height: int) -> tuple[int, int, int, int]:
    box = (PADDING, HEADER_HEIGHT, WIDTH - PADDING, height - PADDING)
    draw.rounded_rectangle(box, radius=28, fill=CARD_BG, outline=CARD_BORDER, width=3)
    return box


async def render_bracket(matches: list[dict], round_name: str, tournament_name: str) -> bytes:
    normalized_matches = [normalize_match(match) for match in matches]
    match_count = max(len(normalized_matches), 1)
    content_lines = 2 + (match_count * 5)
    card_height = CARD_PADDING * 2 + content_lines * LINE_HEIGHT
    height = HEADER_HEIGHT + card_height + PADDING

    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = load_font(36)
    label_font = load_font(24)
    code_font = load_font(22)

    draw.text((PADDING, 26), tournament_name, font=title_font, fill=WHITE)
    title_width, _ = text_size(draw, tournament_name, title_font)
    draw.text((PADDING + title_width + 22, 36), round_name, font=label_font, fill=GOLD)

    card = draw_card(draw, height)
    x = card[0] + CARD_PADDING
    y = card[1] + CARD_PADDING

    draw_text_line(draw, x, y, round_name.upper(), code_font, WHITE)
    y += LINE_HEIGHT * 2

    if not normalized_matches:
        draw_text_line(draw, x, y, "No matches generated yet.", code_font, GRAY)
        return image_to_png_bytes(image)

    for match in normalized_matches:
        y = draw_match_block(draw, x, y, match, code_font)

    return image_to_png_bytes(image)


def standing_value(participant: dict[str, Any], key: str, default: int = 0) -> int:
    value = participant.get(key, default)
    return int(value or default)


def standings_rows(participants: list[dict]) -> list[dict]:
    return sorted(
        participants,
        key=lambda item: (
            -standing_value(item, "points", standing_value(item, "wins") * 3),
            -standing_value(item, "wins"),
            standing_value(item, "losses"),
            -standing_value(item, "ovr"),
            str(item.get("username", "")).lower(),
        ),
    )


def table_line() -> str:
    return "+------+--------------------------+-----+------+--------+--------+"


def table_row(rank: str, username: str, ovr: str, wins: str, losses: str, points: str) -> str:
    return (
        f"| {rank:<4} | {truncate(username, 24):<24} | {ovr:>3} | "
        f"{wins:>4} | {losses:>6} | {points:>6} |"
    )


async def render_standings(participants: list[dict], group_name: str | None) -> bytes:
    rows = standings_rows(participants)
    content_lines = 5 + max(len(rows), 1)
    card_height = CARD_PADDING * 2 + content_lines * LINE_HEIGHT
    height = HEADER_HEIGHT + card_height + PADDING

    image = Image.new("RGB", (WIDTH, height), BACKGROUND)
    draw = ImageDraw.Draw(image)

    title_font = load_font(36)
    label_font = load_font(24)
    code_font = load_font(22)

    title = "Standings"
    subtitle = f"Group {group_name}" if group_name else "Round Robin"
    draw.text((PADDING, 26), title, font=title_font, fill=WHITE)
    title_width, _ = text_size(draw, title, title_font)
    draw.text((PADDING + title_width + 22, 36), subtitle, font=label_font, fill=GOLD)

    card = draw_card(draw, height)
    x = card[0] + CARD_PADDING
    y = card[1] + CARD_PADDING

    draw_text_line(draw, x, y, subtitle.upper(), code_font, WHITE)
    y += LINE_HEIGHT * 2
    draw_text_line(draw, x, y, table_line(), code_font, WHITE)
    y += LINE_HEIGHT
    draw_text_line(draw, x, y, table_row("Rank", "Username", "OVR", "Wins", "Losses", "Points"), code_font, GOLD)
    y += LINE_HEIGHT
    draw_text_line(draw, x, y, table_line(), code_font, WHITE)
    y += LINE_HEIGHT

    if not rows:
        draw_text_line(draw, x, y, "| No standings available.                                      |", code_font, GRAY)
        y += LINE_HEIGHT
    else:
        for index, participant in enumerate(rows, start=1):
            wins = standing_value(participant, "wins")
            losses = standing_value(participant, "losses")
            points = standing_value(participant, "points", wins * 3)
            row = table_row(
                str(index),
                str(participant.get("username", "TBD")),
                str(participant.get("ovr", "")),
                str(wins),
                str(losses),
                str(points),
            )
            draw_text_line(draw, x, y, row, code_font, WHITE)
            y += LINE_HEIGHT

    draw_text_line(draw, x, y, table_line(), code_font, WHITE)

    return image_to_png_bytes(image)

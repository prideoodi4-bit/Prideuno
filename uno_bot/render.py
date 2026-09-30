from __future__ import annotations

import math
import os
import tempfile
from textwrap import wrap
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from .engine import COLOR_EMOJI, COLOR_NAME_AR

CARD_COLORS = {
    'R': (227, 57, 53),
    'Y': (241, 194, 50),
    'G': (41, 163, 84),
    'B': (43, 105, 214),
    None: (33, 33, 33),
}



def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf' if bold else '/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf',
    ]
    for path in candidates:
        if os.path.exists(path):
            return ImageFont.truetype(path, size=size)
    return ImageFont.load_default()


TITLE_FONT = _font(42, bold=True)
SUB_FONT = _font(28)
BODY_FONT = _font(24)
SMALL_FONT = _font(18)
CARD_BIG_FONT = _font(78, bold=True)
CARD_SMALL_FONT = _font(28, bold=True)


def _rounded_rect(draw: ImageDraw.ImageDraw, xy, radius: int, fill, outline=None, width: int = 1):
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline, width=width)



def card_symbol(card: dict[str, Any]) -> str:
    kind = str(card['kind'])
    if kind == 'skip':
        return '⛔'
    if kind == 'reverse':
        return '↺'
    if kind == 'draw2':
        return '+2'
    if kind == 'wild':
        return 'WILD'
    if kind == 'wild4':
        return '+4'
    return kind



def render_single_card(card: dict[str, Any], width: int = 180, height: int = 270) -> Image.Image:
    img = Image.new('RGB', (width, height), 'white')
    draw = ImageDraw.Draw(img)

    base = CARD_COLORS.get(card.get('color'), (0, 0, 0))
    _rounded_rect(draw, (0, 0, width - 1, height - 1), 22, fill=base, outline=(255, 255, 255), width=4)
    _rounded_rect(draw, (18, 18, width - 19, height - 19), 18, fill=(255, 255, 255), outline=None)

    # inner ellipse-like lozenge
    oval_box = (25, 55, width - 25, height - 55)
    draw.rounded_rectangle(oval_box, radius=90, fill=base)

    symbol = card_symbol(card)
    small = COLOR_EMOJI.get(card.get('color'), '🌈') if card.get('color') else '🌈'
    draw.text((18, 12), small, font=CARD_SMALL_FONT, fill=(255, 255, 255))
    bbox = draw.textbbox((0, 0), symbol, font=CARD_BIG_FONT)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    draw.text(((width - tw) / 2, (height - th) / 2 - 6), symbol, font=CARD_BIG_FONT, fill=(255, 255, 255))

    bbox2 = draw.textbbox((0, 0), symbol, font=CARD_SMALL_FONT)
    sw = bbox2[2] - bbox2[0]
    sh = bbox2[3] - bbox2[1]
    draw.text((width - sw - 18, height - sh - 16), symbol, font=CARD_SMALL_FONT, fill=(255, 255, 255))
    return img



def _save_temp(img: Image.Image, prefix: str) -> str:
    fd, path = tempfile.mkstemp(prefix=prefix, suffix='.png')
    os.close(fd)
    img.save(path, format='PNG')
    return path



def render_board_image(state: dict[str, Any]) -> str:
    width, height = 1280, 900
    img = Image.new('RGB', (width, height), (16, 62, 58))
    draw = ImageDraw.Draw(img)

    # panels
    _rounded_rect(draw, (28, 28, width - 28, height - 28), 28, fill=(22, 84, 78), outline=(255, 255, 255), width=2)
    draw.text((50, 40), 'Pride UNO', font=TITLE_FONT, fill='white')

    discard = state.get('discard') or [{'color': None, 'kind': 'wild'}]
    top = discard[-1]
    current = state['players'][state.get('current_idx', 0)] if state.get('players') else {'name': '-'}
    direction = 'Clockwise ↻' if state.get('direction', 1) == 1 else 'Counter ↺'
    current_color = state.get('current_color')
    color_text = f"{COLOR_EMOJI.get(current_color, '🌈')} {COLOR_NAME_AR.get(current_color, 'Wild')}"

    card_img = render_single_card(top, width=280, height=420)
    img.paste(card_img, (70, 120))

    info_x = 400
    draw.text((info_x, 130), 'Current card', font=SUB_FONT, fill=(235, 247, 245))
    draw.text((info_x, 180), f'Color: {color_text}', font=BODY_FONT, fill='white')
    draw.text((info_x, 225), f'Turn: {current["name"]}', font=BODY_FONT, fill='white')
    draw.text((info_x, 270), f'Direction: {direction}', font=BODY_FONT, fill='white')
    draw.text((info_x, 315), f'Deck left: {len(state.get("deck", []))}', font=BODY_FONT, fill='white')

    draw.text((400, 390), 'Players', font=SUB_FONT, fill=(235, 247, 245))
    y = 440
    for p in state.get('players', []):
        marker = '▶' if int(p['user_id']) == int(current['user_id']) and state.get('phase') == 'playing' else '•'
        line = f"{marker} {p['name']} — {len(p['hand'])} card(s)"
        draw.text((400, y), line, font=BODY_FONT, fill='white')
        y += 42

    event = state.get('last_event') or ''
    if event:
        draw.text((70, 590), 'Last event', font=SUB_FONT, fill=(235, 247, 245))
        wrapped = []
        for raw in event.splitlines():
            wrapped.extend(wrap(raw, width=48) or [''])
        ey = 640
        for line in wrapped[:5]:
            draw.text((70, ey), line, font=BODY_FONT, fill='white')
            ey += 34

    if state.get('phase') == 'finished':
        overlay = Image.new('RGBA', img.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rounded_rectangle((250, 300, 1030, 560), radius=32, fill=(0, 0, 0, 170), outline=(255, 255, 255, 200), width=3)
        odraw.text((430, 360), '🏆 GAME OVER', font=TITLE_FONT, fill=(255, 255, 255, 255))
        winner = state.get('last_event', 'The game has ended.')
        wrapped = wrap(winner, width=34)
        yy = 430
        for line in wrapped[:3]:
            bbox = odraw.textbbox((0, 0), line, font=BODY_FONT)
            tw = bbox[2] - bbox[0]
            odraw.text(((width - tw) / 2, yy), line, font=BODY_FONT, fill=(255, 255, 255, 255))
            yy += 34
        img = Image.alpha_composite(img.convert('RGBA'), overlay).convert('RGB')

    return _save_temp(img, 'uno_board_')



def render_hand_image(state: dict[str, Any], user_id: int) -> str:
    player = next((p for p in state['players'] if int(p['user_id']) == int(user_id)), None)
    if not player:
        img = Image.new('RGB', (900, 240), (28, 28, 28))
        draw = ImageDraw.Draw(img)
        draw.text((30, 80), 'You are not in this game.', font=TITLE_FONT, fill='white')
        return _save_temp(img, 'uno_hand_')

    cards = list(player['hand'])
    count = len(cards)
    cols = min(5, max(1, count))
    rows = max(1, math.ceil(count / cols))
    card_w, card_h = 180, 270
    gap = 22
    padding = 32
    header_h = 120
    width = max(950, padding * 2 + cols * card_w + (cols - 1) * gap)
    height = header_h + padding * 2 + rows * card_h + max(0, rows - 1) * gap

    img = Image.new('RGB', (width, height), (32, 36, 44))
    draw = ImageDraw.Draw(img)
    _rounded_rect(draw, (10, 10, width - 10, height - 10), 28, fill=(32, 36, 44), outline=(255, 255, 255), width=2)
    draw.text((32, 26), f"{player['name']} — Your hand", font=TITLE_FONT, fill='white')
    current = state['players'][state['current_idx']] if state.get('phase') == 'playing' else None
    status = '✅ It is your turn' if current and int(current['user_id']) == int(user_id) else (
        f"⏳ Turn: {current['name']}" if current else 'Game lobby'
    )
    draw.text((34, 76), f"Cards: {count}    {status}", font=SUB_FONT, fill=(220, 230, 230))

    for idx, card in enumerate(cards):
        row = idx // cols
        col = idx % cols
        x = padding + col * (card_w + gap)
        y = header_h + padding + row * (card_h + gap)
        card_img = render_single_card(card, width=card_w, height=card_h)
        img.paste(card_img, (x, y))
        label = f"#{idx + 1}"
        draw.text((x + 8, y + card_h - 28), label, font=SMALL_FONT, fill=(255, 255, 255))

    return _save_temp(img, 'uno_hand_')

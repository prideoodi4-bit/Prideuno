from __future__ import annotations

from typing import Any

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

from .engine import COLOR_EMOJI, COLOR_NAME_AR, card_label, card_sort_key


def lobby_text(state: dict[str, Any]) -> str:
    players = state.get('players', [])
    lines = [
        '🎮 UNO — غرفة انتظار',
        '',
        f'👥 اللاعبين: {len(players)}/10',
    ]
    if players:
        for i, p in enumerate(players, 1):
            lines.append(f"{i}. {p['name']}")
    else:
        lines.append('ماكو لاعبين بعد.')
    lines += [
        '',
        'كل لاعب يضغط ➕ انضم.',
        'بعد البداية، زر 🃏 أوراقي يطلع أوراق اللاعب داخل نفس القسم.',
        'مهم: عرض الأوراق داخل الكروب يكون داخل نفس الـTopic، لذلك اللعب الخاص يبقى أكثر سرّية إذا احتجته لاحقاً.',
    ]
    return '\n'.join(lines)


def lobby_keyboard(code: str, bot_username: str | None = None) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('➕ انضم', callback_data=f'u:j:{code}'),
            InlineKeyboardButton('➖ انسحب', callback_data=f'u:l:{code}'),
        ],
        [InlineKeyboardButton('▶️ ابدأ اللعبة', callback_data=f'u:s:{code}')],
    ])


def board_text(state: dict[str, Any]) -> str:
    if state.get('phase') == 'finished':
        lines = ['🏆 انتهت لعبة UNO', '', state.get('last_event', '')]
        return '\n'.join(lines)

    top = state['discard'][-1]
    color = state.get('current_color')
    direction = '↻' if state.get('direction', 1) == 1 else '↺'
    current = state['players'][state['current_idx']]
    lines = [
        '🎮 UNO',
        '',
        f"🃏 الورقة الحالية: {card_label(top)}",
        f"🎨 اللون الحالي: {COLOR_EMOJI.get(color, '🌈')} {COLOR_NAME_AR.get(color, 'Wild')}",
        f'🔁 الاتجاه: {direction}',
        f"👉 الدور: {current['name']}",
        f"📦 الرزمة المتبقية: {len(state.get('deck', []))}",
        '',
        '👥 اللاعبين:',
    ]
    for p in state['players']:
        marker = '▶️' if int(p['user_id']) == int(current['user_id']) else '•'
        lines.append(f"{marker} {p['name']} — {len(p['hand'])} ورقة")
    if state.get('last_event'):
        lines += ['', f"📣 {state['last_event']}"]
    return '\n'.join(lines)



def board_keyboard(code: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('🃏 أوراقي', callback_data=f'u:show:{code}'),
            InlineKeyboardButton('🔄 تحديث اللوحة', callback_data=f'u:rb:{code}'),
        ],
    ])



def hand_caption(state: dict[str, Any], user_id: int) -> str:
    p = next((x for x in state['players'] if int(x['user_id']) == int(user_id)), None)
    if not p:
        return 'أنت مو لاعب بهذه اللعبة.'
    current = state['players'][state['current_idx']] if state.get('phase') == 'playing' else None
    your_turn = bool(current and int(current['user_id']) == int(user_id))
    status = '✅ دورك هسه' if your_turn else (f"⏳ الدور على {current['name']}" if current else '')
    return (
        f"🃏 أوراقك: {len(p['hand'])}\n"
        f"{status}\n"
        'اختَر الورقة من الأزرار تحت الصورة.'
    )



def hand_keyboard(code: str, state: dict[str, Any], user_id: int) -> InlineKeyboardMarkup | None:
    if state.get('phase') != 'playing':
        return InlineKeyboardMarkup([[InlineKeyboardButton('🔄 تحديث', callback_data=f'u:h:{code}')]])
    current = state['players'][state['current_idx']]
    p = next((x for x in state['players'] if int(x['user_id']) == int(user_id)), None)
    if not p:
        return None
    if int(current['user_id']) != int(user_id):
        return InlineKeyboardMarkup([[InlineKeyboardButton('🔄 تحديث اليد', callback_data=f'u:h:{code}')]])

    cards = sorted(p['hand'], key=card_sort_key)
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    drawn_uid = state.get('drawn_uid') if state.get('has_drawn') else None
    for card in cards:
        if drawn_uid is not None and int(card['uid']) != int(drawn_uid):
            continue
        row.append(InlineKeyboardButton(card_label(card), callback_data=f"u:p:{code}:{card['uid']}"))
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    if state.get('has_drawn'):
        rows.append([InlineKeyboardButton('⏭ مرر الدور', callback_data=f'u:pass:{code}')])
    else:
        rows.append([InlineKeyboardButton('🃏 اسحب ورقة', callback_data=f'u:d:{code}')])
    rows.append([InlineKeyboardButton('🔄 تحديث اليد', callback_data=f'u:h:{code}')])
    return InlineKeyboardMarkup(rows)



def color_keyboard(code: str, uid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton('🔴 أحمر', callback_data=f'u:c:{code}:{uid}:R'),
            InlineKeyboardButton('🟡 أصفر', callback_data=f'u:c:{code}:{uid}:Y'),
        ],
        [
            InlineKeyboardButton('🟢 أخضر', callback_data=f'u:c:{code}:{uid}:G'),
            InlineKeyboardButton('🔵 أزرق', callback_data=f'u:c:{code}:{uid}:B'),
        ],
    ])

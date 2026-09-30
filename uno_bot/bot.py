from __future__ import annotations

import asyncio
import logging
import os
import secrets
import string
from typing import Any

from telegram import BotCommand, InputFile, InputMediaPhoto, Update
from telegram.constants import ChatMemberStatus, ChatType
from telegram.error import BadRequest
from telegram.ext import Application, ApplicationBuilder, CallbackQueryHandler, CommandHandler, ContextTypes

from .engine import COLORS, create_started_state, draw_for_turn, find_player_index, pass_after_draw, play_card
from .render import render_board_image, render_hand_image
from .storage import Storage
from .ui import board_keyboard, board_text, color_keyboard, hand_caption, hand_keyboard, lobby_keyboard, lobby_text

log = logging.getLogger(__name__)

DB_PATH = os.getenv('DATABASE_PATH', 'data/uno.db')
storage = Storage(DB_PATH)
game_locks: dict[str, asyncio.Lock] = {}


def game_lock(code: str) -> asyncio.Lock:
    if code not in game_locks:
        game_locks[code] = asyncio.Lock()
    return game_locks[code]



def short_code() -> str:
    alphabet = string.ascii_uppercase + string.digits
    return ''.join(secrets.choice(alphabet) for _ in range(6))



def display_name(user: Any) -> str:
    return (user.full_name or user.first_name or 'Player')[:40]


async def reply_same_thread(message, text: str, **kwargs):
    params = {'chat_id': message.chat_id, 'text': text, **kwargs}
    if message.message_thread_id is not None:
        params['message_thread_id'] = message.message_thread_id
    return await message.get_bot().send_message(**params)


async def send_in_game_topic(bot, game: dict[str, Any], text: str, **kwargs):
    params = {'chat_id': game['chat_id'], 'text': text, **kwargs}
    if game.get('thread_id') is not None:
        params['message_thread_id'] = game['thread_id']
    return await bot.send_message(**params)


async def edit_board(bot, game: dict[str, Any]) -> None:
    state = game['state']
    mid = game.get('board_message_id')
    path = render_board_image(state)
    try:
        if not mid:
            with open(path, 'rb') as fh:
                sent = await bot.send_photo(
                    chat_id=game['chat_id'],
                    message_thread_id=game.get('thread_id'),
                    photo=fh,
                    caption=board_text(state),
                    reply_markup=board_keyboard(game['code']),
                    protect_content=True,
                )
            storage.set_board_message(game['code'], sent.message_id)
            game['board_message_id'] = sent.message_id
            return

        with open(path, 'rb') as fh:
            media = InputMediaPhoto(media=InputFile(fh), caption=board_text(state))
            await bot.edit_message_media(
                chat_id=game['chat_id'],
                message_id=mid,
                media=media,
                reply_markup=board_keyboard(game['code']),
            )
    except BadRequest as e:
        if 'message is not modified' not in str(e).lower():
            log.warning('Could not edit board: %s', e)


async def show_hand_panel(bot, game: dict[str, Any], user_id: int) -> bool:
    state = game['state']
    if find_player_index(state, user_id) is None:
        return False
    panel_messages = state.setdefault('panel_messages', {})
    old_mid = panel_messages.get(str(user_id))
    path = render_hand_image(state, user_id)
    caption = hand_caption(state, user_id)
    markup = hand_keyboard(game['code'], state, user_id)

    try:
        if old_mid:
            with open(path, 'rb') as fh:
                media = InputMediaPhoto(media=InputFile(fh), caption=caption)
                await bot.edit_message_media(
                    chat_id=game['chat_id'],
                    message_id=int(old_mid),
                    media=media,
                    reply_markup=markup,
                )
            return True

        with open(path, 'rb') as fh:
            sent = await bot.send_photo(
                chat_id=game['chat_id'],
                message_thread_id=game.get('thread_id'),
                photo=fh,
                caption=caption,
                reply_markup=markup,
                protect_content=True,
            )
        panel_messages[str(user_id)] = sent.message_id
        storage.save_state(game['code'], state, active=state.get('phase') != 'finished')
        return True
    except BadRequest as e:
        log.warning('Could not show hand panel for %s: %s', user_id, e)
        return False


async def refresh_open_panels(bot, game: dict[str, Any]) -> None:
    state = game['state']
    for uid_str in list(state.get('panel_messages', {}).keys()):
        try:
            await show_hand_panel(bot, game, int(uid_str))
        except Exception as e:  # noqa: BLE001
            log.warning('Failed to refresh hand panel for %s: %s', uid_str, e)


async def is_admin(bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in (ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER)
    except Exception:
        return False


async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_message:
        return
    await update.effective_message.reply_text(
        '🎮 Pride UNO Bot\n\n'
        'استعمل /uno داخل كروب أو داخل Topic مخصص للعبة.\n'
        'بعد بدء اللعبة، كل لاعب يضغط زر 🃏 أوراقي حتى يشوف أوراقه داخل نفس القسم.'
    )


async def uno_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    if chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        await reply_same_thread(msg, 'هذا الأمر ينستخدم داخل كروب.')
        return

    thread_id = msg.message_thread_id
    if getattr(chat, 'is_forum', False) and thread_id is None:
        await reply_same_thread(msg, 'افتح موضوع UNO أولاً واكتب /uno داخله حتى تبقى اللعبة كلها بالقسم وما تروح للرئيسي.')
        return

    existing = storage.get_active_at(chat.id, thread_id)
    if existing:
        await reply_same_thread(msg, 'أكو لعبة UNO فعالة بهذا الموضوع بالفعل. استخدم /uno_status.')
        return

    code = short_code()
    while storage.get_game(code):
        code = short_code()
    state = {
        'phase': 'lobby',
        'players': [],
        'last_event': '',
        'panel_messages': {},
    }
    storage.create_game(code, chat.id, thread_id, user.id, state)
    game = storage.get_game(code)

    await send_in_game_topic(
        context.bot,
        game,
        lobby_text(state),
        reply_markup=lobby_keyboard(code, context.bot.username),
    )


async def uno_status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    if not msg or not chat:
        return
    game = storage.get_active_at(chat.id, msg.message_thread_id)
    if not game:
        await reply_same_thread(msg, 'ماكو لعبة UNO فعالة بهذا الموضوع.')
        return
    text = lobby_text(game['state']) if game['state'].get('phase') == 'lobby' else board_text(game['state'])
    await reply_same_thread(msg, text)


async def uno_stop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    game = storage.get_active_at(chat.id, msg.message_thread_id)
    if not game:
        await reply_same_thread(msg, 'ماكو لعبة فعالة بهذا الموضوع.')
        return
    if int(game['creator_id']) != int(user.id) and not await is_admin(context.bot, chat.id, user.id):
        await reply_same_thread(msg, 'فقط منشئ اللعبة أو الأدمن يگدر يوقفها.')
        return
    state = game['state']
    state['phase'] = 'finished'
    state['last_event'] = f'🛑 تم إيقاف اللعبة بواسطة {display_name(user)}'
    storage.save_state(game['code'], state, active=False)
    game['state'] = state
    await edit_board(context.bot, game)
    await refresh_open_panels(context.bot, game)


async def uno_rules_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        '📘 قواعد البوت:\n'
        '• 2–10 لاعبين، 7 أوراق لكل لاعب.\n'
        '• التطابق يكون باللون أو الرقم/الرمز.\n'
        '• Skip يتخطى اللاعب التالي، Reverse يعكس الاتجاه، +2 يسحب التالي ورقتين وينطاف دوره.\n'
        '• Wild يختار لون، و+4 يختار لون ويسحب التالي 4 وينطاف دوره.\n'
        '• +4 مسموحة فقط إذا ما عندك ورقة من اللون الحالي.\n'
        '• ماكو stacking (+2 فوق +2 مثلاً).\n'
        '• إذا سحبت ورقة وكانت قابلة للعب، تگدر تلعبها أو تمرر؛ ما تگدر تلعب ورقة ثانية من يدك بعد السحب.\n'
        '• أول واحد تخلص أوراقه يفوز.\n\n'
        'ملاحظة: عرض الأوراق داخل نفس الكروب/الـTopic، لذلك المشاركين الآخرين يگدرون يشوفون الرسالة إذا فتحوها بالكروب.'
    )
    await reply_same_thread(update.effective_message, text)


async def uno_topic_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = update.effective_message
    chat = update.effective_chat
    user = update.effective_user
    if not msg or not chat or not user:
        return
    if chat.type != ChatType.SUPERGROUP or not getattr(chat, 'is_forum', False):
        await reply_same_thread(msg, 'هذا الأمر يحتاج Supergroup مفعّل بيه Topics.')
        return
    if not await is_admin(context.bot, chat.id, user.id):
        await reply_same_thread(msg, 'فقط الأدمن يگدر ينشئ قسم UNO.')
        return
    try:
        topic = await context.bot.create_forum_topic(chat.id, '🎮 UNO')
        await context.bot.send_message(
            chat_id=chat.id,
            message_thread_id=topic.message_thread_id,
            text='🎮 هذا قسم UNO.\nاكتب /uno هنا لفتح لعبة جديدة.',
        )
        await reply_same_thread(msg, '✅ تم إنشاء موضوع 🎮 UNO.')
    except BadRequest as e:
        await reply_same_thread(msg, f'ما كدرت أنشئ الموضوع. تأكد أن البوت Admin وعنده Manage Topics.\n{e}')


async def callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    if not q or not q.data or not update.effective_user:
        return
    data = q.data.split(':')
    if len(data) < 3 or data[0] != 'u':
        return
    action, code = data[1], data[2]
    user = update.effective_user

    async with game_lock(code):
        game = storage.get_game(code)
        if not game or not game['active']:
            await q.answer('اللعبة منتهية.', show_alert=True)
            return
        state = game['state']

        if action == 'j':
            if state.get('phase') != 'lobby':
                await q.answer('اللعبة بدأت بالفعل.', show_alert=True)
                return
            if find_player_index(state, user.id) is not None:
                await q.answer('أنت منضم أصلاً.')
                return
            if len(state['players']) >= 10:
                await q.answer('الغرفة ممتلئة.', show_alert=True)
                return
            state['players'].append({
                'user_id': user.id,
                'name': display_name(user),
                'username': user.username,
                'private_ready': True,
                'hand': [],
            })
            storage.save_state(code, state)
            game['state'] = state
            await q.edit_message_text(lobby_text(state), reply_markup=lobby_keyboard(code, context.bot.username))
            await q.answer('تم الانضمام ✅')
            return

        if action == 'l':
            if state.get('phase') != 'lobby':
                await q.answer('بعد بدء اللعبة ما تگدر تنسحب من الزر.', show_alert=True)
                return
            pidx = find_player_index(state, user.id)
            if pidx is None:
                await q.answer('أنت مو منضم.')
                return
            state['players'].pop(pidx)
            storage.save_state(code, state)
            game['state'] = state
            await q.edit_message_text(lobby_text(state), reply_markup=lobby_keyboard(code, context.bot.username))
            await q.answer('تم الانسحاب')
            return

        if action == 's':
            if state.get('phase') != 'lobby':
                await q.answer('اللعبة بدأت.')
                return
            if int(game['creator_id']) != int(user.id) and not await is_admin(context.bot, game['chat_id'], user.id):
                await q.answer('فقط منشئ اللعبة أو الأدمن يگدر يبدأها.', show_alert=True)
                return
            if len(state['players']) < 2:
                await q.answer('نحتاج لاعبين على الأقل.', show_alert=True)
                return
            players = [{k: p[k] for k in ('user_id', 'name', 'username', 'private_ready')} | {'hand': []} for p in state['players']]
            panel_messages = state.get('panel_messages', {})
            state = create_started_state(players)
            state['panel_messages'] = panel_messages
            storage.save_state(code, state)
            game['state'] = state
            try:
                await q.edit_message_text('✅ بدأت اللعبة. استخدموا زر 🃏 أوراقي في اللوحة أدناه.')
            except BadRequest:
                pass
            await edit_board(context.bot, game)
            await q.answer('بدأت اللعبة 🎮')
            return

        if action == 'show':
            if find_player_index(state, user.id) is None:
                await q.answer('أنت مو منضم بهذه اللعبة.', show_alert=True)
                return
            if state.get('phase') == 'lobby':
                await q.answer('انتظر لحد ما تبدأ اللعبة.', show_alert=True)
                return
            ok = await show_hand_panel(context.bot, game, user.id)
            await q.answer('تم عرض أوراقك 🃏' if ok else 'ما كدرت أعرض أوراقك.', show_alert=not ok)
            return

        if action == 'rb':
            if state.get('phase') != 'playing' and state.get('phase') != 'finished':
                await q.answer('اللعبة بعد ما بدت.', show_alert=True)
                return
            await edit_board(context.bot, game)
            await q.answer('تم تحديث اللوحة')
            return

        if state.get('phase') != 'playing':
            await q.answer('اللعبة مو جارية.', show_alert=True)
            return

        if action == 'h':
            ok = await show_hand_panel(context.bot, game, user.id)
            await q.answer('تم التحديث' if ok else 'ما كدرت أحدث يدك.', show_alert=not ok)
            return

        if action == 'p' and len(data) >= 4:
            uid = int(data[3])
            try:
                result = play_card(state, user.id, uid)
                if result.get('needs_color'):
                    await q.edit_message_caption(
                        caption=hand_caption(state, user.id) + '\n\n🎨 اختَر اللون:',
                        reply_markup=color_keyboard(code, uid),
                    )
                    await q.answer()
                    return
            except ValueError as e:
                await q.answer(str(e), show_alert=True)
                return
            storage.save_state(code, state, active=state.get('phase') != 'finished')
            game['state'] = state
            await edit_board(context.bot, game)
            await refresh_open_panels(context.bot, game)
            if state.get('phase') == 'finished':
                storage.deactivate(code)
            await q.answer('تم لعب الورقة ✅')
            return

        if action == 'c' and len(data) >= 5:
            uid = int(data[3])
            color = data[4]
            if color not in COLORS:
                await q.answer('لون غير صالح', show_alert=True)
                return
            try:
                play_card(state, user.id, uid, chosen_color=color)
            except ValueError as e:
                await q.answer(str(e), show_alert=True)
                return
            storage.save_state(code, state, active=state.get('phase') != 'finished')
            game['state'] = state
            await edit_board(context.bot, game)
            await refresh_open_panels(context.bot, game)
            if state.get('phase') == 'finished':
                storage.deactivate(code)
            await q.answer('تم اختيار اللون ✅')
            return

        if action == 'd':
            try:
                result = draw_for_turn(state, user.id)
            except ValueError as e:
                await q.answer(str(e), show_alert=True)
                return
            storage.save_state(code, state)
            game['state'] = state
            await edit_board(context.bot, game)
            await refresh_open_panels(context.bot, game)
            await q.answer('تم السحب 🃏')
            return

        if action == 'pass':
            try:
                pass_after_draw(state, user.id)
            except ValueError as e:
                await q.answer(str(e), show_alert=True)
                return
            storage.save_state(code, state)
            game['state'] = state
            await edit_board(context.bot, game)
            await refresh_open_panels(context.bot, game)
            await q.answer('تم تمرير الدور')
            return

        await q.answer()


async def post_init(app: Application) -> None:
    await app.bot.set_my_commands([
        BotCommand('uno', 'فتح لعبة UNO في هذا الموضوع'),
        BotCommand('uno_status', 'عرض حالة اللعبة بهذا الموضوع'),
        BotCommand('uno_rules', 'قواعد اللعبة'),
        BotCommand('uno_stop', 'إيقاف اللعبة - منشئ اللعبة/الأدمن'),
        BotCommand('uno_topic', 'إنشاء موضوع UNO - للأدمن'),
    ])



def build_app(token: str) -> Application:
    app = ApplicationBuilder().token(token).post_init(post_init).build()
    app.add_handler(CommandHandler('start', start_cmd))
    app.add_handler(CommandHandler('uno', uno_cmd))
    app.add_handler(CommandHandler('uno_status', uno_status_cmd))
    app.add_handler(CommandHandler('uno_rules', uno_rules_cmd))
    app.add_handler(CommandHandler('uno_stop', uno_stop_cmd))
    app.add_handler(CommandHandler('uno_topic', uno_topic_cmd))
    app.add_handler(CallbackQueryHandler(callback, pattern=r'^u:'))
    return app

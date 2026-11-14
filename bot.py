"""Telegram-бот: удаляет из группы сообщения, зазывающие в другие группы и каналы."""

from __future__ import annotations

import asyncio
import logging
import os
import time

from aiogram import Bot, Dispatcher, F
from aiogram.exceptions import TelegramAPIError
from aiogram.types import ChatPermissions, Message

from spamfilter import check_text, find_bot_call, find_bot_mention

log = logging.getLogger("antispam")


def _flag(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "да"}


# Юзернеймы (через запятую), ссылки и упоминания которых разрешены.
ALLOWED = [a.strip() for a in os.getenv("ALLOWED_CHATS", "").split(",") if a.strip()]
# Удалять по зазывающим фразам даже без ссылки ("переходите в нашу новую группу").
CHECK_PHRASES = _flag("CHECK_PHRASES", True)
# Удалять пересылки из чужих каналов и групп.
DELETE_FORWARDS = _flag("DELETE_FORWARDS", False)
# Что делать с тем, кто вызвал чужого бота сообщением вида "@SomeBot код"
# (так рассылают спам со взломанных аккаунтов): mute — запретить писать, ban — забанить, delete — только удалить.
ON_BOT_CALL = os.getenv("ON_BOT_CALL", "mute").strip().lower()

ADMIN_CACHE_TTL = 300
_admin_cache: dict[tuple[int, int], tuple[float, bool]] = {}
_mention_cache: dict[str, bool] = {}

dp = Dispatcher()
GROUPS = F.chat.type.in_({"group", "supergroup"})


async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    key = (chat_id, user_id)
    cached = _admin_cache.get(key)
    if cached and cached[0] > time.monotonic():
        return cached[1]
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        result = member.status in {"creator", "administrator"}
    except TelegramAPIError:
        result = False
    _admin_cache[key] = (time.monotonic() + ADMIN_CACHE_TTL, result)
    return result


async def mention_is_chat(bot: Bot, username: str) -> bool:
    """True, если @username — группа или канал, а не человек."""
    key = username.lower()
    if key not in _mention_cache:
        try:
            chat = await bot.get_chat(f"@{username}")
            _mention_cache[key] = chat.type in {"group", "supergroup", "channel"}
        except TelegramAPIError:
            # Пользователей по @username бот получить не может — значит, это не чат.
            _mention_cache[key] = False
    return _mention_cache[key]


def _bot_allowed(user, bot: Bot) -> bool:
    """Наш бот и боты из ALLOWED_CHATS могут писать, остальные — нет."""
    if user.id == bot.id:
        return True
    return (user.username or "").lower() in {a.lower().lstrip("@") for a in ALLOWED}


async def find_reason(message: Message, bot: Bot) -> str | None:
    chat = message.chat
    raw = message.text or message.caption or ""
    bot_name = find_bot_mention(raw, ALLOWED)
    if bot_name:
        return f"упоминание бота: @{bot_name}"

    text = message.text or message.caption or ""
    entities = message.entities or message.caption_entities or []

    urls = [e.url for e in entities if e.type == "text_link" and e.url]
    if message.reply_markup:
        urls += [b.url for row in message.reply_markup.inline_keyboard for b in row if b.url]

    reason = check_text(
        text,
        extra_urls=urls,
        own_username=chat.username,
        own_chat_id=chat.id,
        allowed=ALLOWED,
        check_phrases=CHECK_PHRASES,
    )
    if reason:
        return reason

    allowed = {a.lower().lstrip("@") for a in ALLOWED}
    if chat.username:
        allowed.add(chat.username.lower())
    for e in entities:
        if e.type != "mention":
            continue
        username = e.extract_from(text).lstrip("@")
        if username.lower() in allowed:
            continue
        if await mention_is_chat(bot, username):
            return f"упоминание чата: @{username}"

    if DELETE_FORWARDS and message.forward_origin:
        origin = message.forward_origin
        source = getattr(origin, "chat", None) or getattr(origin, "sender_chat", None)
        if source and source.id != chat.id and (source.username or "").lower() not in allowed:
            return f"пересылка из: {source.title or source.id}"

    return None


@dp.message(GROUPS, F.new_chat_members)
async def kick_added_bots(message: Message, bot: Bot) -> None:
    """Выгоняет чужих ботов, которых добавил не админ."""
    adder = message.from_user
    if adder and await is_admin(bot, message.chat.id, adder.id):
        return
    for member in message.new_chat_members:
        if member.is_bot and not _bot_allowed(member, bot):
            try:
                await bot.ban_chat_member(message.chat.id, member.id)
                log.info("Выгнан бот @%s из «%s»", member.username, message.chat.title)
            except TelegramAPIError as exc:
                log.warning("Не удалось выгнать бота @%s: %s", member.username, exc)


@dp.message(GROUPS)
@dp.edited_message(GROUPS)
async def moderate(message: Message, bot: Bot) -> None:
    chat = message.chat
    # Посты привязанного канала и сообщения от имени самой группы (анонимные админы).
    if message.is_automatic_forward:
        return
    if message.sender_chat and message.sender_chat.id == chat.id:
        return
    # Чужие боты: участники-боты, гостевые боты (вызов через @упоминание) и инлайн-боты (via).
    sender = message.from_user
    caller = message.guest_bot_caller_user
    human = caller or (sender if sender and not sender.is_bot and not message.sender_chat else None)
    human_is_admin = bool(human) and await is_admin(bot, chat.id, human.id)

    reason = None
    if sender and sender.is_bot and not message.sender_chat and not _bot_allowed(sender, bot):
        # Бот пишет сам: удаляем всегда, кроме ответа на вызов админа.
        if not (caller and human_is_admin):
            reason = f"сообщение чужого бота @{sender.username}"
            if caller:
                reason += f" по вызову {caller.full_name}"
    elif human_is_admin:
        return
    elif caller:
        reason = f"ответ гостевого бота по вызову {caller.full_name}"
    elif message.via_bot and not _bot_allowed(message.via_bot, bot):
        reason = f"сообщение через бота @{message.via_bot.username}"
    else:
        reason = await find_reason(message, bot)
    if not reason:
        return

    who = (
        message.sender_chat.title
        if message.sender_chat
        else message.from_user.full_name
        if message.from_user
        else "?"
    )
    try:
        await message.delete()
        log.info("Удалено в «%s» от %s — %s", chat.title, who, reason)
    except TelegramAPIError as exc:
        log.warning("Не удалось удалить в «%s» (%s): %s", chat.title, reason, exc)

    # Сообщение целиком "@SomeBot код" — аккаунт, скорее всего, взломан и рассылает спам.
    offender = caller or (message.from_user if not message.sender_chat else None)
    is_call = caller or find_bot_call(message.text or message.caption or "", ALLOWED)
    if offender and is_call and not offender.is_bot and ON_BOT_CALL in {"mute", "ban"}:
        try:
            if ON_BOT_CALL == "ban":
                await bot.ban_chat_member(chat.id, offender.id)
            else:
                await bot.restrict_chat_member(
                    chat.id, offender.id, ChatPermissions(can_send_messages=False)
                )
            log.info("%s в «%s»: %s", "Бан" if ON_BOT_CALL == "ban" else "Мут", chat.title, offender.full_name)
        except TelegramAPIError as exc:
            log.warning("Не удалось ограничить %s в «%s»: %s", offender.full_name, chat.title, exc)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise SystemExit("Задайте переменную окружения BOT_TOKEN (токен от @BotFather)")
    bot = Bot(token)
    me = await bot.get_me()
    log.info("Запущен @%s", me.username)
    await dp.start_polling(bot, allowed_updates=["message", "edited_message"])


if __name__ == "__main__":
    asyncio.run(main())

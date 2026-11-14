"""Определение сообщений, зазывающих в другие группы/каналы.

Модуль не зависит от Telegram-библиотек, чтобы его можно было тестировать отдельно.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

# t.me/name, t.me/+invite, t.me/joinchat/xxx, telegram.me/..., tg://join?invite=..., tg://resolve?domain=...
_LINK_RE = re.compile(
    r"(?:https?://)?(?:www\.)?(?:t|telegram)\.(?:me|dog)/(?P<path>[^\s<>\"')\]]+)"
    r"|tg://(?:join\?invite=|resolve\?domain=)(?P<tg>[\w+-]+)",
    re.IGNORECASE,
)

# Латинские буквы, которыми спамеры подменяют кириллицу ("пepeходитe").
_HOMOGLYPHS = str.maketrans(
    "aeopcxykmthb30",
    "аеорсхукмтнвзо",
)

_TARGET = r"(?:групп|чат|канал|бесед|сообществ|паблик)"
_VERB = (
    # только повелительные формы: "переходи(те)", но не "переходил"
    r"(?:(?:переходи|перейди|заходи|зайди|залетай|вступай|вступи|присоединяй|присоедини|"
    r"подписывай|подпиши|добавляй|добавь)(?:те)?(?:сь|ся)?"
    r"|приглашаю|приглашаем|жд[её]м\s+(?:вас|тебя|всех)|переезжаем|переехали|перебираемся|го\s+в)"
)

_PHRASES = [
    # "переходите в нашу новую группу", "подписывайтесь на канал"
    re.compile(rf"\b{_VERB}\b.{{0,40}}?\b{_TARGET}", re.DOTALL),
    # "новая группа", "наш новый канал", "мой чат"
    re.compile(rf"\b(?:нов\w+|наш\w*|мо[йюеё]\w*|друг\w+|основн\w+|резервн\w+)\s+(?:\w+\s+)?{_TARGET}"),
    # "группа переехала", "канал теперь тут"
    re.compile(rf"\b{_TARGET}\w*\s+(?:переехал|теперь\s+(?:тут|здесь|по\s+ссылке))"),
    # "чат переносится в новую группу"
    re.compile(rf"\b{_TARGET}\w*\s+(?:переносится|переезжает|перенесен|перемещается)"),
    # "нажмите на этот текст, чтобы перейти в группу"
    re.compile(r"\bнажмите\b.{0,60}?\bчтобы\s+(?:перейти|присоединиться|вступить)", re.DOTALL),
    # "ссылка в профиле/био"
    re.compile(r"\bссылк\w*\s+(?:в|на)\s+(?:мо[её]м\s+)?(?:профил|био|bio|описани|шапк)"),
]

_PHRASES_EN = [
    re.compile(r"\bjoin\s+(?:us\b|(?:to\s+)?(?:our|my|the|this|new)\s+(?:\w+\s+)?(?:group|channel|chat))"),
    re.compile(r"\b(?:our|my)\s+new\s+(?:group|channel|chat)\b"),
    re.compile(r"\b(?:subscribe|follow)\s+(?:to\s+)?(?:our|my|the)\s+(?:\w+\s+)?(?:group|channel|chat)"),
]


# Вызов гостевого бота: всё сообщение — "@SomeBot <код>" (так запускается рассылка от имени участника).
_BOT_CALL_RE = re.compile(r"\s*@(\w*bot)\b[^\n]{0,64}\s*", re.IGNORECASE)
_BOT_MENTION_RE = re.compile(r"@(\w*bot)\b", re.IGNORECASE)


def find_bot_call(text: str, allowed: Iterable[str] = ()) -> Optional[str]:
    """Юзернейм бота, если сообщение целиком является вызовом бота, иначе None."""
    m = _BOT_CALL_RE.fullmatch(text or "")
    if m and m.group(1).lower() not in {a.lower().lstrip("@") for a in allowed}:
        return m.group(1)
    return None


def find_bot_mention(text: str, allowed: Iterable[str] = ()) -> Optional[str]:
    """Юзернейм первого упомянутого бота (@...bot), не входящего в разрешённые."""
    allowed_set = {a.lower().lstrip("@") for a in allowed}
    for m in _BOT_MENTION_RE.finditer(text or ""):
        if m.group(1).lower() not in allowed_set:
            return m.group(1)
    return None


def _normalize(text: str) -> str:
    text = text.lower().replace("ё", "е")
    return re.sub(r"[ \t ​-‏⁠﻿]+", " ", text)


def find_foreign_link(
    texts: Iterable[str],
    own_username: Optional[str] = None,
    own_chat_id: Optional[int] = None,
    allowed: Iterable[str] = (),
) -> Optional[str]:
    """Возвращает первую найденную ссылку на чужой Telegram-чат или None."""
    allowed_set = {a.lower().lstrip("@") for a in allowed}
    if own_username:
        allowed_set.add(own_username.lower())
    # Ссылки на сообщения внутри приватной супергруппы: t.me/c/<id>/<msg>
    own_internal = None
    if own_chat_id is not None:
        s = str(own_chat_id)
        own_internal = s[4:] if s.startswith("-100") else s.lstrip("-")

    for text in texts:
        if not text:
            continue
        for m in _LINK_RE.finditer(text):
            path = m.group("path") or m.group("tg") or ""
            parts = [p for p in re.split(r"[/?#]", path) if p]
            if not parts:
                continue
            head = parts[0].lower()
            if head == "c" and len(parts) > 1 and parts[1] == own_internal:
                continue
            if head in allowed_set:
                continue
            return m.group(0)
    return None


def find_invite_phrase(text: str) -> Optional[str]:
    """Возвращает найденную зазывающую фразу или None."""
    if not text:
        return None
    norm = _normalize(text)
    for variant in (norm, norm.translate(_HOMOGLYPHS)):
        for rx in _PHRASES:
            m = rx.search(variant)
            if m:
                return m.group(0)
    for rx in _PHRASES_EN:
        m = rx.search(norm)
        if m:
            return m.group(0)
    return None


def check_text(
    text: str,
    extra_urls: Iterable[str] = (),
    own_username: Optional[str] = None,
    own_chat_id: Optional[int] = None,
    allowed: Iterable[str] = (),
    check_phrases: bool = True,
) -> Optional[str]:
    """Возвращает причину удаления или None, если сообщение чистое."""
    link = find_foreign_link([text, *extra_urls], own_username, own_chat_id, allowed)
    if link:
        return f"ссылка: {link}"
    if check_phrases:
        phrase = find_invite_phrase(text)
        if phrase:
            return f"фраза: {phrase}"
    return None

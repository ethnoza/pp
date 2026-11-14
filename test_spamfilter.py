import pytest

from spamfilter import check_text, find_bot_call, find_bot_mention

SPAM = [
    "Переходите в другую группу",
    "Ребята, переходите в нашу новую группу, там интереснее",
    "Все сюда https://t.me/+AbCdEf123",
    "t.me/joinchat/AAAAAE",
    "подписывайтесь на мой канал",
    "Пepeходитe в нoвую гpуппу",  # латиница вместо кириллицы
    "Группа переехала, ищите нас",
    "Заработок от 500$ в день, ссылка в профиле",
    "Join our new group for free signals",
    "tg://join?invite=abcdef",
    "Ждём вас в чате @something",
    "вступайте\nв группу",
    "‼️ Чат переносится в новую группу. Нажмите на этот текст, чтобы перейти в группу",
    "Чат переносится. Подробности позже",
    "💬 Затем нажмите кнопку «Начать», чтобы присоединиться к группе",
]

CLEAN = [
    "Привет всем! Как дела?",
    "Я вчера переходил дорогу и видел канал",
    "В какой группе крови нуждаются?",
    "Кто знает, во сколько начало?",
    "Смотрите https://example.com/t.mex",
    "Этот чат лучший",
]


@pytest.mark.parametrize("text", SPAM)
def test_spam(text):
    assert check_text(text) is not None


@pytest.mark.parametrize("text", CLEAN)
def test_clean(text):
    assert check_text(text) is None


def test_own_and_allowed_links():
    assert check_text("правила: t.me/mygroup/15", own_username="MyGroup") is None
    assert check_text("https://t.me/c/1234567890/42", own_chat_id=-1001234567890) is None
    assert check_text("https://t.me/c/999/42", own_chat_id=-1001234567890) is not None
    assert check_text("наш партнёр t.me/friend", allowed=["@Friend"], check_phrases=False) is None


def test_hidden_link_and_phrases_off():
    assert check_text("жми сюда", extra_urls=["https://t.me/spamchannel"]) is not None
    assert check_text("переходите в другую группу", check_phrases=False) is None


def test_bot_call():
    assert find_bot_call("@galaxyplay_bot 4a55249b3d") == "galaxyplay_bot"
    assert find_bot_call("@Whipholdbot 4a55249b3d") == "Whipholdbot"
    assert find_bot_call("@AminAutoHunterBot") == "AminAutoHunterBot"
    assert find_bot_call("@ethnoza привет") is None
    assert find_bot_call("советую @WeatherBot, удобный, пользуюсь каждый день, там всё просто и понятно без рекламы") is None
    assert find_bot_call("@mybot 123", allowed=["MyBot"]) is None
    assert find_bot_mention("попробуйте @WeatherBot") == "WeatherBot"
    assert find_bot_mention("не наш админ @ethnoza") is None

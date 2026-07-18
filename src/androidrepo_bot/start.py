from typing import TYPE_CHECKING

from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.utils.formatting import Bold, Text
from aiogram.utils.keyboard import InlineKeyboardBuilder

if TYPE_CHECKING:
    from aiogram.types import InlineKeyboardMarkup, Message

SOURCE_CODE_URL = "https://github.com/AndroidRepo-OSS/Bot"
CHANNEL_URL = "https://t.me/AndroidRepo"
COMMUNITY_URL = "https://t.me/AndroidRepo_chat"

router = Router(name=__name__)


def start_keyboard() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💻 Source code", url=SOURCE_CODE_URL)
    builder.button(text="📢 Channel", url=CHANNEL_URL)
    builder.button(text="💬 Community", url=COMMUNITY_URL)
    builder.adjust(1, 2)
    return builder.as_markup()


@router.message(CommandStart())
async def handle_start(message: Message) -> None:
    content = Text(
        "🤖 ",
        Bold("Android Repository Bot"),
        "\n\n",
        "I help the Android Repository team turn public GitHub and GitLab projects into polished channel posts. ",
        "I collect repository details, generate the description and banner, and prepare everything for staff review ",
        "before publication.",
        "\n\n",
        "Discover open-source Android projects in our channel and join the community discussion.",
    )
    await message.answer(**content.as_kwargs(), reply_markup=start_keyboard())

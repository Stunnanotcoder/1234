from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError


async def safe_delete(bot: Bot, chat_id: int, message_id: int | None) -> None:
    if not message_id:
        return
    try:
        await bot.delete_message(chat_id=chat_id, message_id=message_id)
    except (TelegramBadRequest, TelegramForbiddenError):
        # сообщение могло быть удалено / недоступно / старое
        return

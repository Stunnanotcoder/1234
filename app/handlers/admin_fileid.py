from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message

router = Router()


def _extract_file_id(message: Message) -> tuple[str | None, str | None]:
    if message.video:
        return message.video.file_id, "video"
    if message.photo:
        return message.photo[-1].file_id, "photo"
    if message.document:
        return message.document.file_id, "document"
    if message.animation:
        return message.animation.file_id, "animation"
    if message.audio:
        return message.audio.file_id, "audio"
    if message.voice:
        return message.voice.file_id, "voice"
    if message.video_note:
        return message.video_note.file_id, "video_note"
    return None, None


def _is_fileid_token(token: str) -> bool:
    token = token.strip()
    return token == "/fileid" or token.startswith("/fileid@")


def _caption_has_fileid(caption: str | None) -> bool:
    if not caption:
        return False
    # берём первый токен: "/fileid" или "/fileid@bot"
    first = caption.strip().split()[0]
    return _is_fileid_token(first)


@router.message(Command("fileid"))
async def cmd_fileid(message: Message, admin_ids: set[int]):
    if message.from_user.id not in admin_ids:
        return

    # 1) Если это ответ на сообщение — пытаемся вытащить file_id
    if message.reply_to_message:
        src = message.reply_to_message
        file_id, kind = _extract_file_id(src)
        if file_id:
            await message.answer(f"{kind} file_id:\n<code>{file_id}</code>", parse_mode="HTML")
            return

        # диагностика: что за сообщение было в reply
        what = []
        if src.photo:
            what.append("photo")
        if src.video:
            what.append("video")
        if src.document:
            what.append("document")
        if src.animation:
            what.append("animation")
        if src.audio:
            what.append("audio")
        if src.voice:
            what.append("voice")
        if src.video_note:
            what.append("video_note")

        await message.answer(
            "Я вижу, что ты ответил на сообщение, но в нём нет медиа, из которого можно взять file_id.\n\n"
            f"Типы, которые бот нашёл в reply: <code>{', '.join(what) if what else 'ничего'}</code>\n\n"
            "Сделай так:\n"
            "— отправь ОДНО фото/видео (не альбом)\n"
            "— и ответь на него командой <code>/fileid</code>\n"
            "или пришли медиа с подписью <code>/fileid</code>.",
            parse_mode="HTML",
        )
        return

    # 2) Иначе — инструкция
    await message.answer(
        "Сделай так (любой способ):\n\n"
        "1) Отправь фото/видео с подписью:\n"
        "<code>/fileid</code>\n\n"
        "или\n\n"
        "2) Отправь фото/видео, затем ответь на него командой:\n"
        "<code>/fileid</code>\n",
        parse_mode="HTML",
    )


@router.message((F.photo | F.video | F.document | F.animation | F.audio | F.voice | F.video_note) & F.caption)
async def media_with_caption(message: Message, admin_ids: set[int]):
    if message.from_user.id not in admin_ids:
        return

    if not _caption_has_fileid(message.caption):
        return

    file_id, kind = _extract_file_id(message)
    if not file_id:
        await message.reply("Не смог прочитать file_id из этого медиа.")
        return

    await message.reply(f"{kind} file_id:\n<code>{file_id}</code>", parse_mode="HTML")

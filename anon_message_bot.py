from telegram import Update, InputMediaPhoto, InputMediaVideo, InputMediaAnimation
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
import os
from dotenv import load_dotenv
import time
import logging

SPAM_LIMIT =15
SPAM_INTERVAL = 10  # секунд
BLOCK_DURATION = 18000  # секунд (1 час)

# Для хранения времени сообщений: {chat_id: [timestamps]}
message_timestamps = {}
# Для хранения блокировок: {chat_id: block_until_timestamp}
blocked_users = {}

async def anti_spam(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    chat_id = update.message.chat_id
    now = time.time()

    # Проверка блокировки
    if chat_id in blocked_users:
        if now < blocked_users[chat_id]:
            await update.message.reply_text("Вы временно заблокированы за спам. Попробуйте позже.")
            return False
        else:
            del blocked_users[chat_id]

    timestamps = message_timestamps.get(chat_id, [])
    timestamps = [t for t in timestamps if now - t <= SPAM_INTERVAL]
    timestamps.append(now)
    message_timestamps[chat_id] = timestamps

    if len(timestamps) > SPAM_LIMIT:
        blocked_users[chat_id] = now + BLOCK_DURATION
        await update.message.reply_text("Вы были временно заблокированы за спам.")
        return False

    return True


# Загрузка переменных окружения
load_dotenv("database.env")
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_CHAT_ID = int(os.getenv("ADMIN_CHAT_ID"))

# Настройка логирования
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Словари
user_map = {}  # {анонимный_id: chat_id}
reverse_user_map = {}  # {chat_id: анонимный_id}
user_nicks = {}  # {анонимный_id: никнейм}

# Хранилище для обработки альбомов
pending_albums = {}  # {chat_id: {"media": [...], "timeout": int, "caption": str}}

ALBUM_TIMEOUT = 10  # Таймаут ожидания, чтобы собрать альбом, в секундах

def generate_anonymous_id() -> int:
    """Генерация уникального анонимного ID."""
    return len(user_map) + 1

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Приветик. Добро пожаловать в моё место. Хрю~🐷\n\n"
        "https://t.me/+IgBDGmBXimU3NzUy - ссылка на исходный код.\n"
        "https://t.me/Anonimnoe_Soobchenie_bot - анонимная обратная связь с разработчиком и админом."
    )

async def delete_me(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id
    if chat_id in reverse_user_map:
        anon_id = reverse_user_map.pop(chat_id)
        user_map.pop(anon_id, None)
        await update.message.reply_text("Вы удалены. Админ больше не сможет вам написать.")
    else:
        await update.message.reply_text("Вы ещё не зарегистрированы или уже удалены.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.message.chat_id

    if not await anti_spam(update, context):
        return

    if chat_id not in reverse_user_map:
        anonymous_id = generate_anonymous_id()
        user_map[anonymous_id] = chat_id
        reverse_user_map[chat_id] = anonymous_id

    else:
        anonymous_id = reverse_user_map[chat_id]

    if update.message.text:
        await context.bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text=f"Аноним #{anonymous_id}: {update.message.text}"
        )
        await update.message.reply_text("Отправлено!")

    elif update.message.media_group_id:
        if chat_id not in pending_albums:
            pending_albums[chat_id] = {"media": [], "timeout": None, "caption": None}

        media_group = pending_albums[chat_id]["media"]
        if update.message.caption:
            pending_albums[chat_id]["caption"] = update.message.caption

        if update.message.photo:
            media_group.append(InputMediaPhoto(update.message.photo[-1].file_id))
        elif update.message.video:
            media_group.append(InputMediaVideo(update.message.video.file_id))

        jobs = context.job_queue.get_jobs_by_name(f"album_{chat_id}")
        if jobs:
            jobs[0].schedule_removal()

        pending_albums[chat_id]["timeout"] = context.job_queue.run_once(
            send_album, ALBUM_TIMEOUT, chat_id=chat_id, name=f"album_{chat_id}", data=anonymous_id
        )

    else:
        if update.message.photo:
            await context.bot.send_photo(
                chat_id=ADMIN_CHAT_ID,
                photo=update.message.photo[-1].file_id,
                caption=f"Аноним #{anonymous_id}: {update.message.caption or ''}"
            )
        elif update.message.video:
            await context.bot.send_video(
                chat_id=ADMIN_CHAT_ID,
                video=update.message.video.file_id,
                caption=f"Аноним #{anonymous_id}: {update.message.caption or ''}"
            )
        elif update.message.voice:
            await context.bot.send_voice(
                chat_id=ADMIN_CHAT_ID,
                voice=update.message.voice.file_id,
                caption=f"Аноним #{anonymous_id} отправил голосовое сообщение."
            )
        elif update.message.video_note:
            await context.bot.send_video_note(
                chat_id=ADMIN_CHAT_ID,
                video_note=update.message.video_note.file_id
            )
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"Аноним #{anonymous_id} отправил видео кружочек."
            )
        elif update.message.animation:
            await context.bot.send_animation(
                chat_id=ADMIN_CHAT_ID,
                animation=update.message.animation.file_id,
                caption=f"Аноним #{anonymous_id}: {update.message.caption or ''}"
            )
        elif update.message.sticker:
            await context.bot.send_sticker(
                chat_id=ADMIN_CHAT_ID,
                sticker=update.message.sticker.file_id
            )
            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"Аноним #{anonymous_id} отправил стикер."
            )
        await update.message.reply_text("Отправлено!")

async def send_album(context: ContextTypes.DEFAULT_TYPE):
    job = context.job
    chat_id = job.chat_id
    anonymous_id = job.data

    if chat_id in pending_albums:
        media_group = pending_albums[chat_id]["media"]
        caption = pending_albums[chat_id].get("caption", f"Аноним #{anonymous_id}")

        if media_group:
            for i in range(0, len(media_group), 10):
                chunk = media_group[i:i + 10]

                if i == 0 and caption:
                    if isinstance(chunk[0], InputMediaPhoto):
                        chunk[0] = InputMediaPhoto(media=chunk[0].media, caption=caption)
                    elif isinstance(chunk[0], InputMediaVideo):
                        chunk[0] = InputMediaVideo(media=chunk[0].media, caption=caption)
                    elif isinstance(chunk[0], InputMediaAnimation):
                        chunk[0] = InputMediaAnimation(media=chunk[0].media, caption=caption)

                await context.bot.send_media_group(
                    chat_id=ADMIN_CHAT_ID,
                    media=chunk
                )

            await context.bot.send_message(
                chat_id=ADMIN_CHAT_ID,
                text=f"Аноним #{anonymous_id}  отправил альбом."
            )
            await context.bot.send_message(
                chat_id=chat_id,
                text="Ваш альбом был успешно отправлен!"
            )

        pending_albums.pop(chat_id, None)

async def handle_admin_response(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.message.chat_id != ADMIN_CHAT_ID:
        return

    if update.message.text.startswith("/a"):
        parts = update.message.text.split(" ", 2)
        if len(parts) < 3:
            await update.message.reply_text("Формат: /a [ID] [сообщение]")
            return

        try:
            anonymous_id = int(parts[1])
            response_message = parts[2]
        except ValueError:
            await update.message.reply_text("ID должен быть числом.")
            return

        if anonymous_id in user_map:
            user_chat_id = user_map[anonymous_id]
            await context.bot.send_message(
                chat_id=user_chat_id,
                text=response_message
            )
        else:
            await update.message.reply_text("Пользователь с таким ID не найден.")

if __name__ == "__main__":
    if not ADMIN_CHAT_ID:
        raise ValueError("Переменная ADMIN_CHAT_ID не указана в database.env.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("delete_me", delete_me))
    app.add_handler(CommandHandler("a", handle_admin_response))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_message))

    print("Бот запущен!")
    app.run_polling()

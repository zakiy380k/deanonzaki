import hashlib
import hmac
import json
import logging
import os
import time
from urllib.parse import parse_qsl
from fastapi.responses import HTMLResponse

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo,
)
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
WEBAPP_URL = os.getenv("WEBAPP_URL")

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not WEBAPP_URL:
    raise RuntimeError("WEBAPP_URL is not set")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Закрытый канал с анкетами (если используете Telethon или сохраняете посты через хендлер)
CHANNEL_ID = -1004413368129 

# Временное хранилище анкет в памяти (можно заменить на файл или БД)
PROFILES_DB = [
    {
        "name": "Даниил",
        "photo_url": "https://hc1.checker.in/file2link/photos/file_548829.jpg/file_548829.jpg"
    },
    {
        "name": "Сабрина",
        "photo_url": "https://hc1.checker.in/file2link/photos/file_548826.jpg/file_548826.jpg"
    }
]

# ==========================================
# Проверка initData Telegram
# ==========================================

@dp.channel_post(F.chat.id == CHANNEL_ID)
async def catch_channel_post(message: Message):
    # Проверяем, что в посте есть и фотография, и текст (подпись)
    if message.photo and message.caption:
        try:
            # Берем самую качественную фотографию
            photo = message.photo[-1]
            file = await bot.get_file(photo.file_id)
            
            # Формируем прямую ссылку на фото в телеграме
            photo_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file.file_path}"
            name = message.caption.strip()
            
            # Добавляем новую анкету в начало списка
            PROFILES_DB.insert(0, {
                "name": name,
                "photo_url": photo_url
            })
            
            logger.info(f"[NEW PROFILE] Добавлена новая анкета из канала: {name}")
        except Exception as e:
            logger.exception("Ошибка при обработке поста из канала")


def validate_telegram_init_data(
    init_data: str,
    bot_token: str,
    max_age: int = 86400,
):
    try:
        parsed = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = parsed.pop("hash", None)
        if not received_hash:
            return None

        auth_date = parsed.get("auth_date")
        if not auth_date:
            return None

        if time.time() - int(auth_date) > max_age:
            return None

        data_check_string = "\n".join(
            f"{key}={value}"
            for key, value in sorted(parsed.items())
        )

        secret_key = hmac.new(
            b"WebAppData",
            bot_token.encode(),
            hashlib.sha256,
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256,
        ).hexdigest()

        if not hmac.compare_digest(
            calculated_hash,
            received_hash,
        ):
            return None

        user_data = parsed.get("user")
        if not user_data:
            return None

        return json.loads(user_data)

    except Exception:
        logger.exception("Failed to validate Telegram initData")
        return None


# ==========================================
# FastAPI
# ==========================================

app = FastAPI()

class MiniAppRequest(BaseModel):
    init_data: str


@app.get("/")
async def root():
    return {
        "status": "ok",
        "service": "Telegram Mini App",
    }


@app.post("/api/miniapp/open")
async def miniapp_open(data: MiniAppRequest):
    user = validate_telegram_init_data(data.init_data, BOT_TOKEN)
    if not user:
        raise HTTPException(status_code=403, detail="Invalid Telegram initData")

    user_id = user["id"]
    username = user.get("username")
    first_name = user.get("first_name", "")
    last_name = user.get("last_name", "")

    logger.info(
        "[MINI APP OPEN] id=%s username=%s first_name=%s last_name=%s",
        user_id, username, first_name, last_name,
    )

    username_text = f"@{username}" if username else "нет username"
    name = " ".join(x for x in [first_name, last_name] if x)

    await bot.send_message(
        ADMIN_ID,
        (
            "🚀 <b>Новый переход в Mini App</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"👤 Имя: {name or 'не указано'}\n"
            f"🔹 Username: {username_text}"
        ),
    )

    return {"status": "ok"}


@app.post("/api/miniapp/profiles")
async def get_profiles(data: MiniAppRequest):
    user = validate_telegram_init_data(data.init_data, BOT_TOKEN)
    if not user:
        raise HTTPException(status_code=403, detail="Unauthorized")
    
    logger.info(f"[PROFILES FETCH] Пользователь {user.get('id')} запросил список анкет")
    return {"profiles": PROFILES_DB}


@app.get("/webapp", response_class=HTMLResponse)
async def serve_webapp():
    with open("miniapp/index.html", "r", encoding="utf-8") as f:
        return f.read()


# ==========================================
# Telegram Bot
# ==========================================

@dp.message(Command("start"))
async def start_command(message: Message):
    if message.text == "/start suggest":
        await message.answer(
            "📝 Напиши имя, скинь ссылку или фото человека, которого хочешь предложить в рейтинг. "
            "Администратор рассмотрит заявку!"
        )
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🚀 Открыть Mini App",
                    web_app=WebAppInfo(url=WEBAPP_URL),
                )
            ]
        ]
    )

    await message.answer(
        "Нажми кнопку ниже:",
        reply_markup=keyboard,
    )


@dp.message(Command("id"))
async def id_command(message: Message):
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")


# ==========================================
# Запуск бота
# ==========================================

async def start_bot():
    await dp.start_polling(bot)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import asyncio
    task = asyncio.create_task(start_bot())
    yield
    task.cancel()

app.router.lifespan_context = lifespan

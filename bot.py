import os
import re
import asyncio
import time
import uuid
from pathlib import Path

from http.server import BaseHTTPRequestHandler, HTTPServer
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import BadRequest
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ContextTypes,
    filters,
)


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK")

    def log_message(self, format, *args):
        return


def run_web():
    port = int(os.getenv("PORT", "10000"))
    server = HTTPServer(("0.0.0.0", port), HealthHandler)
    server.serve_forever()

TOKEN = os.getenv("BOT_TOKEN")

BASE_DIR = Path.home() / "video_bot"
DOWNLOAD_DIR = BASE_DIR / "downloads"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك!\n\n"
        "أرسل رابط الفيديو وسأعطيك خيارات الجودة:\n\n"
        "360p / 480p / 720p / 1080p\n\n"
        "يدعم المواقع التي يدعمها yt-dlp."
    )


async def receive_url(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    match = re.search(r"https?://\S+", text)

    if not match:
        await update.message.reply_text("❌ أرسل رابطًا صحيحًا.")
        return

    url = match.group(0)

    context.user_data["url"] = url

    keyboard = [
        [
            InlineKeyboardButton("360p", callback_data="q:360"),
            InlineKeyboardButton("480p", callback_data="q:480"),
        ],
        [
            InlineKeyboardButton("720p", callback_data="q:720"),
            InlineKeyboardButton("1080p", callback_data="q:1080"),
        ],
        [
            InlineKeyboardButton("⭐ أفضل جودة", callback_data="q:best"),
        ],
    ]

    await update.message.reply_text(
        "🎬 اختر الجودة:",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def do_download(query, url, quality):
    job_id = uuid.uuid4().hex[:10]
    job_dir = DOWNLOAD_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    output = str(job_dir / "%(title).80s.%(ext)s")

    if quality == "best":
        fmt = "bv*+ba/b"
        quality_text = "أفضل جودة"
    else:
        fmt = (
            f"bv*[height<={quality}]+ba/"
            f"b[height<={quality}]/b"
        )
        quality_text = f"{quality}p"

    command = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "--merge-output-format",
        "mp4",
        "-f",
        fmt,
        "-o",
        output,
        url,
    ]

    try:
        await query.edit_message_text(
            f"⏳ جارٍ التحميل بجودة {quality_text}...\n"
            "انتظر حتى يكتمل التحميل."
        )

        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )

        last_update = 0
        progress_line = ""

        while True:
            line = await process.stdout.readline()

            if not line:
                break

            text = line.decode(errors="ignore").strip()

            if "[download]" in text:
                progress_line = text

                if time.monotonic() - last_update >= 5:
                    try:
                        await query.edit_message_text(
                            f"⏳ جارٍ التحميل بجودة {quality_text}...\n\n"
                            f"{progress_line}"
                        )
                        last_update = time.monotonic()
                    except Exception:
                        pass

        await process.wait()
        stdout = b""
        stderr = b""

        if process.returncode != 0:
            await query.edit_message_text(
                "❌ لم أستطع تنزيل هذا الرابط.\n\n"
                "قد يكون الرابط خاصًا أو غير مدعوم أو يتطلب تسجيل دخول."
            )
            return

        files = [
            p for p in job_dir.iterdir()
            if p.is_file()
        ]

        if not files:
            await query.edit_message_text(
                "❌ لم يتم العثور على الفيديو بعد التحميل."
            )
            return

        file_path = max(
            files,
            key=lambda p: p.stat().st_mtime
        )

        await query.edit_message_text(
            "📤 تم التحميل، جارٍ إرسال الفيديو..."
        )

        with open(file_path, "rb") as video:
            await query.message.reply_video(
                video=video,
                caption=f"✅ تم التحميل — {quality_text}"
            )

    except Exception:
        try:
            await query.edit_message_text(
                "❌ حدث خطأ أثناء تنزيل الفيديو."
            )
        except Exception:
            pass

    finally:
        try:
            for p in job_dir.iterdir():
                if p.is_file():
                    p.unlink()
            job_dir.rmdir()
        except Exception:
            pass


async def download_video(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query

    # الرد على الزر فورًا حتى لا تنتهي صلاحيته
    try:
        await query.answer()
    except BadRequest:
        return

    url = context.user_data.get("url")

    if not url:
        try:
            await query.edit_message_text(
                "❌ أرسل الرابط من جديد."
            )
        except Exception:
            pass
        return

    quality = query.data.split(":")[1]

    # تشغيل التحميل في مهمة مستقلة
    asyncio.create_task(
        do_download(query, url, quality)
    )


def main():
    if not TOKEN:
        print("❌ BOT_TOKEN غير موجود.")
        print("استخدم:")
        print("export BOT_TOKEN='توكن_البوت'")
        return

    app = (
        Application.builder()
        .token(TOKEN)
        .concurrent_updates(True)
        .build()
    )

    app.add_handler(CommandHandler("start", start))

    app.add_handler(
        CallbackQueryHandler(
            download_video,
            pattern=r"^q:"
        )
    )

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            receive_url
        )
    )


    Thread(target=run_web, daemon=True).start()
    app.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":
    main()

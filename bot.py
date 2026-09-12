import os
import re
import glob
import time
import asyncio
import threading
import subprocess
import yt_dlp
import static_ffmpeg
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    ContextTypes,
)

# تفعيل ffmpeg
static_ffmpeg.add_paths()

# خادم ويب لإبقاء Render مستيقظاً 24/7
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is alive 24/7!"

def run_flask():
    port = int(os.environ.get("PORT", 8080))
    web_app.run(host="0.0.0.0", port=port)

threading.Thread(target=run_flask, daemon=True).start()

TOKEN = "8850349497:AAF8kUGQJaNNLhrHVZakm55N8EjYn59YXNM"

def clean_url(text):
    match = re.search(r'(https?://[^\s]+)', text)
    if not match:
        return None
    url = match.group(1)
    if "instagram.com" in url:
        url = url.split("?")[0]
    return url

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك في بوت التحميل السحابي!\n"
        "أرسل لي أي رابط فيديو (يوتيوب أو إنستغرام) للتحميل فوراً 🎬"
    )

async def ask_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    url = clean_url(raw_text)

    if not url:
        await update.message.reply_text("⚠️ لم أتمكن من العثور على رابط صالح في رسالتك.")
        return

    context.user_data['url'] = url

    keyboard = [
        [
            InlineKeyboardButton("🌟 أعلى جودة متاحة (Best)", callback_data="q_best"),
        ],
        [
            InlineKeyboardButton("🎬 720p (HD)", callback_data="q_720"),
            InlineKeyboardButton("📱 360p (سريع)", callback_data="q_360"),
        ],
        [
            InlineKeyboardButton("🎵 صوت فقط (MP3)", callback_data="q_mp3"),
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر الجودة المطلوبة للتحميل:", reply_markup=reply_markup)

def compress_video(input_path, output_path):
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-crf", "32", "-preset", "ultrafast",
        "-c:a", "aac", "-b:a", "96k",
        "-fs", "48M", output_path
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

async def handle_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    choice = query.data
    url = context.user_data.get('url')

    if not url:
        await query.edit_message_text("⚠️ انتهت الجلسة، يرجى إعادة إرسال الرابط.")
        return

    status_msg = await query.edit_message_text("⏳ بدء التحميل من السيرفر السحابي...")

    # تنظيف أي ملفات مؤقتة سابقة
    for f in glob.glob("temp_file*") + glob.glob("compressed*"):
        try:
            os.remove(f)
        except Exception:
            pass

    ydl_opts = {
        'outtmpl': 'temp_file.%(ext)s',
        'quiet': True,
        'no_warnings': True,
        'merge_output_format': 'mp4',
        'nocheckcertificate': True,
        'geo_bypass': True,
        # إجبار يوتيوب على مسار سفاري الذي يتجاوز فحص الروبوت
        'extractor_args': {
            'youtube': {
                'player_client': ['web_safari', 'mweb', 'android'],
                'player_skip': ['web', 'configs']
            }
        },
        'http_headers': {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15',
            'Accept-Language': 'en-US,en;q=0.9',
        },
    }

    if choice == "q_best":
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
    elif choice == "q_720":
        ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best[height<=720]/best'
    elif choice == "q_360":
        ydl_opts['format'] = 'bestvideo[height<=360]+bestaudio/best[height<=360]/best'
    else:
        ydl_opts['format'] = 'bestaudio/best'
        ydl_opts['postprocessors'] = [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }]

    # التحقق من وجود الكوكيز إذا كانت متوفرة
    if os.path.exists("/etc/secrets/cookies.txt"):
        ydl_opts['cookiefile'] = "/etc/secrets/cookies.txt"
    elif os.path.exists("cookies.txt"):
        ydl_opts['cookiefile'] = "cookies.txt"

    try:
        await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))

        files = glob.glob("temp_file.*")
        if not files:
            await status_msg.edit_text("❌ تعذر العثور على الفيديو بعد المعالجة.")
            return

        file_to_send = files[0]
        size_mb = os.path.getsize(file_to_send) / (1024 * 1024)

        if choice != "q_mp3" and size_mb > 49:
            await status_msg.edit_text("⚙️ حجم الفيديو أكبر من 50MB، جاري ضغطه...")
            compressed_file = "compressed.mp4"
            await asyncio.to_thread(compress_video, file_to_send, compressed_file)
            if os.path.exists(compressed_file) and os.path.getsize(compressed_file) > 0:
                os.remove(file_to_send)
                file_to_send = compressed_file

        await status_msg.edit_text("📤 جاري إرسال الملف إليك...")

        with open(file_to_send, 'rb') as f:
            if choice == "q_mp3":
                await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, read_timeout=300, write_timeout=300)
            else:
                await context.bot.send_video(chat_id=query.message.chat_id, video=f, read_timeout=300, write_timeout=300)

        await status_msg.delete()

        if os.path.exists(file_to_send):
            os.remove(file_to_send)

    except Exception as err:
        await status_msg.edit_text(f"❌ خطأ أثناء المعالجة:\n{str(err)[:120]}")

if __name__ == '__main__':
    app = (
        ApplicationBuilder()
        .token(TOKEN)
        .read_timeout(300)
        .write_timeout(300)
        .connect_timeout(60)
        .build()
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, ask_quality))
    app.add_handler(CallbackQueryHandler(handle_choice))

    app.run_polling()

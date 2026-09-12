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

# تفعيل ffmpeg في بيئة العمل السحابية تلقائياً
static_ffmpeg.add_paths()

# 1. تشغيل خادم الويب لإبقاء البوت نشطاً
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
    # تنظيف روابط إنستغرام من المعاملات الزائدة
    if "instagram.com" in url:
        url = url.split("?")[0]
    return url

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك في بوت التحميل السحابي!\n"
        "أرسل لي أي رابط فيديو لاختيار الدقة والتحميل فوراً 🎬"
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
            InlineKeyboardButton("🎬 1080p (FHD)", callback_data="q_1080"),
            InlineKeyboardButton("🎬 720p (HD)", callback_data="q_720"),
        ],
        [
            InlineKeyboardButton("📱 360p (سريع)", callback_data="q_360"),
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

    for f in glob.glob("temp_file*") + glob.glob("compressed*"):
        try:
            os.remove(f)
        except Exception:
            pass

    last_update_time = 0
    loop = asyncio.get_running_loop()

    def progress_hook(d):
        nonlocal last_update_time
        if d['status'] == 'downloading':
            now = time.time()
            if now - last_update_time > 3:
                last_update_time = now
                total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
                downloaded = d.get('downloaded_bytes', 0)
                eta = d.get('eta', 0)
                speed = d.get('speed', 0)

                percent = (downloaded / total * 100) if total > 0 else 0
                speed_mb = (speed / (1024 * 1024)) if speed else 0

                text = (
                    f"⏳ **جاري التحميل...**\n"
                    f"📊 التقدم: {percent:.1f}%\n"
                    f"⏱ الوقت المتبقي: {int(eta)} ثانية\n"
                    f"⚡ السرعة: {speed_mb:.2f} MB/s"
                )
                asyncio.run_coroutine_threadsafe(
                    context.bot.edit_message_text(
                        chat_id=query.message.chat_id,
                        message_id=status_msg.message_id,
                        text=text,
                        parse_mode="Markdown"
                    ),
                    loop
                )

    ydl_opts = {
        'outtmpl': 'temp_file.%(ext)s',
        'progress_hooks': [progress_hook],
        'quiet': True,
        'no_warnings': True,
    }

    if choice == "q_best":
        ydl_opts['format'] = 'bestvideo+bestaudio/best'
    elif choice == "q_1080":
        ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best[height<=1080]/best'
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

    try:
        await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))

        files = glob.glob("temp_file.*")
        if not files:
            await status_msg.edit_text("❌ تعذر العثور على الفيديو.")
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

        await status_msg.edit_text("📤 جاري الإرسال إليك...")

        with open(file_to_send, 'rb') as f:
            if choice == "q_mp3":
                await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, read_timeout=300, write_timeout=300)
            else:
                await context.bot.send_video(chat_id=query.message.chat_id, video=f, read_timeout=300, write_timeout=300)

        await status_msg.delete()

        if os.path.exists(file_to_send):
            os.remove(file_to_send)

    except Exception as err:
        # إظهار سبب الخطأ بدقة لمعرفته فوراً
        await status_msg.edit_text(f"❌ حدث خطأ أثناء المعالجة: {str(err)[:100]}")

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

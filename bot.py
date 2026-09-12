import os
import re
import glob
import time
import asyncio
import threading
import subprocess
import requests
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

static_ffmpeg.add_paths()

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

def download_via_universal_api(url, choice):
    """محرك فك الحظر المباشر لمنصات يوتيوب وإنستغرام"""
    is_audio = (choice == "q_mp3")
    q = "720"
    if choice == "q_1080":
        q = "1080"
    elif choice == "q_360":
        q = "360"

    # استخدام وسيط تنزيل خارجي فوري
    endpoints = [
        "https://api.vkrdownloader.com/server?vkr=",
        "https://downloader.freemedia.workers.dev/?url="
    ]
    
    download_url = None
    for ep in endpoints:
        try:
            r = requests.get(f"{ep}{url}", timeout=15)
            res = r.json()
            if res.get("data") and res["data"].get("downloadUrl"):
                download_url = res["data"]["downloadUrl"]
                break
            elif res.get("url"):
                download_url = res["url"]
                break
        except Exception:
            continue

    if not download_url:
        return None

    ext = "mp3" if is_audio else "mp4"
    out_file = f"temp_file.{ext}"
    with requests.get(download_url, stream=True, timeout=60) as dl:
        dl.raise_for_status()
        with open(out_file, "wb") as f:
            for chunk in dl.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
    return out_file

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 أهلاً بك في بوت التحميل السريع!\n"
        "أرسل لي الرابط وسأقوم بتحميله فوراً 🎬"
    )

async def ask_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    url = clean_url(raw_text)

    if not url:
        await update.message.reply_text("⚠️ يرجى إرسال رابط صالح.")
        return

    context.user_data['url'] = url

    keyboard = [
        [InlineKeyboardButton("🌟 أعلى جودة (1080p / Best)", callback_data="q_1080")],
        [InlineKeyboardButton("🎬 جودة عالية (HD 720p)", callback_data="q_720")],
        [InlineKeyboardButton("📱 جودة خفيفة (360p)", callback_data="q_360")],
        [InlineKeyboardButton("🎵 صوت فقط (MP3)", callback_data="q_mp3")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("اختر الجودة المطلوبة:", reply_markup=reply_markup)

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
        await query.edit_message_text("⚠️ انتهت الجلسة، أرسل الرابط ثانية.")
        return

    status_msg = await query.edit_message_text("⏳ جاري سحب وتجهيز الفيديو...")

    for f in glob.glob("temp_file*") + glob.glob("compressed*"):
        try:
            os.remove(f)
        except Exception:
            pass

    file_to_send = None

    # المحاولة الأولى: عبر المحرك المباشر لفك حظر السيرفرات
    try:
        file_to_send = await asyncio.to_thread(download_via_universal_api, url, choice)
    except Exception:
        file_to_send = None

    # المحاولة الثانية: عبر yt-dlp في حال فشل المحرك
    if not file_to_send:
        ydl_opts = {
            'outtmpl': 'temp_file.%(ext)s',
            'quiet': True,
            'no_warnings': True,
            'merge_output_format': 'mp4',
            'nocheckcertificate': True,
            'http_headers': {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36',
            }
        }
        if choice == "q_1080":
            ydl_opts['format'] = 'bestvideo[height<=1080]+bestaudio/best'
        elif choice == "q_720":
            ydl_opts['format'] = 'bestvideo[height<=720]+bestaudio/best'
        elif choice == "q_360":
            ydl_opts['format'] = 'bestvideo[height<=360]+bestaudio/best'
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
            if files:
                file_to_send = files[0]
        except Exception as err:
            await status_msg.edit_text(f"❌ تعذر التحميل:\n{str(err)[:120]}")
            return

    if not file_to_send or not os.path.exists(file_to_send):
        await status_msg.edit_text("❌ تعذر العثور على الفيديو أو تم تقييد المحتوى.")
        return

    size_mb = os.path.getsize(file_to_send) / (1024 * 1024)

    if choice != "q_mp3" and size_mb > 49:
        await status_msg.edit_text("⚙️ جاري ضغط الفيديو ليتطابق مع قيود تيليجرام...")
        compressed_file = "compressed.mp4"
        await asyncio.to_thread(compress_video, file_to_send, compressed_file)
        if os.path.exists(compressed_file) and os.path.getsize(compressed_file) > 0:
            os.remove(file_to_send)
            file_to_send = compressed_file

    await status_msg.edit_text("📤 جاري الرفع إلى تيليجرام...")

    try:
        with open(file_to_send, 'rb') as f:
            if choice == "q_mp3":
                await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, read_timeout=300, write_timeout=300)
            else:
                await context.bot.send_video(chat_id=query.message.chat_id, video=f, read_timeout=300, write_timeout=300)

        await status_msg.delete()
    except Exception as e:
        await status_msg.edit_text(f"❌ فشل إرسال الملف:\n{str(e)[:100]}")
    finally:
        if os.path.exists(file_to_send):
            os.remove(file_to_send)

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

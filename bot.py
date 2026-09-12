import os
import re
import glob
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

# سيرفر لإبقاء الخدمة نشطة
web_app = Flask(__name__)

@web_app.route('/')
def home():
    return "Bot is running!"

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

def extract_yt_id(url):
    match = re.search(r'(?:youtu\.be\/|youtube\.com\/(?:.*v=|shorts\/|live\/))([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None

def download_youtube_direct(video_id, choice):
    """سحب الفيديو من مصادر متجاوزة لحظر السيرفرات السحابية بالكامل"""
    instances = [
        "https://invidious.jing.rocks",
        "https://inv.nadeko.net",
        "https://invidious.nerdvpn.de",
        "https://invidious.slipfox.xyz"
    ]
    
    data = None
    for base in instances:
        try:
            r = requests.get(f"{base}/api/v1/videos/{video_id}", timeout=6)
            if r.status_code == 200:
                data = r.json()
                break
        except Exception:
            continue

    if not data or "formatStreams" not in data:
        raise Exception("فشل جلب بيانات الفيديو، الخوادم الوسيطة مشغولة حالياً.")

    streams = data.get("formatStreams", [])
    # ترتيب السيرفرات تصاعدياً لضمان الدقة
    streams_sorted = sorted(streams, key=lambda x: int(re.search(r'\d+', x.get('qualityLabel', '0')).group() if re.search(r'\d+', x.get('qualityLabel', '0')) else 0))

    target_url = None
    target_quality = {
        "q_max": 9999,
        "q_1080": 1080,
        "q_720": 720,
        "q_480": 480,
        "q_360": 360,
        "q_mp3": 0
    }.get(choice, 720)

    if choice == "q_mp3":
        target_url = streams_sorted[0].get("url")
    elif choice == "q_max":
        target_url = streams_sorted[-1].get("url")
    else:
        # البحث عن أقرب دقة مطابقة بالضبط
        for s in streams_sorted:
            h_match = re.search(r'\d+', s.get('qualityLabel', ''))
            if h_match and int(h_match.group()) <= target_quality:
                target_url = s.get("url")

    if not target_url:
        target_url = streams_sorted[-1].get("url")

    out_file = "temp_file.mp4"
    with requests.get(target_url, stream=True, timeout=90) as r:
        r.raise_for_status()
        with open(out_file, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)

    if choice == "q_mp3":
        audio_file = "temp_file.mp3"
        subprocess.run(["ffmpeg", "-y", "-i", out_file, "-vn", "-b:a", "192k", audio_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(out_file)
        return audio_file

    return out_file

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("أهلاً بك! أرسل رابط الفيديو للتحميل فوراً 🎬")

async def ask_quality(update: Update, context: ContextTypes.DEFAULT_TYPE):
    raw_text = update.message.text
    url = clean_url(raw_text)

    if not url:
        await update.message.reply_text("⚠️ لم يتم العثور على رابط صالح.")
        return

    context.user_data['url'] = url

    keyboard = [
        [InlineKeyboardButton("🌟 أعلى جودة متاحة (Best)", callback_data="q_max")],
        [InlineKeyboardButton("🎬 Full HD (1080p)", callback_data="q_1080")],
        [InlineKeyboardButton("📺 دقة عالية (720p)", callback_data="q_720")],
        [InlineKeyboardButton("📀 دقة متوسطة (480p)", callback_data="q_480")],
        [InlineKeyboardButton("📱 دقة خفيفة (360p)", callback_data="q_360")],
        [InlineKeyboardButton("🎵 صوت فقط (MP3)", callback_data="q_mp3")],
    ]
    await update.message.reply_text("اختر الجودة المطلوبة:", reply_markup=InlineKeyboardMarkup(keyboard))

def compress_video(input_path, output_path):
    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-c:v", "libx264", "-crf", "30", "-preset", "ultrafast",
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
        await query.edit_message_text("⚠️ انتهت الجلسة، أعد إرسال الرابط.")
        return

    status_msg = await query.edit_message_text("⏳ جاري التحميل والمعالجة...")

    for f in glob.glob("temp_file*") + glob.glob("compressed*"):
        try:
            os.remove(f)
        except Exception:
            pass

    try:
        yt_id = extract_yt_id(url)
        if yt_id:
            # تنزيل يوتيوب عبر الوسيط المتخطي للحظر
            file_to_send = await asyncio.to_thread(download_youtube_direct, yt_id, choice)
        else:
            # المنصات الأخرى (إنستغرام، تيك توك، فيسبوك)
            format_map = {
                "q_max": "bestvideo+bestaudio/best",
                "q_1080": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "q_720": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "q_480": "bestvideo[height<=480]+bestaudio/best[height<=480]/best",
                "q_360": "bestvideo[height<=360]+bestaudio/best[height<=360]/best",
                "q_mp3": "bestaudio/best"
            }
            ydl_opts = {
                'outtmpl': 'temp_file.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'merge_output_format': 'mp4',
                'nocheckcertificate': True,
                'format': format_map.get(choice, "best")
            }
            if choice == "q_mp3":
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            if os.path.exists("cookies.txt"):
                ydl_opts['cookiefile'] = "cookies.txt"

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

        await status_msg.edit_text("📤 جاري الإرسال...")
        with open(file_to_send, 'rb') as f:
            if choice == "q_mp3":
                await context.bot.send_audio(chat_id=query.message.chat_id, audio=f, read_timeout=300, write_timeout=300)
            else:
                await context.bot.send_video(chat_id=query.message.chat_id, video=f, read_timeout=300, write_timeout=300)

        await status_msg.delete()
        if os.path.exists(file_to_send):
            os.remove(file_to_send)

    except Exception as err:
        await status_msg.edit_text(f"❌ خطأ:\n{str(err)[:120]}")

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

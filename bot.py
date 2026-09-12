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

# تفعيل ffmpeg تلقائياً
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

def extract_yt_id(url):
    match = re.search(r'(?:youtu\.be\/|youtube\.com\/(?:watch\?v=|shorts\/|live\/))([a-zA-Z0-9_-]{11})', url)
    return match.group(1) if match else None

def download_youtube_stream(video_id, choice):
    """تخطي حظر يوتيوب عبر خوادم Invidious الآمنة"""
    instances = [
        "https://inv.tux.pizza",
        "https://invidious.nerdvpn.de",
        "https://vid.puffyan.us",
        "https://invidious.private.coffee"
    ]
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
    data = None
    
    for base in instances:
        try:
            res = requests.get(f"{base}/api/v1/videos/{video_id}", headers=headers, timeout=7)
            if res.status_code == 200:
                data = res.json()
                break
        except Exception:
            continue
            
    if not data or "formatStreams" not in data:
        raise Exception("تعذر جلب بيانات الفيديو من خوادم يوتيوب البديلة.")

    streams = data.get("formatStreams", [])
    if not streams:
        raise Exception("لم يتم العثور على صيغ فيديو مباشرة.")

    target_url = None
    if choice == "q_360":
        for s in streams:
            if "360p" in s.get("qualityLabel", ""):
                target_url = s.get("url")
                break
    elif choice in ["q_720", "q_1080", "q_best"]:
        # اختيار أعلى دقة متوفرة مدمجة
        target_url = streams[-1].get("url")

    if not target_url:
        target_url = streams[0].get("url")

    out_file = "temp_file.mp4"
    with requests.get(target_url, stream=True, headers=headers, timeout=60) as r:
        r.raise_for_status()
        with open(out_file, "wb") as f:
            for chunk in r.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    f.write(chunk)
                    
    # إذا كان المطلوب صوت فقط MP3
    if choice == "q_mp3":
        audio_file = "temp_file.mp3"
        subprocess.run(["ffmpeg", "-y", "-i", out_file, "-vn", "-b:a", "192k", audio_file], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(out_file)
        return audio_file

    return out_file

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

    status_msg = await query.edit_message_text("⏳ بدء التحميل من السيرفر...")

    for f in glob.glob("temp_file*") + glob.glob("compressed*"):
        try:
            os.remove(f)
        except Exception:
            pass

    try:
        yt_id = extract_yt_id(url)
        if yt_id:
            # تنزيل يوتيوب عبر مسار تخطي الحظر السحابي
            file_to_send = await asyncio.to_thread(download_youtube_stream, yt_id, choice)
        else:
            # تنزيل إنستغرام والمنصات الأخرى عبر yt-dlp
            ydl_opts = {
                'outtmpl': 'temp_file.%(ext)s',
                'quiet': True,
                'no_warnings': True,
                'merge_output_format': 'mp4',
                'nocheckcertificate': True,
                'format': 'bestvideo+bestaudio/best' if choice != "q_mp3" else 'bestaudio/best'
            }
            if choice == "q_mp3":
                ydl_opts['postprocessors'] = [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]

            if os.path.exists("/etc/secrets/cookies.txt"):
                ydl_opts['cookiefile'] = "/etc/secrets/cookies.txt"
            elif os.path.exists("cookies.txt"):
                ydl_opts['cookiefile'] = "cookies.txt"

            await asyncio.to_thread(lambda: yt_dlp.YoutubeDL(ydl_opts).download([url]))

            files = glob.glob("temp_file.*")
            if not files:
                await status_msg.edit_text("❌ تعذر العثور على الملف.")
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

import os
import aiohttp
import asyncio
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ChatAction
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, ContextTypes, filters

# Environment variable for security
BOT_TOKEN = os.getenv("BOT_TOKEN")
TERABOX_API = "https://wdzone-terabox-api.vercel.app/api"
TERABOX_DOMAINS = (
    "terabox.com", "1024terabox.com", "teraboxapp.com",
    "teraboxlink.com", "terasharelink.com", "terafileshare.com"
)

def create_progress_bar(percentage):
    total_blocks = 10
    filled_blocks = int(total_blocks * percentage // 100)
    empty_blocks = total_blocks - filled_blocks
    return f"{'█' * filled_blocks}{'▒' * empty_blocks} {percentage:.2f}%"

async def extract_link(terabox_url):
    params = {"url": terabox_url}
    async with aiohttp.ClientSession() as session:
        async with session.get(TERABOX_API, params=params) as resp:
            data = await resp.json()
            return data.get("📜 Extracted Info", [None])[0]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📌 Developer Channel", url="https://t.me/Opleech_WD")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("👋 Welcome! Send a valid TeraBox link.", reply_markup=reply_markup)

async def download_file(url, filepath, update):
    prog_msg = await update.message.reply_text("⏳ Starting download...")
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as resp:
            total = int(resp.headers.get('Content-Length', 0))
            downloaded = 0
            chunk_size = 1024 * 1024  # 1MB
            start_time = time.time()

            with open(filepath, 'wb') as f:
                async for chunk in resp.content.iter_chunked(chunk_size):
                    if chunk:
                        f.write(chunk)
                        downloaded += len(chunk)
                        percent = (downloaded / total) * 100 if total else 0
                        bar = create_progress_bar(percent)
                        elapsed = time.time() - start_time
                        speed = (downloaded / 1024) / elapsed if elapsed > 0 else 0
                        eta = ((total - downloaded) / 1024) / speed if speed > 0 else 0
                        await prog_msg.edit_text(f"⬇️ Downloading:\n{bar}\nSpeed: {speed:.2f} KB/s\nETA: {eta:.1f}s")
                        print(f"Koyeb Log ➜ {percent:.2f}% | {speed:.2f} KB/s | ETA: {eta:.1f}s")
    await prog_msg.edit_text("✅ Download complete!")

async def upload_file(filepath, update, context):
    prog_msg = await update.message.reply_text("⏫ Starting upload...")
    file_size = os.path.getsize(filepath)
    sent_bytes = 0
    chunk_size = 1024 * 256  # 256KB

    with open(filepath, 'rb') as f:
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            sent_bytes += len(chunk)
            percent = (sent_bytes / file_size) * 100
            bar = create_progress_bar(percent)
            await prog_msg.edit_text(f"⬆️ Uploading:\n{bar}")
            await asyncio.sleep(0.3)  # simulate delay

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=ChatAction.UPLOAD_DOCUMENT)
    await context.bot.send_document(chat_id=update.effective_chat.id, document=open(filepath, 'rb'))
    await prog_msg.edit_text("✅ Upload complete!")

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    if not any(domain in url for domain in TERABOX_DOMAINS):
        await update.message.reply_text("❌ Invalid TeraBox link!")
        return

    await update.message.reply_text("🔍 Extracting link...")
    file_info = await extract_link(url)

    if not file_info:
        await update.message.reply_text("❌ Failed to extract link.")
        return

    direct_link = file_info.get("🔽 Direct Download Link")
    filename = file_info.get("📂 Title", "file.mp4")

    local_path = f"./{filename}"
    try:
        await download_file(direct_link, local_path, update)
        await upload_file(local_path, update, context)
        os.remove(local_path)
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

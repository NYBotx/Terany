import os
import time
import math
import requests
import logging
from urllib.parse import urlparse
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram.constants import ParseMode
import asyncio
import aiohttp
import aiofiles
from datetime import datetime
import shutil

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv(BOT_TOKEN)
API_URL = 'https://wdzone-terabox-api.vercel.app/api?url='
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit
TELEGRAM_FILE_LIMIT = 2 * 1024 * 1024 * 1024  # 2GB Telegram limit for videos
CHUNK_SIZE = 8 * 1024 * 1024  # 8MB chunks for better performance

class TeraBoxBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.setup_handlers()
    
    def setup_handlers(self):
        """Setup command and message handlers"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stats", self.stats))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        welcome_text = """
🚀 **TeraBox Direct Link Bot - 2GB Support**

🔥 **Features:**
• Extract direct download links from TeraBox
• Auto-download and upload files (up to 2GB)
• Support for large video files
• Progress tracking with real-time updates
• Multiple file format support

📝 **How to use:**
1. Send any TeraBox share link
2. Bot will extract direct download link
3. Files are automatically processed and uploaded

💡 **Commands:**
/start - Show this welcome message
/help - Get detailed help
/stats - Bot statistics

⚡ **Just send a TeraBox link to get started!**
        """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Help", callback_data="help"),
             InlineKeyboardButton("📊 Stats", callback_data="stats")]
        ])
        
        await update.message.reply_text(
            welcome_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    
    async def help_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Help command handler"""
        help_text = """
📖 **Detailed Help Guide**

🔗 **Supported Links:**
• TeraBox share links (https://terabox.com/...)
• 1024TeraBox links
• TeraBox app links

📱 **Usage Examples:**
```
https://terabox.com/s/1ABC123...
https://1024terabox.com/s/1XYZ789...
```

💾 **File Processing:**
• Videos up to 2GB: Direct upload
• Documents up to 50MB: Direct upload
• Large files: Processed with progress tracking

⚠️ **Limitations:**
• Max video file: 2GB
• Max document file: 50MB
• Processing time varies with file size

🛠️ **Troubleshooting:**
• Ensure link is public and accessible
• Check if file hasn't expired
• Large files may take several minutes

💬 **Support:** Forward any issues to bot admin
        """
        
        await update.message.reply_text(
            help_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def stats(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Stats command handler"""
        stats_text = f"""
📊 **Bot Statistics**

🕒 **Uptime:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
🤖 **Bot Version:** v3.1 (2GB Video Support)
⚡ **Status:** Active
🌐 **API Status:** Connected

💾 **Limits:**
• Max video file: 2GB
• Max document file: 50MB
• Optimized for large file processing
• High-speed downloads with progress tracking
        """
        
        await update.message.reply_text(
            stats_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    def progress_bar(self, percentage):
        """Generate progress bar"""
        filled = int(percentage / 5)
        empty = 20 - filled
        bar = '█' * filled + '░' * empty
        return f"[{bar}] {percentage:.1f}%"
    
    def format_file_size(self, size_bytes):
        """Format file size in human readable format"""
        if size_bytes == 0:
            return "0B"
        size_names = ["B", "KB", "MB", "GB"]
        i = int(math.floor(math.log(size_bytes, 1024)))
        p = math.pow(1024, i)
        s = round(size_bytes / p, 2)
        return f"{s} {size_names[i]}"
    
    def is_valid_terabox_url(self, url):
        """Validate TeraBox URL"""
        valid_domains = ['terabox.com', '1024terabox.com', 'teraboxapp.com']
        try:
            parsed = urlparse(url)
            return any(domain in parsed.netloc.lower() for domain in valid_domains)
        except:
            return False
    
    def is_video_file(self, filename):
        """Check if file is a video"""
        video_extensions = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.m4v', '.3gp']
        return any(filename.lower().endswith(ext) for ext in video_extensions)
    
    def calculate_speed(self, bytes_downloaded, time_elapsed):
        """Calculate download speed"""
        if time_elapsed <= 0:
            return "Unknown"
        
        speed_bps = bytes_downloaded / time_elapsed
        return f"{self.format_file_size(speed_bps)}/s"
    
    async def download_file_async(self, url, file_path, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Download file asynchronously with progress tracking"""
        try:
            timeout = aiohttp.ClientTimeout(total=3600)  # 1 hour timeout for large files
            
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}")
                    
                    total_size = int(response.headers.get('content-length', 0))
                    
                    if total_size > MAX_FILE_SIZE:
                        await update.message.reply_text(
                            f"❌ File too large ({self.format_file_size(total_size)})\n"
                            f"Maximum allowed: {self.format_file_size(MAX_FILE_SIZE)}\n\n"
                            "🔗 Use the direct link to download manually."
                        )
                        return None
                    
                    progress_msg = await update.message.reply_text("⬇️ Starting download...")
                    downloaded = 0
                    start_time = time.time()
                    last_update_time = start_time
                    last_update_percent = 0
                    
                    async with aiofiles.open(file_path, 'wb') as f:
                        async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                            await f.write(chunk)
                            downloaded += len(chunk)
                            
                            if total_size > 0:
                                percent = (downloaded / total_size) * 100
                                current_time = time.time()
                                
                                # Update every 5% or every 15 seconds
                                if (percent - last_update_percent >= 5) or (current_time - last_update_time >= 15):
                                    elapsed = current_time - start_time
                                    speed = self.calculate_speed(downloaded, elapsed)
                                    eta = ((total_size - downloaded) / (downloaded / elapsed)) if downloaded > 0 else 0
                                    eta_str = f"{int(eta//60)}m {int(eta%60)}s" if eta > 0 else "Unknown"
                                    
                                    msg = (
                                        f"⬇️ **Downloading...**\n"
                                        f"{self.progress_bar(percent)}\n"
                                        f"📊 {self.format_file_size(downloaded)} / {self.format_file_size(total_size)}\n"
                                        f"🚀 Speed: {speed}\n"
                                        f"⏱️ ETA: {eta_str}"
                                    )
                                    try:
                                        await context.bot.edit_message_text(
                                            chat_id=update.effective_chat.id,
                                            message_id=progress_msg.message_id,
                                            text=msg,
                                            parse_mode=ParseMode.MARKDOWN
                                        )
                                        last_update_percent = percent
                                        last_update_time = current_time
                                    except Exception as e:
                                        logger.warning(f"Progress update failed: {e}")
                    
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=progress_msg.message_id,
                        text="✅ Download completed! Preparing upload...",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    return file_path
                    
        except Exception as e:
            logger.error(f"Download failed: {e}")
            return None
    
    async def upload_and_send_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE, file_path: str, original_name: str):
        """Upload and send file to user"""
        try:
            file_size = os.path.getsize(file_path)
            is_video = self.is_video_file(original_name)
            
            # Check file size limits
            limit = TELEGRAM_FILE_LIMIT if is_video else 50 * 1024 * 1024
            
            if file_size > limit:
                os.remove(file_path)
                file_type = "video" if is_video else "document"
                await update.message.reply_text(
                    f"❌ {file_type.title()} too large for Telegram ({self.format_file_size(file_size)})\n"
                    f"Maximum allowed for {file_type}: {self.format_file_size(limit)}\n\n"
                    "🔗 Use the direct download link instead."
                )
                return
            
            upload_msg = await update.message.reply_text("⬆️ **Uploading to Telegram...**\n⏳ Please wait...")
            
            # Send file based on type
            with open(file_path, 'rb') as file:
                if is_video:
                    await context.bot.send_video(
                        chat_id=update.effective_chat.id,
                        video=file,
                        filename=original_name,
                        caption=f"🎥 **{original_name}**\n📊 Size: {self.format_file_size(file_size)}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_to_message_id=update.message.message_id,
                        supports_streaming=True
                    )
                else:
                    await context.bot.send_document(
                        chat_id=update.effective_chat.id,
                        document=file,
                        filename=original_name,
                        caption=f"📁 **{original_name}**\n📊 Size: {self.format_file_size(file_size)}",
                        parse_mode=ParseMode.MARKDOWN,
                        reply_to_message_id=update.message.message_id
                    )
            
            # Clean up
            try:
                await context.bot.delete_message(
                    chat_id=update.effective_chat.id,
                    message_id=upload_msg.message_id
                )
            except:
                pass
            
            os.remove(file_path)
            
            await update.message.reply_text(
                "✅ **Upload completed successfully!**",
                parse_mode=ParseMode.MARKDOWN
            )
            
        except Exception as e:
            logger.error(f"Upload failed: {e}")
            if os.path.exists(file_path):
                os.remove(file_path)
            await update.message.reply_text(
                "❌ **Upload failed**\n"
                "File might be corrupted or there was a network issue.\n"
                "Please try again or use the direct download link.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle incoming messages"""
        text = update.message.text.strip()
        
        if not self.is_valid_terabox_url(text):
            await update.message.reply_text(
                "❌ **Invalid URL**\n\n"
                "Please send a valid TeraBox link:\n"
                "• https://terabox.com/s/...\n"
                "• https://1024terabox.com/s/...\n"
                "• https://teraboxapp.com/s/...",
                parse_mode=ParseMode.MARKDOWN
            )
            return
        
        processing_msg = await update.message.reply_text(
            "🔍 **Processing TeraBox link...**\n"
            "⏳ Extracting file information...",
            parse_mode=ParseMode.MARKDOWN
        )
        
        try:
            # Call API to extract direct link
            timeout = aiohttp.ClientTimeout(total=60)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(API_URL + text) as response:
                    if response.status != 200:
                        raise Exception(f"API returned status {response.status}")
                    
                    data = await response.json()
            
            # Extract file information
            if "📜 Extracted Info" not in data or not data["📜 Extracted Info"]:
                raise Exception("No file information found")
            
            file_info = data["📜 Extracted Info"][0]
            direct_link = file_info.get("🔽 Direct Download Link")
            file_name = file_info.get("📂 Title", f"terabox_file_{int(time.time())}")
            file_size_str = file_info.get("📊 Size", "Unknown")
            
            if not direct_link:
                raise Exception("Direct download link not found")
            
            # Clean filename
            safe_filename = "".join(c for c in file_name if c.isalnum() or c in (' ', '.', '_', '-')).strip()
            if not safe_filename:
                safe_filename = f"terabox_file_{int(time.time())}"
            
            # Create response with file info
            is_video = self.is_video_file(file_name)
            file_type_emoji = "🎥" if is_video else "📁"
            
            info_text = (
                f"✅ **Link Extracted Successfully!**\n\n"
                f"{file_type_emoji} **File:** `{file_name}`\n"
                f"📊 **Size:** {file_size_str}\n"
                f"🔗 **Direct Link:** [Download]({direct_link})\n\n"
                f"⬇️ **Auto-downloading and uploading...**"
            )
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📥 Direct Download", url=direct_link)]
            ])
            
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=processing_msg.message_id,
                text=info_text,
                parse_mode=ParseMode.MARKDOWN,
                reply_markup=keyboard,
                disable_web_page_preview=True
            )
            
            # Start auto-download
            await self.auto_download_and_send(update, context, direct_link, safe_filename)
            
        except Exception as e:
            logger.error(f"Error processing TeraBox link: {e}")
            error_text = (
                "❌ **Failed to process TeraBox link**\n\n"
                "**Possible reasons:**\n"
                "• Link has expired or is invalid\n"
                "• File is private or restricted\n"
                "• API service is temporarily down\n"
                "• Network connectivity issues\n\n"
                "🔄 **Try again or check the link**"
            )
            
            await context.bot.edit_message_text(
                chat_id=update.effective_chat.id,
                message_id=processing_msg.message_id,
                text=error_text,
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def auto_download_and_send(self, update: Update, context: ContextTypes.DEFAULT_TYPE, direct_link: str, file_name: str):
        """Auto download and send file to user"""
        try:
            # Generate unique file path
            timestamp = int(time.time())
            file_path = f"./downloads/{timestamp}_{file_name}"
            
            # Create downloads directory if it doesn't exist
            os.makedirs("./downloads", exist_ok=True)
            
            # Download file
            downloaded_file = await self.download_file_async(direct_link, file_path, update, context)
            
            if downloaded_file:
                await self.upload_and_send_file(update, context, downloaded_file, file_name)
            else:
                await update.message.reply_text(
                    "❌ **Download failed**\n"
                    "Please use the direct download link above.",
                    parse_mode=ParseMode.MARKDOWN
                )
            
        except Exception as e:
            logger.error(f"Auto download failed: {e}")
            await update.message.reply_text(
                "❌ **Auto download failed**\n"
                "Use the direct download link instead.",
                parse_mode=ParseMode.MARKDOWN
            )
    
    async def run_polling(self):
        """Run bot in polling mode"""
        try:
            logger.info("🚀 Starting TeraBox Bot in polling mode...")
            
            # Initialize and start application
            await self.application.initialize()
            await self.application.start()
            
            # Start polling
            await self.application.updater.start_polling(
                poll_interval=2.0,
                timeout=30,
                bootstrap_retries=5,
                read_timeout=30,
                write_timeout=30,
                connect_timeout=30,
                pool_timeout=30
            )
            
            logger.info("✅ Bot is running and polling for updates...")
            
            # Keep the application running
            import signal
            stop_signals = (signal.SIGINT, signal.SIGTERM)
            
            loop = asyncio.get_running_loop()
            
            def signal_handler():
                logger.info("🛑 Received stop signal, shutting down...")
                for task in asyncio.all_tasks(loop):
                    task.cancel()
            
            for sig in stop_signals:
                loop.add_signal_handler(sig, signal_handler)
            
            # Wait for tasks to complete
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                pass
            
        except Exception as e:
            logger.error(f"❌ Error starting bot: {e}")
        finally:
            # Cleanup
            try:
                await self.application.updater.stop()
                await self.application.stop()
                await self.application.shutdown()
            except:
                pass

def main():
    """Main function to run the bot"""
    try:
        bot = TeraBoxBot()
        
        # Run the bot
        asyncio.run(bot.run_polling())
        
    except KeyboardInterrupt:
        logger.info("🛑 Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Fatal error: {e}")

if __name__ == '__main__':
    # Set up environment for Koyeb
    if not BOT_TOKEN or BOT_TOKEN == 'YOUR_BOT_TOKEN':
        logger.error("❌ BOT_TOKEN environment variable not set!")
        exit(1)
    
    # Clean up downloads directory on startup
    if os.path.exists('./downloads'):
        try:
            shutil.rmtree('./downloads')
        except:
            pass
    
    main()

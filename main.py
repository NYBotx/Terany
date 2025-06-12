import os
import asyncio
import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
import pymongo
from pymongo import MongoClient
import gridfs
import io
import time
from urllib.parse import quote
import logging
from bson import ObjectId
import threading
from datetime import datetime

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Environment variables (Koyeb Secrets)
BOT_TOKEN = os.getenv('BOT_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb://localhost:27017/')
TERABOX_API = "https://terabox-fzslcxeeh-nybotxs-projects.vercel.app/"
PORT = int(os.getenv('PORT', 8080))  # Koyeb port
WEBHOOK_URL = os.getenv('WEBHOOK_URL', '')  # Optional webhook URL

# Validate required environment variables
if not BOT_TOKEN:
    logger.error("BOT_TOKEN environment variable is required!")
    exit(1)

# MongoDB setup with GridFS
try:
    client = MongoClient(MONGODB_URI, serverSelectionTimeoutMS=5000)
    # Test connection
    client.admin.command('ping')
    db = client.terabox_bot
    fs = gridfs.GridFS(db)
    downloads_collection = db.downloads
    users_collection = db.users
    logger.info("MongoDB connection established successfully")
except Exception as e:
    logger.error(f"Failed to connect to MongoDB: {e}")
    exit(1)

class TeraboxBot:
    def __init__(self):
        self.session = None
        self.keep_alive_task = None
        self.last_activity = time.time()
        self.start_time = time.time()
        
    async def start_session(self):
        if not self.session:
            connector = aiohttp.TCPConnector(limit=100, limit_per_host=30)
            timeout = aiohttp.ClientTimeout(total=300, connect=30)
            self.session = aiohttp.ClientSession(
                connector=connector,
                timeout=timeout
            )
    
    async def close_session(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def keep_alive(self):
        """Keep the bot alive by periodic activity"""
        while True:
            try:
                # Update last activity
                self.last_activity = time.time()
                
                # Ping MongoDB to keep connection alive
                client.admin.command('ping')
                
                # Log activity
                logger.info(f"Keep-alive ping at {datetime.now()}")
                
                # Clean up old downloads (older than 1 hour)
                cutoff_time = time.time() - 3600  # 1 hour ago
                old_downloads = downloads_collection.find({
                    "status": "completed",
                    "completed_at": {"$lt": cutoff_time},
                    "cleanup_completed": {"$ne": True}
                })
                
                cleanup_count = 0
                for download in old_downloads:
                    if download.get('gridfs_file_id'):
                        try:
                            self.delete_file_from_mongodb(download['gridfs_file_id'])
                            downloads_collection.update_one(
                                {"_id": download['_id']},
                                {"$set": {"cleanup_completed": True}}
                            )
                            cleanup_count += 1
                        except Exception as e:
                            logger.error(f"Cleanup error for {download['_id']}: {e}")
                
                if cleanup_count > 0:
                    logger.info(f"Cleaned up {cleanup_count} old files")
                
                await asyncio.sleep(300)  # Keep alive every 5 minutes
                
            except Exception as e:
                logger.error(f"Keep-alive error: {e}")
                await asyncio.sleep(60)  # Retry after 1 minute on error

    async def get_terabox_info(self, url: str):
        """Get video information from Terabox API"""
        try:
            await self.start_session()
            api_url = f"{TERABOX_API}?url={quote(url)}"
            
            async with self.session.get(api_url, timeout=30) as response:
                if response.status == 200:
                    data = await response.json()
                    return data
                else:
                    logger.error(f"API request failed: {response.status}")
                    return None
        except Exception as e:
            logger.error(f"Error getting Terabox info: {e}")
            return None

    async def download_to_mongodb(self, download_url: str, filename: str, progress_callback=None):
        """Download file directly to MongoDB GridFS"""
        try:
            await self.start_session()
            
            async with self.session.get(download_url, timeout=None) as response:
                if response.status != 200:
                    logger.error(f"Download failed with status: {response.status}")
                    return None
                
                total_size = int(response.headers.get('content-length', 0))
                downloaded = 0
                
                # Create a BytesIO buffer to collect data
                file_buffer = io.BytesIO()
                
                async for chunk in response.content.iter_chunked(8192):
                    file_buffer.write(chunk)
                    downloaded += len(chunk)
                    
                    # Update activity
                    self.last_activity = time.time()
                    
                    if progress_callback and total_size > 0:
                        progress = (downloaded / total_size) * 100
                        await progress_callback(progress, downloaded, total_size)
                
                # Reset buffer position
                file_buffer.seek(0)
                
                # Store in GridFS
                file_id = fs.put(
                    file_buffer.getvalue(),
                    filename=filename,
                    content_type='application/octet-stream',
                    upload_date=datetime.utcnow(),
                    metadata={'downloaded_at': time.time()}
                )
                
                file_buffer.close()
                logger.info(f"File {filename} stored in GridFS with ID: {file_id}")
                return file_id
                
        except Exception as e:
            logger.error(f"Download error: {e}")
            return None

    def get_file_from_mongodb(self, file_id):
        """Retrieve file from MongoDB GridFS"""
        try:
            return fs.get(file_id)
        except Exception as e:
            logger.error(f"Error retrieving file: {e}")
            return None

    def delete_file_from_mongodb(self, file_id):
        """Delete file from MongoDB GridFS"""
        try:
            fs.delete(file_id)
            logger.info(f"File {file_id} deleted from GridFS")
            return True
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False

bot_instance = TeraboxBot()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    bot_instance.last_activity = time.time()
    user_id = update.effective_user.id
    username = update.effective_user.username or "Unknown"
    
    # Store user info
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "username": username, 
            "last_active": time.time(),
            "first_interaction": time.time()
        }},
        upsert=True
    )
    
    welcome_text = """
🎬 **Terabox Download Bot** - *24/7 Active*

Send me a Terabox link and I'll download and upload the video for you!

**Features:**
✅ Fast downloads from Terabox
✅ Progress tracking
✅ Direct upload to Telegram
✅ MongoDB file storage
✅ File information display
🚀 24/7 Uptime on Koyeb

**How to use:**
1. Send me a Terabox link
2. Wait for file information
3. Click download to start
4. Receive your file!

**Credits:** NY BOTZ

**Commands:**
/start - Start the bot
/help - Show help
/stats - Show your stats
/status - Bot status
    """
    
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler"""
    bot_instance.last_activity = time.time()
    help_text = """
🆘 **Help - How to use the bot**

**Step by Step:**
1. Copy a Terabox share link
2. Send it to this bot
3. Bot will fetch file information
4. Click "📥 Download" button
5. Wait for download and upload to complete

**Supported Links:**
- terabox.com
- 1024terabox.com
- teraboxapp.com

**File Limits:**
- Maximum file size: 2GB (Telegram limit)
- Supported formats: All video/audio formats

**Storage:**
- Files are temporarily stored in MongoDB
- Automatic cleanup after upload
- 24/7 availability on Koyeb

**Credits:** NY BOTZ

Need more help? Contact @NY_BOTZ
    """
    
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stats command handler"""
    bot_instance.last_activity = time.time()
    user_id = update.effective_user.id
    
    user_downloads = downloads_collection.count_documents({"user_id": user_id, "status": "completed"})
    total_downloads = downloads_collection.count_documents({"status": "completed"})
    pending_downloads = downloads_collection.count_documents({"status": {"$in": ["pending", "downloading"]}})
    
    # Get GridFS stats
    try:
        gridfs_files = db.fs.files.count_documents({})
        gridfs_size = sum([doc.get('length', 0) for doc in db.fs.files.find({}, {'length': 1})])
        gridfs_size_mb = gridfs_size / (1024 * 1024)
    except:
        gridfs_files = 0
        gridfs_size_mb = 0
    
    stats_text = f"""
📊 **Statistics Dashboard**

👤 **Your Downloads:** {user_downloads}
📈 **Total Bot Downloads:** {total_downloads}
⏳ **Pending Downloads:** {pending_downloads}

💾 **Storage Info:**
📁 Files in MongoDB: {gridfs_files}
💽 Storage Used: {gridfs_size_mb:.2f} MB

🚀 **Hosting:** Koyeb 24/7
⏰ **Uptime:** {(time.time() - bot_instance.start_time) / 3600:.1f} hours

**Credits:** NY BOTZ
    """
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Status command handler"""
    bot_instance.last_activity = time.time()
    
    try:
        # Test MongoDB connection
        client.admin.command('ping')
        mongodb_status = "✅ Connected"
    except:
        mongodb_status = "❌ Disconnected"
    
    uptime = time.time() - bot_instance.start_time
    uptime_hours = uptime / 3600
    
    status_text = f"""
🔧 **Bot Status Dashboard**

🤖 **Bot:** ✅ Online
🌐 **Hosting:** Koyeb
🗄️ **MongoDB:** {mongodb_status}
🔗 **API Session:** {'✅ Active' if bot_instance.session else '❌ Inactive'}

⏰ **Last Activity:** {datetime.fromtimestamp(bot_instance.last_activity).strftime('%Y-%m-%d %H:%M:%S')}
🕐 **Uptime:** {uptime_hours:.1f} hours
🚀 **Platform:** 24/7 Cloud Hosting

💡 **Keep-Alive:** Active
🔄 **Auto-Cleanup:** Enabled

**Credits:** NY BOTZ
    """
    
    await update.message.reply_text(status_text, parse_mode='Markdown')

async def handle_terabox_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle Terabox links"""
    bot_instance.last_activity = time.time()
    user_id = update.effective_user.id
    message_text = update.message.text
    
    # Check if it's a Terabox link
    terabox_domains = ['terabox.com', '1024terabox.com', 'teraboxapp.com']
    if not any(domain in message_text.lower() for domain in terabox_domains):
        await update.message.reply_text(
            "❌ Please send a valid Terabox link!\n\n**Credits:** NY BOTZ"
        )
        return
    
    # Send processing message
    processing_msg = await update.message.reply_text(
        "🔍 **Processing your Terabox link...**\n\n**Credits:** NY BOTZ",
        parse_mode='Markdown'
    )
    
    # Get file information
    file_info = await bot_instance.get_terabox_info(message_text)
    
    if not file_info or not file_info.get('success'):
        await processing_msg.edit_text(
            "❌ **Failed to fetch file information!**\n\n"
            "Please check if the link is valid and try again.\n\n"
            "**Credits:** NY BOTZ",
            parse_mode='Markdown'
        )
        return
    
    # Extract file details
    try:
        file_data = file_info.get('data', {})
        file_name = file_data.get('filename', 'Unknown')
        file_size = file_data.get('size', 0)
        download_url = file_data.get('downloadUrl', '')
        thumbnail = file_data.get('thumbnail', '')
        
        # Convert size to readable format
        size_mb = file_size / (1024 * 1024) if file_size else 0
        size_text = f"{size_mb:.2f} MB" if size_mb < 1024 else f"{size_mb/1024:.2f} GB"
        
        # Check Telegram file size limit (2GB)
        if file_size > 2 * 1024 * 1024 * 1024:
            await processing_msg.edit_text(
                f"❌ **File too large for Telegram!**\n\n"
                f"📁 **File:** {file_name}\n"
                f"📊 **Size:** {size_text}\n"
                f"🚫 **Limit:** 2GB\n\n"
                "**Credits:** NY BOTZ",
                parse_mode='Markdown'
            )
            return
        
        # Store download info in MongoDB
        download_doc = {
            "user_id": user_id,
            "file_name": file_name,
            "file_size": file_size,
            "download_url": download_url,
            "thumbnail": thumbnail,
            "original_link": message_text,
            "timestamp": time.time(),
            "status": "pending",
            "gridfs_file_id": None
        }
        
        result = downloads_collection.insert_one(download_doc)
        download_id = str(result.inserted_id)
        
        # Create download button
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Download", callback_data=f"download_{download_id}")]
        ])
        
        info_text = f"""
📁 **File Information**

📄 **Name:** {file_name}
📊 **Size:** {size_text}
🔗 **Source:** Terabox
💾 **Storage:** MongoDB GridFS
🚀 **Server:** Koyeb 24/7

**Credits:** NY BOTZ
        """
        
        await processing_msg.edit_text(info_text, parse_mode='Markdown', reply_markup=keyboard)
        
    except Exception as e:
        logger.error(f"Error processing file info: {e}")
        await processing_msg.edit_text(
            "❌ **Error processing file information!**\n\n**Credits:** NY BOTZ",
            parse_mode='Markdown'
        )

async def handle_download_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle download button callback"""
    bot_instance.last_activity = time.time()
    query = update.callback_query
    await query.answer()
    
    callback_data = query.data
    download_id = callback_data.split('_')[1]
    
    # Get download info from MongoDB
    try:
        download_doc = downloads_collection.find_one({"_id": ObjectId(download_id)})
    except:
        await query.edit_message_text(
            "❌ **Invalid download session!**\n\n**Credits:** NY BOTZ",
            parse_mode='Markdown'
        )
        return
    
    if not download_doc:
        await query.edit_message_text(
            "❌ **Download session expired!**\n\n**Credits:** NY BOTZ",
            parse_mode='Markdown'
        )
        return
    
    # Check if already downloaded
    if download_doc.get('status') == 'completed':
        await query.edit_message_text(
            "✅ **File already processed!**\n\n**Credits:** NY BOTZ",
            parse_mode='Markdown'
        )
        return
    
    # Update status to downloading
    downloads_collection.update_one(
        {"_id": ObjectId(download_id)},
        {"$set": {"status": "downloading", "download_started": time.time()}}
    )
    
    # Start download process
    await query.edit_message_text(
        "⬇️ **Starting download to MongoDB...**\n\n**Credits:** NY BOTZ",
        parse_mode='Markdown'
    )
    
    # Progress callback
    last_update = 0
    async def progress_callback(progress, downloaded, total):
        nonlocal last_update
        current_time = time.time()
        
        # Update activity
        bot_instance.last_activity = current_time
        
        # Update every 5 seconds
        if current_time - last_update >= 5:
            progress_text = f"""
⬇️ **Downloading to MongoDB...**

📁 **File:** {download_doc['file_name']}
📊 **Progress:** {progress:.1f}%
📥 **Downloaded:** {downloaded/(1024*1024):.1f} MB / {total/(1024*1024):.1f} MB
💾 **Storage:** GridFS
🚀 **Server:** Koyeb 24/7

**Credits:** NY BOTZ
            """
            
            try:
                await query.edit_message_text(progress_text, parse_mode='Markdown')
                last_update = current_time
            except:
                pass  # Ignore rate limit errors
    
    # Download file to MongoDB GridFS
    file_id = await bot_instance.download_to_mongodb(
        download_doc['download_url'], 
        download_doc['file_name'],
        progress_callback
    )
    
    if not file_id:
        downloads_collection.update_one(
            {"_id": ObjectId(download_id)},
            {"$set": {"status": "failed", "error": "Download failed"}}
        )
        
        await query.edit_message_text(
            "❌ **Download failed!**\n\n"
            "Please try again later.\n\n"
            "**Credits:** NY BOTZ",
            parse_mode='Markdown'
        )
        return
    
    # Update document with GridFS file ID
    downloads_collection.update_one(
        {"_id": ObjectId(download_id)},
        {"$set": {"gridfs_file_id": file_id, "status": "uploading"}}
    )
    
    # Upload to Telegram
    await query.edit_message_text(
        "⬆️ **Uploading to Telegram...**\n\n**Credits:** NY BOTZ",
        parse_mode='Markdown'
    )
    
    try:
        # Get file from GridFS
        grid_file = bot_instance.get_file_from_mongodb(file_id)
        
        if not grid_file:
            raise Exception("Failed to retrieve file from MongoDB")
        
        # Create file-like object from GridFS
        file_data = io.BytesIO(grid_file.read())
        file_data.name = download_doc['file_name']
        
        # Send document to Telegram
        await context.bot.send_document(
            chat_id=query.from_user.id,
            document=file_data,
            filename=download_doc['file_name'],
            caption=f"📁 **{download_doc['file_name']}**\n\n🔥 **Downloaded from Terabox**\n💾 **Processed via MongoDB**\n🚀 **Powered by Koyeb 24/7**\n\n**Credits:** NY BOTZ",
            parse_mode='Markdown'
        )
        
        # Update status to completed
        downloads_collection.update_one(
            {"_id": ObjectId(download_id)},
            {
                "$set": {
                    "status": "completed", 
                    "completed_at": time.time(),
                    "uploaded_to_telegram": True
                }
            }
        )
        
        await query.edit_message_text(
            "✅ **Download completed successfully!**\n\n"
            f"📁 **File:** {download_doc['file_name']}\n"
            f"💾 **Storage:** MongoDB GridFS\n"
            f"📤 **Uploaded:** Telegram\n"
            f"🚀 **Server:** Koyeb 24/7\n\n"
            "**Credits:** NY BOTZ",
            parse_mode='Markdown'
        )
        
        # Clean up: Delete file from GridFS after successful upload
        await asyncio.sleep(5)  # Wait 5 seconds before cleanup
        bot_instance.delete_file_from_mongodb(file_id)
        
        downloads_collection.update_one(
            {"_id": ObjectId(download_id)},
            {"$set": {"gridfs_file_id": None, "cleanup_completed": True}}
        )
        
    except Exception as e:
        logger.error(f"Upload error: {e}")
        
        # Clean up failed upload
        if file_id:
            bot_instance.delete_file_from_mongodb(file_id)
        
        downloads_collection.update_one(
            {"_id": ObjectId(download_id)},
            {"$set": {"status": "upload_failed", "error": str(e)}}
        )
        
        await query.edit_message_text(
            "❌ **Upload to Telegram failed!**\n\n"
            "File was downloaded but couldn't be uploaded.\n\n"
            "**Credits:** NY BOTZ",
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Global error handler"""
    logger.error(f"Update {update} caused error {context.error}")
    bot_instance.last_activity = time.time()

async def shutdown_handler(application):
    """Graceful shutdown handler"""
    logger.info("Shutting down bot...")
    await bot_instance.close_session()
    if bot_instance.keep_alive_task:
        bot_instance.keep_alive_task.cancel()
    client.close()
    logger.info("Bot shutdown complete")

def main():
    """Main function to run the bot"""
    logger.info("Starting Terabox Download Bot...")
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("stats", stats_command))
    application.add_handler(CommandHandler("status", status_command))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_terabox_link))
    application.add_handler(CallbackQueryHandler(handle_download_callback, pattern=r"^download_"))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start keep-alive task
    async def post_init(application):
        bot_instance.keep_alive_task = asyncio.create_task(bot_instance.keep_alive())
        logger.info("Keep-alive task started")
    
    # Add shutdown handler
    async def post_shutdown(application):
        await shutdown_handler(application)
    
    application.post_init = post_init
    application.post_shutdown = post_shutdown
    
    # Run the bot
    if WEBHOOK_URL:
        # Use webhook for production
        logger.info(f"Starting webhook on port {PORT}")
        application.run_webhook(
            listen="0.0.0.0",
            port=PORT,
            webhook_url=WEBHOOK_URL,
            url_path=BOT_TOKEN
        )
    else:
        # Use polling for development
        logger.info("Starting polling...")
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )

if __name__ == '__main__':
    main()

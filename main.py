import os
import time
import math
import requests
import logging
from urllib.parse import urlparse
from telegram import Bot, Update, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler
from telegram.constants import ParseMode
import asyncio
import aiohttp
import aiofiles
from datetime import datetime
import mimetypes
import tempfile
import motor.motor_asyncio
from gridfs import GridFS
import pymongo
from io import BytesIO

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
BOT_TOKEN = os.getenv('BOT_TOKEN', 'YOUR_BOT_TOKEN')
MONGODB_URI = os.getenv('MONGODB_URI', 'mongodb+srv://Nischay999:Nischay999@cluster0.5kufo.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0')
PORT = int(os.getenv('PORT', 8000))
API_URL = 'https://wdzone-terabox-api.vercel.app/api?url='
MAX_FILE_SIZE = 2 * 1024 * 1024 * 1024  # 2GB limit
TELEGRAM_FILE_LIMIT = 2 * 1024 * 1024 * 1024  # 2GB Telegram limit (Premium)
CHUNK_SIZE = 1024 * 1024  # 1MB chunks

class TeraBoxBot:
    def __init__(self):
        self.application = Application.builder().token(BOT_TOKEN).build()
        self.user_settings = {}  # Store user preferences
        self.mongo_client = None
        self.db = None
        self.fs = None
        self.setup_handlers()
    
    async def init_mongodb(self):
        """Initialize MongoDB connection"""
        try:
            self.mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
            self.db = self.mongo_client.terabox_bot
            # Test connection
            await self.db.list_collection_names()
            logger.info("✅ MongoDB connected successfully")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            raise
    
    def setup_handlers(self):
        """Setup command and message handlers"""
        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("help", self.help_command))
        self.application.add_handler(CommandHandler("stats", self.stats))
        self.application.add_handler(CommandHandler("settings", self.settings))
        self.application.add_handler(CallbackQueryHandler(self.handle_callback))
        self.application.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_message)
        )
    
    def get_user_setting(self, user_id, setting, default):
        """Get user setting with default value"""
        return self.user_settings.get(user_id, {}).get(setting, default)
    
    def set_user_setting(self, user_id, setting, value):
        """Set user setting"""
        if user_id not in self.user_settings:
            self.user_settings[user_id] = {}
        self.user_settings[user_id][setting] = value
    
    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Start command handler"""
        welcome_text = """
🚀 **TeraBox Direct Link Bot - Premium**

🔥 **Features:**
• Extract direct download links from TeraBox
• Auto-download and upload files (up to 2GB)
• Full video support without splitting
• Customizable upload format (Video/Document)
• Progress tracking with real-time updates
• Support for all file formats

📝 **How to use:**
1. Send any TeraBox share link
2. Bot will extract direct download link
3. Files are automatically processed and uploaded as full files

💡 **Commands:**
/start - Show this welcome message
/help - Get detailed help
/stats - Bot statistics
/settings - Configure bot settings

⚡ **Just send a TeraBox link to get started!**
        """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📚 Help", callback_data="help"),
             InlineKeyboardButton("⚙️ Settings", callback_data="settings")],
            [InlineKeyboardButton("📊 Stats", callback_data="stats")]
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
• All files up to 2GB are uploaded as complete files
• No splitting - videos remain intact
• Customizable upload format

⚙️ **Settings:**
• Video Format: Upload videos as Video or Document
• Auto Upload: Enable/disable automatic upload
• Quality: Choose upload quality preference

⚠️ **Limitations:**
• Max file size: 2GB
• Processing time varies with file size
• Requires Telegram Premium for files >50MB

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
🤖 **Bot Version:** v4.0 Premium (2GB Full Files)
⚡ **Status:** Active
🌐 **API Status:** Connected
🗄️ **Storage:** MongoDB GridFS

💾 **Current Limits:**
• Max file processing: 2GB
• Full file upload (no splitting)
• Video format preservation
• Concurrent downloads: 2

👥 **Users:** {len(self.user_settings)} active users
        """
        
        await update.message.reply_text(
            stats_text,
            parse_mode=ParseMode.MARKDOWN
        )
    
    async def settings(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Settings command handler"""
        user_id = update.effective_user.id
        video_format = self.get_user_setting(user_id, 'video_format', 'video')
        auto_upload = self.get_user_setting(user_id, 'auto_upload', True)
        
        settings_text = f"""
⚙️ **Bot Settings**

📹 **Video Format:** {'🎬 Video' if video_format == 'video' else '📄 Document'}
🔄 **Auto Upload:** {'✅ Enabled' if auto_upload else '❌ Disabled'}

**Current Settings:**
• Videos will be uploaded as {'Video files' if video_format == 'video' else 'Documents'}
• Auto upload is {'enabled' if auto_upload else 'disabled'}
        """
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"📹 Video Format: {'Video' if video_format == 'video' else 'Document'}", 
                callback_data="toggle_video_format"
            )],
            [InlineKeyboardButton(
                f"🔄 Auto Upload: {'ON' if auto_upload else 'OFF'}", 
                callback_data="toggle_auto_upload"
            )],
            [InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu")]
        ])
        
        await update.message.reply_text(
            settings_text,
            parse_mode=ParseMode.MARKDOWN,
            reply_markup=keyboard
        )
    
    async def handle_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle callback queries from inline keyboards"""
        query = update.callback_query
        user_id = update.effective_user.id
        
        await query.answer()
        
        if query.data == "help":
            await self.help_command(update, context)
        
        elif query.data == "stats":
            await self.stats(update, context)
        
        elif query.data == "settings":
            await self.settings(update, context)
        
        elif query.data == "toggle_video_format":
            current = self.get_user_setting(user_id, 'video_format', 'video')
            new_format = 'document' if current == 'video' else 'video'
            self.set_user_setting(user_id, 'video_format', new_format)
            
            await query.edit_message_text(
                f"✅ Video format changed to: {'🎬 Video' if new_format == 'video' else '📄 Document'}\n\n"
                f"Videos will now be uploaded as {'video files' if new_format == 'video' else 'documents'}.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif query.data == "toggle_auto_upload":
            current = self.get_user_setting(user_id, 'auto_upload', True)
            new_setting = not current
            self.set_user_setting(user_id, 'auto_upload', new_setting)
            
            await query.edit_message_text(
                f"✅ Auto upload {'enabled' if new_setting else 'disabled'}\n\n"
                f"Files will {'automatically be uploaded' if new_setting else 'only show direct links'}.",
                parse_mode=ParseMode.MARKDOWN
            )
        
        elif query.data == "main_menu":
            await self.start(update, context)
    
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
    
    def get_file_type(self, filename):
        """Get file type and MIME type"""
        mime_type, _ = mimetypes.guess_type(filename)
        if mime_type:
            if mime_type.startswith('video/'):
                return 'video'
            elif mime_type.startswith('audio/'):
                return 'audio'
            elif mime_type.startswith('image/'):
                return 'photo'
        return 'document'
    
    async def store_file_mongodb(self, file_data, filename):
        """Store file in MongoDB GridFS"""
        try:
            collection = self.db.fs.files
            chunks_collection = self.db.fs.chunks
            
            # Create file document
            file_doc = {
                'filename': filename,
                'uploadDate': datetime.utcnow(),
                'length': len(file_data),
                'chunkSize': 261120,  # GridFS default chunk size
                'md5': None
            }
            
            # Insert file document
            file_result = await collection.insert_one(file_doc)
            file_id = file_result.inserted_id
            
            # Store file chunks
            chunk_size = 261120
            chunk_num = 0
            
            for i in range(0, len(file_data), chunk_size):
                chunk_data = file_data[i:i + chunk_size]
                chunk_doc = {
                    'files_id': file_id,
                    'n': chunk_num,
                    'data': chunk_data
                }
                await chunks_collection.insert_one(chunk_doc)
                chunk_num += 1
            
            return file_id
            
        except Exception as e:
            logger.error(f"Error storing file in MongoDB: {e}")
            return None
    
    async def retrieve_file_mongodb(self, file_id):
        """Retrieve file from MongoDB GridFS"""
        try:
            collection = self.db.fs.files
            chunks_collection = self.db.fs.chunks
            
            # Get file metadata
            file_doc = await collection.find_one({'_id': file_id})
            if not file_doc:
                return None
            
            # Get file chunks
            chunks = chunks_collection.find({'files_id': file_id}).sort('n', 1)
            file_data = b''
            
            async for chunk in chunks:
                file_data += chunk['data']
            
            return file_data, file_doc['filename']
            
        except Exception as e:
            logger.error(f"Error retrieving file from MongoDB: {e}")
            return None, None
    
    async def download_to_mongodb(self, url, filename, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Download file directly to MongoDB without local storage"""
        try:
            timeout = aiohttp.ClientTimeout(total=3600)  # 1 hour timeout
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        raise Exception(f"HTTP {response.status}: {response.reason}")
                    
                    total_size = int(response.headers.get('content-length', 0))
                    
                    if total_size > MAX_FILE_SIZE:
                        await update.message.reply_text(
                            f"❌ File too large ({self.format_file_size(total_size)})\n"
                            f"Maximum allowed: {self.format_file_size(MAX_FILE_SIZE)}\n\n"
                            "🔗 Use the direct link to download manually."
                        )
                        return None
                    
                    progress_msg = await update.message.reply_text(
                        f"⬇️ **Downloading to cloud storage...**\n"
                        f"📊 File size: {self.format_file_size(total_size)}",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    downloaded = 0
                    last_update_time = time.time()
                    last_update_percent = 0
                    start_time = time.time()
                    file_data = b''
                    
                    async for chunk in response.content.iter_chunked(CHUNK_SIZE):
                        file_data += chunk
                        downloaded += len(chunk)
                        
                        if total_size > 0:
                            percent = (downloaded / total_size) * 100
                            current_time = time.time()
                            
                            # Update every 5% or every 10 seconds
                            if (percent - last_update_percent >= 5) or (current_time - last_update_time >= 10):
                                elapsed_time = current_time - start_time
                                speed = downloaded / elapsed_time if elapsed_time > 0 else 0
                                eta = (total_size - downloaded) / speed if speed > 0 else 0
                                
                                msg = (
                                    f"⬇️ **Downloading to cloud...**\n"
                                    f"{self.progress_bar(percent)}\n"
                                    f"📊 {self.format_file_size(downloaded)} / {self.format_file_size(total_size)}\n"
                                    f"🚀 Speed: {self.format_file_size(speed)}/s\n"
                                    f"⏱️ ETA: {self.format_time(eta)}"
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
                    
                    # Store in MongoDB
                    await context.bot.edit_message_text(
                        chat_id=update.effective_chat.id,
                        message_id=progress_msg.message_id,
                        text="💾 **Storing in cloud database...**",
                        parse_mode=ParseMode.MARKDOWN
                    )
                    
                    file_id = await self.store_file_mongodb(file_data, filename)
                    
                    await context.bot.delete_message(
                        chat_id=update.effective_chat.id,
                        message_id=progress_msg.message_id
                    )
                    
                    return file_id, len(file_data)
                    
        except Exception as e:
            logger.error(f"Download to MongoDB failed: {e}")
            return None, 0
    
    def format_time(self, seconds):
        """Format time in human readable format"""
        if seconds < 60:
            return f"{int(seconds)}s"
        elif seconds < 3600:
            return f"{int(seconds // 60)}m {int(seconds % 60)}s"
        else:
            return f"{int(seconds // 3600)}h {int((seconds % 3600) // 60)}m"
    
    async def upload_from_mongodb(self, update: Update, context: ContextTypes.DEFAULT_TYPE, file_id, original_name: str, direct_link: str, file_size: int):
        """Upload file from MongoDB to Telegram"""
        user_id = update.effective_user.id
        video_format = self.get_user_setting(user_id, 'video_format', 'video')
        
        try:
            upload_msg = await update.message.reply_text(
                f"⬆️ **Uploading from cloud to Telegram...**\n"
                f"📁 {original_name}\n"
                f"📊 {self.format_file_size(file_size)}",
                parse_mode=ParseMode.MARKDOWN
            )
            
            # Retrieve file from MongoDB
            file_data, filename = await self.retrieve_file_mongodb(file_id)
            if not file_data:
                raise Exception("Failed to retrieve file from database")
            
            file_type = self.get_file_type(original_name)
            caption = f"📁 **{original_name}**\n📊 Size: {self.format_file_size(file_size)}"
            
            # Create BytesIO object for upload
            file_buffer = BytesIO(file_data)
            file_buffer.name = original_name
            
            if file_type == 'video' and video_format == 'video':
                await context.bot.send_video(
                    chat_id=update.effective_chat.id,
                    video=file_buffer,
                    filename=original_name,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    supports_streaming=True,
                    reply_to_message_id=update.message.message_id
                )
            elif file_type == 'audio':
                await context.bot.send_audio(
                    chat_id=update.effective_chat.id,
                    audio=file_buffer,
                    filename=original_name,
                    caption=caption,
                    parse_mode=ParseMode.MARKDOWN,
                    reply_to_message_id=update.message.message_id
                )
            elif file_type == 'photo':
       

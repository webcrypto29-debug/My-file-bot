import os
import time
import uuid
import pymongo
import dns.resolver
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler
)

# Render / Web Service Port Binding (Port Keep-Alive Server)
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")
    def log_message(self, format, *args):
        return  # Disable console spam for health checks

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

# Start background web server thread
threading.Thread(target=run_web_server, daemon=True).start()

# Termux DNS Fix (Keep it safe for cloud deployment too)
try:
    dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
    dns.resolver.default_resolver.nameservers = ['8.8.8.8', '8.8.4.4']
except Exception:
    pass

# ----------------- CONFIGURATION -----------------
TOKEN = "8737537284:AAGtP8lwqR3LRwAy4ZWg5iyQG8SdNcFW6fg"
MINI_APP_URL = "https://webcrypto29-debug.github.io/My-file-bot/"
BOT_USERNAME = "MyFile727_bot"

MONGO_URI = "mongodb+srv://n2665099_db_user:sagar_sagr@cluster0.2h1q2w8.mongodb.net/?appName=Cluster0&tlsAllowInvalidCertificates=true"

ADMIN_ID = 5911965767
# --------------------------------------------------

mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["FileBotDB"]
files_col = db["files"]
batch_col = db["batches"]
users_col = db["users"]
channels_col = db["fsub_channels"]
settings_col = db["settings"]

user_data = {}

def get_ad_status():
    st = settings_col.find_one({"_id": "ad_status"})
    if st:
        return st.get("status", True)
    return True

async def check_force_sub(bot, user_id):
    channels = list(channels_col.find())
    unjoined = []
    for ch in channels:
        ch_id = ch["_id"]
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status not in ['member', 'administrator', 'creator']:
                unjoined.append(ch)
        except Exception:
            pass
    return unjoined

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    args = context.args

    async def safe_reply(text, **kwargs):
        if update.message:
            return await update.message.reply_text(text, **kwargs)
        elif update.callback_query and update.callback_query.message:
            return await update.callback_query.message.reply_text(text, **kwargs)
        else:
            return await context.bot.send_message(chat_id=user_id, text=text, **kwargs)

    user_doc = users_col.find_one({"_id": user_id})
    if not user_doc:
        users_col.insert_one({"_id": user_id, "credits": 0})
        current_credits = 0
    else:
        current_credits = user_doc.get("credits", 0)

    # 1. Force Sub Check FIRST
    unjoined_channels = await check_force_sub(context.bot, user_id)
    if unjoined_channels:
        keyboard = []
        for ch in unjoined_channels:
            link = ch.get("link", f"https://t.me/{str(ch['_id']).replace('@', '')}")
            keyboard.append([InlineKeyboardButton(f"Join {ch.get('title', 'Channel')} 📢", url=link)])

        start_param = args[0] if args else "None"
        keyboard.append([InlineKeyboardButton("Joined! Check Now 🔄", callback_data=f"check_fsub_{start_param}")])
        reply_markup = InlineKeyboardMarkup(keyboard)

        await safe_reply(
            "⚠️ **Must Join Channels!**\n\nTo access files/links, please join our required channels first:",
            reply_markup=reply_markup,
            parse_mode="Markdown"
        )
        return

    # 2. Production Ad Verification Handler (Anti-Cheat & Replay Protection)
    if args and args[0] == "VERIFY_AD":
        user_session = user_data.get(user_id)
        if not user_session:
            await safe_reply("⚠️ No active file request found. Please click a share link first!")
            return

        if user_session.get("verified", False):
            await safe_reply("⚠️ This ad session is already used. Please open a new share link.")
            return

        click_time = user_session.get("click_time", 0)
        time_elapsed = time.time() - click_time

        if time_elapsed < 14:
            await safe_reply(
                f"⚠️ **Verification Failed!**\n\n"
                f"The rewarded ad was not completed properly or finished too quickly. Please watch the ad fully.",
                parse_mode="Markdown"
            )
            return

        user_session["verified"] = True

        users_col.update_one({"_id": user_id}, {"$inc": {"credits": 3}}, upsert=True)
        updated_user = users_col.find_one({"_id": user_id})
        new_balance = updated_user.get("credits", 0)

        await safe_reply(
            f"🎉 **Ad Completed Successfully!**\n🎁 **+3 Credits** added to your account.\n💰 Total Balance: **{new_balance} Credits**",
            parse_mode="Markdown"
        )

        if new_balance >= 1:
            users_col.update_one({"_id": user_id}, {"$inc": {"credits": -1}})
            await send_requested_item_direct(update, context, user_id, user_session)
        return

    # 3. File / Link / Batch Share Check
    if args:
        param = args[0]
        file_doc = files_col.find_one({"_id": param})
        batch_doc = batch_col.find_one({"_id": param})

        if file_doc or batch_doc:
            session_info = {
                "type": "batch" if batch_doc else "single",
                "id": param,
                "verified": False,
                "click_time": time.time()
            }
            user_data[user_id] = session_info

            if current_credits >= 1:
                users_col.update_one({"_id": user_id}, {"$inc": {"credits": -1}})
                await send_requested_item_direct(update, context, user_id, session_info)
                return

            if not get_ad_status():
                await safe_reply("ℹ️ Ads are currently disabled by admin, and you have 0 credits.")
                return

            keyboard = [
                [InlineKeyboardButton("Watch Ad Now  🚀", web_app=WebAppInfo(url=MINI_APP_URL))]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            instruction_text = (
                f"🔒 **File / Link Locked!**\n\n"
                f"💰 Your Current Credits: **{current_credits}**\n\n"
                f"📜 **Steps to unlock:**\n"
                f"1. Click the **'Watch Ad Now'** button below.\n"
                f"2. Complete the rewarded ad and wait for the verification timer.\n"
                f"3. You will instantly receive **+3 Credits** and your file!\n\n"
                f"👇 Click below to start:"
            )

            await safe_reply(instruction_text, reply_markup=reply_markup, parse_mode="Markdown")
            return
        else:
            await safe_reply("❌ Invalid or expired link!")
            return

    await safe_reply(
        f"👋 Welcome!\n\n💰 Your Current Balance: **{current_credits} Credits**\n"
        "Send or click any share link to get files, photos, videos, or web links!",
        parse_mode="Markdown"
    )

        # RichAds Ad Fetch & Send
        try:
            import requests
            res = requests.post(
                "http://15068.xml.adx1.com/telegram-mb",
                json={
                    "language_code": "en",
                    "publisher_id": "792361",
                    "telegram_id": str(user_id),
                    "production": True
                },
                timeout=5
            )
            if res.status_code == 200:
                ad_data = res.json()
                if "text" in ad_data:
                    await safe_reply(ad_data["text"])
        except Exception as e:
            print("RichAds Error:", e)
            
async def fsub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data.startswith("check_fsub_"):
        param = data.replace("check_fsub_", "")
        unjoined = await check_force_sub(context.bot, user_id)

        if unjoined:
            await query.answer("❌ You haven't joined all channels yet!", show_alert=True)
        else:
            await query.answer("✅ Verified Successfully!")
            try:
                await query.message.delete()
            except Exception:
                pass

            context.args = [param] if param and param != "None" else []
            await start(update, context)

async def send_requested_item_direct(update, context, user_id, session):
    item_id = session["id"]
    item_type = session["type"]

    await context.bot.send_message(chat_id=user_id, text="⚡ **1 Credit Deducted.** Delivering your content...")
    try:
        if item_type == "single":
            doc = files_col.find_one({"_id": item_id})
            if doc:
                itype = doc.get("item_type")
                if itype == "text":
                    await context.bot.send_message(chat_id=user_id, text=f"🔗 **Your Requested Link/Text:**\n\n{doc['text']}")
                elif itype == "photo":
                    await context.bot.send_photo(chat_id=user_id, photo=doc["file_id"], caption=doc.get("caption", ""))
                elif itype == "video":
                    await context.bot.send_video(chat_id=user_id, video=doc["file_id"], caption=doc.get("caption", ""))
                else:
                    await context.bot.send_document(chat_id=user_id, document=doc["file_id"], caption=doc.get("caption", ""))
        elif item_type == "batch":
            batch_doc = batch_col.find_one({"_id": item_id})
            if batch_doc:
                for f_id in batch_doc["files"]:
                    doc = files_col.find_one({"_id": f_id})
                    if doc:
                        itype = doc.get("item_type")
                        if itype == "text":
                            await context.bot.send_message(chat_id=user_id, text=f"🔗 **Link/Text:**\n\n{doc['text']}")
                        elif itype == "photo":
                            await context.bot.send_photo(chat_id=user_id, photo=doc["file_id"], caption=doc.get("caption", ""))
                        elif itype == "video":
                            await context.bot.send_video(chat_id=user_id, video=doc["file_id"], caption=doc.get("caption", ""))
                        else:
                            await context.bot.send_document(chat_id=user_id, document=doc["file_id"], caption=doc.get("caption", ""))
    except Exception as e:
        await context.bot.send_message(chat_id=user_id, text=f"❌ Error sending item: {str(e)}")

    if user_id in user_data:
        del user_data[user_id]

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    status_text = "🟢 ON" if get_ad_status() else "🔴 OFF"
    await update.message.reply_text(
        f"🛠 **Admin Panel:**\n"
        f"• Send any File, Photo, Video or Web Link to create a link.\n"
        f"• `/batch` - Start/Finish batch.\n"
        f"• `/togglead` - Turn Ads ON/OFF (Current: {status_text})\n"
        f"• `/addchannel @username`\n"
        f"• `/delchannel @username`\n"
        f"• `/channels`"
    )

async def toggle_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    current = get_ad_status()
    new_status = not current
    settings_col.update_one({"_id": "ad_status"}, {"$set": {"status": new_status}}, upsert=True)
    state_str = "🟢 ON" if new_status else "🔴 OFF"
    await update.message.reply_text(f"⚙️ Ad Status updated: {state_str}")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    if not context.args:
        await update.message.reply_text("⚠️ Use format: `/addchannel @yourchannel` or send channel username/ID", parse_mode="Markdown")
        return
    ch_input = context.args[0]
    try:
        chat = await context.bot.get_chat(ch_input)
        channels_col.update_one({"_id": chat.id}, {"$set": {"title": chat.title, "link": f"https://t.me/{chat.username}" if chat.username else ""}}, upsert=True)
        await update.message.reply_text(f"✅ Channel **{chat.title}** added successfully!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error adding channel: {str(e)}\nMake sure bot is an admin in that channel!")

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    if not context.args: return
    try:
        channels_col.delete_one({"_id": int(context.args[0])})
    except:
        channels_col.delete_one({"_id": context.args[0]})
    await update.message.reply_text("✅ Channel removed!")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    channels = list(channels_col.find())
    if not channels:
        await update.message.reply_text("ℹ️ No channels added.")
        return
    msg = "📢 **Force Sub Channels:**\n" + "\n".join([f"- {c.get('title')} (`{c['_id']}`)" for c in channels])
    await update.message.reply_text(msg)

async def handle_admin_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    msg = update.message
    if not msg:
        return

    unique_id = str(uuid.uuid4())[:8]
    item_type = "text"
    file_id = None
    caption = msg.caption or ""
    text_content = msg.text

    if msg.document:
        item_type = "file"
        file_id = msg.document.file_id
    elif msg.video:
        item_type = "video"
        file_id = msg.video.file_id
    elif msg.photo:
        item_type = "photo"
        file_id = msg.photo[-1].file_id
    elif text_content and not text_content.startswith("/"):
        item_type = "text"
    else:
        return

    files_col.insert_one({
        "_id": unique_id,
        "item_type": item_type,
        "file_id": file_id,
        "caption": caption,
        "text": text_content if item_type == "text" else ""
    })

    if context.user_data.get("in_batch"):
        context.user_data["batch_files"].append(unique_id)
        await msg.reply_text(f"✅ Item added to batch! (Total: {len(context.user_data['batch_files'])})")
    else:
        share_link = f"https://t.me/{BOT_USERNAME}?start={unique_id}"
        await msg.reply_text(f"✅ **Link Generated Successfully!**\n\n🔗 **Shareable Link:**\n`{share_link}`", parse_mode="Markdown")

async def start_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    if context.user_data.get("in_batch"):
        files_list = context.user_data.get("batch_files", [])
        if not files_list:
            await update.message.reply_text("⚠️ Batch is empty!")
            return
        batch_id = f"batch_{str(uuid.uuid4())[:8]}"
        batch_col.insert_one({"_id": batch_id, "files": files_list})
        context.user_data["in_batch"] = False
        context.user_data["batch_files"] = []
        batch_link = f"https://t.me/{BOT_USERNAME}?start={batch_id}"
        await update.message.reply_text(f"🎉 **Batch Link Created!**\n\n🔗 **Batch Link:**\n`{batch_link}`", parse_mode="Markdown")
    else:
        context.user_data["in_batch"] = True
        context.user_data["batch_files"] = []
        await update.message.reply_text("📦 **Batch Mode Started!** Send items, then type `/batch` again.")

if __name__ == '__main__':
    print("🚀 Starting Bot on Cloud/Render...")
    app = ApplicationBuilder().token(TOKEN).connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("batch", start_batch))
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("togglead", toggle_ad))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("delchannel", del_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CallbackQueryHandler(fsub_callback, pattern="^check_fsub_"))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_admin_content))
    print("✅ Bot is online and polling...")
    app.run_polling()

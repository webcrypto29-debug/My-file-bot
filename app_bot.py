import asyncio
import json
import os
import re
import threading
import time
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, HTTPServer

import dns.resolver
import pymongo
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update, WebAppInfo
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ----------------- SERVER KEEP-ALIVE -----------------
class SimpleHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Bot is active and running!")

    def log_message(self, format, *args):
        return

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()

# Termux DNS Fix
try:
    dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
    dns.resolver.default_resolver.nameservers = ["8.8.8.8", "8.8.4.4"]
except Exception:
    pass

# ----------------- CONFIGURATION -----------------
TOKEN = "8737537284:AAGtP8lwqR3LRwAy4ZWg5iyQG8SdNcFW6fg"
MINI_APP_URL = "https://webcrypto29-debug.github.io/My-file-bot/"
BOT_USERNAME = "MyFile727_bot"

MONGO_URI = "mongodb+srv://n2665099_db_user:sagar_sagr@cluster0.2h1q2w8.mongodb.net/?appName=Cluster0&tlsAllowInvalidCertificates=true"
ADMIN_ID = 5911965767
AUTO_DELETE_SECONDS = 120  # 2 Minutes Auto-Delete

# Database Channel ID (Add your DB Channel ID here, e.g., -100xxxxxxxxxx)
# Make sure the bot is ADMIN in your DB channel: https://t.me/+PD3_G7V35rEzODM9
DB_CHANNEL_ID = -1002233445566  # Replace this with your exact DB Channel ID
# --------------------------------------------------

# MongoDB Setup
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["FileBotDB"]
files_col = db["files"]
batch_col = db["batches"]
users_col = db["users"]
channels_col = db["fsub_channels"]
settings_col = db["settings"]
broadcast_history_col = db["broadcast_history"]

user_data = {}
broadcast_control = {"is_running": False}

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
            if member.status not in ["member", "administrator", "creator"]:
                unjoined.append(ch)
        except Exception:
            pass
    return unjoined

# ----------------- AUTO DELETE TASK -----------------
async def delete_message_after_delay(bot, chat_id, message_ids, delay):
    await asyncio.sleep(delay)
    for msg_id in message_ids:
        try:
            await bot.delete_message(chat_id=chat_id, message_id=msg_id)
        except Exception:
            pass

# ----------------- MAIN START HANDLER -----------------
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

    # 1. Force Sub Check
    unjoined_channels = await check_force_sub(context.bot, user_id)
    if unjoined_channels:
        keyboard = []
        for ch in unjoined_channels:
            link = ch.get("link", f"https://t.me/{str(ch['_id']).replace('@', '')}")
            keyboard.append([InlineKeyboardButton(f"Join {ch.get('title', 'Channel')} 📢", url=link)])
        
        start_param = args[0] if args else "None"
        keyboard.append([InlineKeyboardButton("Joined! Check Now 🔄", callback_data=f"check_fsub_{start_param}")])
        
        await safe_reply(
            "⚠️ **Must Join Channels!**\n\nTo access files/links, please join our required channels first:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown",
        )
        return

    # 2. Ad Verification Handler
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
                "⚠️ **Verification Failed!**\n\nThe rewarded ad was not completed properly or finished too quickly. Please watch the ad fully.",
                parse_mode="Markdown",
            )
            return

        user_session["verified"] = True
        users_col.update_one({"_id": user_id}, {"$inc": {"credits": 3}}, upsert=True)
        updated_user = users_col.find_one({"_id": user_id})
        new_balance = updated_user.get("credits", 0)

        await safe_reply(
            f"🎉 **Ad Completed Successfully!**\n🎁 **+3 Credits** added to your account.\n💰 Total Balance: **{new_balance} Credits**",
            parse_mode="Markdown",
        )

        if new_balance >= 1:
            users_col.update_one({"_id": user_id}, {"$inc": {"credits": -1}})
            await send_requested_item_direct(update, context, user_id, user_session, deduct_credit=True)
        return

    # 3. File / Batch Request
    if args:
        param = args[0]
        file_doc = files_col.find_one({"_id": param})
        batch_doc = batch_col.find_one({"_id": param})

        if file_doc or batch_doc:
            session_info = {
                "type": "batch" if batch_doc else "single",
                "id": param,
                "verified": False,
                "click_time": time.time(),
            }
            user_data[user_id] = session_info

            if not get_ad_status():
                await send_requested_item_direct(update, context, user_id, session_info, deduct_credit=False)
                return

            if current_credits >= 1:
                users_col.update_one({"_id": user_id}, {"$inc": {"credits": -1}})
                await send_requested_item_direct(update, context, user_id, session_info, deduct_credit=True)
                return

            keyboard = [[InlineKeyboardButton("Watch Ad Now  🚀", web_app=WebAppInfo(url=MINI_APP_URL))]]
            await safe_reply(
                f"🔒 **File Locked!**\n\n💰 Your Credits: **{current_credits}**\n\n👇 Click below to watch a short ad. You will get **+3 Credits** and your file instantly!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return
        else:
            await safe_reply("❌ Invalid or expired link!")
            return

    # 4. Normal Start
    await safe_reply(
        f"👋 Welcome!\n\n💰 Your Current Balance: **{current_credits} Credits**\nClick any file link to download content!",
        parse_mode="Markdown",
    )

# ----------------- FILE DELIVERY WITH 2-MIN AUTO DELETE -----------------
async def send_requested_item_direct(update, context, user_id, session, deduct_credit=True):
    item_id = session["id"]
    item_type = session["type"]

    msg_text = "⚡ **1 Credit Deducted.** Delivering content..." if deduct_credit else "⚡ Delivering content..."
    info_msg = await context.bot.send_message(chat_id=user_id, text=msg_text)

    sent_message_ids = [info_msg.message_id]

    try:
        docs = []
        if item_type == "single":
            doc = files_col.find_one({"_id": item_id})
            if doc: docs.append(doc)
        elif item_type == "batch":
            batch_doc = batch_col.find_one({"_id": item_id})
            if batch_doc:
                for f_id in batch_doc["files"]:
                    d = files_col.find_one({"_id": f_id})
                    if d: docs.append(d)

        for doc in docs:
            itype = doc.get("item_type")
            cap = (doc.get("caption", "") or "") + "\n\n⚠️ **This file will be automatically deleted in 2 minutes! Forward it to Saved Messages now.**"

            if itype == "text":
                sent = await context.bot.send_message(chat_id=user_id, text=f"🔗 **Link/Text:**\n\n{doc['text']}\n\n⚠️ **Deletes in 2 minutes!**")
            elif itype == "photo":
                sent = await context.bot.send_photo(chat_id=user_id, photo=doc["file_id"], caption=cap, parse_mode="Markdown")
            elif itype == "video":
                sent = await context.bot.send_video(chat_id=user_id, video=doc["file_id"], caption=cap, parse_mode="Markdown")
            else:
                sent = await context.bot.send_document(chat_id=user_id, document=doc["file_id"], caption=cap, parse_mode="Markdown")
            
            if sent:
                sent_message_ids.append(sent.message_id)

        # Background timer for 2-Minute Auto Delete in User PM
        asyncio.create_task(delete_message_after_delay(context.bot, user_id, sent_message_ids, AUTO_DELETE_SECONDS))

    except Exception as e:
        await context.bot.send_message(chat_id=user_id, text=f"❌ Error: {str(e)}")

    if user_id in user_data:
        del user_data[user_id]

# ----------------- DATABASE CHANNEL AUTO-SAVER -----------------
async def handle_db_channel_post(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.channel_post
    if not msg:
        return

    unique_id = str(uuid.uuid4())[:8]
    item_type, file_id = "text", None

    if msg.document: item_type, file_id = "file", msg.document.file_id
    elif msg.video: item_type, file_id = "video", msg.video.file_id
    elif msg.photo: item_type, file_id = "photo", msg.photo[-1].file_id
    elif msg.text: item_type = "text"
    else: return

    caption_text = msg.caption or msg.text or "File Link"

    # Store directly in Mongo DB
    files_col.insert_one({
        "_id": unique_id,
        "item_type": item_type,
        "file_id": file_id,
        "caption": caption_text,
        "text": msg.text if item_type == "text" else "",
        "created_at": time.time()
    })

# ----------------- GROUP SEARCH & HYPERLINK FORMATTER WITH AUTO-DELETE -----------------
async def handle_group_search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or not msg.text or msg.text.startswith("/"):
        return

    if msg.chat.type not in ["group", "supergroup"]:
        return

    start_time = time.time()
    query_text = msg.text.strip()
    if len(query_text) < 2:
        return

    regex_pattern = re.compile(re.escape(query_text), re.IGNORECASE)
    results = list(files_col.find({
        "$or": [
            {"caption": {"$regex": regex_pattern}},
            {"text": {"$regex": regex_pattern}}
        ]
    }).limit(10))

    user = msg.from_user
    user_name = user.first_name if user else "User"

    if results:
        elapsed = round(time.time() - start_time, 2)
        
        # Exact Formatting from Second Photo
        response = (
            f"🏷 **TITLE :** `{query_text}`\n"
            f"📦 **TOTAL FILES :** {len(results)}\n"
            f"⏰ **RESULT IN :** {elapsed} SECONDS\n\n"
            f"📝 **REQUESTED BY :** {user_name}\n"
            f"⚜️ **POWERED BY :** {BOT_USERNAME}\n\n"
            f"<u><b>Your Requested Files Are Here</b></u>\n\n"
        )

        for idx, file_item in enumerate(results, start=1):
            title = file_item.get("caption") or file_item.get("text") or "Download File"
            clean_title = title.replace("\n", " ").strip()
            if len(clean_title) > 60:
                clean_title = clean_title[:57] + "..."
            
            bot_link = f"https://t.me/{BOT_USERNAME}?start={file_item['_id']}"
            response += f"**{idx}.** [{clean_title}]({bot_link})\n\n"

        sent_group_msg = await msg.reply_text(response, parse_mode="Markdown", disable_web_page_preview=True)

        # 2-Minute Auto Delete for Group Search Result
        asyncio.create_task(delete_message_after_delay(context.bot, msg.chat.id, [sent_group_msg.message_id], AUTO_DELETE_SECONDS))
    else:
        # File Not Found Alert (Deletes in 2 minutes too)
        sent_group_msg = await msg.reply_text(
            f"❌ **File Not Found!**\n\nYour request for `{query_text}` has been logged.",
            parse_mode="Markdown"
        )
        asyncio.create_task(delete_message_after_delay(context.bot, msg.chat.id, [sent_group_msg.message_id], AUTO_DELETE_SECONDS))

# ----------------- BROADCAST & ADMIN COMMANDS -----------------
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    total_users = users_col.count_documents({})
    total_files = files_col.count_documents({})
    await update.message.reply_text(f"📊 **Bot Stats:**\n👥 Users: **{total_users}**\n📁 Files: **{total_files}**", parse_mode="Markdown")

# ----------------- MAIN APP INITIALIZATION -----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))

    # Callbacks
    app.add_handler(CallbackQueryHandler(fsub_callback))

    # 1. DB Channel Auto Posts Handler
    app.add_handler(MessageHandler(
        filters.ChatType.CHANNEL,
        handle_db_channel_post
    ))

    # 2. Group Auto Search (Formatted + Auto Delete in 2 Mins)
    app.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.GROUPS,
        handle_group_search
    ))

    print("🤖 Bot is active with DB Channel Listener...")
    app.run_polling()

if __name__ == "__main__":
    main()

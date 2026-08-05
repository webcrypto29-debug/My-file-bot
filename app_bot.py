import asyncio
import json
import os
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
        f"👋 Welcome!\n\n💰 Your Current Balance: **{current_credits} Credits**\nSend or click any share link to get files!",
        parse_mode="Markdown",
    )


# ----------------- BROADCAST & DELETE CONTROLS -----------------
async def run_background_broadcast(bot, admin_chat_id, reply_msg, extra_markup):
    global broadcast_control
    broadcast_control["is_running"] = True

    all_users = list(users_col.find({}))
    total_users = len(all_users)

    if total_users == 0:
        broadcast_control["is_running"] = False
        await bot.send_message(chat_id=admin_chat_id, text="ℹ️ डेटाबेस में कोई भी यूज़र नहीं मिला।")
        return

    status_msg = await bot.send_message(chat_id=admin_chat_id, text=f"🚀 {total_users} यूज़र्स को ब्रॉडकास्ट भेजा जा रहा है...\n🛑 रोकने के लिए `/stopbroadcast` भेजें।")

    success = 0
    failed = 0

    for u in all_users:
        if not broadcast_control["is_running"]:
            await bot.send_message(chat_id=admin_chat_id, text="⚠️ **ब्रॉडकास्ट बीच में ही रोक दिया गया है!**")
            break

        u_id = u["_id"]
        try:
            sent_msg = await bot.copy_message(
                chat_id=int(u_id),
                from_chat_id=reply_msg.chat_id,
                message_id=reply_msg.message_id,
                reply_markup=extra_markup
            )
            if sent_msg:
                broadcast_history_col.insert_one({
                    "user_id": int(u_id),
                    "message_id": sent_msg.message_id
                })
            success += 1
            await asyncio.sleep(0.05)
        except Exception:
            failed += 1

    broadcast_control["is_running"] = False

    try:
        await status_msg.edit_text(
            f"✅ **ब्रॉडकास्ट प्रक्रिया समाप्त हुई!**\n\n"
            f"👥 कुल यूज़र्स: **{total_users}**\n"
            f"🎯 सफलतापूर्वक भेजा गया: **{success}**\n"
            f"❌ विफल/ब्लॉक: **{failed}**",
            parse_mode="Markdown"
        )
    except Exception:
        pass


async def broadcast_richads(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return

    if broadcast_control["is_running"]:
        await update.message.reply_text("⚠️ पहले से एक ब्रॉडकास्ट चल रहा है! उसे रोकने के लिए `/stopbroadcast` भेजें।")
        return

    if not update.message.reply_to_message:
        await update.message.reply_text(
            "⚠️ **उपयोग का तरीका:**\n\n"
            "जिस भी एड्स या बटन्स वाले मैसेज को सभी को भेजना है, उस पर **Reply** करें और फिर `/sendad` लिखें!",
            parse_mode="Markdown"
        )
        return

    reply_msg = update.message.reply_to_message
    extra_markup = reply_msg.reply_markup if reply_msg.reply_markup else None

    asyncio.create_task(run_background_broadcast(
        bot=context.bot,
        admin_chat_id=update.effective_chat.id,
        reply_msg=reply_msg,
        extra_markup=extra_markup
    ))


async def stop_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    
    if broadcast_control["is_running"]:
        broadcast_control["is_running"] = False
        await update.message.reply_text("🛑 ब्रॉडकास्ट रोकने की कमांड ले ली गई है। यह तुरंत बंद हो रहा है...")
    else:
        await update.message.reply_text("ℹ️ इस समय कोई भी ब्रॉडकास्ट चालू नहीं है।")


async def delete_broadcasts(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    
    records = list(broadcast_history_col.find({}))
    if not records:
        await update.message.reply_text("ℹ️ डेटाबेस में डिलीट करने के लिए कोई पुराना ब्रॉडकास्ट रिकॉर्ड नहीं मिला।")
        return
    
    status_msg = await update.message.reply_text(f"🗑 कुल {len(records)} ब्रॉडकास्ट मैसेज्स को यूज़र्स की चैट से डिलीट किया जा रहा है...")
    
    deleted_count = 0
    failed_count = 0
    
    for rec in records:
        try:
            await context.bot.delete_message(chat_id=rec["user_id"], message_id=rec["message_id"])
            deleted_count += 1
            await asyncio.sleep(0.03)
        except Exception:
            failed_count += 1
            
    broadcast_history_col.delete_many({})
    
    try:
        await status_msg.edit_text(
            f"✅ **ब्रॉडकास्ट डिलीट प्रक्रिया पूरी हुई!**\n\n"
            f"🗑 सफलतापूर्वक डिलीट किए गए मैसेज: **{deleted_count}**\n"
            f"⚠️ जो डिलीट नहीं हो सके (यूज़र द्वारा डिलीट या बॉट ब्लॉक): **{failed_count}**",
            parse_mode="Markdown"
        )
    except Exception:
        pass


# ----------------- HELPER FUNCTIONS -----------------
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
            await query.answer("✅ Verified!")
            try:
                await query.message.delete()
            except Exception:
                pass
            context.args = [param] if param and param != "None" else []
            await start(update, context)

async def send_requested_item_direct(update, context, user_id, session, deduct_credit=True):
    item_id = session["id"]
    item_type = session["type"]

    msg_text = "⚡ **1 Credit Deducted.** Delivering content..." if deduct_credit else "⚡ Delivering content..."
    await context.bot.send_message(chat_id=user_id, text=msg_text)

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
            if itype == "text":
                await context.bot.send_message(chat_id=user_id, text=f"🔗 **Link/Text:**\n\n{doc['text']}")
            elif itype == "photo":
                await context.bot.send_photo(chat_id=user_id, photo=doc["file_id"], caption=doc.get("caption", ""))
            elif itype == "video":
                await context.bot.send_video(chat_id=user_id, video=doc["file_id"], caption=doc.get("caption", ""))
            else:
                await context.bot.send_document(chat_id=user_id, document=doc["file_id"], caption=doc.get("caption", ""))
    except Exception as e:
        await context.bot.send_message(chat_id=user_id, text=f"❌ Error: {str(e)}")

    if user_id in user_data:
        del user_data[user_id]


# ----------------- ADMIN COMMANDS -----------------
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    
    total_users = users_col.count_documents({})
    total_files = files_col.count_documents({})
    total_batches = batch_col.count_documents({})
    
    await update.message.reply_text(
        f"📊 **Bot Statistics:**\n\n"
        f"👥 Total Users: **{total_users}**\n"
        f"📁 Single Files: **{total_files}**\n"
        f"📦 Batches Created: **{total_batches}**",
        parse_mode="Markdown"
    )

async def admin_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    status = "🟢 ON" if get_ad_status() else "🔴 OFF"
    await update.message.reply_text(
        "🛠 **Admin Panel:**\n"
        "• `/stats` - यूज़र्स और फाइल्स के स्टैट्स देखें।\n"
        "• **Direct Send / /genlink:** फाइल भेजें या `/genlink` से लिंक बनाएं।\n"
        "• `/sendad` - (मैसेज पर Reply करके) ब्रॉडकास्ट शुरू करें।\n"
        "• `/stopbroadcast` - चालू ब्रॉडकास्ट रोकें।\n"
        "• `/deletebroadcast` - सभी ब्रॉडकास्ट मैसेज्स डिलीट करें।\n"
        "• `/batch` - बैच लिंक मोड ऑन/ऑफ करें।\n"
        f"• `/togglead` - एड्स टॉगल करें ({status})\n"
        "• `/addchannel @username`\n"
        "• `/delchannel @username`\n"
        "• `/channels`"
    )

async def toggle_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    new_status = not get_ad_status()
    settings_col.update_one({"_id": "ad_status"}, {"$set": {"status": new_status}}, upsert=True)
    await update.message.reply_text(f"⚙️ Ad Status: {'🟢 ON' if new_status else '🔴 OFF'}")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    if not context.args: return await update.message.reply_text("⚠️ Use: `/addchannel @channel`")
    try:
        chat = await context.bot.get_chat(context.args[0])
        channels_col.update_one(
            {"_id": chat.id},
            {"$set": {"title": chat.title, "link": f"https://t.me/{chat.username}" if chat.username else ""}},
            upsert=True
        )
        await update.message.reply_text(f"✅ Added {chat.title}!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    if not context.args: return
    try: channels_col.delete_one({"_id": int(context.args[0])})
    except: channels_col.delete_one({"_id": context.args[0]})
    await update.message.reply_text("✅ Channel removed!")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    channels = list(channels_col.find())
    if not channels: return await update.message.reply_text("ℹ️ No channels.")
    await update.message.reply_text("📢 Channels:\n" + "\n".join([f"- {c.get('title')}" for c in channels]))

# --- /genlink COMMAND HANDLER ---
async def gen_link_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID:
        return
    
    msg = update.message
    if not msg.reply_to_message:
        await update.message.reply_text("⚠️ कृपया किसी फाइल, फोटो या टेक्स्ट मैसेज पर **Reply** करके `/genlink` लिखें!")
        return
    
    target_msg = msg.reply_to_message
    unique_id = str(uuid.uuid4())[:8]
    item_type, file_id = "text", None

    if target_msg.document: item_type, file_id = "file", target_msg.document.file_id
    elif target_msg.video: item_type, file_id = "video", target_msg.video.file_id
    elif target_msg.photo: item_type, file_id = "photo", target_msg.photo[-1].file_id
    elif target_msg.text: item_type = "text"
    else:
        await update.message.reply_text("❌ समर्थित फ़ॉर्मेट नहीं है!")
        return

    files_col.insert_one({
        "_id": unique_id, "item_type": item_type, "file_id": file_id,
        "caption": target_msg.caption or "", "text": target_msg.text if item_type == "text" else ""
    })

    await update.message.reply_text(f"✅ **Single File Link Generated:**\n`https://t.me/{BOT_USERNAME}?start={unique_id}`", parse_mode="Markdown")

# --- AUTOMATIC SINGLE FILE / BATCH HANDLER ---
async def handle_admin_content(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    msg = update.message
    if not msg: return

    unique_id = str(uuid.uuid4())[:8]
    item_type, file_id = "text", None

    if msg.document: item_type, file_id = "file", msg.document.file_id
    elif msg.video: item_type, file_id = "video", msg.video.file_id
    elif msg.photo: item_type, file_id = "photo", msg.photo[-1].file_id
    elif msg.text and not msg.text.startswith("/"): item_type = "text"
    else: return

    files_col.insert_one({
        "_id": unique_id, "item_type": item_type, "file_id": file_id,
        "caption": msg.caption or "", "text": msg.text if item_type == "text" else ""
    })

    if context.user_data.get("in_batch"):
        if "batch_files" not in context.user_data:
            context.user_data["batch_files"] = []
        context.user_data["batch_files"].append(unique_id)
        await msg.reply_text(f"✅ Added to batch ({len(context.user_data['batch_files'])})")
    else:
        await msg.reply_text(f"✅ **Single File Link Generated:**\n`https://t.me/{BOT_USERNAME}?start={unique_id}`", parse_mode="Markdown")

async def start_batch(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user or update.effective_user.id != ADMIN_ID: return
    if context.user_data.get("in_batch"):
        if not context.user_data.get("batch_files"): 
            context.user_data["in_batch"] = False
            return await update.message.reply_text("⚠️ Batch empty! Batch mode exited.")
        
        batch_id = f"batch_{str(uuid.uuid4())[:8]}"
        batch_col.insert_one({"_id": batch_id, "files": context.user_data["batch_files"]})
        context.user_data["in_batch"] = False
        context.user_data["batch_files"] = []
        await update.message.reply_text(f"🎉 **Batch Link Generated:**\n`https://t.me/{BOT_USERNAME}?start={batch_id}`", parse_mode="Markdown")
    else:
        context.user_data["in_batch"] = True
        context.user_data["batch_files"] = []
        await update.message.reply_text("📦 **Batch Mode Started!** अब आप जितनी चाहें उतनी फाइल्स भेजें, अंत में दोबारा `/batch` दबाएं।")

# ----------------- MAIN BOOT -----------------
if __name__ == "__main__":
    app = ApplicationBuilder().token(TOKEN).connect_timeout(30.0).read_timeout(30.0).write_timeout(30.0).build()
    
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("sendad", broadcast_richads))
    app.add_handler(CommandHandler("stopbroadcast", stop_broadcast))
    app.add_handler(CommandHandler("deletebroadcast", delete_broadcasts))
    app.add_handler(CommandHandler("genlink", gen_link_command))
    app.add_handler(CommandHandler("batch", start_batch))
    app.add_handler(CommandHandler("admin", admin_help))
    app.add_handler(CommandHandler("togglead", toggle_ad))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("delchannel", del_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CallbackQueryHandler(fsub_callback, pattern="^check_fsub_"))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_admin_content))

    print("✅ Bot is polling...")
    app.run_polling()

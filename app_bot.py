import os
import time
import asyncio
import threading
import uuid
import pymongo
import dns.resolver
import requests
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, ContextTypes, filters
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

# Termux / DNS Fix
try:
    dns.resolver.default_resolver = dns.resolver.Resolver(configure=False)
    dns.resolver.default_resolver.nameservers = ['8.8.8.8', '8.8.4.4']
except Exception:
    pass

# ----------------- CONFIGURATION -----------------
TOKEN = os.environ.get("BOT_TOKEN", "8737537284:AAGtP8lwqR3LRwAy4ZWg5iyQG8SdNcFW6fg")
MINI_APP_URL = "https://webcrypto29-debug.github.io/My-file-bot/"
BOT_USERNAME = "MyFile727_bot"

MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://n2665099_db_user:sagar_sagr@cluster0.2h1q2w8.mongodb.net/?appName=Cluster0&tlsAllowInvalidCertificates=true")
ADMIN_ID = 5911965767

WARNING_TEXT = (
    "⚠️ 𝗪𝗔𝗥𝗡𝗜𝗡𝗚 ⚠️\n\n"
    "𝗕𝗲𝗳𝗼𝗿𝗲 𝗗𝗼𝘄𝗻𝗹𝗼𝗮𝗱𝗶𝗻𝗴 𝘁𝗵𝗲 𝗘𝗽𝗶𝘀𝗼𝗱𝗲(𝘀) 𝗣𝗹𝗲𝗮𝘀𝗲 𝗙𝗼𝗿𝘄𝗮𝗿𝗱 𝗧𝗵𝗲𝗺 𝘁𝗼 "
    "𝗦𝗮𝘃𝗲𝗱 𝗠𝗲𝘀𝘀𝗮𝗴𝗲𝘀 𝗼𝗿 𝗔𝗻𝗼𝘁𝗵𝗲𝗿 𝗖𝗵𝗮𝘁, 𝗛𝗲𝗿𝗲 𝗧𝗵𝗲𝘆 𝗪𝗶𝗹𝗹 𝗕𝗲 𝗗𝗲𝗹𝗲𝘁𝗲𝗱 𝗜𝗻 𝟯𝟬 𝗠𝗶𝗻𝘂𝘁𝗲𝘀 "
    "𝗧𝗼 𝗔𝘃𝗼𝗶𝗱 𝗖𝗼𝗽𝘆𝗿𝗶𝗴𝗵𝘁 𝗶𝘀𝘀𝘂𝗲𝘀"
)
DELETE_TIME_SECONDS = 1800  # 30 Minutes

# ----------------- DATABASE SETUP -----------------
mongo_client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS=5000)
db = mongo_client["FileBotDB"]
files_col = db["files"]
batch_col = db["batches"]
users_col = db["users"]
channels_col = db["fsub_channels"]
settings_col = db["settings"]
broadcast_history_col = db["broadcast_history"]
sessions_col = db["sessions"]

broadcast_control = {"is_running": False}
admin_states = {}
batch_sessions = {}

def get_ad_status():
    try:
        st = settings_col.find_one({"_id": "ad_status"})
        if st:
            return st.get("status", True)
    except Exception as e:
        print(f"DB Error (get_ad_status): {e}")
    return True

def get_current_earn_link():
    try:
        st = settings_col.find_one({"_id": "earn_link"})
        if st and st.get("link"):
            return st.get("link")
    except Exception:
        pass
    return "https://t.me/MailTaskProBot?start=5911965767"

async def delete_message_after_delay(context: ContextTypes.DEFAULT_TYPE, chat_id: int, message_id: int, delay: int):
    await asyncio.sleep(delay)
    try:
        await context.bot.delete_message(chat_id=chat_id, message_id=message_id)
    except Exception as e:
        print(f"❌ Failed to auto-delete message: {e}")

async def check_force_sub(bot, user_id):
    try:
        channels = await asyncio.to_thread(lambda: list(channels_col.find()))
    except Exception as e:
        return []
    if not channels:
        return []

    unjoined = []
    for ch in channels:
        ch_id = ch["_id"]
        try:
            member = await asyncio.wait_for(bot.get_chat_member(chat_id=ch_id, user_id=user_id), timeout=2.5)
            if member.status not in ["member", "administrator", "creator"]:
                unjoined.append(ch)
        except Exception:
            continue
    return unjoined

# ----------------- CORE START & FLOW HANDLER -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id

    # Ads Galaxy Integration Ping
    try:
        await asyncio.to_thread(
            requests.get,
            "https://app.adsgalaxy.online/api/bot/integration/235/sysbraLOEEQ6ocZK8-yIK9YtHvcJRsLL366eNluVp-Y",
            params={"user_id": user_id},
            timeout=3
        )
    except Exception as e:
        print(f"Ads Galaxy Ping Error: {e}")

    try:
        user_doc = await asyncio.to_thread(users_col.find_one, {"_id": user_id})
        if not user_doc:
            await asyncio.to_thread(users_col.insert_one, {"_id": user_id})
    except Exception as e:
        print(f"User DB Error: {e}")
    
    is_callback = update.callback_query is not None
    if is_callback:
        try:
            await update.callback_query.answer()
        except Exception:
            pass
    
    async def send_response(text, reply_markup=None, parse_mode="Markdown"):
        try:
            if is_callback and update.callback_query and update.callback_query.message:
                await update.callback_query.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            else:
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            try:
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            except Exception:
                pass

    args = context.args if hasattr(context, "args") and context.args else []

    unjoined = await check_force_sub(context.bot, user_id)
    if unjoined:
        keyboard = []
        for ch in unjoined:
            link = ch.get("link", f"https://t.me/{str(ch['_id']).replace('@', '')}")
            keyboard.append([InlineKeyboardButton(f"Join {ch.get('title', 'Channel')} 📢", url=link)])
        
        param_val = args[0] if (args and len(args) > 0) else "NO_PARAM"
        keyboard.append([InlineKeyboardButton("Joined! Check Now 🔄", callback_data=f"check_fsub_{param_val}")])
        
        await send_response("⚠️ **Must Join Channels!**\n\nPlease join our required channels first:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    if args and len(args) > 0 and args[0] == "VERIFY_AD":
        user_session = await asyncio.to_thread(sessions_col.find_one, {"_id": user_id})
        if not user_session:
            await send_response("⚠️ Session expired. Please open your file link again.")
            return

        if user_session.get("verified", False):
            await send_response("⚠️ This session is already used. Please open your link again.")
            return

        await asyncio.to_thread(sessions_col.update_one, {"_id": user_id}, {"$set": {"verified": True}})
        await send_response("🎉 **Ad Completed Successfully!**\n\n📥 Delivering your file now...")
        await send_requested_item_direct(context, user_id, user_session)
        return

    if args and len(args) > 0 and args[0] not in ["NO_PARAM", "None", "VERIFY_AD"]:
        param = args[0]
        file_doc = await asyncio.to_thread(files_col.find_one, {"_id": param})
        batch_doc = await asyncio.to_thread(batch_col.find_one, {"_id": param})

        if file_doc or batch_doc:
            session_info = {
                "_id": user_id,
                "type": "batch" if batch_doc else "single",
                "id": param,
                "verified": False,
                "click_time": time.time()
            }
            await asyncio.to_thread(sessions_col.update_one, {"_id": user_id}, {"$set": session_info}, True)

            if not get_ad_status():
                await send_requested_item_direct(context, user_id, session_info)
                return

            keyboard = [[InlineKeyboardButton("🎬 Watch Ad Now to Unlock", web_app=WebAppInfo(url=MINI_APP_URL))]]
            await send_response(
                "🔒 **File Locked!**\n\n"
                "👉 **Click below** to watch a quick ad and unlock your file instantly:",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    # Clean, Catchy Welcome Message for direct bot open (No clutter)
    await send_response(
        "👋 **Welcome to Veronica Bot!**\n\n"
        "✨ Send or open a valid file link to download your favorite movies and content safely.",
        parse_mode="Markdown"
    )

async def send_requested_item_direct(context, user_id, session):
    item_id = session["id"]
    item_type = session["type"]

    try:
        if item_type == "single":
            doc = await asyncio.to_thread(files_col.find_one, {"_id": item_id})
            if doc:
                itype = doc.get("item_type")
                orig_cap = doc.get("caption", "")
                full_caption = f"{orig_cap}\n\n{WARNING_TEXT}".strip() if orig_cap else WARNING_TEXT
                
                sent_msg = None
                if itype == "text":
                    sent_msg = await context.bot.send_message(chat_id=user_id, text=f"{doc['text']}\n\n{WARNING_TEXT}")
                elif itype == "photo":
                    sent_msg = await context.bot.send_photo(chat_id=user_id, photo=doc["file_id"], caption=full_caption)
                elif itype == "video":
                    sent_msg = await context.bot.send_video(chat_id=user_id, video=doc["file_id"], caption=full_caption)
                else:
                    sent_msg = await context.bot.send_document(chat_id=user_id, document=doc["file_id"], caption=full_caption)

                if sent_msg:
                    asyncio.create_task(delete_message_after_delay(context, user_id, sent_msg.message_id, DELETE_TIME_SECONDS))

        elif item_type == "batch":
            batch_doc = await asyncio.to_thread(batch_col.find_one, {"_id": item_id})
            if batch_doc:
                for f_id in batch_doc.get("files", []):
                    doc = await asyncio.to_thread(files_col.find_one, {"_id": f_id})
                    if doc:
                        itype = doc.get("item_type")
                        orig_cap = doc.get("caption", "")
                        full_caption = f"{orig_cap}\n\n{WARNING_TEXT}".strip() if orig_cap else WARNING_TEXT
                        
                        sent_msg = None
                        if itype == "text":
                            sent_msg = await context.bot.send_message(chat_id=user_id, text=f"{doc['text']}\n\n{WARNING_TEXT}")
                        elif itype == "photo":
                            sent_msg = await context.bot.send_photo(chat_id=user_id, photo=doc["file_id"], caption=full_caption)
                        elif itype == "video":
                            sent_msg = await context.bot.send_video(chat_id=user_id, video=doc["file_id"], caption=full_caption)
                        else:
                            sent_msg = await context.bot.send_document(chat_id=user_id, document=doc["file_id"], caption=full_caption)

                        if sent_msg:
                            asyncio.create_task(delete_message_after_delay(context, user_id, sent_msg.message_id, DELETE_TIME_SECONDS))
                        await asyncio.sleep(0.5)

        # --- EXACTLY HERE: Right after the file is successfully delivered ---
        current_earn_link = get_current_earn_link()
        earn_keyboard = [[InlineKeyboardButton("🔥 Earn Extra Money / Passive Income", url=current_earn_link)]]
        await context.bot.send_message(
            chat_id=user_id,
            text="💰 **Want to earn passive income online?**\n\nClick the button below to join tasks and start earning:",
            reply_markup=InlineKeyboardMarkup(earn_keyboard)
        )

    except Exception as e:
        print(f"Delivery Error: {e}")

# ----------------- ADMIN FILE MANAGEMENT COMMANDS -----------------
async def my_files_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    
    files = list(files_col.find().limit(10))
    total_files = files_col.count_documents({})
    total_batches = batch_col.count_documents({})

    if not files:
        await update.message.reply_text("📂 डेटाबेस में कोई फाइल नहीं है।")
        return

    text = f"🗂 **Database File Manager**\n📊 Total Files: `{total_files}` | Batches: `{total_batches}`\n\nनीचे हाल की फाइल्स दी गई हैं:"
    
    keyboard = []
    for f in files:
        f_id = f["_id"]
        f_type = f.get("item_type", "file")
        keyboard.append([InlineKeyboardButton(f"🗑️ Delete: {f_id} ({f_type})", callback_data=f"del_file_{f_id}")])
    
    keyboard.append([InlineKeyboardButton("⚠️ Clear ALL Files from DB", callback_data="del_all_files")])
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode="Markdown")

async def admin_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.from_user.id != ADMIN_ID: return
    data = query.data

    if data.startswith("del_file_"):
        f_id = data.replace("del_file_", "")
        res1 = files_col.delete_one({"_id": f_id})
        res2 = batch_col.delete_one({"_id": f_id})
        
        try:
            if res1.deleted_count > 0 or res2.deleted_count > 0:
                await query.answer(f"✅ File {f_id} deleted successfully!", show_alert=True)
            else:
                await query.answer(f"⚠️ File {f_id} already deleted or not found.", show_alert=True)
            
            files = list(files_col.find().limit(10))
            total_files = files_col.count_documents({})
            total_batches = batch_col.count_documents({})

            if not files:
                await query.message.edit_text("📂 डेटाबेस अब पूरी तरह खाली है। कोई फाइल नहीं बची।")
                return

            text = f"🗂 **Database File Manager**\n📊 Total Files: `{total_files}` | Batches: `{total_batches}`\n\nनीचे हाल की फाइल्स दी गई हैं:"
            keyboard = []
            for f in files:
                fid = f["_id"]
                ftype = f.get("item_type", "file")
                keyboard.append([InlineKeyboardButton(f"🗑️ Delete: {fid} ({ftype})", callback_data=f"del_file_{fid}")])
            
            keyboard.append([InlineKeyboardButton("⚠️ Clear ALL Files from DB", callback_data="del_all_files")])
            await query.message.edit_reply_markup(reply_markup=InlineKeyboardMarkup(keyboard))
            
        except Exception as e:
            print(f"Delete callback error: {e}")

    elif data == "del_all_files":
        files_col.delete_many({})
        batch_col.delete_many({})
        try:
            await query.answer("🗑️ All files cleared from database!", show_alert=True)
            await query.message.edit_text("🗑️ डेटाबेस की सभी फाइल्स और बैचेस को सफलतापूर्वक साफ़ कर दिया गया है!")
        except Exception:
            pass
            
    elif data.startswith("check_fsub_"):
        param = data.replace("check_fsub_", "")
        unjoined = await check_force_sub(context.bot, query.from_user.id)
        if unjoined:
            try:
                await query.answer("❌ आपने अभी तक सभी चैनल ज्वाइन नहीं किए हैं!", show_alert=True)
            except Exception:
                pass
        else:
            try:
                await query.answer("✅ वेरिफिकेशन सफल!")
            except Exception:
                pass
            context.args = [param] if param not in ["NO_PARAM", "None"] else []
            await start(update, context)

# ----------------- ADMIN COMMANDS (WITH BROADCAST & EARN LINK CONTROL) -----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    current_link = get_current_earn_link()
    text = (
        f"🛠 **Admin Commands Guide:**\n\n"
        f"start - Start the bot or receive requested files\n"
        f"stats - View total users and bot statistics\n"
        f"genlink - Reply to a file/message to generate a single link\n"
        f"sendad - Broadcast message with rich ads or buttons\n"
        f"stopbroadcast - Stop the ongoing broadcast process\n"
        f"deletebroadcast - Delete all broadcasted messages from users\n"
        f"batch - Toggle batch mode to create multi-file links\n"
        f"admin - Open admin panel and view help instructions\n"
        f"togglead - Enable or disable the watch-ad system\n"
        f"addchannel - Add a force-subscription channel\n"
        f"delchannel - Remove a force-subscription channel\n"
        f"channels - View list of all force-sub channels\n"
        f"myfiles - Manage and delete stored database files\n"
        f"setearnlink - Change earning/referral link (`/setearnlink <new_link>`)\n\n"
        f"🔗 **Current Earning Link:** `{current_link}`"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def set_earn_link(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args:
        current = get_current_earn_link()
        await update.message.reply_text(f"⚠️ Use: `/setearnlink <URL>`\n\nCurrent Link: `{current}`", parse_mode="Markdown")
        return
    new_link = args[0].strip()
    settings_col.update_one({"_id": "earn_link"}, {"$set": {"link": new_link}}, True)
    await update.message.reply_text(f"✅ **Earning Link Updated Successfully!**\n\nNew Link: `{new_link}`", parse_mode="Markdown")

async def toggle_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    current = get_ad_status()
    new_status = not current
    settings_col.update_one({"_id": "ad_status"}, {"$set": {"status": new_status}}, True)
    await update.message.reply_text(f"⚙️ Ads Mode is now **{'ENABLED 🟢' if new_status else 'DISABLED 🔴'}**", parse_mode="Markdown")

async def genlink(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = update.message.reply_to_message
    if msg:
        unique_id = str(uuid.uuid4())[:8]
        item_type, file_id = "text", None
        if msg.document: item_type, file_id = "document", msg.document.file_id
        elif msg.video: item_type, file_id = "video", msg.video.file_id
        elif msg.photo: item_type, file_id = "photo", msg.photo[-1].file_id
        elif msg.text: item_type = "text"

        files_col.insert_one({"_id": unique_id, "item_type": item_type, "file_id": file_id, "caption": msg.caption or "", "text": msg.text or ""})
        await update.message.reply_text(f"✅ **Single File Link:**\n\n`https://t.me/{BOT_USERNAME}?start={unique_id}`", parse_mode="Markdown")
        return
    admin_states[update.effective_user.id] = "WAITING_FOR_SINGLE_FILE"
    await update.message.reply_text("📥 **Send or forward the media/text now...**", parse_mode="Markdown")

async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    admin_id = update.effective_user.id
    if admin_id in batch_sessions:
        files = batch_sessions[admin_id]
        if not files:
            del batch_sessions[admin_id]
            await update.message.reply_text("❌ Batch cancelled.")
            return
        batch_id = str(uuid.uuid4())[:8]
        batch_col.insert_one({"_id": batch_id, "files": files})
        del batch_sessions[admin_id]
        await update.message.reply_text(f"🎉 **Batch Created ({len(files)} items)!**\n\n`https://t.me/{BOT_USERNAME}?start={batch_id}`", parse_mode="Markdown")
    else:
        batch_sessions[admin_id] = []
        await update.message.reply_text("📦 **Batch Mode Started!** Send files, then type `/batch` again to finish.")

async def handle_admin_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    msg = update.message
    if not msg or msg.from_user.id != ADMIN_ID: return
    admin_id = msg.from_user.id

    if admin_states.get(admin_id) == "WAITING_FOR_SINGLE_FILE":
        unique_id = str(uuid.uuid4())[:8]
        item_type, file_id = "text", None
        if msg.document: item_type, file_id = "document", msg.document.file_id
        elif msg.video: item_type, file_id = "video", msg.video.file_id
        elif msg.photo: item_type, file_id = "photo", msg.photo[-1].file_id
        elif msg.text: item_type = "text"

        files_col.insert_one({"_id": unique_id, "item_type": item_type, "file_id": file_id, "caption": msg.caption or "", "text": msg.text or ""})
        del admin_states[admin_id]
        await update.message.reply_text(f"✅ **Single Link Generated:**\n\n`https://t.me/{BOT_USERNAME}?start={unique_id}`", parse_mode="Markdown")
        return

    if admin_id in batch_sessions:
        unique_id = str(uuid.uuid4())[:8]
        item_type, file_id = "text", None
        if msg.document: item_type, file_id = "document", msg.document.file_id
        elif msg.video: item_type, file_id = "video", msg.video.file_id
        elif msg.photo: item_type, file_id = "photo", msg.photo[-1].file_id
        elif msg.text: item_type = "text"

        files_col.insert_one({"_id": unique_id, "item_type": item_type, "file_id": file_id, "caption": msg.caption or "", "text": msg.text or ""})
        batch_sessions[admin_id].append(unique_id)
        await update.message.reply_text(f"➕ Item #{len(batch_sessions[admin_id])} added to Batch.")

async def send_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = update.message.reply_to_message
    if not msg:
        await update.message.reply_text("⚠️ Reply to a message to broadcast!")
        return

    broadcast_control["is_running"] = True
    users = list(users_col.find())
    total = len(users)
    success, failed = 0, 0
    broadcast_id = str(int(time.time()))
    sent_details = []

    status_msg = await update.message.reply_text(f"🚀 Broadcast started to {total} users...")

    for u in users:
        if not broadcast_control["is_running"]:
            await update.message.reply_text("🛑 Broadcast stopped manually.")
            break
        u_id = u["_id"]
        try:
            sent = await msg.copy(chat_id=u_id)
            sent_details.append({"user_id": u_id, "message_id": sent.message_id})
            success += 1
        except Exception:
            failed += 1
        await asyncio.sleep(0.05)

    if sent_details:
        broadcast_history_col.insert_one({"_id": broadcast_id, "sent_details": sent_details})

    broadcast_control["is_running"] = False
    await status_msg.edit_text(f"✅ **Broadcast Completed!**\n🎯 Success: {success}\n❌ Failed: {failed}", parse_mode="Markdown")

async def stop_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    if broadcast_control["is_running"]:
        broadcast_control["is_running"] = False
        await update.message.reply_text("🛑 Broadcast stop signal sent. It will halt shortly.")
    else:
        await update.message.reply_text("⚠️ No broadcast is currently running.")

async def delete_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    histories = list(broadcast_history_col.find())
    if not histories:
        await update.message.reply_text("📭 No broadcast history found to delete.")
        return

    status_msg = await update.message.reply_text("🗑️ Deleting broadcasted messages from users...")
    deleted_total = 0

    for h in histories:
        for item in h.get("sent_details", []):
            try:
                await context.bot.delete_message(chat_id=item["user_id"], message_id=item["message_id"])
                deleted_total += 1
            except Exception:
                pass
        broadcast_history_col.delete_one({"_id": h["_id"]})

    await status_msg.edit_text(f"✅ **Broadcast Deletion Completed!**\nDeleted {deleted_total} messages.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    await update.message.reply_text(f"📊 **Stats:**\n👥 Users: {users_col.count_documents({})}\n📁 Files: {files_col.count_documents({})}\n📦 Batches: {batch_col.count_documents({})}")

async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ `/addchannel @channel`", parse_mode="Markdown")
        return
    raw = args[0].strip()
    target = "@" + raw.split("t.me/")[-1].replace("+", "").replace("/", "") if "t.me/" in raw else (int(raw) if raw.replace("-", "").isdigit() else raw)
    try:
        chat = await context.bot.get_chat(target)
        channels_col.update_one({"_id": chat.id}, {"$set": {"link": chat.invite_link or f"https://t.me/{chat.username}", "title": chat.title}}, True)
        await update.message.reply_text(f"✅ Channel **{chat.title}** added successfully!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {e}")

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args: return
    channels_col.delete_many({"$or": [{"_id": int(args[0]) if args[0].isdigit() else 0}, {"username": args[0].replace("@", "").lower()}]})
    await update.message.reply_text("✅ Channel removed.")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    chs = list(channels_col.find())
    if not chs:
        await update.message.reply_text("📑 No channels found.")
        return
    text = "📢 **Channels:**\n" + "\n".join([f"• {c.get('title')} (`{c['_id']}`)" for c in chs])
    await update.message.reply_text(text, parse_mode="Markdown")

# ----------------- MAIN -----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("togglead", toggle_ad))
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch_command))
    app.add_handler(CommandHandler("myfiles", my_files_command))
    app.add_handler(CommandHandler("sendad", send_ad))
    app.add_handler(CommandHandler("stopbroadcast", stop_broadcast))
    app.add_handler(CommandHandler("deletebroadcast", delete_broadcast))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("delchannel", del_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CommandHandler("stats", stats_command))
    app.add_handler(CommandHandler("setearnlink", set_earn_link))
    
    app.add_handler(CallbackQueryHandler(admin_callback_handler))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_admin_messages))

    print("Bot started successfully with correct message flow.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

import os
import time
import asyncio
import threading
import uuid
import pymongo
import dns.resolver
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
# NOTE: कृपया सुनिश्चित करें कि BotFather से नया टोकन लेकर यहाँ डालें अगर पुराना Revoke हो गया हो।
TOKEN = os.environ.get("BOT_TOKEN", "8737537284:AAGtP8lwqR3LRwAy4ZWg5iyQG8SdNcFW6fg")
MINI_APP_URL = "https://webcrypto29-debug.github.io/My-file-bot/"
BOT_USERNAME = "MyFile727_bot"

MONGO_URI = os.environ.get("MONGO_URI", "mongodb+srv://n2665099_db_user:sagar_sagr@cluster0.2h1q2w8.mongodb.net/?appName=Cluster0&tlsAllowInvalidCertificates=true")
ADMIN_ID = 5911965767
# --------------------------------------------------

# MongoDB Setup (Connect Timeout जोड़ा गया है ताकि DB ब्लॉक न करे)
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

# ----------------- HELPER: FORCE SUB CHECK -----------------
async def check_force_sub(bot, user_id):
    try:
        channels = await asyncio.to_thread(lambda: list(channels_col.find()))
    except Exception as e:
        print(f"DB Error (check_force_sub): {e}")
        channels = []

    unjoined = []
    for ch in channels:
        ch_id = ch["_id"]
        try:
            member = await bot.get_chat_member(chat_id=ch_id, user_id=user_id)
            if member.status not in ["member", "administrator", "creator"]:
                unjoined.append(ch)
        except Exception as e:
            print(f"Force Sub Check Error for {ch_id}: {e}")
            pass
    return unjoined

# ----------------- CORE START & FLOW HANDLER -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    
    # Callback query response safety
    if update.callback_query:
        try:
            await update.callback_query.answer()
        except Exception:
            pass

    is_callback = update.callback_query is not None
    
    async def send_response(text, reply_markup=None, parse_mode="Markdown"):
        try:
            if is_callback and update.callback_query.message:
                await update.callback_query.message.edit_text(text=text, reply_markup=reply_markup, parse_mode=parse_mode)
            else:
                await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        except Exception as e:
            print(f"Send Response Error: {e}")
            await context.bot.send_message(chat_id=user_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)

    args = context.args if hasattr(context, "args") and context.args else []

    # Database User Reg (Non-blocking thread)
    try:
        user_doc = await asyncio.to_thread(users_col.find_one, {"_id": user_id})
        if not user_doc:
            await asyncio.to_thread(users_col.insert_one, {"_id": user_id, "credits": 0})
            current_credits = 0
        else:
            current_credits = user_doc.get("credits", 0)
    except Exception as e:
        print(f"User Reg DB Error: {e}")
        current_credits = 0

    # 1. FORCE SUB VERIFICATION
    unjoined = await check_force_sub(context.bot, user_id)
    if unjoined:
        keyboard = []
        for ch in unjoined:
            link = ch.get("link", f"https://t.me/{str(ch['_id']).replace('@', '')}")
            keyboard.append([InlineKeyboardButton(f"Join {ch.get('title', 'Channel')} 📢", url=link)])
        
        param_val = args[0] if (args and len(args) > 0) else "NO_PARAM"
        keyboard.append([InlineKeyboardButton("Joined! Check Now 🔄", callback_data=f"check_fsub_{param_val}")])
        
        msg_text = "⚠️ **Must Join Channels!**\n\nTo access files/links, please join our required channels first:"
        await send_response(msg_text, reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # 2. AD VERIFICATION LOGIC
    if args and len(args) > 0 and args[0] == "VERIFY_AD":
        user_session = await asyncio.to_thread(sessions_col.find_one, {"_id": user_id})
        
        if not user_session:
            await asyncio.to_thread(users_col.update_one, {"_id": user_id}, {"$inc": {"credits": 3}}, True)
            updated_user = await asyncio.to_thread(users_col.find_one, {"_id": user_id})
            new_bal = updated_user.get("credits", 0) if updated_user else 3
            await send_response(
                f"🎉 **Ad Completed Successfully!**\n🎁 **+3 Credits** added to your account.\n💰 Total Balance: **{new_bal} Credits**"
            )
            return

        if user_session.get("verified", False):
            await send_response("⚠️ This ad session is already used. Please open a new share link.")
            return

        click_time = user_session.get("click_time", 0)
        if time.time() - click_time < 3:
            await send_response(
                "⚠️ **Verification Failed!**\n\nThe ad was not watched completely. Please try again."
            )
            return

        await asyncio.to_thread(sessions_col.update_one, {"_id": user_id}, {"$set": {"verified": True}})
        await asyncio.to_thread(users_col.update_one, {"_id": user_id}, {"$inc": {"credits": 3}}, True)
        updated_user = await asyncio.to_thread(users_col.find_one, {"_id": user_id})
        new_balance = updated_user.get("credits", 0) if updated_user else 3

        await send_response(
            f"🎉 **Ad Completed Successfully!**\n🎁 **+3 Credits** added to your account.\n💰 Total Balance: **{new_balance} Credits**"
        )

        if new_balance >= 1:
            await asyncio.to_thread(users_col.update_one, {"_id": user_id}, {"$inc": {"credits": -1}})
            await send_requested_item_direct(context, user_id, user_session, deduct_credit=True)
        return

    # 3. FILE / BATCH DOWNLOAD REQUEST
    if args and len(args) > 0 and args[0] not in ["NO_PARAM", "None"]:
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
                await send_requested_item_direct(context, user_id, session_info, deduct_credit=False)
                return

            if current_credits >= 1:
                await asyncio.to_thread(users_col.update_one, {"_id": user_id}, {"$inc": {"credits": -1}})
                await send_requested_item_direct(context, user_id, session_info, deduct_credit=True)
                return

            keyboard = [[InlineKeyboardButton("Watch Ad Now 🚀", web_app=WebAppInfo(url=MINI_APP_URL))]]
            await send_response(
                f"🔒 **File Locked!**\n\n💰 Your Credits: **{current_credits}**\n\n👇 Click below to watch an ad, earn **+3 Credits** and unlock your file!",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return

    # 4. DEFAULT START RESPONSE
    await send_response(
        f"👋 Welcome to Veronica Bot!\n\n💰 Your Current Balance: **{current_credits} Credits**\n\nSend or click any link to download content!"
    )

# ----------------- DIRECT FILE DELIVERY -----------------
async def send_requested_item_direct(context, user_id, session, deduct_credit=True):
    item_id = session["id"]
    item_type = session["type"]

    if deduct_credit:
        await context.bot.send_message(chat_id=user_id, text="⚡ **1 Credit Deducted.** Delivering content...", parse_mode="Markdown")

    try:
        if item_type == "single":
            doc = await asyncio.to_thread(files_col.find_one, {"_id": item_id})
            if doc:
                itype = doc.get("item_type")
                cap = doc.get("caption", "")
                if itype == "text":
                    await context.bot.send_message(chat_id=user_id, text=f"🔗 **Link/Text:**\n\n{doc['text']}")
                elif itype == "photo":
                    await context.bot.send_photo(chat_id=user_id, photo=doc["file_id"], caption=cap)
                elif itype == "video":
                    await context.bot.send_video(chat_id=user_id, video=doc["file_id"], caption=cap)
                else:
                    await context.bot.send_document(chat_id=user_id, document=doc["file_id"], caption=cap)

        elif item_type == "batch":
            batch_doc = await asyncio.to_thread(batch_col.find_one, {"_id": item_id})
            if batch_doc:
                for f_id in batch_doc.get("files", []):
                    doc = await asyncio.to_thread(files_col.find_one, {"_id": f_id})
                    if doc:
                        itype = doc.get("item_type")
                        cap = doc.get("caption", "")
                        if itype == "text":
                            await context.bot.send_message(chat_id=user_id, text=f"🔗 **Link/Text:**\n\n{doc['text']}")
                        elif itype == "photo":
                            await context.bot.send_photo(chat_id=user_id, photo=doc["file_id"], caption=cap)
                        elif itype == "video":
                            await context.bot.send_video(chat_id=user_id, video=doc["file_id"], caption=cap)
                        else:
                            await context.bot.send_document(chat_id=user_id, document=doc["file_id"], caption=cap)
                        await asyncio.sleep(0.5)

    except Exception as e:
        await context.bot.send_message(chat_id=user_id, text=f"❌ Error delivering content: {str(e)}")

    await asyncio.to_thread(sessions_col.delete_one, {"_id": user_id})

# ----------------- CALLBACK QUERY HANDLER -----------------
async def fsub_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data

    if data.startswith("check_fsub_"):
        param = data.replace("check_fsub_", "")
        unjoined = await check_force_sub(context.bot, user_id)
        if unjoined:
            await query.answer("❌ You haven't joined all required channels yet!", show_alert=True)
        else:
            await query.answer("✅ Verification successful!")
            context.args = [param] if param not in ["NO_PARAM", "None"] else []
            await start(update, context)

# ----------------- ADD & DELETE FORCE SUB CHANNELS -----------------
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Usage:\n`/addchannel @channelusername` OR `/addchannel -100xxxxxxxxxx`", parse_mode="Markdown")
        return

    raw_input = args[0].strip()
    ch_id = int(raw_input) if raw_input.replace("-", "").isdigit() else raw_input

    try:
        chat = await context.bot.get_chat(ch_id)
        bot_member = await context.bot.get_chat_member(chat_id=chat.id, user_id=context.bot.id)

        if bot_member.status not in ["administrator", "creator"]:
            await update.message.reply_text(
                f"❌ **Bot is not an Admin!**\n\nPlease add @{BOT_USERNAME} as an **Admin** in **{chat.title}** first, then re-run this command.",
                parse_mode="Markdown"
            )
            return

        invite_link = chat.invite_link
        if not invite_link and chat.username:
            invite_link = f"https://t.me/{chat.username}"
        elif not invite_link:
            try:
                invite_link = await context.bot.export_chat_invite_link(chat.id)
            except Exception:
                invite_link = f"https://t.me/{str(chat.id).replace('-100', '')}"

        await asyncio.to_thread(
            channels_col.update_one,
            {"_id": chat.id},
            {"$set": {
                "link": invite_link, 
                "title": chat.title, 
                "username": chat.username.lower() if chat.username else ""
            }},
            True
        )

        await update.message.reply_text(
            f"✅ **Force Sub Channel Added Successfully!**\n\n📌 **Title:** {chat.title}\n🆔 **ID:** `{chat.id}`\n🔗 **Link:** {invite_link}",
            parse_mode="Markdown"
        )

    except Exception as e:
        await update.message.reply_text(
            f"❌ **Error accessing channel!**\n\nMake sure the Bot is added to the channel and the Username/ID is correct.\n\n`Error: {str(e)}`",
            parse_mode="Markdown"
        )

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Usage:\n`/delchannel @channelusername` OR `/delchannel -100xxxxxxxxxx`", parse_mode="Markdown")
        return

    raw_input = args[0].strip()
    
    deleted_count = 0
    if raw_input.replace("-", "").isdigit():
        res = await asyncio.to_thread(channels_col.delete_one, {"_id": int(raw_input)})
        deleted_count = res.deleted_count
    else:
        clean_user = raw_input.replace("@", "").lower()
        res = await asyncio.to_thread(channels_col.delete_many, {
            "$or": [
                {"username": clean_user},
                {"_id": raw_input}
            ]
        })
        deleted_count = res.deleted_count

    if deleted_count > 0:
        await update.message.reply_text("✅ Force Sub Channel removed successfully!")
    else:
        await update.message.reply_text("❌ Channel not found in database!")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    chs = await asyncio.to_thread(lambda: list(channels_col.find()))
    if not chs:
        await update.message.reply_text("📑 No Force Sub channels registered.")
        return
    text = "📢 **Active Force Sub Channels:**\n\n"
    for c in chs:
        text += f"• `{c['_id']}` | [{c.get('title', 'Channel')}]({c.get('link')})\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ----------------- ADMIN COMMANDS -----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    text = (
        "🛠 **Admin Commands Guide:**\n\n"
        "🔗 `/genlink` - Generate link\n"
        "📦 `/batch` - Create file batch\n"
        "📢 `/sendad` - Broadcast message\n"
        "➕ `/addchannel <username_or_id>` - Add Force Sub\n"
        "➖ `/delchannel <username_or_id>` - Remove Force Sub\n"
        "📑 `/channels` - List Force Sub channels\n"
        "🔘 `/togglead` - Toggle rewarded ads\n"
        "📊 `/stats` - View stats"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def toggle_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    current = get_ad_status()
    new_status = not current
    await asyncio.to_thread(settings_col.update_one, {"_id": "ad_status"}, {"$set": {"status": new_status}}, True)
    status_str = "ENABLED 🟢" if new_status else "DISABLED 🔴"
    await update.message.reply_text(f"⚙️ Rewarded Ads Mode is now **{status_str}**", parse_mode="Markdown")

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

        await asyncio.to_thread(files_col.insert_one, {
            "_id": unique_id,
            "item_type": item_type,
            "file_id": file_id,
            "caption": msg.caption or "",
            "text": msg.text or ""
        })

        link = f"https://t.me/{BOT_USERNAME}?start={unique_id}"
        await update.message.reply_text(f"✅ **Single File Link:**\n\n`{link}`", parse_mode="Markdown")
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
            await update.message.reply_text("❌ Batch Mode cancelled (no files added).")
            return

        batch_id = str(uuid.uuid4())[:8]
        await asyncio.to_thread(batch_col.insert_one, {"_id": batch_id, "files": files})
        del batch_sessions[admin_id]

        link = f"https://t.me/{BOT_USERNAME}?start={batch_id}"
        await update.message.reply_text(f"🎉 **Batch Created ({len(files)} items)!**\n\n🔗 Link:\n`{link}`", parse_mode="Markdown")
    else:
        batch_sessions[admin_id] = []
        await update.message.reply_text("📦 **Batch Mode Started!** Send/forward files, then type `/batch` again to finish.")

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

        await asyncio.to_thread(files_col.insert_one, {
            "_id": unique_id,
            "item_type": item_type,
            "file_id": file_id,
            "caption": msg.caption or "",
            "text": msg.text or ""
        })

        del admin_states[admin_id]
        link = f"https://t.me/{BOT_USERNAME}?start={unique_id}"
        await update.message.reply_text(f"✅ **Single Link Generated:**\n\n`{link}`", parse_mode="Markdown")
        return

    if admin_id in batch_sessions:
        unique_id = str(uuid.uuid4())[:8]
        item_type, file_id = "text", None

        if msg.document: item_type, file_id = "document", msg.document.file_id
        elif msg.video: item_type, file_id = "video", msg.video.file_id
        elif msg.photo: item_type, file_id = "photo", msg.photo[-1].file_id
        elif msg.text: item_type = "text"

        await asyncio.to_thread(files_col.insert_one, {
            "_id": unique_id,
            "item_type": item_type,
            "file_id": file_id,
            "caption": msg.caption or "",
            "text": msg.text or ""
        })

        batch_sessions[admin_id].append(unique_id)
        count = len(batch_sessions[admin_id])
        await update.message.reply_text(f"➕ Item #{count} added to Batch.")
        return

async def send_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    msg = update.message.reply_to_message
    if not msg:
        await update.message.reply_text("⚠️ Reply to a message to broadcast!")
        return

    broadcast_control["is_running"] = True
    users = await asyncio.to_thread(lambda: list(users_col.find()))
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

    await asyncio.to_thread(broadcast_history_col.insert_one, {"_id": broadcast_id, "sent_details": sent_details})
    broadcast_control["is_running"] = False
    await status_msg.edit_text(f"✅ **Broadcast Completed!**\n🎯 Success: {success}\n❌ Failed: {failed}", parse_mode="Markdown")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    total_users = await asyncio.to_thread(users_col.count_documents, {})
    total_files = await asyncio.to_thread(files_col.count_documents, {})
    total_batches = await asyncio.to_thread(batch_col.count_documents, {})
    await update.message.reply_text(f"📊 **Stats:**\n👥 Users: {total_users}\n📁 Files: {total_files}\n📦 Batches: {total_batches}")

# ----------------- MAIN INITIALIZATION -----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("togglead", toggle_ad))
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch_command))
    app.add_handler(CommandHandler("sendad", send_ad))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("delchannel", del_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CommandHandler("stats", stats_command))
    
    app.add_handler(CallbackQueryHandler(fsub_callback))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_admin_messages))

    print("Bot started with synchronized handlers.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    main()

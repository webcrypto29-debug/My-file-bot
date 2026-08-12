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

# Termux DNS Fix
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

# MongoDB Setup
mongo_client = pymongo.MongoClient(MONGO_URI)
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
            # अगर बोट को चैनल से निकाल दिया गया हो या कोई एरर आए
            pass
    return unjoined

# ----------------- START HANDLER -----------------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user:
        return
    user_id = user.id
    args = context.args

    async def safe_reply(text, **kwargs):
        try:
            if update.message:
                return await update.message.reply_text(text, **kwargs)
            elif update.callback_query and update.callback_query.message:
                return await update.callback_query.message.reply_text(text, **kwargs)
            else:
                return await context.bot.send_message(chat_id=user_id, text=text, **kwargs)
        except Exception as e:
            print(f"Error in safe_reply: {e}")

    # User registration
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
        
        start_param = args[0] if (args and len(args) > 0) else "NO_PARAM"
        keyboard.append([InlineKeyboardButton("Joined! Check Now 🔄", callback_data=f"check_fsub_{start_param}")])
        
        await safe_reply(
            "⚠️ **Must Join Channels!**\n\nTo access files/links, please join our required channels first:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    # 2. Ad Verification Handler
    if args and len(args) > 0 and args[0] == "VERIFY_AD":
        user_session = sessions_col.find_one({"_id": user_id})
        
        if not user_session:
            users_col.update_one({"_id": user_id}, {"$inc": {"credits": 3}}, upsert=True)
            updated_user = users_col.find_one({"_id": user_id})
            new_bal = updated_user.get("credits", 0)
            await safe_reply(
                f"🎉 **Ad Completed Successfully!**\n🎁 **+3 Credits** added to your account.\n💰 Total Balance: **{new_bal} Credits**\n\nClick any file link to use your credits!",
                parse_mode="Markdown"
            )
            return

        if user_session.get("verified", False):
            await safe_reply("⚠️ This ad session is already used. Please open a new share link.")
            return

        click_time = user_session.get("click_time", 0)
        time_elapsed = time.time() - click_time

        if time_elapsed < 3:
            await safe_reply(
                "⚠️ **Verification Failed!**\n\nThe rewarded ad was not completed properly or finished too quickly. Please watch the ad fully.",
                parse_mode="Markdown"
            )
            return

        sessions_col.update_one({"_id": user_id}, {"$set": {"verified": True}})
        users_col.update_one({"_id": user_id}, {"$inc": {"credits": 3}}, upsert=True)
        updated_user = users_col.find_one({"_id": user_id})
        new_balance = updated_user.get("credits", 0)

        await safe_reply(
            f"🎉 **Ad Completed Successfully!**\n🎁 **+3 Credits** added to your account.\n💰 Total Balance: **{new_balance} Credits**",
            parse_mode="Markdown"
        )

        if new_balance >= 1:
            users_col.update_one({"_id": user_id}, {"$inc": {"credits": -1}})
            await send_requested_item_direct(update, context, user_id, user_session, deduct_credit=True)
        return

    # 3. File / Batch Request
    if args and len(args) > 0 and args[0] != "NO_PARAM":
        param = args[0]
        file_doc = files_col.find_one({"_id": param})
        batch_doc = batch_col.find_one({"_id": param})

        if file_doc or batch_doc:
            session_info = {
                "_id": user_id,
                "type": "batch" if batch_doc else "single",
                "id": param,
                "verified": False,
                "click_time": time.time()
            }
            sessions_col.update_one({"_id": user_id}, {"$set": session_info}, upsert=True)

            if not get_ad_status():
                await send_requested_item_direct(update, context, user_id, session_info, deduct_credit=False)
                return

            if current_credits >= 1:
                users_col.update_one({"_id": user_id}, {"$inc": {"credits": -1}})
                await send_requested_item_direct(update, context, user_id, session_info, deduct_credit=True)
                return

            keyboard = [[InlineKeyboardButton("Watch Ad Now 🚀", web_app=WebAppInfo(url=MINI_APP_URL))]]
            await safe_reply(
                f"🔒 **File Locked!**\n\n💰 Your Credits: **{current_credits}**\n\n👇 Click below to watch a short ad. You will get **+3 Credits** and your file instantly!",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            return

    # 4. Normal Start
    await safe_reply(
        f"👋 Welcome to Veronica Bot!\n\n💰 Your Current Balance: **{current_credits} Credits**\n\nClick any file link or share link to download content!",
        parse_mode="Markdown"
    )

# ----------------- DIRECT FILE DELIVERY -----------------
async def send_requested_item_direct(update, context, user_id, session, deduct_credit=True):
    item_id = session["id"]
    item_type = session["type"]

    if deduct_credit:
        await context.bot.send_message(chat_id=user_id, text="⚡ **1 Credit Deducted.** Delivering content...", parse_mode="Markdown")

    try:
        if item_type == "single":
            doc = files_col.find_one({"_id": item_id})
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
            batch_doc = batch_col.find_one({"_id": item_id})
            if batch_doc:
                for f_id in batch_doc["files"]:
                    doc = files_col.find_one({"_id": f_id})
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
        await context.bot.send_message(chat_id=user_id, text=f"❌ Error delivering file: {str(e)}")

    sessions_col.delete_one({"_id": user_id})

# ----------------- CALLBACK HANDLER -----------------
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
            try:
                await query.message.delete()
            except Exception:
                pass
            context.args = [param] if param not in ["NO_PARAM", "None"] else []
            await start(update, context)

# ----------------- IMPROVED FORCE SUB MANAGEMENT -----------------
async def add_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Usage: `/addchannel <channel_id_or_username>`\n\nExample:\n`/addchannel -100123456789` or `/addchannel @mychannel`", parse_mode="Markdown")
        return

    raw_input = args[0].strip()
    ch_id = int(raw_input) if raw_input.replace("-", "").isdigit() else raw_input

    try:
        # Check if bot is present in the channel
        chat = await context.bot.get_chat(ch_id)
        bot_member = await context.bot.get_chat_member(chat_id=chat.id, user_id=context.bot.id)

        if bot_member.status not in ["administrator", "member"]:
            await update.message.reply_text(
                f"❌ **Bot is not in the channel!**\n\nPlease add @{BOT_USERNAME} as an Administrator in **{chat.title}** first, then try again.",
                parse_mode="Markdown"
            )
            return

        # Fetch channel invite link
        invite_link = chat.invite_link
        if not invite_link and chat.username:
            invite_link = f"https://t.me/{chat.username}"
        elif not invite_link:
            try:
                invite_link = await context.bot.export_chat_invite_link(chat.id)
            except Exception:
                invite_link = f"https://t.me/{str(chat.id).replace('-100', '')}"

        # Save to Mongo DB
        channels_col.update_one(
            {"_id": chat.id},
            {"$set": {"link": invite_link, "title": chat.title, "username": chat.username}},
            upsert=True
        )

        await update.message.reply_text(
            f"✅ **Force Sub Channel Added Successfully!**\n\n📌 **Title:** {chat.title}\n🆔 **ID:** `{chat.id}`\n🔗 **Link:** {invite_link}\n\n🤖 *Bot is tracking this channel now.*",
            parse_mode="Markdown"
        )

    except Exception as e:
        await update.message.reply_text(
            f"⚠️ **Error:** Could not access channel `{ch_id}`.\n\nMake sure the Channel ID/Username is correct and the bot is added to that channel as an **Admin**.\n\n`Details: {str(e)}`",
            parse_mode="Markdown"
        )

async def del_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Usage: `/delchannel <channel_id_or_username>`", parse_mode="Markdown")
        return

    raw_input = args[0].strip()
    
    # Check by exact ID or search username
    target_id = None
    if raw_input.replace("-", "").isdigit():
        target_id = int(raw_input)
    else:
        # Search by Username or ID string in DB
        username_clean = raw_input.replace("@", "").lower()
        found = channels_col.find_one({"$or": [{"username": username_clean}, {"_id": raw_input}]})
        if found:
            target_id = found["_id"]

    if target_id is None:
        target_id = raw_input

    res = channels_col.delete_one({"_id": target_id})
    if res.deleted_count > 0:
        await update.message.reply_text("✅ Force Sub Channel removed successfully from database!")
    else:
        await update.message.reply_text("❌ Channel not found in Force Sub database!")

async def list_channels(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    chs = list(channels_col.find())
    if not chs:
        await update.message.reply_text("📑 No Force Sub channels active.")
        return
    text = "📢 **Active Force Sub Channels:**\n\n"
    for c in chs:
        text += f"• `{c['_id']}` | [{c.get('title', 'Channel')}]({c.get('link')})\n"
    await update.message.reply_text(text, parse_mode="Markdown")

# ----------------- OTHER ADMIN COMMANDS -----------------
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    text = (
        "🛠 **Admin Commands Guide:**\n\n"
        "🔗 `/genlink` - Generate link (Send / Reply file/media/text)\n"
        "📦 `/batch` - Start / Finish batching multiple files\n"
        "📢 `/sendad` - Reply to message to broadcast\n"
        "🛑 `/stopbroadcast` - Stop ongoing broadcast\n"
        "🗑 `/deletebroadcast <id>` - Delete broadcast messages\n"
        "➕ `/addchannel <channel_id_or_username>` - Add Force Sub Channel\n"
        "➖ `/delchannel <channel_id_or_username>` - Remove Force Sub Channel\n"
        "📑 `/channels` - List all Force Sub Channels\n"
        "🔘 `/togglead` - Enable/Disable Ads Mode\n"
        "📊 `/stats` - View total stats"
    )
    await update.message.reply_text(text, parse_mode="Markdown")

async def toggle_ad(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    current = get_ad_status()
    new_status = not current
    settings_col.update_one({"_id": "ad_status"}, {"$set": {"status": new_status}}, upsert=True)
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

        files_col.insert_one({
            "_id": unique_id,
            "item_type": item_type,
            "file_id": file_id,
            "caption": msg.caption or "",
            "text": msg.text or ""
        })

        link = f"https://t.me/{BOT_USERNAME}?start={unique_id}"
        await update.message.reply_text(f"✅ **Single File Link Generated:**\n\n`{link}`", parse_mode="Markdown")
        return

    admin_states[update.effective_user.id] = "WAITING_FOR_SINGLE_FILE"
    await update.message.reply_text(
        "📥 **Send or Forward the File / Photo / Video / Text now...**\nI will generate a shareable link for it!",
        parse_mode="Markdown"
    )

async def batch_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    admin_id = update.effective_user.id

    if admin_id in batch_sessions:
        files = batch_sessions[admin_id]
        if not files:
            del batch_sessions[admin_id]
            await update.message.reply_text("❌ Batch Mode cancelled (no files were added).")
            return

        batch_id = str(uuid.uuid4())[:8]
        batch_col.insert_one({"_id": batch_id, "files": files})
        del batch_sessions[admin_id]

        link = f"https://t.me/{BOT_USERNAME}?start={batch_id}"
        await update.message.reply_text(
            f"🎉 **Batch Created ({len(files)} items)!**\n\n🔗 Shareable Link:\n`{link}`", 
            parse_mode="Markdown"
        )
    else:
        batch_sessions[admin_id] = []
        await update.message.reply_text(
            "📦 **Batch Mode Started!**\n\nNow send/forward all files/photos/videos/links you want to add.\n\nWhen done, type `/batch` again to generate the final batch link.",
            parse_mode="Markdown"
        )

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

        files_col.insert_one({
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

        files_col.insert_one({
            "_id": unique_id,
            "item_type": item_type,
            "file_id": file_id,
            "caption": msg.caption or "",
            "text": msg.text or ""
        })

        batch_sessions[admin_id].append(unique_id)
        count = len(batch_sessions[admin_id])
        await update.message.reply_text(f"➕ Added item #{count} to Batch. (Send more or type `/batch` to finish)")
        return

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

    broadcast_history_col.insert_one({"_id": broadcast_id, "sent_details": sent_details})
    broadcast_control["is_running"] = False
    await status_msg.edit_text(f"✅ **Broadcast Completed!**\n🆔 ID: `{broadcast_id}`\n🎯 Success: {success}\n❌ Failed: {failed}", parse_mode="Markdown")

async def stop_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    broadcast_control["is_running"] = False
    await update.message.reply_text("🛑 Stopping broadcast process...")

async def delete_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    args = context.args
    if not args:
        await update.message.reply_text("⚠️ Usage: `/deletebroadcast <broadcast_id>`", parse_mode="Markdown")
        return
    b_id = args[0]
    record = broadcast_history_col.find_one({"_id": b_id})
    if not record:
        await update.message.reply_text("❌ Broadcast ID not found!")
        return

    del_success = 0
    for item in record.get("sent_details", []):
        try:
            await context.bot.delete_message(chat_id=item["user_id"], message_id=item["message_id"])
            del_success += 1
        except Exception:
            pass
        await asyncio.sleep(0.03)

    broadcast_history_col.delete_one({"_id": b_id})
    await update.message.reply_text(f"🗑 Deleted {del_success} broadcast messages.")

async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    total_users = users_col.count_documents({})
    total_files = files_col.count_documents({})
    total_batches = batch_col.count_documents({})
    await update.message.reply_text(f"📊 **Stats:**\n👥 Users: {total_users}\n📁 Files: {total_files}\n📦 Batches: {total_batches}")

# ----------------- MAIN APP INITIALIZATION -----------------
def main():
    app = ApplicationBuilder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("togglead", toggle_ad))
    app.add_handler(CommandHandler("genlink", genlink))
    app.add_handler(CommandHandler("batch", batch_command))
    app.add_handler(CommandHandler("sendad", send_ad))
    app.add_handler(CommandHandler("stopbroadcast", stop_broadcast))
    app.add_handler(CommandHandler("deletebroadcast", delete_broadcast))
    app.add_handler(CommandHandler("addchannel", add_channel))
    app.add_handler(CommandHandler("delchannel", del_channel))
    app.add_handler(CommandHandler("channels", list_channels))
    app.add_handler(CommandHandler("stats", stats_command))
    
    app.add_handler(CallbackQueryHandler(fsub_callback))
    app.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), handle_admin_messages))

    print("Bot is starting...")
    app.run_polling()

if __name__ == "__main__":
    main()

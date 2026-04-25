import os
import logging
import asyncio
from flask import Flask
from threading import Thread
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = "7529003560:AAGIIp-RM4tPwbH8dxD5fc2cdz22pvuu-Cw"
# Default configuration
BOT_CONFIG = {
    "name": "GP Help Bot",
    "owner_id": None,
    "away_mode": False
}
CUSTOM_FACTS = {} 
SETTINGS = {
    "antichannelpin": "off",
    "cleanlinked": "off"
}

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- WEB SERVER FOR RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running 24/7!"

# --- HELPERS ---
async def is_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == constants.ChatType.PRIVATE:
        return True
    member = await context.bot.get_chat_member(update.effective_chat.id, update.effective_user.id)
    return member.status in [constants.ChatMemberStatus.ADMINISTRATOR, constants.ChatMemberStatus.OWNER]

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Hello! I am {BOT_CONFIG['name']}, your group management bot. Use /help to see what I can do.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        f"<b>Current Bot Name:</b> {BOT_CONFIG['name']}\n\n"
        "<b>General Commands:</b>\n"
        "/start - Start the bot\n"
        "/help - Show this message\n"
        "/setname [name] - Change my name (Admin only)\n"
        "/away - Toggle Owner Away Mode\n"
        "/teach [fact] [value] - Teach me something\n"
        "/id - Get IDs\n\n"
        "<b>Admin/Mod Commands:</b>\n"
        "/ban - Ban a user (Reply)\n"
        "/kick - Kick a user (Reply)\n"
        "/mute - Mute a user (Reply)\n"
        "/unban - Unban a user\n"
        "/unmute - Unmute a user\n\n"
        "<b>Pin Commands:</b>\n"
        "/pinned - Get current pin\n"
        "/pin - Pin a message (Reply)\n"
        "/permapin [text] - Pin custom text\n"
        "/unpin - Unpin message\n"
        "/unpinall - Unpin all\n"
        "/antichannelpin [on/off] - Toggle channel pin blocking\n"
        "/cleanlinked [on/off] - Delete linked channel messages\n\n"
        f"<i>Tip: Mention '{BOT_CONFIG['name']}' in your message to talk to me!</i>"
    )
    await update.message.reply_text(help_text, parse_mode=constants.ParseMode.HTML)

async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not context.args:
        await update.message.reply_text("Usage: /setname [new_name]")
        return
    new_name = " ".join(context.args)
    BOT_CONFIG["name"] = new_name
    await update.message.reply_text(f"My name has been changed to: {new_name}\nFrom now on, call me '{new_name}' to get my attention!")

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        return

    # Handle linked channel messages
    if update.message.is_automatic_forward and SETTINGS["cleanlinked"] == "on":
        try:
            await update.message.delete()
            return
        except:
            pass

    # Handle channel pins
    if update.message.sender_chat and update.message.sender_chat.type == constants.ChatType.CHANNEL:
        if SETTINGS["antichannelpin"] == "on":
            try:
                await context.bot.unpin_chat_message(update.effective_chat.id, update.message.message_id)
            except:
                pass

    if not update.message.text:
        return

    text = update.message.text.lower()
    user_id = update.message.from_user.id
    
    if BOT_CONFIG["owner_id"] is None:
        BOT_CONFIG["owner_id"] = user_id

    # Check for Name Mention (Dynamic)
    if BOT_CONFIG["name"].lower() in text:
        found_fact = False
        for fact in CUSTOM_FACTS:
            if fact in text:
                await update.message.reply_text(f"I remember you told me: {CUSTOM_FACTS[fact]}")
                found_fact = True
                break
        if not found_fact:
            await update.message.reply_text(f"Yes? I'm {BOT_CONFIG['name']}! How can I help you today?")
        return

    # Owner Away Mode
    if BOT_CONFIG["away_mode"] and user_id != BOT_CONFIG["owner_id"]:
        if update.message.chat.type in [constants.ChatType.GROUP, constants.ChatType.SUPERGROUP]:
            await update.message.reply_text(f"The Owner is currently busy. I am {BOT_CONFIG['name']}, here to assist you!")

# --- PIN COMMANDS ---

async def get_pinned(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = await context.bot.get_chat(update.effective_chat.id)
    if chat.pinned_message:
        await update.message.reply_text("Current pinned message is here.", reply_to_message_id=chat.pinned_message.message_id)
    else:
        await update.message.reply_text("No message is currently pinned.")

async def pin_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to pin it.")
        return
    
    notify = any(arg in context.args for arg in ["loud", "notify"])
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id, disable_notification=not notify)
        await update.message.reply_text("Message pinned successfully.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def permapin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not context.args:
        await update.message.reply_text("Usage: /permapin [text]")
        return
    text = " ".join(context.args)
    msg = await update.message.reply_text(text, parse_mode=constants.ParseMode.MARKDOWN)
    try:
        await context.bot.pin_chat_message(update.effective_chat.id, msg.message_id)
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def unpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    try:
        if update.message.reply_to_message:
            await context.bot.unpin_chat_message(update.effective_chat.id, update.message.reply_to_message.message_id)
        else:
            await context.bot.unpin_chat_message(update.effective_chat.id)
        await update.message.reply_text("Message unpinned.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def unpinall(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    try:
        await context.bot.unpin_all_chat_messages(update.effective_chat.id)
        await update.message.reply_text("All messages unpinned.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def set_antichannelpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not context.args:
        await update.message.reply_text(f"Current setting: {SETTINGS['antichannelpin']}")
        return
    val = context.args[0].lower()
    if val in ["yes", "on"]: SETTINGS["antichannelpin"] = "on"
    elif val in ["no", "off"]: SETTINGS["antichannelpin"] = "off"
    await update.message.reply_text(f"Anti-channel pin set to: {SETTINGS['antichannelpin']}")

async def set_cleanlinked(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    if not context.args:
        await update.message.reply_text(f"Current setting: {SETTINGS['cleanlinked']}")
        return
    val = context.args[0].lower()
    if val in ["yes", "on"]: SETTINGS["cleanlinked"] = "on"
    elif val in ["no", "off"]: SETTINGS["cleanlinked"] = "off"
    await update.message.reply_text(f"Clean linked channel set to: {SETTINGS['cleanlinked']}")

# --- UTILS ---

async def teach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /teach [keyword] [information]")
        return
    keyword = context.args[0].lower()
    info = " ".join(context.args[1:])
    CUSTOM_FACTS[keyword] = info
    await update.message.reply_text(f"Got it! I've memorized that {keyword} is {info}.")

async def toggle_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    BOT_CONFIG["away_mode"] = not BOT_CONFIG["away_mode"]
    status = "ON" if BOT_CONFIG["away_mode"] else "OFF"
    await update.message.reply_text(f"Owner Away Mode is now {status}.")

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: {update.effective_user.id}\nChat ID: {update.effective_chat.id}")

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    try:
        if update.message.reply_to_message:
            await context.bot.ban_chat_member(update.effective_chat.id, update.message.reply_to_message.from_user.id)
            await update.message.reply_text("User has been banned.")
        else:
            await update.message.reply_text("Reply to a user to ban.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await is_admin(update, context): return
    try:
        if update.message.reply_to_message:
            uid = update.message.reply_to_message.from_user.id
            await context.bot.unban_chat_member(update.effective_chat.id, uid)
            await update.message.reply_text("User has been kicked.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

# --- MAIN ---

async def run_bot():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setname", set_name))
    application.add_handler(CommandHandler("away", toggle_away))
    application.add_handler(CommandHandler("teach", teach))
    application.add_handler(CommandHandler("id", get_id))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("kick", kick))
    
    application.add_handler(CommandHandler("pinned", get_pinned))
    application.add_handler(CommandHandler("pin", pin_message))
    application.add_handler(CommandHandler("permapin", permapin))
    application.add_handler(CommandHandler("unpin", unpin))
    application.add_handler(CommandHandler("unpinall", unpinall))
    application.add_handler(CommandHandler("antichannelpin", set_antichannelpin))
    application.add_handler(CommandHandler("cleanlinked", set_cleanlinked))
    
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, handle_messages))

    print("Bot started...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    def start_bot_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())

    Thread(target=start_bot_thread, daemon=True).start()

    import subprocess
    def start_pinger():
        if os.environ.get("RENDER_EXTERNAL_URL"):
            subprocess.Popen(["python3", "keep_alive.py"])
    
    Thread(target=start_pinger, daemon=True).start()
    
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

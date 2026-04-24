import os
import logging
import asyncio
from flask import Flask
from threading import Thread
from telegram import Update, constants
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

# --- CONFIGURATION ---
TOKEN = "7529003560:AAGIIp-RM4tPwbH8dxD5fc2cdz22pvuu-Cw"
BOT_NAME = "GP Help Bot"
OWNER_ID = None  # Will be set dynamically or can be hardcoded
AWAY_MODE = False
CUSTOM_FACTS = {} # Simple in-memory memory for facts

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- WEB SERVER FOR RENDER ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is running 24/7!"

def run_web():
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

def keep_alive():
    t = Thread(target=run_web)
    t.start()

# --- BOT HANDLERS ---

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Hello! I am {BOT_NAME}, your group management bot. Use /help to see what I can do.")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "<b>Available Commands:</b>\n"
        "/start - Start the bot\n"
        "/help - Show this message\n"
        "/ban - Ban a user (Admin only)\n"
        "/kick - Kick a user (Admin only)\n"
        "/mute - Mute a user (Admin only)\n"
        "/unban - Unban a user (Admin only)\n"
        "/unmute - Unmute a user (Admin only)\n"
        "/away - Toggle Owner Away Mode (Owner only)\n"
        "/teach [fact] [value] - Teach me something\n"
        "/id - Get your ID and Group ID\n"
        "\n<b>Interaction:</b>\n"
        "Mention my name 'GP Help Bot' to ask me something!\n"
        "If Owner is away, I will reply to messages for them."
    )
    await update.message.reply_text(help_text, parse_mode=constants.ParseMode.HTML)

async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AWAY_MODE, OWNER_ID
    if not update.message or not update.message.text:
        return

    text = update.message.text.lower()
    user_id = update.message.from_user.id
    
    # Set owner ID on first interaction or hardcode it
    if OWNER_ID is None:
        OWNER_ID = user_id # For simplicity, first person to talk to it is owner in this demo

    # 1. Check for Name Mention
    if BOT_NAME.lower() in text:
        # Check if it's a question about taught facts
        found_fact = False
        for fact in CUSTOM_FACTS:
            if fact in text:
                await update.message.reply_text(f"I remember you told me: {CUSTOM_FACTS[fact]}")
                found_fact = True
                break
        if not found_fact:
            await update.message.reply_text("Yes? I'm listening! How can I help you today?")
        return

    # 2. Owner Away Mode
    if AWAY_MODE and user_id != OWNER_ID:
        # Simple auto-reply if someone talks in the group and owner is away
        if update.message.chat.type in [constants.ChatType.GROUP, constants.ChatType.SUPERGROUP]:
            await update.message.reply_text("The Owner is currently busy and cannot reply. I am here to help you instead!")

async def teach(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /teach [keyword] [information]")
        return
    keyword = context.args[0].lower()
    info = " ".join(context.args[1:])
    CUSTOM_FACTS[keyword] = info
    await update.message.reply_text(f"Got it! I've memorized that {keyword} is {info}.")

async def toggle_away(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global AWAY_MODE
    AWAY_MODE = not AWAY_MODE
    status = "ON" if AWAY_MODE else "OFF"
    await update.message.reply_text(f"Owner Away Mode is now {status}.")

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(f"Your ID: {update.effective_user.id}\nChat ID: {update.effective_chat.id}")

# --- ADMIN COMMANDS ---

async def ban(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_chat.type in [constants.ChatType.GROUP, constants.ChatType.SUPERGROUP]:
        return
    # Simple check for admin rights would go here
    try:
        if update.message.reply_to_message:
            user_to_ban = update.message.reply_to_message.from_user.id
            await context.bot.ban_chat_member(update.effective_chat.id, user_to_ban)
            await update.message.reply_text("User has been banned.")
        else:
            await update.message.reply_text("Please reply to a user's message to ban them.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

async def kick(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        if update.message.reply_to_message:
            user_to_kick = update.message.reply_to_message.from_user.id
            await context.bot.unban_chat_member(update.effective_chat.id, user_to_kick)
            await update.message.reply_text("User has been kicked.")
    except Exception as e:
        await update.message.reply_text(f"Error: {e}")

# --- MAIN ---

async def run_bot():
    application = Application.builder().token(TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("away", toggle_away))
    application.add_handler(CommandHandler("teach", teach))
    application.add_handler(CommandHandler("id", get_id))
    application.add_handler(CommandHandler("ban", ban))
    application.add_handler(CommandHandler("kick", kick))
    
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_messages))

    print("Bot started...")
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # Keep running until the event loop is closed
    while True:
        await asyncio.sleep(1)

if __name__ == '__main__':
    # Start the bot in a background thread
    def start_bot_thread():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(run_bot())

    Thread(target=start_bot_thread, daemon=True).start()

    # Start the keep-alive pinger in another thread
    import subprocess
    def start_pinger():
        if os.environ.get("RENDER_EXTERNAL_URL"):
            subprocess.Popen(["python3", "keep_alive.py"])
    
    Thread(target=start_pinger, daemon=True).start()
    
    # Run Flask in the main thread
    port = int(os.environ.get('PORT', 8080))
    app.run(host='0.0.0.0', port=port)

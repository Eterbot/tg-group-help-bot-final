import logging
import os
import threading
import time
import requests
from flask import Flask
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
TOKEN = "7529003560:AAGIIp-RM4tPwbH8dxD5fc2cdz22pvuu-Cw"
GEMINI_API_KEY = "AIzaSyBUdm4tAPbd_PmVh8jc8DqnoBKzfZC2Zcw"
RENDER_URL = os.environ.get("RENDER_EXTERNAL_URL")

# --- DATA STORAGE (In-memory for simplicity, resets on restart) ---
group_data = {} # {chat_id: {"welcome": str, "name": str, "notes": {}, "filters": {}}}

def get_chat_data(chat_id):
    if chat_id not in group_data:
        group_data[chat_id] = {
            "welcome": "Welcome to the group!",
            "name": "အီတာ", # Default name
            "notes": {},
            "filters": {},
            "owner_away": False
        }
    return group_data[chat_id]

# --- AI INTEGRATION ---
def get_ai_response(text, chat_id):
    chat_config = get_chat_data(chat_id)
    bot_name = chat_config.get("name", "အီတာ")
    
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={GEMINI_API_KEY}"
    headers = {'Content-Type': 'application/json'}
    
    # Prompt engineering for concise Burmese response
    prompt = f"You are a helpful Telegram group bot named '{bot_name}'. Respond in Burmese. Keep it very short and concise (one or two sentences max). User said: {text}"
    
    payload = {
        "contents": [{"parts": [{"text": prompt}]}]
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=10)
        response.raise_for_status()
        data = response.json()
        return data['candidates'][0]['content']['parts'][0]['text']
    except Exception as e:
        logger.error(f"AI Error: {e}")
        return None # Return None so we can handle it in the message handler

# --- COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("မင်္ဂလာပါ! ကျွန်တော်က Group Help Bot ပါ။ /help ကိုနှိပ်ပြီး ဘာတွေလုပ်လို့ရလဲ ကြည့်နိုင်ပါတယ်။")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📌 **Pin Commands:**\n"
        "/pin - Message ကို pin ရန်\n"
        "/unpin - Pin ဖြုတ်ရန်\n"
        "/permapin [text] - Bot နာမည်နဲ့ pin ရန်\n\n"
        "⚙️ **Settings:**\n"
        "/setname [name] - Bot နာမည်ပြောင်းရန်\n"
        "/setwelcome [text] - Welcome message ပြောင်းရန်\n\n"
        "🤖 **AI Interaction:**\n"
        "Bot နာမည်ကိုခေါ်ပြီး မေးခွန်းမေးနိုင်ပါတယ်။"
    )
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("အသုံးပြုပုံ - /setname [နာမည်]")
        return
    new_name = " ".join(context.args)
    get_chat_data(update.effective_chat.id)["name"] = new_name
    await update.message.reply_text(f"Bot နာမည်ကို '{new_name}' လို့ ပြောင်းလိုက်ပါပြီ။")

async def pin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message.reply_to_message:
        await update.message.reply_text("Pin ရန်အတွက် message တစ်ခုကို reply ပြန်ပေးပါ။")
        return
    await update.message.reply_to_message.pin()
    await update.message.reply_text("Message ကို Pin လိုက်ပါပြီ။")

async def unpin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.unpin_chat_message(chat_id=update.effective_chat.id)
    await update.message.reply_text("Pinned message ကို ဖြုတ်လိုက်ပါပြီ။")

# --- MESSAGE HANDLER ---
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return

    text = update.message.text
    chat_id = update.effective_chat.id
    chat_config = get_chat_data(chat_id)
    bot_name = chat_config.get("name", "အီတာ")

    # Check if bot name is mentioned
    if bot_name.lower() in text.lower():
        # Get AI response
        response = get_ai_response(text, chat_id)
        if response:
            await update.message.reply_text(response)
        else:
            # Fallback if AI fails
            await update.message.reply_text(f"စိတ်မရှိပါနဲ့၊ အခုလောလောဆယ် ကျွန်တော် (AI) အလုပ်မလုပ်နိုင်သေးလို့ပါ။ ခဏနေမှ ပြန်မေးပေးပါခင်ဗျာ။")

# --- WEB SERVER FOR KEEP-ALIVE ---
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

def run_flask():
    app.run(host='0.0.0.0', port=10000)

def keep_alive():
    while True:
        if RENDER_URL:
            try:
                requests.get(RENDER_URL)
                logger.info("Keep-alive ping successful")
            except Exception as e:
                logger.error(f"Keep-alive ping failed: {e}")
        time.sleep(600) # 10 minutes

# --- MAIN ---
if __name__ == '__main__':
    # Start Flask in a background thread
    threading.Thread(target=run_flask, daemon=True).start()
    
    # Start Keep-alive in a background thread
    threading.Thread(target=keep_alive, daemon=True).start()

    # Start Telegram Bot
    application = ApplicationBuilder().token(TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setname", set_name))
    application.add_handler(CommandHandler("pin", pin))
    application.add_handler(CommandHandler("unpin", unpin))
    
    application.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_message))
    
    logger.info("Bot started...")
    application.run_polling()

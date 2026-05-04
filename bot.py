import logging
import os
import threading
import time
import sqlite3
import json
import requests
from flask import Flask
from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.constants import ParseMode, ChatMemberStatus
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes, CallbackQueryHandler

# Configure logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIGURATION ---
TOKEN = os.environ.get("BOT_TOKEN", "8628273502:AAH1dxrSMZtV1tOUKAyYRQMrkAu8EfHsuWc")

# --- DATABASE SETUP ---
conn = sqlite3.connect("bot.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("CREATE TABLE IF NOT EXISTS warns (chat_id TEXT, user_id TEXT, count INTEGER DEFAULT 0, PRIMARY KEY (chat_id, user_id))")
cursor.execute("CREATE TABLE IF NOT EXISTS activity (chat_id TEXT, user_id TEXT, messages INTEGER DEFAULT 0, last_seen INTEGER, PRIMARY KEY (chat_id, user_id))")
cursor.execute("CREATE TABLE IF NOT EXISTS settings (chat_id TEXT, key TEXT, value TEXT, PRIMARY KEY (chat_id, key))")
cursor.execute("CREATE TABLE IF NOT EXISTS knowledge (chat_id TEXT, fact TEXT, value TEXT, PRIMARY KEY (chat_id, fact))")
cursor.execute("CREATE TABLE IF NOT EXISTS filters (chat_id TEXT, keyword TEXT, reply TEXT, PRIMARY KEY (chat_id, keyword))")
cursor.execute("CREATE TABLE IF NOT EXISTS notes (chat_id TEXT, note_name TEXT, content TEXT, PRIMARY KEY (chat_id, note_name))")
cursor.execute("CREATE TABLE IF NOT EXISTS rules (chat_id TEXT, rules_text TEXT, PRIMARY KEY (chat_id))")
cursor.execute("CREATE TABLE IF NOT EXISTS connections (user_id TEXT PRIMARY KEY, chat_id TEXT, last_chat_id TEXT)")
conn.commit()

# --- HELPERS ---
def get_setting(chat_id, key, default=None):
    cursor.execute("SELECT value FROM settings WHERE chat_id=? AND key=?", (str(chat_id), key))
    r = cursor.fetchone()
    return r[0] if r else default

def set_setting(chat_id, key, value):
    cursor.execute("INSERT OR REPLACE INTO settings (chat_id, key, value) VALUES (?, ?, ?)", (str(chat_id), key, str(value)))
    conn.commit()

async def get_connected_chat(user_id):
    cursor.execute("SELECT chat_id FROM connections WHERE user_id=?", (str(user_id),))
    r = cursor.fetchone()
    return r[0] if r else None

async def get_effective_chat_id(update: Update):
    if update.effective_chat.type == "private":
        connected = await get_connected_chat(update.effective_user.id)
        return connected if connected else str(update.effective_chat.id)
    return str(update.effective_chat.id)

async def is_admin(update: Update, target_chat_id=None):
    user_id = update.effective_user.id
    chat_id = target_chat_id or update.effective_chat.id
    
    # In private chat with no connection, user is "admin" of their own chat
    if update.effective_chat.type == "private" and not target_chat_id:
        return True
        
    try:
        member = await update.get_bot().get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

# --- CONNECTION COMMANDS ---
async def connect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if update.effective_chat.type != "private":
        # If in group, connect to current group
        chat_id = str(update.effective_chat.id)
        chat_title = update.effective_chat.title
        cursor.execute("INSERT INTO connections (user_id, chat_id, last_chat_id) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET last_chat_id=chat_id, chat_id=?", (user_id, chat_id, chat_id, chat_id))
        conn.commit()
        await update.message.reply_text(f"✅ Connected to **{chat_title}**. You can now manage it in private chat.", parse_mode=ParseMode.MARKDOWN)
        return

    if not context.args:
        # List recent connections or show help
        cursor.execute("SELECT chat_id, last_chat_id FROM connections WHERE user_id=?", (user_id,))
        r = cursor.fetchone()
        if r:
            curr, last = r
            await update.message.reply_text(f"Current connection: `{curr}`\nLast connection: `{last}`\n\nUse `/connect <chat_id>` to connect to a group.", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("Usage: `/connect <chat_id/username>`\nOr use `/connect` inside a group.", parse_mode=ParseMode.MARKDOWN)
        return

    target = context.args[0]
    try:
        chat = await context.bot.get_chat(target)
        # Verify admin status in target chat
        member = await chat.get_member(update.effective_user.id)
        if member.status not in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]:
            await update.message.reply_text("❌ You must be an admin in that chat to connect.")
            return
            
        cursor.execute("INSERT INTO connections (user_id, chat_id, last_chat_id) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET last_chat_id=chat_id, chat_id=?", (user_id, str(chat.id), str(chat.id), str(chat.id)))
        conn.commit()
        await update.message.reply_text(f"✅ Connected to **{chat.title}** (`{chat.id}`).", parse_mode=ParseMode.MARKDOWN)
    except Exception as e:
        await update.message.reply_text(f"❌ Failed to connect: {str(e)}")

async def disconnect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    cursor.execute("SELECT chat_id FROM connections WHERE user_id=?", (user_id,))
    r = cursor.fetchone()
    if r:
        cursor.execute("UPDATE connections SET last_chat_id=chat_id, chat_id=NULL WHERE user_id=?", (user_id,))
        conn.commit()
        await update.message.reply_text("🔌 Disconnected from chat.")
    else:
        await update.message.reply_text("You are not connected to any chat.")

async def reconnect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    cursor.execute("SELECT last_chat_id FROM connections WHERE user_id=?", (user_id,))
    r = cursor.fetchone()
    if r and r[0]:
        last_id = r[0]
        cursor.execute("UPDATE connections SET chat_id=? WHERE user_id=?", (last_id, user_id))
        conn.commit()
        await update.message.reply_text(f"✅ Reconnected to `{last_id}`.")
    else:
        await update.message.reply_text("No previous connection found.")

async def connection_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    chat_id = await get_connected_chat(user_id)
    if chat_id:
        try:
            chat = await context.bot.get_chat(chat_id)
            await update.message.reply_text(f"📍 Currently connected to: **{chat.title}**\nID: `{chat_id}`", parse_mode=ParseMode.MARKDOWN)
        except:
            await update.message.reply_text(f"📍 Currently connected to ID: `{chat_id}`", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("You are not currently connected to any chat.")

# --- ENHANCED COMMAND HANDLERS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Ultra Bot Ready! Use /help to see available commands. Use /connect in a group to manage it from here.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "**User Commands:**\n"
        "/info - Get user info\n"
        "/rules - View group rules\n"
        "/notes - View saved notes\n"
        "/filters - View active filters\n\n"
        "**Admin Commands:**\n"
        "/lock /unlock - Lock/Unlock group\n"
        "/filter [word] [reply] - Add filter\n"
        "/stop [word] - Remove filter\n"
        "/save [name] [content] - Save a note\n"
        "/clear [name] - Delete a note\n"
        "/setrules [text] - Set group rules\n"
        "/setwelcome [text] - Set welcome message\n\n"
        "**Connections:**\n"
        "/connect <id> - Connect to a chat\n"
        "/disconnect - Disconnect\n"
        "/reconnect - Reconnect\n"
        "/connection - Show current connection"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def set_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id): 
        await update.message.reply_text("❌ Admin rights required.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /setrules [text]")
        return
    rules_text = " ".join(context.args)
    cursor.execute("INSERT OR REPLACE INTO rules (chat_id, rules_text) VALUES (?, ?)", (chat_id, rules_text))
    conn.commit()
    await update.message.reply_text(f"✅ Rules updated for {chat_id}!")

async def get_rules(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    cursor.execute("SELECT rules_text FROM rules WHERE chat_id=?", (chat_id,))
    r = cursor.fetchone()
    if r:
        await update.message.reply_text(f"📜 **Rules:**\n\n{r[0]}", parse_mode=ParseMode.MARKDOWN)
    else:
        await update.message.reply_text("No rules set.")

async def save_note(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /save [name] [content]")
        return
    name = context.args[0].lower()
    content = " ".join(context.args[1:])
    cursor.execute("INSERT OR REPLACE INTO notes (chat_id, note_name, content) VALUES (?, ?, ?)", (chat_id, name, content))
    conn.commit()
    await update.message.reply_text(f"✅ Note '{name}' saved for {chat_id}!")

async def add_filter(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /filter [word] [reply]")
        return
    word = context.args[0].lower()
    reply = " ".join(context.args[1:])
    cursor.execute("INSERT OR REPLACE INTO filters (chat_id, keyword, reply) VALUES (?, ?, ?)", (chat_id, word, reply))
    conn.commit()
    await update.message.reply_text(f"✅ Filter for '{word}' added for {chat_id}!")

# --- KEEP ALIVE ---
app = Flask('')
@app.route('/')
def home(): return "Bot is alive 24/7!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- MAIN ---
if __name__ == '__main__':
    threading.Thread(target=run_flask).start()
    app_tg = ApplicationBuilder().token(TOKEN).build()
    
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("help", help_cmd))
    app_tg.add_handler(CommandHandler("connect", connect_chat))
    app_tg.add_handler(CommandHandler("disconnect", disconnect_chat))
    app_tg.add_handler(CommandHandler("reconnect", reconnect_chat))
    app_tg.add_handler(CommandHandler("connection", connection_info))
    app_tg.add_handler(CommandHandler("setrules", set_rules))
    app_tg.add_handler(CommandHandler("rules", get_rules))
    app_tg.add_handler(CommandHandler("save", save_note))
    app_tg.add_handler(CommandHandler("filter", add_filter))
    
    # Message handler for group filtering (should always use local chat_id)
    async def handle_group_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.message or not update.message.text: return
        text = update.message.text.lower()
        chat_id = str(update.effective_chat.id)
        cursor.execute("SELECT keyword, reply FROM filters WHERE chat_id=?", (chat_id,))
        for keyword, reply in cursor.fetchall():
            if keyword in text:
                await update.message.reply_text(reply)
                return
                
    app_tg.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & (~filters.COMMAND), handle_group_messages))
    
    print("Bot started...")
    app_tg.run_polling()

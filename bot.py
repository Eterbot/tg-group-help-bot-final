import logging
import os
import threading
import time
import sqlite3
import json
import requests
import re
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

def track_user(chat_id, user_id):
    now = int(time.time())
    chat_id, user_id = str(chat_id), str(user_id)
    cursor.execute("SELECT messages FROM activity WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    d = cursor.fetchone()
    if d:
        cursor.execute("UPDATE activity SET messages=?, last_seen=? WHERE chat_id=? AND user_id=?", (d[0]+1, now, chat_id, user_id))
    else:
        cursor.execute("INSERT INTO activity (chat_id, user_id, messages, last_seen) VALUES (?, ?, ?, ?)", (chat_id, user_id, 1, now))
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
    
    if update.effective_chat.type == "private" and not target_chat_id:
        return True
        
    try:
        member = await update.get_bot().get_chat_member(chat_id, user_id)
        return member.status in [ChatMemberStatus.ADMINISTRATOR, ChatMemberStatus.OWNER]
    except Exception as e:
        logger.error(f"Error checking admin status: {e}")
        return False

# --- CALCULATOR ---
async def calculate(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: `/calc 5 + 5` or `/calc 10 * 2`", parse_mode=ParseMode.MARKDOWN)
        return
    
    expression = "".join(context.args).replace('×', '*').replace('÷', '/').replace(' ', '')
    try:
        # Restricted evaluation for safety
        allowed_chars = re.compile(r'^[0-9+-*/().]*$')
        if allowed_chars.match(expression):
            # Using eval in a restricted namespace
            result = eval(expression, {"__builtins__": None}, {})
            await update.message.reply_text(f"🔢 **Result:** `{result}`", parse_mode=ParseMode.MARKDOWN)
        else:
            await update.message.reply_text("❌ Only numbers and `+ - * / ( )` are allowed.")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# --- CONNECTION COMMANDS ---
async def connect_chat(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = str(update.effective_user.id)
    
    if update.effective_chat.type != "private":
        chat_id = str(update.effective_chat.id)
        chat_title = update.effective_chat.title
        cursor.execute("INSERT INTO connections (user_id, chat_id, last_chat_id) VALUES (?, ?, ?) ON CONFLICT(user_id) DO UPDATE SET last_chat_id=chat_id, chat_id=?", (user_id, chat_id, chat_id, chat_id))
        conn.commit()
        await update.message.reply_text(f"✅ Connected to **{chat_title}**. You can now manage it in private chat.", parse_mode=ParseMode.MARKDOWN)
        return

    if not context.args:
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

# --- ADMIN COMMANDS ---
async def set_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /setname [new name]")
        return
    new_name = " ".join(context.args)
    set_setting(chat_id, "bot_name", new_name)
    await update.message.reply_text(f"✅ Bot name changed to '{new_name}'!")

async def warn_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to warn them.")
        return
    
    user_id = str(update.message.reply_to_message.from_user.id)
    cursor.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    r = cursor.fetchone()
    count = (r[0] if r else 0) + 1
    cursor.execute("INSERT OR REPLACE INTO warns (chat_id, user_id, count) VALUES (?, ?, ?)", (chat_id, user_id, count))
    conn.commit()
    await update.message.reply_text(f"⚠️ User warned! Warnings: {count}/3")

async def clear_warns(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to clear their warns.")
        return
    
    user_id = str(update.message.reply_to_message.from_user.id)
    cursor.execute("DELETE FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    conn.commit()
    await update.message.reply_text("✅ Warns cleared!")

async def get_warnings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user to check their warnings.")
        return
    
    user_id = str(update.message.reply_to_message.from_user.id)
    cursor.execute("SELECT count FROM warns WHERE chat_id=? AND user_id=?", (chat_id, user_id))
    r = cursor.fetchone()
    count = r[0] if r else 0
    await update.message.reply_text(f"⚠️ Warnings: {count}/3")

async def antilink_toggle(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if not context.args or context.args[0].lower() not in ['on', 'off']:
        await update.message.reply_text("Usage: /antilink [on/off]")
        return
    
    state = context.args[0].lower()
    set_setting(chat_id, "antilink", state)
    await update.message.reply_text(f"✅ Antilink turned {state}!")

async def set_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /setwelcome [text]")
        return
    
    welcome_text = " ".join(context.args)
    set_setting(chat_id, "welcome_msg", welcome_text)
    set_setting(chat_id, "welcome_on", "true")
    await update.message.reply_text(f"✅ Welcome message set!")

async def toggle_welcome(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if not context.args or context.args[0].lower() not in ['on', 'off']:
        await update.message.reply_text("Usage: /welcome [on/off]")
        return
    
    state = context.args[0].lower()
    set_setting(chat_id, "welcome_on", state)
    await update.message.reply_text(f"✅ Welcome turned {state}!")

async def tag_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    
    try:
        chat = await context.bot.get_chat(chat_id)
        await update.message.reply_text("Tagging all members...")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

async def delete_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a message to delete it.")
        return
    
    try:
        await update.message.reply_to_message.delete()
        await update.message.reply_text("✅ Message deleted!")
    except Exception as e:
        await update.message.reply_text(f"❌ Error: {str(e)}")

# --- GENERAL COMMANDS ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🤖 Bot Ready! Use /help to see available commands.")

async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "**User Commands:**\n"
        "/id - Get IDs\n"
        "/calc [expression] - Calculator (+ - * /)\n"
        "/rules - View group rules\n"
        "/notes - View saved notes\n"
        "/filters - View active filters\n\n"
        "**Admin Commands:**\n"
        "/setname [name] - Change bot name\n"
        "/warn - Warn a user (reply)\n"
        "/warnings - Check user warnings (reply)\n"
        "/clearwarns - Clear user warnings (reply)\n"
        "/antilink [on/off] - Toggle antilink\n"
        "/welcome [on/off] - Toggle welcome\n"
        "/setwelcome [text] - Set welcome message\n"
        "/tagall - Tag all members\n"
        "/del - Delete replied message\n"
        "/save [name] [content] - Save a note\n"
        "/filter [word] [reply] - Add filter\n"
        "/setrules [text] - Set group rules\n\n"
        "**Connections:**\n"
        "/connect <id> - Connect to a chat\n"
        "/disconnect - Disconnect\n"
        "/reconnect - Reconnect\n"
        "/connection - Show current connection"
    )
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN)

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    user_id = update.effective_user.id
    await update.message.reply_text(f"Chat ID: `{chat_id}`\nUser ID: `{user_id}`", parse_mode=ParseMode.MARKDOWN)

async def get_stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    cursor.execute("SELECT COUNT(*) FROM activity WHERE chat_id=?", (chat_id,))
    total_users = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(messages) FROM activity WHERE chat_id=?", (chat_id,))
    total_msgs = cursor.fetchone()[0] or 0
    await update.message.reply_text(f"📊 **Stats:**\nTotal Users: {total_users}\nTotal Messages: {total_msgs}", parse_mode=ParseMode.MARKDOWN)

async def get_active(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    cursor.execute("SELECT user_id, messages FROM activity WHERE chat_id=? ORDER BY messages DESC LIMIT 5", (chat_id,))
    rows = cursor.fetchall()
    if not rows:
        await update.message.reply_text("No activity data yet.")
        return
    text = "🔥 **Most Active Users:**\n"
    for user_id, msgs in rows:
        text += f"User {user_id}: {msgs} messages\n"
    await update.message.reply_text(text, parse_mode=ParseMode.MARKDOWN)

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
    await update.message.reply_text(f"✅ Rules updated!")

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
    await update.message.reply_text(f"✅ Note '{name}' saved!")

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
    await update.message.reply_text(f"✅ Filter for '{word}' added!")

async def teach_fact(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = await get_effective_chat_id(update)
    if not await is_admin(update, chat_id):
        await update.message.reply_text("❌ Admin rights required.")
        return
    if len(context.args) < 2:
        await update.message.reply_text("Usage: /teach [fact] [value]")
        return
    fact = context.args[0].lower()
    value = " ".join(context.args[1:])
    cursor.execute("INSERT OR REPLACE INTO knowledge (chat_id, fact, value) VALUES (?, ?, ?)", (chat_id, fact, value))
    conn.commit()
    await update.message.reply_text(f"✅ Learned: {fact} = {value}")

async def get_ai_response(text, chat_id):
    bot_name = get_setting(chat_id, "bot_name", "အီတာ")
    cursor.execute("SELECT value FROM knowledge WHERE chat_id=? AND ? LIKE '%' || fact || '%'", (str(chat_id), text.lower()))
    fact = cursor.fetchone()
    if fact:
        return fact[0]
    return f"ကျွန်တော် {bot_name} ပါ။ အခုလောလောဆယ်တော့ အခြေခံမေးခွန်းတွေကိုပဲ ဖြေနိုင်ပါသေးတယ်။ ဘာကူညီပေးရမလဲခင်ဗျာ?"

# --- MESSAGE HANDLERS ---
async def handle_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    
    text = update.message.text
    chat_id = str(update.effective_chat.id)
    user_id = update.effective_user.id
    
    track_user(chat_id, user_id)
    
    # Antilink check
    if get_setting(chat_id, "antilink") == "on" and ("http://" in text or "https://" in text or "t.me/" in text):
        try:
            await update.message.delete()
            await update.message.reply_text("❌ Links not allowed!")
        except:
            pass
        return
    
    # Calculator detection
    math_pattern = re.compile(r'^[0-9+-*/().\s×÷]+$')
    if math_pattern.match(text) and any(op in text for op in "+-*/×÷"):
        expression = text.replace('×', '*').replace('÷', '/').replace(' ', '')
        try:
            result = eval(expression, {"__builtins__": None}, {})
            await update.message.reply_text(f"🔢 **Result:** `{result}`", parse_mode=ParseMode.MARKDOWN)
            return
        except:
            pass

    # Filter check
    text_lower = text.lower()
    cursor.execute("SELECT keyword, reply FROM filters WHERE chat_id=?", (chat_id,))
    for keyword, reply in cursor.fetchall():
        if keyword in text_lower:
            await update.message.reply_text(reply)
            return
    
    # AI mention
    bot_name = get_setting(chat_id, "bot_name", "အီတာ")
    if bot_name.lower() in text.lower() or (update.message.reply_to_message and update.message.reply_to_message.from_user.is_bot):
        response = await get_ai_response(text, chat_id)
        await update.message.reply_text(response)

# --- KEEP ALIVE ---
app = Flask('')
@app.route('/')
def home():
    return "Bot is alive 24/7!"

def run_flask():
    app.run(host='0.0.0.0', port=8080)

# --- MAIN ---
if __name__ == '__main__':
    threading.Thread(target=run_flask, daemon=True).start()
    app_tg = ApplicationBuilder().token(TOKEN).build()
    
    # Command handlers
    app_tg.add_handler(CommandHandler("start", start))
    app_tg.add_handler(CommandHandler("help", help_cmd))
    app_tg.add_handler(CommandHandler("id", get_id))
    app_tg.add_handler(CommandHandler("stats", get_stats))
    app_tg.add_handler(CommandHandler("active", get_active))
    app_tg.add_handler(CommandHandler("calc", calculate))
    
    # Admin commands
    app_tg.add_handler(CommandHandler("setname", set_name))
    app_tg.add_handler(CommandHandler("warn", warn_user))
    app_tg.add_handler(CommandHandler("warnings", get_warnings))
    app_tg.add_handler(CommandHandler("clearwarns", clear_warns))
    app_tg.add_handler(CommandHandler("antilink", antilink_toggle))
    app_tg.add_handler(CommandHandler("welcome", toggle_welcome))
    app_tg.add_handler(CommandHandler("setwelcome", set_welcome))
    app_tg.add_handler(CommandHandler("tagall", tag_all))
    app_tg.add_handler(CommandHandler("del", delete_message))
    app_tg.add_handler(CommandHandler("save", save_note))
    app_tg.add_handler(CommandHandler("filter", add_filter))
    app_tg.add_handler(CommandHandler("teach", teach_fact))
    app_tg.add_handler(CommandHandler("setrules", set_rules))
    app_tg.add_handler(CommandHandler("rules", get_rules))
    
    # Connection commands
    app_tg.add_handler(CommandHandler("connect", connect_chat))
    app_tg.add_handler(CommandHandler("disconnect", disconnect_chat))
    app_tg.add_handler(CommandHandler("reconnect", reconnect_chat))
    app_tg.add_handler(CommandHandler("connection", connection_info))
    
    # Message handler
    app_tg.add_handler(MessageHandler(filters.TEXT & (~filters.COMMAND), handle_messages))
    
    print("Bot started...")
    app_tg.run_polling()

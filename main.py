import asyncio
import json
import os
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- CONFIG VIA ENV ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DATA_FILE = 'quiz_data.json'

# --- DATABASE LOAD/SAVE ---
def load_db():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {
        "users": {}, 
        "questions": {"Umum": [{"q": "Menara yang miring di Italia", "h": "p__a", "a": "pisa"}]}, 
        "ads_text": "Bot Tebak-tebakan v1.0",
        "ads_photo": None
    }

db = load_db()

def save_db():
    with open(DATA_FILE, 'w') as f:
        json.dump(db, f, indent=4)

current_games = {}

# --- ADMIN PANEL ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    keyboard = [
        [InlineKeyboardButton("📤 Send Database (.json)", callback_data='send_db')],
        [InlineKeyboardButton("🖼 Set Iklan (Foto+Teks)", callback_data='set_ads')],
        [InlineKeyboardButton("➕ Tambah Soal", callback_data='add_ques')]
    ]
    await update.message.reply_text("🛠 **ADMIN PANEL**", reply_markup=InlineKeyboardMarkup(keyboard))

# --- HANDLER INPUT ADMIN ---
async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID: return
    state = context.user_data.get('state')

    if state == 'waiting_ads':
        db['ads_text'] = update.message.caption or update.message.text
        if update.message.photo:
            db['ads_photo'] = update.message.photo[-1].file_id
        save_db()
        context.user_data['state'] = None
        await update.message.reply_text("✅ Iklan Berhasil di Update!")

    elif state == 'waiting_ques':
        # Format: Kategori | Soal | Clue | Jawaban
        try:
            txt = update.message.text.split("|")
            kat, soal, clue, jaw = txt[0].strip(), txt[1].strip(), txt[2].strip(), txt[3].strip()
            if kat not in db['questions']: db['questions'][kat] = []
            db['questions'][kat].append({"q": soal, "h": clue, "a": jaw})
            save_db()
            context.user_data['state'] = None
            await update.message.reply_text(f"✅ Soal Berhasil Ditambah ke Kategori {kat}!")
        except:
            await update.message.reply_text("❌ Gagal! Format salah. Gunakan:\nKategori | Soal | Clue | Jawaban")

# --- QUIZ ENGINE (TIMER 15s + LEADERBOARD) ---
async def start_quiz(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in current_games: return # Jangan double game

    # Ambil soal acak dari semua kategori
    all_cats = list(db['questions'].keys())
    cat = random.choice(all_cats)
    q_data = random.choice(db['questions'][cat])
    
    caption = f"✨ **TEBAK-TEBAKAN [{cat}]** ✨\n\n"
    caption += f"Soal: *{q_data['q']}*\n"
    caption += f"Petunjuk: `{q_data['h']}`\n\n"
    caption += f"⏱ *Waktu: 15 Detik!*\n"
    caption += f"━━━━━━━━━━━━━━\n{db['ads_text']}"

    if db.get('ads_photo'):
        msg = await context.bot.send_photo(chat_id, photo=db['ads_photo'], caption=caption, parse_mode='Markdown')
    else:
        msg = await context.bot.send_message(chat_id, caption, parse_mode='Markdown')

    current_games[chat_id] = {"ans": q_data['a'].lower(), "answered": False, "msg_id": msg.message_id}

    # --- TIMER 15 DETIK ---
    await asyncio.sleep(15)
    if chat_id in current_games and not current_games[chat_id]['answered']:
        await context.bot.send_message(chat_id, f"⌛ **WAKTU HABIS!**\nJawabannya adalah: *{q_data['a']}*", parse_mode='Markdown')
        del current_games[chat_id]
        # Auto start soal berikutnya setelah 3 detik
        await asyncio.sleep(3)
        await start_quiz(update, context)

async def check_answer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    if chat_id in current_games and not current_games[chat_id]['answered']:
        if update.message.text.lower() == current_games[chat_id]['ans']:
            current_games[chat_id]['answered'] = True
            user = update.effective_user
            uid = str(user.id)
            
            # --- POINT SYSTEM ---
            if uid not in db['users']: db['users'][uid] = {"name": user.first_name, "pts": 0}
            db['users'][uid]['pts'] += 10
            save_db()

            # --- LEADERBOARD GLOBAL TOP 3 ---
            top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:3]
            lb = "🏆 **TOP GLOBAL LEADERBOARD** 🏆\n"
            for i, (id, data) in enumerate(top, 1):
                lb += f"{i}. {data['name']} — {data['pts']} Pts\n"
            
            await update.message.reply_text(f"✅ **{user.first_name} BENAR!** (+10 Pts)\n\n{lb}")
            del current_games[chat_id]
            
            # Auto next soal
            await asyncio.sleep(3)
            await start_quiz(update, context)

# --- CALLBACK ---
async def on_click(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == 'send_db':
        await query.message.reply_document(document=open(DATA_FILE, 'rb'))
    elif query.data == 'set_ads':
        context.user_data['state'] = 'waiting_ads'
        await query.message.reply_text("Kirim Foto iklan + Caption-nya.")
    elif query.data == 'add_ques':
        context.user_data['state'] = 'waiting_ques'
        await query.message.reply_text("Kirim soal dengan format:\nKategori | Soal | Clue | Jawaban\n\nContoh:\nUmum | Ibukota Perancis | P__is | Paris")
    await query.answer()

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start_quiz))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CallbackQueryHandler(on_click))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, check_answer))
    app.add_handler(MessageHandler((filters.PHOTO | filters.TEXT) & filters.ChatType.PRIVATE, handle_admin_input))
    app.run_polling()

if __name__ == '__main__':
    main()

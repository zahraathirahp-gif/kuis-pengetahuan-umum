import asyncio
import json
import os
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DATA_FILE = 'quiz_data.json'

def load_db():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, 'r') as f:
            return json.load(f)
    return {
        "users": {}, 
        "questions": {
            "Umum": [{"q": "Menara yang miring di Italia", "h": "p__a", "a": "pisa"}],
            "Sejarah": [{"q": "Presiden pertama RI", "h": "S__k__no", "a": "soekarno"}]
        }, 
        "ads_text": "Bot Tebak-tebakan v1.0",
        "ads_photo": None
    }

db = load_db()

def save_db():
    with open(DATA_FILE, 'w') as f:
        json.dump(db, f, indent=4)

current_games = {} # {chat_id: {data}}
group_players = {} # {chat_id: set(user_ids)} untuk cek minimal 2 orang

# --- ADMIN PANEL ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id != ADMIN_ID:
        return await update.message.reply_text("❌ Anda bukan admin.")
    
    keyboard = [
        [InlineKeyboardButton("📤 Send DB", callback_data='adm_send_db')],
        [InlineKeyboardButton("🖼 Set Iklan", callback_data='adm_set_ads')],
        [InlineKeyboardButton("➕ Tambah Soal", callback_data='adm_add_ques')]
    ]
    await update.message.reply_text("🛠 **ADMIN CONTROL PANEL**", reply_markup=InlineKeyboardMarkup(keyboard))

# --- START & CATEGORY ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    # Tombol Kategori
    keyboard = []
    for cat in db['questions'].keys():
        keyboard.append([InlineKeyboardButton(f"📁 {cat}", callback_data=f"start_{cat}")])
    
    text = "🎮 **TEBAK-TEBAKAN UMUM**\n\nPilih kategori soal di bawah ini untuk memulai:"
    await update.message.reply_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

# --- QUIZ ENGINE ---
async def send_question(context, chat_id, category):
    q_data = random.choice(db['questions'][category])
    
    text = f"✨ **KATEGORI: {category}** ✨\n\n"
    text += f"Soal: *{q_data['q']}*\n"
    text += f"Petunjuk: `{q_data['h']}`\n\n"
    text += f"⏱ *Waktu: 15 Detik*\n"
    text += f"⚠️ *Minimal 2 orang untuk dapat poin!*\n"
    text += f"━━━━━━━━━━━━━━\n{db['ads_text']}"

    # Tombol Control
    kb = [[
        InlineKeyboardButton("⏭ Skip", callback_data="game_skip"),
        InlineKeyboardButton("🛑 Stop", callback_data="game_stop")
    ]]

    if db.get('ads_photo'):
        msg = await context.bot.send_photo(chat_id, photo=db['ads_photo'], caption=text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        msg = await context.bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    current_games[chat_id] = {
        "ans": q_data['a'].lower(),
        "cat": category,
        "answered": False,
        "msg_id": msg.message_id,
        "start_by": None # Bisa diisi ID yang mulai
    }

    await asyncio.sleep(15)
    if chat_id in current_games and not current_games[chat_id]['answered']:
        await context.bot.send_message(chat_id, f"⌛ Waktu habis! Jawabannya: *{q_data['a']}*")
        await asyncio.sleep(2)
        await send_question(context, chat_id, category)

# --- CALLBACK HANDLER ---
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data

    # Admin actions
    if data.startswith('adm_'):
        if query.from_user.id != ADMIN_ID: return await query.answer("Bukan Admin!")
        
        if data == 'adm_send_db':
            save_db()
            await query.message.reply_document(open(DATA_FILE, 'rb'))
        elif data == 'adm_set_ads':
            context.user_data['state'] = 'waiting_ads'
            await query.message.reply_text("Kirim Foto + Caption Iklan.")
        elif data == 'adm_add_ques':
            context.user_data['state'] = 'waiting_ques'
            await query.message.reply_text("Format: Kategori | Soal | Clue | Jawaban")
    
    # Game actions
    elif data.startswith('start_'):
        cat = data.split('_')[1]
        await query.message.delete()
        await send_question(context, chat_id, cat)
        
    elif data == 'game_skip':
        if chat_id in current_games:
            cat = current_games[chat_id]['cat']
            current_games[chat_id]['answered'] = True
            await query.message.reply_text("⏭ Soal dilewati...")
            await send_question(context, chat_id, cat)
            
    elif data == 'game_stop':
        if chat_id in current_games:
            current_games[chat_id]['answered'] = True
            del current_games[chat_id]
            await query.message.reply_text("🛑 Game dihentikan.")

    await query.answer()

# --- ANSWER CHECKER ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    
    # Admin Input Logic
    state = context.user_data.get('state')
    if update.effective_chat.type == 'private' and state:
        if state == 'waiting_ads':
            db['ads_text'] = update.message.caption or update.message.text
            if update.message.photo: db['ads_photo'] = update.message.photo[-1].file_id
            save_db(); context.user_data['state'] = None
            await update.message.reply_text("✅ Iklan di-set!")
        elif state == 'waiting_ques':
            try:
                k, s, c, j = update.message.text.split("|")
                k=k.strip(); s=s.strip(); c=c.strip(); j=j.strip()
                if k not in db['questions']: db['questions'][k] = []
                db['questions'][k].append({"q":s, "h":c, "a":j})
                save_db(); context.user_data['state'] = None
                await update.message.reply_text(f"✅ Soal masuk ke {k}!")
            except: await update.message.reply_text("Format salah!")
        return

    # Quiz Answer Logic
    if chat_id in current_games and not current_games[chat_id]['answered']:
        # Track Pemain (Cek curang)
        if chat_id not in group_players: group_players[chat_id] = set()
        group_players[chat_id].add(user.id)

        if update.message.text.lower() == current_games[chat_id]['ans']:
            # Cek minimal 2 orang
            if len(group_players[chat_id]) < 2:
                await update.message.reply_text("⚠️ Jawaban benar, tapi poin tidak bertambah karena minimal harus ada 2 pemain aktif agar tidak curang!")
            else:
                uid = str(user.id)
                if uid not in db['users']: db['users'][uid] = {"name": user.first_name, "pts": 0}
                db['users'][uid]['pts'] += 10
                save_db()
                
                top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:3]
                lb = "\n".join([f"{i+1}. {u[1]['name']} ({u[1]['pts']} pts)" for i, u in enumerate(top)])
                await update.message.reply_text(f"🎯 **{user.first_name} BENAR!** (+10 Pts)\n\n🏆 **TOP GLOBAL:**\n{lb}")

            current_games[chat_id]['answered'] = True
            await asyncio.sleep(3)
            await send_question(context, chat_id, current_games[chat_id]['cat'])

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.ALL, handle_msg))
    app.run_polling()

if __name__ == '__main__':
    main()

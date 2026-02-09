import asyncio
import json
import os
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Setup Logging agar kita tahu kalau ada error
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
# Pastikan ADMIN_ID dikonversi ke INT dengan benar
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except:
    ADMIN_ID = 0

DATA_FILE = 'quiz_data.json'

def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {
        "users": {}, 
        "questions": {"Umum": [{"q": "Ibukota Indonesia", "h": "J__a__a", "a": "jakarta"}]}, 
        "ads_text": "Iklan belum diset. Klik /admin untuk mengatur.",
        "ads_photo": None
    }

db = load_db()

def save_db():
    with open(DATA_FILE, 'w') as f:
        json.dump(db, f, indent=4)

current_games = {} 
group_players = {}

# --- FUNGSI UTAMA GAME ---
async def send_question(context, chat_id, category):
    if chat_id not in current_games or current_games[chat_id].get('stopped'): return
    
    q_list = db['questions'].get(category, [])
    if not q_list: return
    
    q_data = random.choice(q_list)
    
    # UI Bersih tanpa markdown bintang/bold yang bikin error
    text = f"KATEGORI: {category}\n\nSoal: {q_data['q']}\nClue: {q_data['h']}\n\nWaktu: 15 detik!"
    
    kb = [[
        InlineKeyboardButton("Next", callback_data="game_skip"),
        InlineKeyboardButton("Stop", callback_data="game_stop")
    ]]

    msg = await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(kb))
    
    current_games[chat_id].update({
        "ans": q_data['a'].lower().strip(),
        "cat": category,
        "answered": False,
        "msg_id": msg.message_id
    })

    # Timer 15 Detik
    await asyncio.sleep(15)
    if chat_id in current_games and not current_games[chat_id]['answered'] and not current_games[chat_id].get('stopped'):
        await context.bot.send_message(chat_id, f"Waktu habis! Jawabannya: {q_data['a'].upper()}")
        await asyncio.sleep(2)
        await send_question(context, chat_id, category)

# --- HANDLER SEMUA PESAN (DETEKSI JAWABAN & ADMIN) ---
async def global_msg_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    text = (update.message.text or "").lower().strip()

    # 1. CEK COMMAND /START & /ADMIN MANUAL (Kadang CommandHandler telat respon)
    if text == "/start":
        if update.effective_chat.type == "private":
            kb = [[InlineKeyboardButton("Tambahkan ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
            intro = f"PENGUMUMAN:\n{db['ads_text']}\n\nPerintah:\n/start - Pilih kategori\n/admin - Panel admin"
            if db.get('ads_photo'):
                return await update.message.reply_photo(photo=db['ads_photo'], caption=intro, reply_markup=InlineKeyboardMarkup(kb))
            return await update.message.reply_text(intro, reply_markup=InlineKeyboardMarkup(kb))
        else:
            keyboard = [[InlineKeyboardButton(f"Kategori {cat}", callback_data=f"start_{cat}")] for cat in db['questions'].keys()]
            return await update.message.reply_text("PILIH KATEGORI SOAL:", reply_markup=InlineKeyboardMarkup(keyboard))

    if text == "/admin":
        if uid != ADMIN_ID:
            return await update.message.reply_text(f"ID Anda {uid} tidak terdaftar sebagai ADMIN_ID ({ADMIN_ID})")
        kb = [
            [InlineKeyboardButton("Send DB", callback_data='adm_send_db')],
            [InlineKeyboardButton("Set Iklan", callback_data='adm_set_ads')],
            [InlineKeyboardButton("Tambah Soal", callback_data='adm_add_ques')]
        ]
        return await update.message.reply_text("ADMIN PANEL", reply_markup=InlineKeyboardMarkup(kb))

    # 2. CEK INPUT ADMIN (SEDANG SET IKLAN/SOAL)
    state = context.user_data.get('state')
    if state and uid == ADMIN_ID:
        if state == 'wait_ads':
            db['ads_text'] = update.message.caption or update.message.text
            if update.message.photo: db['ads_photo'] = update.message.photo[-1].file_id
            save_db(); context.user_data['state'] = None
            return await update.message.reply_text("Iklan Updated!")
        elif state == 'wait_q':
            try:
                k, s, c, j = [x.strip() for x in update.message.text.split("|")]
                if k not in db['questions']: db['questions'][k] = []
                db['questions'][k].append({"q":s, "h":c, "a":j})
                save_db(); context.user_data['state'] = None
                return await update.message.reply_text(f"Soal masuk ke {k}!")
            except: return await update.message.reply_text("Gagal! Gunakan format: Kategori | Soal | Clue | Jawaban")

    # 3. CEK JAWABAN GAME
    if chat_id in current_games and not current_games[chat_id]['answered']:
        if text == current_games[chat_id]['ans']:
            current_games[chat_id]['answered'] = True
            
            # Cek 2 Pemain
            if chat_id not in group_players: group_players[chat_id] = set()
            group_players[chat_id].add(uid)
            
            if len(group_players[chat_id]) < 2:
                await update.message.reply_text(f"Benar {update.effective_user.first_name}! (Butuh 1 orang lagi biar poin cair)")
            else:
                s_uid = str(uid)
                if s_uid not in db['users']: db['users'][s_uid] = {"name": update.effective_user.first_name, "pts": 0}
                db['users'][s_uid]['pts'] += 10
                save_db()
                
                top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:3]
                lb = "\n".join([f"{i+1}. {u[1]['name']} - {u[1]['pts']} Pts" for i, u in enumerate(top)])
                await update.message.reply_text(f"BENAR! {update.effective_user.first_name} +10 Poin.\n\nLEADERBOARD GLOBAL:\n{lb}")
            
            await asyncio.sleep(2)
            await send_question(context, chat_id, current_games[chat_id]['cat'])

# --- CALLBACK HANDLER ---
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id
    uid = query.from_user.id

    if data.startswith('adm_'):
        if uid != ADMIN_ID: return await query.answer("Bukan Admin!")
        if data == 'adm_send_db':
            save_db()
            await query.message.reply_document(open(DATA_FILE, 'rb'))
        elif data == 'adm_set_ads':
            context.user_data['state'] = 'wait_ads'; await query.message.reply_text("Kirim Foto + Caption!")
        elif data == 'adm_add_ques':
            context.user_data['state'] = 'wait_q'; await query.message.reply_text("Format: Kategori | Soal | Clue | Jawaban")
    
    elif data.startswith('start_'):
        cat = data.split('_')[1]
        current_games[chat_id] = {"stopped": False, "answered": False, "cat": cat}
        await query.message.delete()
        await send_question(context, chat_id, cat)
    
    elif data == "game_skip":
        if chat_id in current_games:
            current_games[chat_id]['answered'] = True
            await query.message.reply_text("Skip!")
            await send_question(context, chat_id, current_games[chat_id]['cat'])
            
    elif data == "game_stop":
        if chat_id in current_games:
            current_games[chat_id]['stopped'] = True
            current_games.pop(chat_id, None)
            await query.message.reply_text("Stop!")

    await query.answer()

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.ALL, global_msg_handler)) # SEMUA MASUK SINI
    print("Bot Berjalan...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

import asyncio
import json
import os
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Logging setup
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except:
    ADMIN_ID = 0

DATA_FILE = 'quiz_data.json'

# --- DATABASE ---
def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {
        "users": {}, 
        "questions": {"Umum": [{"q": "Ibukota Indonesia", "h": "J__a__a", "a": "jakarta"}]}, 
        "ads_text": "Iklan belum diset. Klik /admin.",
        "ads_photo": None
    }

db = load_db()

def save_db():
    with open(DATA_FILE, 'w') as f:
        json.dump(db, f, indent=4)

# Dictionary untuk menyimpan data game DAN task timer
# Format: {chat_id: {"ans": "...", "task": asyncio.Task, "cat": "..."}}
current_games = {} 
group_players = {}

# --- FUNGSI TIMER (BACKGROUND TASK) ---
async def quiz_timer(context, chat_id, category, correct_ans):
    try:
        # Tunggu 15 Detik
        await asyncio.sleep(15)
        
        # Jika kode sampai sini, berarti waktu habis (task tidak dibatalkan)
        if chat_id in current_games:
            # Hapus game dari memori dulu biar gak double
            del current_games[chat_id]
            
            await context.bot.send_message(chat_id, f"Waktu Habis! Jawabannya: {correct_ans.upper()}")
            await asyncio.sleep(2)
            # Lanjut soal berikutnya
            await send_question(context, chat_id, category)
            
    except asyncio.CancelledError:
        # Task dibatalkan karena ada yang jawab benar atau klik Next/Stop
        pass

# --- ENGINE UTAMA ---
async def send_question(context, chat_id, category):
    # Bersihkan task lama jika ada
    if chat_id in current_games and 'task' in current_games[chat_id]:
        current_games[chat_id]['task'].cancel()

    q_list = db['questions'].get(category, [])
    if not q_list: return await context.bot.send_message(chat_id, "Soal di kategori ini habis/kosong.")
    
    q_data = random.choice(q_list)
    ans_clean = q_data['a'].lower().strip()
    
    text = f"KATEGORI: {category}\n\nSoal: {q_data['q']}\nClue: {q_data['h']}\n\nWaktu: 15 detik"
    kb = [[InlineKeyboardButton("Next", callback_data="game_skip"), 
           InlineKeyboardButton("Stop", callback_data="game_stop")]]

    await context.bot.send_message(chat_id, text, reply_markup=InlineKeyboardMarkup(kb))

    # MULAI TIMER DI BACKGROUND (PENTING BIAR GAK BLOKIR JAWABAN)
    task = asyncio.create_task(quiz_timer(context, chat_id, category, ans_clean))
    
    # Simpan data game & task
    current_games[chat_id] = {
        "ans": ans_clean,
        "cat": category,
        "task": task
    }

# --- HANDLER PESAN (JAWABAN & ADMIN) ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    
    msg = update.message
    text = (msg.text or "").lower().strip()
    uid = update.effective_user.id
    chat_id = update.effective_chat.id

    # --- 1. COMMANDS ---
    if text == "/start":
        if update.effective_chat.type == "private":
            intro = f"INFO:\n{db['ads_text']}\n\nPerintah:\n/start - Main (di grup)\n/admin - Menu Admin"
            kb = [[InlineKeyboardButton("Tambah ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
            if db.get('ads_photo'):
                return await msg.reply_photo(photo=db['ads_photo'], caption=intro, reply_markup=InlineKeyboardMarkup(kb))
            return await msg.reply_text(intro, reply_markup=InlineKeyboardMarkup(kb))
        else:
            kb = [[InlineKeyboardButton(f"Kategori {c}", callback_data=f"start_{c}")] for c in db['questions'].keys()]
            return await msg.reply_text("PILIH KATEGORI:", reply_markup=InlineKeyboardMarkup(kb))

    if text == "/admin":
        if uid != ADMIN_ID:
            return await msg.reply_text(f"Gagal. ID Telegram kamu: {uid}\nMasukkan angka ini ke ADMIN_ID di Railway.")
        kb = [[InlineKeyboardButton("Send DB", callback_data='adm_send_db')],
              [InlineKeyboardButton("Set Iklan", callback_data='adm_set_ads')],
              [InlineKeyboardButton("Tambah Soal", callback_data='adm_add_ques')]]
        return await msg.reply_text("ADMIN PANEL", reply_markup=InlineKeyboardMarkup(kb))

    # --- 2. INPUT ADMIN ---
    state = context.user_data.get('state')
    if state and uid == ADMIN_ID:
        if state == 'wait_ads':
            db['ads_text'] = msg.caption or msg.text
            if msg.photo: db['ads_photo'] = msg.photo[-1].file_id
            save_db(); context.user_data['state'] = None
            return await msg.reply_text("Iklan OK!")
        elif state == 'wait_q':
            try:
                k, s, c, j = [x.strip() for x in msg.text.split("|")]
                if k not in db['questions']: db['questions'][k] = []
                db['questions'][k].append({"q":s, "h":c, "a":j})
                save_db(); context.user_data['state'] = None
                return await msg.reply_text(f"Soal OK di {k}!")
            except: return await msg.reply_text("Salah format!")

    # --- 3. DETEKSI JAWABAN ---
    # Cek apakah ada game aktif di chat ini
    if chat_id in current_games:
        game_data = current_games[chat_id]
        
        if text == game_data['ans']:
            # PENTING: Matikan timer karena sudah terjawab!
            game_data['task'].cancel()
            cat = game_data['cat']
            
            # Cek User Unik (Anti Solo)
            if chat_id not in group_players: group_players[chat_id] = set()
            group_players[chat_id].add(uid)

            if len(group_players[chat_id]) < 2:
                await msg.reply_text(f"Benar {update.effective_user.first_name}! (Butuh 1 orang lagi biar poin cair)")
            else:
                s_uid = str(uid)
                if s_uid not in db['users']: db['users'][s_uid] = {"name": update.effective_user.first_name, "pts": 0}
                db['users'][s_uid]['pts'] += 10
                save_db()
                
                # Leaderboard Simple
                top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:3]
                lb = "\n".join([f"{i+1}. {u[1]['name']} - {u[1]['pts']}" for i, u in enumerate(top)])
                await msg.reply_text(f"BENAR! {update.effective_user.first_name} +10 Pts.\n\nTOP GLOBAL:\n{lb}")
            
            # Hapus data game lama
            del current_games[chat_id]
            
            # Jeda dikit, lalu kirim soal baru
            await asyncio.sleep(2)
            await send_question(context, chat_id, cat)

# --- CALLBACK (TOMBOL) ---
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    cid = q.message.chat_id

    # Handle Admin
    if d.startswith('adm_'):
        if q.from_user.id != ADMIN_ID: return await q.answer("Bukan Admin")
        if d == 'adm_send_db':
            save_db(); await q.message.reply_document(open(DATA_FILE, 'rb'))
        elif d == 'adm_set_ads':
            context.user_data['state'] = 'wait_ads'; await q.message.reply_text("Kirim Foto+Teks")
        elif d == 'adm_add_ques':
            context.user_data['state'] = 'wait_q'; await q.message.reply_text("Format: Kat|Soal|Clue|Jawab")
    
    # Handle Start Game
    elif d.startswith('start_'):
        cat = d.split('_')[1]
        await q.message.delete()
        await send_question(context, cid, cat)
    
    # Handle Next/Stop
    elif d in ["game_skip", "game_stop"]:
        if cid in current_games:
            # Matikan timer
            current_games[cid]['task'].cancel()
            cat = current_games[cid]['cat']
            
            if d == "game_skip":
                await q.message.reply_text("Next soal...")
                del current_games[cid]
                await send_question(context, cid, cat)
            else:
                await q.message.reply_text("Game Stop.")
                del current_games[cid]
        else:
            await q.message.reply_text("Game sudah berhenti.")
            
    await q.answer()

def main():
    if not TOKEN:
        print("ERROR: TOKEN KOSONG")
        return
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CallbackQueryHandler(on_callback))
    # Filter Text & Photo biar mencakup semua input
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_msg))
    
    print("Bot Siap...")
    app.run_polling()

if __name__ == '__main__':
    main()

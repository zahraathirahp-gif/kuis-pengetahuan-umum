import asyncio
import json
import os
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- LOGGING ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- KONFIGURASI ---
TOKEN = os.getenv("BOT_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except:
    ADMIN_ID = 0

DATA_FILE = 'quiz_data.json'

# --- DATABASE ENGINE ---
def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                # Pastikan key 'groups' ada untuk fitur broadcast
                if 'groups' not in data: data['groups'] = []
                return data
        except: pass
    return {
        "users": {}, 
        "groups": [], # List ID grup untuk broadcast
        "questions": {
            "Umum": [{"q": "Ibukota Indonesia", "h": "J__a__a", "a": "jakarta"}],
            "Hewan": [{"q": "Hewan leher panjang", "h": "J__a__h", "a": "jerapah"}]
        }, 
        "ads_text": "Pasang Iklan Disini. Hubungi Admin.",
        "ads_photo": None
    }

db = load_db()

def save_db():
    with open(DATA_FILE, 'w') as f:
        json.dump(db, f, indent=4)

# Fungsi hitung pangkat berdasarkan poin
def get_rank(pts):
    if pts < 50: return "Warga Biasa"
    if pts < 200: return "Pendekar Kuis"
    if pts < 1000: return "Sepuh"
    return "👑 RAJA KUIS"

# Penyimpanan State Game Sementara (RAM)
current_games = {} 
group_players = {}

# --- SISTEM TIMER (TASK BACKGROUND) ---
async def quiz_timer(context, chat_id, category, correct_ans):
    try:
        await asyncio.sleep(15) # Waktu 15 Detik
        if chat_id in current_games:
            del current_games[chat_id]
            await context.bot.send_message(chat_id, f"⌛ Waktu Habis! Jawabannya: {correct_ans.upper()}")
            await asyncio.sleep(2)
            await send_question(context, chat_id, category)
    except asyncio.CancelledError:
        pass # Timer dibatalkan karena ada yg jawab benar/skip

# --- LOGIKA GAME ---
async def send_question(context, chat_id, category):
    # Cancel timer lama jika ada
    if chat_id in current_games and 'task' in current_games[chat_id]:
        current_games[chat_id]['task'].cancel()

    q_list = db['questions'].get(category, [])
    if not q_list: return await context.bot.send_message(chat_id, "Soal habis/kosong.")
    
    q_data = random.choice(q_list)
    ans_clean = q_data['a'].lower().strip()
    
    # UI Soal Bersih
    text = f"🎮 **{category}**\n\n❓ {q_data['q']}\n💡 {q_data['h']}"
    kb = [[InlineKeyboardButton("⏭ Next", callback_data="game_skip"), 
           InlineKeyboardButton("🛑 Stop", callback_data="game_stop")]]

    await context.bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    # Jalanin Timer di Background
    task = asyncio.create_task(quiz_timer(context, chat_id, category, ans_clean))
    
    current_games[chat_id] = {
        "ans": ans_clean,
        "cat": category,
        "task": task
    }

# --- HANDLER PESAN UTAMA ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    
    msg = update.message
    text = (msg.text or "").lower().strip()
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    # 1. AUTO-SAVE GROUP ID (Untuk Broadcast)
    if chat_type in ["group", "supergroup"]:
        if chat_id not in db['groups']:
            db['groups'].append(chat_id)
            save_db()

    # 2. COMMAND START
    if text == "/start":
        if chat_type == "private":
            intro = f"🤖 **BOT KUIS GROUP**\n\n📢 INFO:\n{db['ads_text']}\n\nMasukkan bot ini ke grup kamu untuk bermain & rebut tahta Top Global!"
            kb = [[InlineKeyboardButton("➕ Tambah ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
            if db.get('ads_photo'):
                return await msg.reply_photo(photo=db['ads_photo'], caption=intro, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
            return await msg.reply_text(intro, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        else:
            # Di Grup: Tampilkan tombol Start agar tidak spam
            kb = [[InlineKeyboardButton("▶️ Mulai Game", callback_data="menu_start")]]
            return await msg.reply_text("Siap bermain?", reply_markup=InlineKeyboardMarkup(kb))
            
    # 3. COMMAND LEADERBOARD / TOP
    if text in ["/top", "/rank", "/leaderboard"]:
        top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:10]
        lb_text = "🏆 **TOP 10 GLOBAL** 🏆\n\n"
        for i, (userid, data) in enumerate(top, 1):
            rank_name = get_rank(data['pts'])
            lb_text += f"{i}. {data['name']} ({rank_name}) — {data['pts']} Pts\n"
        return await msg.reply_text(lb_text, parse_mode='Markdown')

    # 4. COMMAND ADMIN (PROTECTED)
    if text == "/admin":
        if uid != ADMIN_ID: return # Silent (User biasa tidak dpt respon)
        
        kb = [
            [InlineKeyboardButton("📢 Broadcast ke Semua Grup", callback_data='adm_broadcast')],
            [InlineKeyboardButton("📤 Backup Database", callback_data='adm_send_db')],
            [InlineKeyboardButton("🖼 Set Iklan", callback_data='adm_set_ads')],
            [InlineKeyboardButton("➕ Tambah Soal", callback_data='adm_add_ques')]
        ]
        return await msg.reply_text("🛠 **PANEL ADMIN**", reply_markup=InlineKeyboardMarkup(kb))

    # 5. INPUT STATE ADMIN (Broadcast/Add Soal/Iklan)
    state = context.user_data.get('state')
    if state and uid == ADMIN_ID:
        if state == 'wait_ads':
            db['ads_text'] = msg.caption or msg.text
            if msg.photo: db['ads_photo'] = msg.photo[-1].file_id
            save_db(); context.user_data['state'] = None
            return await msg.reply_text("✅ Iklan Diperbarui!")
            
        elif state == 'wait_q':
            try:
                k, s, c, j = [x.strip() for x in msg.text.split("|")]
                if k not in db['questions']: db['questions'][k] = []
                db['questions'][k].append({"q":s, "h":c, "a":j})
                save_db(); context.user_data['state'] = None
                return await msg.reply_text(f"✅ Soal ditambah ke {k}!")
            except: return await msg.reply_text("❌ Format Salah! Gunakan: Kategori|Soal|Clue|Jawaban")
            
        elif state == 'wait_bc':
            # Broadcast Logic
            context.user_data['state'] = None
            count = 0
            fail = 0
            status_msg = await msg.reply_text("⏳ Mengirim broadcast...")
            
            for gid in db['groups']:
                try:
                    await msg.copy(chat_id=gid)
                    count += 1
                    await asyncio.sleep(0.1) # Anti flood
                except:
                    fail += 1
                    # Opsional: Hapus grup mati dari DB -> db['groups'].remove(gid)
            
            save_db()
            return await status_msg.edit_text(f"✅ Broadcast Selesai!\nSukses: {count} Grup\nGagal: {fail} Grup")

    # 6. DETEKSI JAWABAN GAME
    if chat_id in current_games:
        game = current_games[chat_id]
        if text == game['ans']:
            game['task'].cancel() # Stop Timer
            
            # Anti Solo Player (Butuh 2 org di grup)
            if chat_id not in group_players: group_players[chat_id] = set()
            group_players[chat_id].add(uid)

            msg_response = ""
            if len(group_players[chat_id]) < 2:
                msg_response = f"✅ **{update.effective_user.first_name}** Benar! (Poin pending, ajak teman lain jawab)."
            else:
                s_uid = str(uid)
                if s_uid not in db['users']: db['users'][s_uid] = {"name": update.effective_user.first_name, "pts": 0}
                
                # Tambah Poin
                added_pts = 10
                db['users'][s_uid]['pts'] += added_pts
                current_pts = db['users'][s_uid]['pts']
                save_db()
                
                rank = get_rank(current_pts)
                msg_response = f"🎯 **{update.effective_user.first_name}** BENAR! (+10)\nTotal: {current_pts} ({rank})"

            await msg.reply_text(msg_response, parse_mode='Markdown')
            
            del current_games[chat_id]
            await asyncio.sleep(2)
            await send_question(context, chat_id, game['cat'])

# --- CALLBACK HANDLER ---
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    cid = q.message.chat_id
    uid = q.from_user.id

    # ADMIN MENU
    if d.startswith('adm_'):
        if uid != ADMIN_ID: return await q.answer("❌ Akses Ditolak", show_alert=True)
        
        if d == 'adm_send_db':
            save_db(); await q.message.reply_document(open(DATA_FILE, 'rb'))
        elif d == 'adm_set_ads':
            context.user_data['state'] = 'wait_ads'; await q.message.reply_text("Kirim Foto + Caption Iklan:")
        elif d == 'adm_add_ques':
            context.user_data['state'] = 'wait_q'; await q.message.reply_text("Format: Kategori|Soal|Clue|Jawaban")
        elif d == 'adm_broadcast':
            context.user_data['state'] = 'wait_bc'; await q.message.reply_text("📢 Kirim pesan (Teks/Foto) yang ingin disebarkan ke semua grup:")
    
    # USER MENU START
    elif d == 'menu_start':
        kb = [[InlineKeyboardButton(f"📂 {c}", callback_data=f"start_{c}")] for c in db['questions'].keys()]
        await q.message.edit_text("🎮 **PILIH KATEGORI SOAL:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        
    # GAME START
    elif d.startswith('start_'):
        cat = d.split('_')[1]
        await q.message.delete()
        await send_question(context, cid, cat)
    
    # GAME CONTROL
    elif d in ["game_skip", "game_stop"]:
        if cid in current_games:
            current_games[cid]['task'].cancel() # Stop timer
            cat = current_games[cid]['cat']
            
            if d == "game_skip":
                await q.message.reply_text("⏩ Soal dilewati...")
                del current_games[cid]
                await send_question(context, cid, cat)
            else:
                await q.message.reply_text("🛑 Permainan Berhenti.")
                del current_games[cid]
        else:
            await q.answer("Game sudah berhenti/dijawab.", show_alert=True)
            
    await q.answer()

# --- MAIN ---
def main():
    if not TOKEN:
        print("ERROR: TOKEN/ADMIN_ID belum di-set!")
        return
    
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_msg))
    
    print("Bot Berjalan Stabil...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

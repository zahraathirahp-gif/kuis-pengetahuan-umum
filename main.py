import asyncio
import json
import os
import random
import logging
import time
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- LOGGING SETUP ---
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

# --- KONFIGURASI ---
TOKEN = os.getenv("BOT_TOKEN")
try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
except:
    ADMIN_ID = 0

DATA_FILE = 'quiz_data.json'

# --- DATABASE & HELPER ---
def load_db():
    default_db = {
        "users": {}, 
        "groups": [],
        "questions": {
            "Umum": [{"q": "Ibukota Indonesia", "a": "jakarta"}],
            "Hewan": [{"q": "Hewan leher panjang", "a": "jerapah"}]
        }, 
        "ads_text": "Iklan Kosong. Hubungi Admin.",
        "ads_photo": None
    }
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                data = json.load(f)
                # Merge data lama dengan struktur baru jika ada update
                for k, v in default_db.items():
                    if k not in data: data[k] = v
                return data
        except: pass
    return default_db

db = load_db()

def save_db():
    with open(DATA_FILE, 'w') as f:
        json.dump(db, f, indent=4)

def get_rank(pts):
    if pts < 50: return "Warga Biasa"
    if pts < 200: return "Pendekar Kuis"
    if pts < 1000: return "Sepuh"
    return "👑 RAJA KUIS"

# Format Clue: "jakarta" -> "J _ _ _ _ T A"
def format_hint(answer, revealed_indices=None):
    answer = answer.upper()
    if revealed_indices is None:
        # Default: Buka huruf pertama dan terakhir
        revealed_indices = {0, len(answer)-1}
    
    chars = []
    for i, char in enumerate(answer):
        if char == " ":
            chars.append("  ") # Spasi ganda antar kata
        elif i in revealed_indices:
            chars.append(char)
        else:
            chars.append("_")
    
    return " ".join(chars) # Gabung dengan spasi biar rapi: P _ _ A

# --- STATE MANAGEMENT ---
# current_games structure: 
# {chat_id: {"ans": "...", "cat": "...", "task": Task, "start_time": float, "revealed": set()}}
current_games = {} 
group_players = {}

# --- AUTO COMMANDS (POST INIT) ---
async def post_init(application: Application):
    # Ini yang bikin menu muncul pas ketik /
    await application.bot.set_my_commands([
        BotCommand("start", "Mulai Game / Menu"),
        BotCommand("top", "Lihat Leaderboard"),
        BotCommand("hint", "Beli Huruf (-5 Poin)"),
        BotCommand("stop", "Hentikan Game"),
        BotCommand("admin", "Panel Admin (Hidden)")
    ])

# --- ENGINE GAME ---
async def quiz_timer(context, chat_id, category, correct_ans):
    try:
        await asyncio.sleep(20) # Waktu main 20 detik (lebih santai dikit)
        if chat_id in current_games:
            del current_games[chat_id]
            await context.bot.send_message(chat_id, f"⌛ Waktu Habis!\nJawabannya: **{correct_ans.upper()}**", parse_mode='Markdown')
            await asyncio.sleep(2)
            await send_question(context, chat_id, category)
    except asyncio.CancelledError:
        pass

async def send_question(context, chat_id, category):
    # Bersihkan task lama
    if chat_id in current_games and 'task' in current_games[chat_id]:
        current_games[chat_id]['task'].cancel()

    q_list = db['questions'].get(category, [])
    if not q_list: return await context.bot.send_message(chat_id, "Soal habis.")
    
    q_data = random.choice(q_list)
    ans_clean = q_data['a'].lower().strip()
    
    # Init hint awal (Huruf depan & belakang)
    initial_reveal = {0, len(ans_clean)-1}
    hint_text = format_hint(ans_clean, initial_reveal)
    
    text = f"🎮 **{category}**\n\n❓ {q_data['q']}\n🔤 Clue: `{hint_text}`"
    
    kb = [[InlineKeyboardButton("⏭ Next", callback_data="game_skip"), 
           InlineKeyboardButton("🛑 Stop", callback_data="game_stop")]]

    msg = await context.bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    task = asyncio.create_task(quiz_timer(context, chat_id, category, ans_clean))
    
    current_games[chat_id] = {
        "ans": ans_clean,
        "cat": category,
        "task": task,
        "start_time": time.time(),
        "revealed": initial_reveal,
        "msg_id": msg.message_id
    }

# --- HANDLER LOGIC ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    
    msg = update.message
    text = (msg.text or "").lower().strip()
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    chat_type = update.effective_chat.type

    # 1. DB GROUP SAVER
    if chat_type in ["group", "supergroup"] and chat_id not in db['groups']:
        db['groups'].append(chat_id); save_db()

    # 2. COMMANDS
    if text == "/start":
        if chat_type == "private":
            intro = f"🤖 **QUIZ BOT**\n\n📢 {db['ads_text']}\n\nPerintah:\n/start - Main\n/top - Ranking\n/hint - Bantuan"
            kb = [[InlineKeyboardButton("➕ Tambah ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
            if db.get('ads_photo'):
                return await msg.reply_photo(db['ads_photo'], caption=intro, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
            return await msg.reply_text(intro, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        else:
            kb = [[InlineKeyboardButton("▶️ Mulai Game", callback_data="menu_start")]]
            return await msg.reply_text("Siap main?", reply_markup=InlineKeyboardMarkup(kb))

    elif text in ["/top", "/rank", "/leaderboard"]:
        top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:10]
        t = "🏆 **TOP 10 GLOBAL** 🏆\n\n"
        for i, (u, d) in enumerate(top, 1):
            t += f"{i}. {d['name']} - {d['pts']} ({get_rank(d['pts'])})\n"
        return await msg.reply_text(t, parse_mode='Markdown')

    elif text == "/hint":
        if chat_id in current_games:
            s_uid = str(uid)
            user_pts = db['users'].get(s_uid, {}).get('pts', 0)
            
            if user_pts < 5:
                return await msg.reply_text("❌ Poin kurang! Butuh 5 poin buat beli hint.")
            
            # Kurangi Poin
            db['users'][s_uid]['pts'] -= 5
            save_db()
            
            # Buka 1 huruf acak
            game = current_games[chat_id]
            ans = game['ans']
            hidden_indices = [i for i in range(len(ans)) if i not in game['revealed'] and ans[i] != " "]
            
            if not hidden_indices:
                return await msg.reply_text("Semua huruf sudah terbuka!")
            
            new_idx = random.choice(hidden_indices)
            game['revealed'].add(new_idx)
            
            new_hint = format_hint(ans, game['revealed'])
            await msg.reply_text(f"🔓 Hint Dibeli oleh {update.effective_user.first_name} (-5 Poin)\nClue: `{new_hint}`", parse_mode='Markdown')
        else:
            await msg.reply_text("Sedang tidak ada game.")
        return

    # 3. ADMIN ZONE
    if text == "/admin": 
        if uid != ADMIN_ID: return 
        kb = [
            [InlineKeyboardButton("📢 Broadcast", callback_data='adm_broadcast')],
            [InlineKeyboardButton("📤 Backup DB", callback_data='adm_send_db')],
            [InlineKeyboardButton("🖼 Set Iklan", callback_data='adm_set_ads')],
            [InlineKeyboardButton("➕ Tambah Soal", callback_data='adm_add_ques')]
        ]
        return await msg.reply_text("🛠 **ADMIN PANEL**", reply_markup=InlineKeyboardMarkup(kb))

    # 4. ADMIN INPUT HANDLER
    state = context.user_data.get('state')
    if state and uid == ADMIN_ID:
        if state == 'wait_ads':
            db['ads_text'] = msg.caption or msg.text
            if msg.photo: db['ads_photo'] = msg.photo[-1].file_id
            save_db(); context.user_data['state'] = None
            return await msg.reply_text("✅ Iklan OK")
        elif state == 'wait_q':
            try:
                # Format simple: Kat|Soal|Jawaban (Clue otomatis dari jawaban)
                k, s, j = [x.strip() for x in msg.text.split("|")]
                if k not in db['questions']: db['questions'][k] = []
                db['questions'][k].append({"q":s, "a":j})
                save_db(); context.user_data['state'] = None
                return await msg.reply_text(f"✅ Soal OK! Clue otomatis: {format_hint(j)}")
            except: return await msg.reply_text("❌ Format: Kategori | Soal | Jawaban")
        elif state == 'wait_bc':
            context.user_data['state'] = None
            s = await msg.reply_text("⏳ Sending...")
            n = 0
            for g in db['groups']:
                try: 
                    await msg.copy(chat_id=g)
                    n += 1
                    await asyncio.sleep(0.1)
                except: pass
            return await s.edit_text(f"✅ Terkirim ke {n} grup.")

    # 5. ANSWER CHECKER
    if chat_id in current_games:
        game = current_games[chat_id]
        if text == game['ans']:
            game['task'].cancel()
            
            # Hitung Speed Bonus
            time_taken = time.time() - game['start_time']
            bonus = 5 if time_taken < 5 else 0
            base_pts = 10
            total_pts = base_pts + bonus

            if chat_id not in group_players: group_players[chat_id] = set()
            group_players[chat_id].add(uid)

            # Cek User DB
            s_uid = str(uid)
            if s_uid not in db['users']: db['users'][s_uid] = {"name": update.effective_user.first_name, "pts": 0}

            # Simpan Poin (Selalu cair biar seru, tapi ada notif solo player)
            db['users'][s_uid]['pts'] += total_pts
            save_db()

            rank = get_rank(db['users'][s_uid]['pts'])
            bonus_text = "⚡ SPEED BONUS! " if bonus > 0 else ""
            
            msg_succ = f"🎯 **{update.effective_user.first_name}** BENAR!\n"
            msg_succ += f"💰 +{total_pts} Poin {bonus_text}\n"
            msg_succ += f"🏅 Pangkat: {rank}"

            await msg.reply_text(msg_succ, parse_mode='Markdown')
            
            del current_games[chat_id]
            await asyncio.sleep(2)
            await send_question(context, chat_id, game['cat'])

# --- CALLBACKS ---
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    q = update.callback_query
    d = q.data
    cid = q.message.chat_id
    uid = q.from_user.id

    if d.startswith('adm_'):
        if uid != ADMIN_ID: return await q.answer("No Access", show_alert=True)
        if d == 'adm_send_db':
            save_db(); await q.message.reply_document(open(DATA_FILE, 'rb'))
        elif d == 'adm_set_ads':
            context.user_data['state'] = 'wait_ads'; await q.message.reply_text("Kirim Foto + Caption")
        elif d == 'adm_add_ques':
            context.user_data['state'] = 'wait_q'; await q.message.reply_text("Format: Kategori | Soal | Jawaban")
        elif d == 'adm_broadcast':
            context.user_data['state'] = 'wait_bc'; await q.message.reply_text("Kirim pesan broadcast:")
    
    elif d == 'menu_start':
        kb = [[InlineKeyboardButton(f"📂 {c}", callback_data=f"start_{c}")] for c in db['questions'].keys()]
        await q.message.edit_text("🎮 **PILIH KATEGORI:**", parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    elif d.startswith('start_'):
        cat = d.split('_')[1]
        await q.message.delete()
        await send_question(context, cid, cat)
    
    elif d == "game_skip":
        if cid in current_games:
            current_games[cid]['task'].cancel()
            cat = current_games[cid]['cat']
            await q.message.reply_text("⏩ Skip...")
            del current_games[cid]
            await send_question(context, cid, cat)
            
    elif d == "game_stop":
        if cid in current_games:
            current_games[cid]['task'].cancel()
            del current_games[cid]
            await q.message.reply_text("🛑 Game Berhenti.")
    
    await q.answer()

# --- MAIN RUNNER ---
def main():
    if not TOKEN:
        print("ERROR: TOKEN NOT FOUND")
        return
    
    app = Application.builder().token(TOKEN).post_init(post_init).build()
    
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.TEXT | filters.PHOTO, handle_msg))
    
    print("Bot Berjalan dengan Fitur Lengkap...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

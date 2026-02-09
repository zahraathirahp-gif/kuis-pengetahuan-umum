import asyncio
import json
import os
import random
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
DATA_FILE = 'quiz_data.json'import asyncio
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
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {
        "users": {}, 
        "questions": {"Umum": [{"q": "Menara miring di Italia", "h": "p__a", "a": "pisa"}]}, 
        "ads_text": "PASANG IKLAN DISINI @admin",
        "ads_photo": None
    }

db = load_db()

def save_db():
    with open(DATA_FILE, 'w') as f:
        json.dump(db, f, indent=4)

current_games = {} 
group_players = {}

# --- UI IKLAN (TAMPILAN BOT) ---
def get_bot_intro():
    text = f"🤖 **TEBAK-TEBAKAN BOT**\n"
    text += f"━━━━━━━━━━━━━━\n"
    text += f"📢 {db['ads_text']}\n"
    text += f"━━━━━━━━━━━━━━\n\n"
    text += "Klik tombol di bawah untuk mulai bermain!"
    return text

# --- ADMIN PANEL ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    # Cek ID dengan teliti
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text(f"❌ Akses Ditolak. ID Anda: {update.effective_user.id}")
    
    keyboard = [
        [InlineKeyboardButton("📤 Send DB", callback_data='adm_send_db')],
        [InlineKeyboardButton("🖼 Set Tampilan Iklan", callback_data='adm_set_ads')],
        [InlineKeyboardButton("➕ Tambah Soal", callback_data='adm_add_ques')]
    ]
    await update.message.reply_text("🛠 **ADMIN PANEL**", reply_markup=InlineKeyboardMarkup(keyboard))

# --- START HANDLER ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    
    if chat.type == "private":
        # Tampilan Iklan Utama ada di sini
        kb = [[InlineKeyboardButton("➕ Masukkan ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
        if db.get('ads_photo'):
            await update.message.reply_photo(photo=db['ads_photo'], caption=get_bot_intro(), parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
        else:
            await update.message.reply_text(get_bot_intro(), parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        # Di Grup: Pilih Kategori
        keyboard = [[InlineKeyboardButton(f"📁 {cat}", callback_data=f"start_{cat}")] for cat in db['questions'].keys()]
        await update.message.reply_text("🎮 **PILIH KATEGORI:**", reply_markup=InlineKeyboardMarkup(keyboard))

# --- QUIZ ENGINE ---
async def send_question(context, chat_id, category):
    if chat_id not in current_games or current_games[chat_id]['stopped']: return
    
    q_list = db['questions'].get(category, [])
    if not q_list: return
    
    q_data = random.choice(q_list)
    text = f"❓ **SOAL:** `{q_data['q']}`\n💡 **CLUE:** `{q_data['h']}`\n\n⏱ *Waktu: 15 Detik*"
    
    kb = [[
        InlineKeyboardButton("⏭ Next", callback_data="game_skip"),
        InlineKeyboardButton("🛑 Stop", callback_data="game_stop")
    ]]

    msg = await context.bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    
    current_games[chat_id].update({
        "ans": q_data['a'].lower().strip(),
        "cat": category,
        "answered": False,
        "msg_id": msg.message_id
    })

    await asyncio.sleep(15)
    if chat_id in current_games and not current_games[chat_id]['answered'] and not current_games[chat_id]['stopped']:
        await context.bot.send_message(chat_id, f"⌛ Habis! Jawabannya: *{q_data['a']}*")
        await asyncio.sleep(2)
        await send_question(context, chat_id, category)

# --- CALLBACK (TOMBOL) ---
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    chat_id = query.message.chat_id

    if data.startswith('adm_'):
        if query.from_user.id != ADMIN_ID: return await query.answer("Bukan Admin")
        if data == 'adm_send_db':
            save_db()
            await query.message.reply_document(open(DATA_FILE, 'rb'))
        elif data == 'adm_set_ads':
            context.user_data['state'] = 'wait_ads'
            await query.message.reply_text("Kirim Foto + Caption untuk iklan.")
        elif data == 'adm_add_ques':
            context.user_data['state'] = 'wait_q'
            await query.message.reply_text("Format: Kategori | Soal | Clue | Jawaban")

    elif data.startswith('start_'):
        cat = data.split('_')[1]
        current_games[chat_id] = {"stopped": False, "answered": False, "cat": cat}
        await query.message.delete()
        await send_question(context, chat_id, cat)

    elif data == "game_skip":
        if chat_id in current_games:
            current_games[chat_id]['answered'] = True
            await query.message.reply_text("⏭ Skip ke soal berikutnya...")
            await send_question(context, chat_id, current_games[chat_id]['cat'])

    elif data == "game_stop":
        if chat_id in current_games:
            current_games[chat_id]['stopped'] = True
            await query.message.reply_text("🛑 Permainan Berhenti.")
            del current_games[chat_id]
            
    await query.answer()

# --- DETEKSI JAWABAN & INPUT ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    msg_text = update.message.text.lower().strip()

    # Admin State
    state = context.user_data.get('state')
    if state and uid == ADMIN_ID:
        if state == 'wait_ads':
            db['ads_text'] = update.message.caption or update.message.text
            if update.message.photo: db['ads_photo'] = update.message.photo[-1].file_id
            save_db(); context.user_data['state'] = None
            await update.message.reply_text("✅ Iklan Diupdate!")
        elif state == 'wait_q':
            try:
                k, s, c, j = [x.strip() for x in update.message.text.split("|")]
                if k not in db['questions']: db['questions'][k] = []
                db['questions'][k].append({"q":s, "h":c, "a":j})
                save_db(); context.user_data['state'] = None
                await update.message.reply_text(f"✅ Soal masuk ke {k}!")
            except: await update.message.reply_text("Format salah!")
        return

    # Deteksi Jawaban di Grup
    if chat_id in current_games and not current_games[chat_id]['answered']:
        if msg_text == current_games[chat_id]['ans']:
            current_games[chat_id]['answered'] = True
            
            # Cek 2 Orang
            if chat_id not in group_players: group_players[chat_id] = set()
            group_players[chat_id].add(uid)
            
            if len(group_players[chat_id]) < 2:
                await update.message.reply_text(f"✅ Benar, tapi poin tak cair (butuh 2 orang aktif).")
            else:
                s_uid = str(uid)
                if s_uid not in db['users']: db['users'][s_uid] = {"name": update.effective_user.first_name, "pts": 0}
                db['users'][s_uid]['pts'] += 10
                save_db()
                
                # Top Global
                top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:3]
                lb = "\n".join([f"{i+1}. {u[1]['name']} - {u[1]['pts']}" for i, u in enumerate(top)])
                await update.message.reply_text(f"🎯 **{update.effective_user.first_name} BENAR!** (+10)\n\n🏆 **TOP GLOBAL:**\n{lb}")

            await asyncio.sleep(2)
            await send_question(context, chat_id, current_games[chat_id]['cat'])

def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.ChatType.GROUPS & filters.TEXT & ~filters.COMMAND, handle_msg))
    app.add_handler(MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.PHOTO), handle_msg))
    app.run_polling()

if __name__ == '__main__':
    main()

def load_db():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, 'r') as f:
                return json.load(f)
        except: pass
    return {
        "users": {}, 
        "questions": {
            "Umum": [{"q": "Menara miring di Italia", "h": "p__a", "a": "pisa"}]
        }, 
        "ads_text": "PASANG IKLAN DISINI @admin",
        "ads_photo": None
    }

db = load_db()

def save_db():
    with open(DATA_FILE, 'w') as f:
        json.dump(db, f, indent=4)

current_games = {} 
group_players = {}

# --- ADMIN PANEL ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text("❌ Akses Ditolak.")
    
    keyboard = [
        [InlineKeyboardButton("📤 Backup Database (Send DB)", callback_data='adm_send_db')],
        [InlineKeyboardButton("🖼 Set Banner & Iklan", callback_data='adm_set_ads')],
        [InlineKeyboardButton("➕ Tambah Soal Kategori", callback_data='adm_add_ques')]
    ]
    await update.message.reply_text("🛠 **ADMINISTRATOR PANEL**", reply_markup=InlineKeyboardMarkup(keyboard))

# --- START HANDLER ---
async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user

    # JIKA DI PC / PRIVATE CHAT
    if chat.type == "private":
        return await update.message.reply_text(
            f"👋 Halo {user.first_name}!\n\n"
            "Bot ini adalah Bot Tebak-tebakan Group.\n"
            "Silahkan masukkan bot ini ke grup kamu untuk mulai bermain bersama teman-teman!",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("➕ Tambahkan ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=true")
            ]])
        )

    # JIKA DI GRUP
    keyboard = []
    for cat in db['questions'].keys():
        keyboard.append([InlineKeyboardButton(f"🎮 Kategori {cat}", callback_data=f"start_{cat}")])
    
    await update.message.reply_text(
        "🕹 **PERMAINAN DIMULAI**\n\nSilahkan pilih kategori soal:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )

# --- SEND QUESTION ENGINE ---
async def send_question(context, chat_id, category):
    if chat_id not in current_games: return
    
    q_list = db['questions'].get(category, db['questions']["Umum"])
    q_data = random.choice(q_list)
    
    # UI Tampilan Soal & Iklan
    text = f"━━━━━━━━━━━━━━\n"
    text += f"📣 **SPONSORED:**\n{db['ads_text']}\n"
    text += f"━━━━━━━━━━━━━━\n\n"
    text += f"❓ **SOAL:** `{q_data['q']}`\n"
    text += f"💡 **CLUE:** `{q_data['h']}`\n\n"
    text += f"⏱ *Waktu: 15 Detik*\n"
    text += f"👥 *Min. 2 Player agar poin cair*"

    kb = [[
        InlineKeyboardButton("⏭ Skip", callback_data="game_skip"),
        InlineKeyboardButton("🛑 Stop", callback_data="game_stop")
    ]]

    if db.get('ads_photo'):
        msg = await context.bot.send_photo(chat_id, photo=db['ads_photo'], caption=text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        msg = await context.bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

    current_games[chat_id].update({
        "ans": q_data['a'].lower().strip(),
        "cat": category,
        "answered": False,
        "msg_id": msg.message_id
    })

    await asyncio.sleep(15)
    # Check if still active and not answered
    if chat_id in current_games and not current_games[chat_id]['answered']:
        await context.bot.send_message(chat_id, f"⌛ **WAKTU HABIS!**\nJawabannya adalah: *{q_data['a']}*")
        await asyncio.sleep(2)
        await send_question(context, chat_id, category)

# --- CALLBACK HANDLER ---
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    chat_id = query.message.chat_id
    data = query.data
    user_id = query.from_user.id

    if data.startswith('adm_'):
        if user_id != ADMIN_ID: return await query.answer("Bukan Admin!")
        if data == 'adm_send_db':
            save_db()
            await query.message.reply_document(open(DATA_FILE, 'rb'), caption="Backup Data")
        elif data == 'adm_set_ads':
            context.user_data['state'] = 'waiting_ads'
            await query.message.reply_text("Kirim Foto + Caption untuk Iklan.")
        elif data == 'adm_add_ques':
            context.user_data['state'] = 'waiting_ques'
            await query.message.reply_text("Format: Kategori | Soal | Clue | Jawaban")
    
    elif data.startswith('start_'):
        cat = data.split('_')[1]
        current_games[chat_id] = {"answered": False} # Init game state
        await query.message.delete()
        await send_question(context, chat_id, cat)
        
    elif data == 'game_skip':
        if chat_id in current_games:
            current_games[chat_id]['answered'] = True
            await query.message.reply_text("⏭ Soal dilewati oleh admin/player...")
            await send_question(context, chat_id, current_games[chat_id]['cat'])
            
    elif data == 'game_stop':
        if chat_id in current_games:
            current_games.pop(chat_id, None)
            await query.message.reply_text("🛑 Permainan telah dihentikan.")

    await query.answer()

# --- MESSAGE HANDLER (ANSWERS & ADMIN INPUT) ---
async def handle_all_messages(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text: return
    
    chat_id = update.effective_chat.id
    user = update.effective_user
    text_input = update.message.text.lower().strip()

    # LOGIKA ADMIN (DI PRIVATE)
    state = context.user_data.get('state')
    if update.effective_chat.type == "private" and user.id == ADMIN_ID and state:
        if state == 'waiting_ads':
            db['ads_text'] = update.message.caption or update.message.text
            if update.message.photo: db['ads_photo'] = update.message.photo[-1].file_id
            save_db(); context.user_data['state'] = None
            await update.message.reply_text("✅ Iklan & Banner Berhasil Diperbarui!")
        elif state == 'waiting_ques':
            try:
                parts = update.message.text.split("|")
                k, s, c, j = [p.strip() for p in parts]
                if k not in db['questions']: db['questions'][k] = []
                db['questions'][k].append({"q": s, "h": c, "a": j})
                save_db(); context.user_data['state'] = None
                await update.message.reply_text(f"✅ Soal berhasil ditambah ke {k}!")
            except: await update.message.reply_text("❌ Gagal. Pastikan format: Kategori | Soal | Clue | Jawaban")
        return

    # LOGIKA JAWABAN (DI GRUP)
    if chat_id in current_games and not current_games[chat_id]['answered']:
        # Track pemain unik di grup
        if chat_id not in group_players: group_players[chat_id] = set()
        group_players[chat_id].add(user.id)

        if text_input == current_games[chat_id]['ans']:
            current_games[chat_id]['answered'] = True
            
            # Cek Minimal 2 Pemain
            if len(group_players[chat_id]) < 2:
                await update.message.reply_text(f"✅ **{user.first_name}**, jawaban benar! Tapi poin tidak masuk karena butuh minimal 2 orang di grup ini agar tidak curang.")
            else:
                uid = str(user.id)
                if uid not in db['users']: db['users'][uid] = {"name": user.first_name, "pts": 0}
                db['users'][uid]['pts'] += 10
                save_db()
                
                # Leaderboard 1-3
                top_global = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:3]
                lb = "🏆 **LEADERBOARD GLOBAL (TOP 3)** 🏆\n"
                for i, (tid, d) in enumerate(top_global, 1):
                    lb += f"{i}. {d['name']} — {d['pts']} Pts\n"
                
                await update.message.reply_text(f"🎯 **{user.first_name} BENAR!** (+10 Poin)\n\n{lb}")

            await asyncio.sleep(3)
            await send_question(context, chat_id, current_games[chat_id]['cat'])

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CallbackQueryHandler(on_callback))
    # Handler ini menangkap SEMUA pesan (Foto/Text) untuk deteksi jawaban & input admin
    app.add_handler(MessageHandler(filters.ALL, handle_all_messages))
    
    print("Bot is running...")
    app.run_polling()

if __name__ == '__main__':
    main()

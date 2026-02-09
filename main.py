import asyncio
import json
import os
import random
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

# Setup Logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)

# --- CONFIG ---
TOKEN = os.getenv("BOT_TOKEN")
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

# --- FUNGSI TAMPILAN IKLAN ---
async def send_start_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = f"🤖 **Pusat Tebak-tebakan Umum**\n━━━━━━━━━━━━━━\n📢 {db['ads_text']}\n━━━━━━━━━━━━━━\n\nMainkan di grup untuk mengumpulkan poin global!"
    kb = [[InlineKeyboardButton("➕ Tambahkan ke Grup", url=f"https://t.me/{context.bot.username}?startgroup=true")]]
    
    if db.get('ads_photo'):
        await update.message.reply_photo(photo=db['ads_photo'], caption=text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))
    else:
        await update.message.reply_text(text, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(kb))

# --- ADMIN PANEL ---
async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return await update.message.reply_text(f"❌ Akses Ditolak. ID Anda: `{update.effective_user.id}`", parse_mode='Markdown')
    
    keyboard = [
        [InlineKeyboardButton("📤 Send Database (Backup)", callback_data='adm_send_db')],
        [InlineKeyboardButton("🖼 Set Iklan (Foto + Teks)", callback_data='adm_set_ads')],
        [InlineKeyboardButton("➕ Tambah Soal", callback_data='adm_add_ques')]
    ]
    await update.message.reply_text("🛠 **ADMIN CONTROL PANEL**", reply_markup=InlineKeyboardMarkup(keyboard))

# --- GAME ENGINE ---
async def send_question(context, chat_id, category):
    if chat_id not in current_games or current_games[chat_id].get('stopped'): return
    
    q_list = db['questions'].get(category, [])
    if not q_list: return
    
    q_data = random.choice(q_list)
    text = f"🎮 **KATEGORI: {category}**\n\n❓ Soal: *{q_data['q']}*\n💡 Clue: `{q_data['h']}`\n\n⏱ Waktu: 15 detik!"
    
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
    if chat_id in current_games and not current_games[chat_id]['answered'] and not current_games[chat_id].get('stopped'):
        await context.bot.send_message(chat_id, f"⌛ Waktu habis! Jawabannya: *{q_data['a'].upper()}*")
        await asyncio.sleep(2)
        await send_question(context, chat_id, category)

# --- CALLBACK HANDLER ---
async def on_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    data = query.data
    user_id = query.from_user.id
    chat_id = query.message.chat_id

    if data.startswith('adm_'):
        if user_id != ADMIN_ID: return await query.answer("Akses Ditolak!")
        if data == 'adm_send_db':
            save_db()
            await query.message.reply_document(open(DATA_FILE, 'rb'), caption="Backup DB")
        elif data == 'adm_set_ads':
            context.user_data['state'] = 'wait_ads'
            await query.message.reply_text("Kirim FOTO iklan dengan CAPTION-nya sekarang.")
        elif data == 'adm_add_ques':
            context.user_data['state'] = 'wait_q'
            await query.message.reply_text("Kirim soal format: Kategori | Soal | Clue | Jawaban")

    elif data.startswith('start_'):
        cat = data.split('_')[1]
        current_games[chat_id] = {"stopped": False, "answered": False, "cat": cat}
        await query.message.delete()
        await send_question(context, chat_id, cat)

    elif data == "game_skip":
        if chat_id in current_games:
            current_games[chat_id]['answered'] = True
            await query.message.reply_text("⏭ Melewati soal...")
            await send_question(context, chat_id, current_games[chat_id]['cat'])

    elif data == "game_stop":
        if chat_id in current_games:
            current_games[chat_id]['stopped'] = True
            await query.message.reply_text("🛑 Permainan dihentikan.")
            current_games.pop(chat_id, None)

    await query.answer()

# --- MESSAGE HANDLER ---
async def handle_msg(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message: return
    
    uid = update.effective_user.id
    chat_id = update.effective_chat.id
    is_private = update.effective_chat.type == "private"
    text = (update.message.text or "").lower().strip()

    # ADMIN INPUT
    state = context.user_data.get('state')
    if is_private and uid == ADMIN_ID and state:
        if state == 'wait_ads':
            db['ads_text'] = update.message.caption or update.message.text
            if update.message.photo: db['ads_photo'] = update.message.photo[-1].file_id
            save_db(); context.user_data['state'] = None
            await update.message.reply_text("✅ Iklan profil diperbarui!")
            return
        elif state == 'wait_q':
            try:
                k, s, c, j = [x.strip() for x in update.message.text.split("|")]
                if k not in db['questions']: db['questions'][k] = []
                db['questions'][k].append({"q":s, "h":c, "a":j})
                save_db(); context.user_data['state'] = None
                await update.message.reply_text(f"✅ Soal masuk ke {k}!")
            except: await update.message.reply_text("Format salah! Kat | Soal | Clue | Jawaban")
            return

    # JAWABAN GRUP
    if chat_id in current_games and not current_games[chat_id]['answered']:
        if text == current_games[chat_id]['ans']:
            current_games[chat_id]['answered'] = True
            
            if chat_id not in group_players: group_players[chat_id] = set()
            group_players[chat_id].add(uid)

            if len(group_players[chat_id]) < 2:
                await update.message.reply_text("✅ Benar! (Poin tidak bertambah karena baru 1 orang yang main).")
            else:
                s_uid = str(uid)
                if s_uid not in db['users']: db['users'][s_uid] = {"name": update.effective_user.first_name, "pts": 0}
                db['users'][s_uid]['pts'] += 10
                save_db()
                
                top = sorted(db['users'].items(), key=lambda x: x[1]['pts'], reverse=True)[:3]
                lb = "\n".join([f"{i+1}. {u[1]['name']} - {u[1]['pts']} Pts" for i, u in enumerate(top)])
                await update.message.reply_text(f"🎯 **{update.effective_user.first_name} BENAR!** (+10)\n\n🏆 **TOP GLOBAL:**\n{lb}")
            
            await asyncio.sleep(2)
            await send_question(context, chat_id, current_games[chat_id]['cat'])

# --- MAIN ---
async def start_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_chat.type == "private":
        await send_start_msg(update, context)
    else:
        keyboard = [[InlineKeyboardButton(f"📁 {cat}", callback_data=f"start_{cat}")] for cat in db['questions'].keys()]
        await update.message.reply_text("🎮 **PILIH KATEGORI:**", reply_markup=InlineKeyboardMarkup(keyboard))

def main():
    app = Application.builder().token(TOKEN).build()
    
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(CommandHandler("start", start_cmd))
    app.add_handler(CallbackQueryHandler(on_callback))
    app.add_handler(MessageHandler(filters.ALL, handle_msg))
    
    print("Bot is alive...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()

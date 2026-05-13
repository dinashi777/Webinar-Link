import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, ChatMemberHandler,
    ContextTypes, CallbackQueryHandler,
)
from config import BOT_TOKEN, CHANNEL_ID, ADMIN_ID, WEBINAR_LINK, REQUIRED_INVITES
from database import Database

logging.basicConfig(format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)
db = Database()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if not db.get_user(user.id):
        db.add_user(user.id, user.username or user.first_name)
    invite_link = db.get_invite_link(user.id)
    if not invite_link:
        try:
            link_obj = await context.bot.create_chat_invite_link(chat_id=CHANNEL_ID, name=f"ref_{user.id}")
            invite_link = link_obj.invite_link
            db.save_invite_link(user.id, invite_link)
        except Exception as e:
            logger.error(f"Could not create invite link: {e}")
            await update.message.reply_text("⚠️ Could not generate your invite link. Make sure the bot is an admin of the channel with 'Invite Users' permission.")
            return
    invite_count = db.get_invite_count(user.id)
    remaining = max(0, REQUIRED_INVITES - invite_count)
    keyboard = [[InlineKeyboardButton("📊 Check My Progress", callback_data="progress")]]
    await update.message.reply_text(
        f"👋 Welcome, {user.first_name}!\n\n🎙️ <b>Webinar Registration Bot</b>\n\n"
        f"Invite <b>{REQUIRED_INVITES} people</b> using your link below.\n\n"
        f"🔗 <b>Your Invite Link:</b>\n<code>{invite_link}</code>\n\n"
        f"📈 <b>Progress:</b> {invite_count}/{REQUIRED_INVITES} invites\n"
        f"{'✅ You have access!' if invite_count >= REQUIRED_INVITES else f'🔒 {remaining} more needed'}",
        parse_mode="HTML", reply_markup=InlineKeyboardMarkup(keyboard))
    if invite_count >= REQUIRED_INVITES:
        await context.bot.send_message(chat_id=user.id, text=f"🎊 <b>Webinar Link:</b>\n👉 {WEBINAR_LINK}", parse_mode="HTML")

async def progress_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await send_progress_message(context, update.effective_user.id)

async def progress_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.callback_query.answer()
    await send_progress_message(context, update.effective_user.id)

async def send_progress_message(context, user_id):
    invite_count = db.get_invite_count(user_id)
    invite_link = db.get_invite_link(user_id)
    remaining = max(0, REQUIRED_INVITES - invite_count)
    bar = "🟩" * int((invite_count / REQUIRED_INVITES) * 10) + "⬜" * (10 - int((invite_count / REQUIRED_INVITES) * 10))
    status = "✅ <b>REGISTERED!</b>" if invite_count >= REQUIRED_INVITES else f"🔒 {remaining} more needed"
    await context.bot.send_message(chat_id=user_id,
        text=f"📊 <b>Progress</b>\n\n{bar}\n<b>{invite_count}/{REQUIRED_INVITES}</b>\n\n{status}\n\n🔗 <code>{invite_link}</code>",
        parse_mode="HTML")

async def track_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.chat_member
    new_member = result.new_chat_member
    old_member = result.old_chat_member
    if old_member.status in ("member", "administrator", "creator"):
        return
    if new_member.status != "member":
        return
    if not result.invite_link:
        return
    referrer_id = db.get_referrer_by_link(result.invite_link.invite_link)
    if not referrer_id or new_member.user.id == referrer_id:
        return
    if db.has_already_counted(referrer_id, new_member.user.id):
        return
    db.record_invite(referrer_id, new_member.user.id)
    invite_count = db.get_invite_count(referrer_id)
    remaining = max(0, REQUIRED_INVITES - invite_count)
    try:
        if invite_count < REQUIRED_INVITES:
            await context.bot.send_message(chat_id=referrer_id,
                text=f"🎉 Someone joined!\n📈 <b>{invite_count}/{REQUIRED_INVITES}</b>\n🔒 {remaining} more needed!",
                parse_mode="HTML")
        else:
            await context.bot.send_message(chat_id=referrer_id,
                text=f"🎊 <b>Congratulations!</b>\n\n🎙️ <b>Webinar Link:</b>\n👉 {WEBINAR_LINK}", parse_mode="HTML")
            referrer = db.get_user(referrer_id)
            await context.bot.send_message(chat_id=ADMIN_ID,
                text=f"✅ <b>New Registration!</b>\n👤 ID: <code>{referrer_id}</code>\n🔗 {invite_count}/{REQUIRED_INVITES}",
                parse_mode="HTML")
    except Exception as e:
        logger.error(f"Error: {e}")

async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Not authorized.")
        return
    stats = db.get_stats()
    await update.message.reply_text(
        f"📊 <b>Stats</b>\n👥 Users: <b>{stats['total_users']}</b>\n✅ Qualified: <b>{stats['qualified_users']}</b>\n🔗 Invites: <b>{stats['total_invites']}</b>",
        parse_mode="HTML")

def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("progress", progress_command))
    app.add_handler(CommandHandler("admin", admin_stats))
    app.add_handler(CallbackQueryHandler(progress_callback, pattern="^progress$"))
    app.add_handler(ChatMemberHandler(track_new_member, ChatMemberHandler.CHAT_MEMBER))
    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()

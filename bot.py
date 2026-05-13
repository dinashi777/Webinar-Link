"""
Webinar Registration Telegram Bot
- Users get a unique invite link to share
- Bot tracks joins via each user's invite link
- At 5 verified invites, user gets webinar access link
- Admin is notified of registrations
"""

import logging
import asyncio
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ChatMemberHandler,
    ContextTypes,
    CallbackQueryHandler,
)
from config import (
    BOT_TOKEN,
    CHANNEL_ID,
    ADMIN_ID,
    WEBINAR_LINK,
    REQUIRED_INVITES,
)
from database import Database

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

db = Database()


# ─────────────────────────────────────────────
# /start
# ─────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user

    # Register user if new
    if not db.get_user(user.id):
        db.add_user(user.id, user.username or user.first_name)

    # Generate or retrieve unique invite link for this user
    invite_link = db.get_invite_link(user.id)
    if not invite_link:
        try:
            link_obj = await context.bot.create_chat_invite_link(
                chat_id=CHANNEL_ID,
                name=f"ref_{user.id}",
                creates_join_request=False,
            )
            invite_link = link_obj.invite_link
            db.save_invite_link(user.id, invite_link)
        except Exception as e:
            logger.error(f"Could not create invite link: {e}")
            await update.message.reply_text(
                "⚠️ Could not generate your invite link. "
                "Make sure the bot is an admin of the channel with 'Invite Users' permission."
            )
            return

    invite_count = db.get_invite_count(user.id)
    remaining = max(0, REQUIRED_INVITES - invite_count)

    keyboard = [[InlineKeyboardButton("📊 Check My Progress", callback_data="progress")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"👋 Welcome, {user.first_name}!\n\n"
        f"🎙️ <b>Webinar Registration Bot</b>\n\n"
        f"To get access to the webinar, invite <b>{REQUIRED_INVITES} people</b> "
        f"to our channel using your unique link below.\n\n"
        f"🔗 <b>Your Invite Link:</b>\n<code>{invite_link}</code>\n\n"
        f"📈 <b>Progress:</b> {invite_count}/{REQUIRED_INVITES} invites\n"
        f"{'✅ You have access!' if invite_count >= REQUIRED_INVITES else f'🔒 {remaining} more invite(s) needed'}\n\n"
        f"Share your link and once <b>{REQUIRED_INVITES} people join</b>, "
        f"you'll automatically receive the webinar link! 🚀",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )

    # If already qualified, resend webinar link
    if invite_count >= REQUIRED_INVITES:
        await send_webinar_link(update.message, user, context)


# ─────────────────────────────────────────────
# /progress
# ─────────────────────────────────────────────
async def progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    await send_progress(update.message, user)


async def progress_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    await send_progress(query.message, update.effective_user)


async def send_progress(message, user):
    if not db.get_user(user.id):
        await message.reply_text("Please start with /start first.")
        return

    invite_count = db.get_invite_count(user.id)
    invite_link = db.get_invite_link(user.id)
    remaining = max(0, REQUIRED_INVITES - invite_count)

    bar_filled = int((invite_count / REQUIRED_INVITES) * 10)
    bar = "🟩" * bar_filled + "⬜" * (10 - bar_filled)

    status = (
        "✅ <b>REGISTERED!</b> You have full access to the webinar."
        if invite_count >= REQUIRED_INVITES
        else f"🔒 Invite <b>{remaining}</b> more person(s) to unlock webinar access."
    )

    await message.reply_text(
        f"📊 <b>Your Registration Progress</b>\n\n"
        f"{bar}\n"
        f"<b>{invite_count} / {REQUIRED_INVITES}</b> invites completed\n\n"
        f"{status}\n\n"
        f"🔗 Your link: <code>{invite_link}</code>",
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
# Track new channel members
# ─────────────────────────────────────────────
async def track_new_member(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    result = update.chat_member
    new_member = result.new_chat_member
    old_member = result.old_chat_member

    # Only care about users newly joining
    if old_member.status in ("member", "administrator", "creator"):
        return
    if new_member.status not in ("member",):
        return

    joined_user = new_member.user
    invite_link_used = result.invite_link

    if not invite_link_used:
        return

    link_url = invite_link_used.invite_link
    referrer_id = db.get_referrer_by_link(link_url)

    if not referrer_id:
        return

    # Don't count self-referral
    if joined_user.id == referrer_id:
        return

    # Don't count duplicate joins
    if db.has_already_counted(referrer_id, joined_user.id):
        return

    db.record_invite(referrer_id, joined_user.id)
    invite_count = db.get_invite_count(referrer_id)

    logger.info(
        f"User {joined_user.id} joined via link of referrer {referrer_id}. "
        f"Referrer now has {invite_count} invites."
    )

    referrer = db.get_user(referrer_id)
    referrer_name = referrer["username"] if referrer else str(referrer_id)

    # Notify referrer of progress
    try:
        remaining = max(0, REQUIRED_INVITES - invite_count)
        if invite_count < REQUIRED_INVITES:
            await context.bot.send_message(
                chat_id=referrer_id,
                text=(
                    f"🎉 Someone just joined using your invite link!\n\n"
                    f"📈 Progress: <b>{invite_count}/{REQUIRED_INVITES}</b>\n"
                    f"🔒 Just <b>{remaining}</b> more to unlock webinar access!"
                ),
                parse_mode="HTML",
            )
        else:
            # Unlocked!
            fake_message = await context.bot.send_message(
                chat_id=referrer_id,
                text="🔓 Unlocking your webinar access...",
            )
            await send_webinar_link(fake_message, type("U", (), {"id": referrer_id, "first_name": referrer_name})(), context)

            # Notify admin
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    f"✅ <b>New Webinar Registration!</b>\n\n"
                    f"👤 User: @{referrer_name} (ID: <code>{referrer_id}</code>)\n"
                    f"🔗 Invites completed: {invite_count}/{REQUIRED_INVITES}"
                ),
                parse_mode="HTML",
            )

    except Exception as e:
        logger.error(f"Failed to notify user {referrer_id}: {e}")


# ─────────────────────────────────────────────
# Send webinar link
# ─────────────────────────────────────────────
async def send_webinar_link(message, user, context: ContextTypes.DEFAULT_TYPE) -> None:
    await context.bot.send_message(
        chat_id=user.id,
        text=(
            f"🎊 <b>Congratulations, {user.first_name}!</b>\n\n"
            f"You've successfully invited {REQUIRED_INVITES} people to the channel!\n\n"
            f"🎙️ <b>Here is your Webinar Access Link:</b>\n"
            f"👉 {WEBINAR_LINK}\n\n"
            f"See you at the webinar! 🚀"
        ),
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
# /admin — Admin stats overview
# ─────────────────────────────────────────────
async def admin_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ You are not authorized.")
        return

    stats = db.get_stats()
    await update.message.reply_text(
        f"📊 <b>Bot Statistics</b>\n\n"
        f"👥 Total registered users: <b>{stats['total_users']}</b>\n"
        f"✅ Fully qualified (webinar access): <b>{stats['qualified_users']}</b>\n"
        f"🔗 Total invites tracked: <b>{stats['total_invites']}</b>",
        parse_mode="HTML",
    )


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main() -> None:
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("progress", progress))
    app.add_handler(CommandHandler("admin", admin_stats))
    app.add_handler(CallbackQueryHandler(progress_callback, pattern="^progress$"))
    app.add_handler(ChatMemberHandler(track_new_member, ChatMemberHandler.CHAT_MEMBER))

    logger.info("Bot is running...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()

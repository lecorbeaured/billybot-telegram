"""
BillyBot Telegram Bot
Commands: /start /bills /all /paid /owe /summary /ask /remind /help
"""
import os
import logging
from difflib import get_close_matches
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler,
)
import api as billybot_api
from scheduler import start_scheduler

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://billybot.app")

CAT_EMOJI = {
    "Housing": "🏠", "Utilities": "⚡", "Insurance": "🛡️",
    "Subscriptions": "📺", "Transport": "🚗", "Food": "🍕",
    "Health": "💊", "Debt": "💳", "Other": "📌",
}

# Per-user chat history for /ask context (in-memory, resets on restart)
chat_histories: dict[int, list] = {}


# ── Helpers ───────────────────────────────────────────────────────────────────

def days_until(due_day: int) -> int:
    from datetime import datetime
    today = datetime.now().day
    d = due_day - today
    return d if d >= 0 else d + 30


def urgency_icon(bill: dict) -> str:
    if bill.get("payment_count", 0) > 0:
        return "✅"
    d = days_until(bill["due_day"])
    if d == 0: return "🔴"
    if d <= 3:  return "⚠️"
    if d <= 7:  return "🟡"
    return "🟢"


def format_bill_line(bill: dict, show_days: bool = True) -> str:
    emoji = CAT_EMOJI.get(bill.get("category", "Other"), "📌")
    icon  = urgency_icon(bill)
    name  = bill["name"]
    amt   = f"${float(bill['amount']):.2f}"
    paid  = bill.get("payment_count", 0) > 0

    if paid:
        return f"{icon} {emoji} ~{name}~ — {amt} ✓"
    else:
        days = days_until(bill["due_day"])
        due_str = "due TODAY" if days == 0 else f"in {days}d"
        return f"{icon} {emoji} *{name}* — {amt} ({due_str})"


async def get_linked_user(update: Update) -> dict | None:
    """Get the BillyBot user linked to this chat, or prompt to connect."""
    chat_id = update.effective_chat.id
    user = billybot_api.get_user_by_chat_id(chat_id)
    if not user:
        token = billybot_api.generate_link_token(
            chat_id,
            update.effective_user.username or ""
        )
        link = f"{FRONTEND_URL}/connect?token={token}"
        keyboard = [[InlineKeyboardButton("🔗 Connect My Account", url=link)]]
        await update.message.reply_text(
            "👋 Your Telegram isn't linked to a BillyBot account yet.\n\n"
            "Tap below to connect — it only takes a second:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return None
    return user


# ── /start ────────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    first_name = update.effective_user.first_name or "there"

    user = billybot_api.get_user_by_chat_id(chat_id)

    if user:
        await update.message.reply_text(
            f"🤖 Hey *{first_name}*! BillyBot is connected and ready.\n\n"
            f"Type /help to see what I can do, or try /bills to see what's due.",
            parse_mode="Markdown"
        )
    else:
        token = billybot_api.generate_link_token(chat_id, update.effective_user.username or "")
        link = f"{FRONTEND_URL}/connect?token={token}"
        keyboard = [[InlineKeyboardButton("🔗 Connect My Account", url=link)]]
        await update.message.reply_text(
            f"👋 Hey *{first_name}*! I'm *BillyBot* — your AI bill pay companion.\n\n"
            f"I'll remind you about upcoming bills, let you mark them as paid, "
            f"and answer any money questions — right here in Telegram.\n\n"
            f"First, connect your BillyBot account:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )


# ── /help ─────────────────────────────────────────────────────────────────────

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🤖 *BillyBot Commands*\n\n"
        "📋 *Bills*\n"
        "/bills — unpaid bills this month\n"
        "/all — all bills (paid + unpaid)\n"
        "/owe — total amount still owed\n"
        "/summary — monthly progress overview\n"
        "/paid <name> — mark a bill as paid\n"
        "  e.g. `/paid rent` or `/paid electric`\n\n"
        "🤖 *AI Assistant*\n"
        "/ask <question> — chat with BillyBot AI\n"
        "  e.g. `/ask which bill should I pay first?`\n\n"
        "⚙️ *Settings*\n"
        "/remind — your reminder settings\n\n"
        "🔗 *Account*\n"
        "/start — connect or reconnect account\n"
        f"\nOpen dashboard: {FRONTEND_URL}",
        parse_mode="Markdown"
    )


# ── /bills ────────────────────────────────────────────────────────────────────

async def cmd_bills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return

    chat_id = update.effective_chat.id
    bills = billybot_api.get_bills(chat_id)
    unpaid = [b for b in bills if b.get("payment_count", 0) == 0]

    if not unpaid:
        await update.message.reply_text(
            "🎉 *All bills are paid this month!*\n\nUse /all to see everything.",
            parse_mode="Markdown"
        )
        return

    # Sort by urgency
    unpaid.sort(key=lambda b: days_until(b["due_day"]))
    lines = ["📋 *Unpaid Bills This Month*\n"]
    for b in unpaid:
        lines.append(format_bill_line(b))

    total = sum(float(b["amount"]) for b in unpaid)
    lines.append(f"\n💰 *Total owed: ${total:.2f}*")
    lines.append("\nUse `/paid <name>` to mark as paid.")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /all ──────────────────────────────────────────────────────────────────────

async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return

    chat_id = update.effective_chat.id
    bills = billybot_api.get_bills(chat_id)

    if not bills:
        await update.message.reply_text(
            "📋 No bills found. Add bills at your dashboard:\n" + FRONTEND_URL
        )
        return

    bills.sort(key=lambda b: (b.get("payment_count", 0) > 0, days_until(b["due_day"])))
    lines = ["📋 *All Bills This Month*\n"]
    for b in bills:
        lines.append(format_bill_line(b))

    paid_count = sum(1 for b in bills if b.get("payment_count", 0) > 0)
    lines.append(f"\n✅ {paid_count}/{len(bills)} paid")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


# ── /owe ──────────────────────────────────────────────────────────────────────

async def cmd_owe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return

    chat_id = update.effective_chat.id
    bills = billybot_api.get_bills(chat_id)
    unpaid = [b for b in bills if b.get("payment_count", 0) == 0]

    if not unpaid:
        await update.message.reply_text("🎉 You owe *$0.00* — all bills paid this month!", parse_mode="Markdown")
        return

    total = sum(float(b["amount"]) for b in unpaid)
    urgent = [b for b in unpaid if days_until(b["due_day"]) <= 3]

    msg = f"💰 *You owe ${total:.2f} this month*\n"
    msg += f"Across {len(unpaid)} unpaid bill{'s' if len(unpaid) > 1 else ''}"
    if urgent:
        msg += f"\n\n⚠️ *{len(urgent)} bill{'s' if len(urgent) > 1 else ''} due within 3 days:*\n"
        for b in urgent:
            msg += f"  • {b['name']} — ${float(b['amount']):.2f}\n"

    await update.message.reply_text(msg, parse_mode="Markdown")


# ── /summary ──────────────────────────────────────────────────────────────────

async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return

    chat_id = update.effective_chat.id
    try:
        data = billybot_api.get_summary(chat_id)
        s = data.get("summary", {})
        bills = data.get("bills", [])

        paid_amt  = float(s.get("paid", 0))
        unpaid_amt = float(s.get("unpaid", 0))
        total     = float(s.get("total", 0))
        count     = s.get("count", 0)
        paid_count = sum(1 for b in bills if b.get("payment_count", 0) > 0)
        pct = int((paid_count / count * 100)) if count else 0

        # Progress bar
        filled = pct // 10
        bar = "█" * filled + "░" * (10 - filled)

        msg = (
            f"📊 *Monthly Summary*\n\n"
            f"`{bar}` {pct}%\n\n"
            f"✅ Paid:    *${paid_amt:.2f}* ({paid_count} bills)\n"
            f"⏳ Owed:    *${unpaid_amt:.2f}* ({count - paid_count} bills)\n"
            f"📋 Total:   *${total:.2f}* ({count} bills)\n"
        )

        # Next bill due
        unpaid = sorted(
            [b for b in bills if b.get("payment_count", 0) == 0],
            key=lambda b: days_until(b["due_day"])
        )
        if unpaid:
            nxt = unpaid[0]
            days = days_until(nxt["due_day"])
            msg += f"\n⏰ *Next up:* {nxt['name']} (${float(nxt['amount']):.2f}) "
            msg += "— due TODAY" if days == 0 else f"— in {days} day{'s' if days != 1 else ''}"

        await update.message.reply_text(msg, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"cmd_summary error: {e}")
        await update.message.reply_text("⚠️ Couldn't load summary. Try again.")


# ── /paid <name> ──────────────────────────────────────────────────────────────

async def cmd_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/paid <bill name>`\nExample: `/paid rent` or `/paid electric`",
            parse_mode="Markdown"
        )
        return

    chat_id = update.effective_chat.id
    search = " ".join(context.args).lower().strip()
    bills = billybot_api.get_bills(chat_id)
    unpaid = [b for b in bills if b.get("payment_count", 0) == 0]

    if not unpaid:
        await update.message.reply_text("🎉 All bills are already paid this month!")
        return

    # Fuzzy match on bill names
    bill_names = [b["name"].lower() for b in unpaid]
    matches = get_close_matches(search, bill_names, n=1, cutoff=0.45)

    # Also try direct substring match
    if not matches:
        matches = [n for n in bill_names if search in n or n in search]

    if not matches:
        names_list = "\n".join(f"  • {b['name']}" for b in unpaid)
        await update.message.reply_text(
            f"❓ Couldn't find *\"{search}\"* in your unpaid bills.\n\n"
            f"Unpaid bills:\n{names_list}\n\n"
            f"Try `/paid rent` or `/paid electric`",
            parse_mode="Markdown"
        )
        return

    matched_name = matches[0]
    matched_bill = next(b for b in unpaid if b["name"].lower() == matched_name)

    # Confirm with inline button
    keyboard = [[
        InlineKeyboardButton(
            f"✓ Yes, mark {matched_bill['name']} as paid",
            callback_data=f"pay:{matched_bill['id']}:{matched_bill['name']}"
        ),
        InlineKeyboardButton("✗ Cancel", callback_data="pay:cancel")
    ]]
    await update.message.reply_text(
        f"Mark *{matched_bill['name']}* (${float(matched_bill['amount']):.2f}) as paid?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def handle_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data
    if data == "pay:cancel":
        await query.edit_message_text("Cancelled.")
        return

    _, bill_id, bill_name = data.split(":", 2)
    chat_id = update.effective_chat.id

    try:
        billybot_api.mark_paid(chat_id, int(bill_id))
        await query.edit_message_text(
            f"✅ *{bill_name}* marked as paid!",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"mark_paid error: {e}")
        await query.edit_message_text("⚠️ Couldn't mark as paid. Try again.")


# ── /ask <question> ───────────────────────────────────────────────────────────

async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return

    if not context.args:
        await update.message.reply_text(
            "Usage: `/ask <your question>`\n"
            "Example: `/ask which bill should I pay first?`",
            parse_mode="Markdown"
        )
        return

    chat_id = update.effective_chat.id
    question = " ".join(context.args)

    # Maintain per-user chat history (last 10 turns)
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []

    chat_histories[chat_id].append({"role": "user", "content": question})
    if len(chat_histories[chat_id]) > 20:
        chat_histories[chat_id] = chat_histories[chat_id][-20:]

    # Show typing indicator
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")

    try:
        reply = billybot_api.chat(chat_id, chat_histories[chat_id])
        chat_histories[chat_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(
            f"🤖 {reply}",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"cmd_ask error: {e}")
        await update.message.reply_text("⚠️ AI is unavailable right now. Try again in a moment.")


# ── /remind ───────────────────────────────────────────────────────────────────

async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return

    chat_id = update.effective_chat.id
    try:
        data = billybot_api.get_summary(chat_id)  # summary includes settings context
        await update.message.reply_text(
            f"🔔 *Your Reminder Settings*\n\n"
            f"Telegram reminders: ✅ Active\n"
            f"Chat ID: `{chat_id}`\n\n"
            f"To change reminder days or disable:\n"
            f"Go to Dashboard → Settings\n{FRONTEND_URL}/dashboard.html",
            parse_mode="Markdown"
        )
    except Exception as e:
        await update.message.reply_text(
            f"🔔 Telegram reminders are *active* for this chat.\n\n"
            f"To adjust settings: {FRONTEND_URL}/dashboard.html",
            parse_mode="Markdown"
        )


# ── Unrecognized messages ─────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Treat any plain text as an /ask query."""
    text = update.message.text.strip()
    if text.startswith("/"):
        return  # Unknown command
    # Route to ask
    context.args = text.split()
    await cmd_ask(update, context)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    app = Application.builder().token(token).build()

    # Command handlers
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("bills",   cmd_bills))
    app.add_handler(CommandHandler("all",     cmd_all))
    app.add_handler(CommandHandler("owe",     cmd_owe))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("paid",    cmd_paid))
    app.add_handler(CommandHandler("ask",     cmd_ask))
    app.add_handler(CommandHandler("remind",  cmd_remind))

    # Inline button callbacks
    app.add_handler(CallbackQueryHandler(handle_pay_callback, pattern="^pay:"))

    # Plain text → ask
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Start reminder scheduler
    start_scheduler(app.bot)

    logger.info("🤖 BillyBot Telegram bot starting...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()

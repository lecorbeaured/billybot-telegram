"""
BillyBot Telegram Bot
Commands: /start /bills /all /paid /owe /summary /ask /remind /help
"""
import os
import asyncio
import logging
from difflib import get_close_matches
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, MessageHandler,
    ContextTypes, filters, CallbackQueryHandler,
)
import api as billybot_api

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
chat_histories: dict = {}


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
    if d <= 3: return "⚠️"
    if d <= 7: return "🟡"
    return "🟢"


def format_bill_line(bill: dict) -> str:
    emoji = CAT_EMOJI.get(bill.get("category", "Other"), "📌")
    icon = urgency_icon(bill)
    name = bill["name"]
    amt = f"${float(bill['amount']):.2f}"
    paid = bill.get("payment_count", 0) > 0
    if paid:
        return f"{icon} {emoji} {name} — {amt} paid"
    days = days_until(bill["due_day"])
    due_str = "due TODAY" if days == 0 else f"in {days}d"
    return f"{icon} {emoji} {name} — {amt} ({due_str})"


async def get_linked_user(update: Update):
    chat_id = update.effective_chat.id
    user = billybot_api.get_user_by_chat_id(chat_id)
    if not user:
        token = billybot_api.generate_link_token(chat_id, update.effective_user.username or "")
        link = f"{FRONTEND_URL}/dashboard.html?token={token}"
        keyboard = [[InlineKeyboardButton("🔗 Connect My Account", url=link)]]
        await update.message.reply_text(
            "Your Telegram is not linked to a BillyBot account yet.\nTap below to connect:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )
        return None
    return user


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    first_name = update.effective_user.first_name or "there"
    user = billybot_api.get_user_by_chat_id(chat_id)
    if user:
        await update.message.reply_text(
            f"Hey {first_name}! BillyBot is connected.\nTry /bills to see what's due."
        )
    else:
        token = billybot_api.generate_link_token(chat_id, update.effective_user.username or "")
        link = f"{FRONTEND_URL}/dashboard.html?token={token}"
        keyboard = [[InlineKeyboardButton("🔗 Connect My Account", url=link)]]
        await update.message.reply_text(
            f"Hey {first_name}! I'm BillyBot — your AI bill pay companion.\nConnect your account to get started:",
            reply_markup=InlineKeyboardMarkup(keyboard),
        )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "BillyBot Commands\n\n"
        "/bills — unpaid bills this month\n"
        "/all — all bills paid and unpaid\n"
        "/owe — total amount still owed\n"
        "/summary — monthly progress\n"
        "/paid <name> — mark a bill as paid\n"
        "/ask <question> — chat with BillyBot AI\n"
        "/remind — reminder settings\n"
        "/start — connect or reconnect account\n"
    )


async def cmd_bills(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return
    bills = billybot_api.get_bills(update.effective_chat.id)
    unpaid = sorted([b for b in bills if b.get("payment_count", 0) == 0], key=lambda b: days_until(b["due_day"]))
    if not unpaid:
        await update.message.reply_text("All bills are paid this month!")
        return
    lines = ["Unpaid Bills\n"] + [format_bill_line(b) for b in unpaid]
    total = sum(float(b["amount"]) for b in unpaid)
    lines.append(f"\nTotal owed: ${total:.2f}\nUse /paid <name> to mark as paid.")
    await update.message.reply_text("\n".join(lines))


async def cmd_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return
    bills = sorted(billybot_api.get_bills(update.effective_chat.id),
                   key=lambda b: (b.get("payment_count", 0) > 0, days_until(b["due_day"])))
    if not bills:
        await update.message.reply_text("No bills found.")
        return
    lines = ["All Bills\n"] + [format_bill_line(b) for b in bills]
    paid_count = sum(1 for b in bills if b.get("payment_count", 0) > 0)
    lines.append(f"\n{paid_count}/{len(bills)} paid")
    await update.message.reply_text("\n".join(lines))


async def cmd_owe(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return
    bills = billybot_api.get_bills(update.effective_chat.id)
    unpaid = [b for b in bills if b.get("payment_count", 0) == 0]
    if not unpaid:
        await update.message.reply_text("You owe $0.00 — all bills paid!")
        return
    total = sum(float(b["amount"]) for b in unpaid)
    urgent = [b for b in unpaid if days_until(b["due_day"]) <= 3]
    msg = f"You owe ${total:.2f} this month\n{len(unpaid)} unpaid bill(s)"
    if urgent:
        msg += "\n\nDue within 3 days:\n" + "\n".join(f"  {b['name']} — ${float(b['amount']):.2f}" for b in urgent)
    await update.message.reply_text(msg)


async def cmd_summary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return
    try:
        data = billybot_api.get_summary(update.effective_chat.id)
        s = data.get("summary", {})
        bills = data.get("bills", [])
        paid_amt = float(s.get("paid", 0))
        unpaid_amt = float(s.get("unpaid", 0))
        total = float(s.get("total", 0))
        count = s.get("count", 0)
        paid_count = sum(1 for b in bills if b.get("payment_count", 0) > 0)
        pct = int((paid_count / count * 100)) if count else 0
        bar = "█" * (pct // 10) + "░" * (10 - pct // 10)
        msg = f"Monthly Summary\n\n{bar} {pct}%\n\nPaid: ${paid_amt:.2f}\nOwed: ${unpaid_amt:.2f}\nTotal: ${total:.2f}"
        unpaid = sorted([b for b in bills if b.get("payment_count", 0) == 0], key=lambda b: days_until(b["due_day"]))
        if unpaid:
            nxt = unpaid[0]
            days = days_until(nxt["due_day"])
            msg += f"\n\nNext: {nxt['name']} ${float(nxt['amount']):.2f} — {'due TODAY' if days == 0 else f'in {days} day(s)'}"
        await update.message.reply_text(msg)
    except Exception as e:
        logger.error(f"cmd_summary: {e}")
        await update.message.reply_text("Couldn't load summary. Try again.")


async def cmd_paid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return
    if not context.args:
        await update.message.reply_text("Usage: /paid <bill name>\nExample: /paid rent")
        return
    chat_id = update.effective_chat.id
    search = " ".join(context.args).lower().strip()
    bills = billybot_api.get_bills(chat_id)
    unpaid = [b for b in bills if b.get("payment_count", 0) == 0]
    if not unpaid:
        await update.message.reply_text("All bills are already paid this month!")
        return
    bill_names = [b["name"].lower() for b in unpaid]
    matches = get_close_matches(search, bill_names, n=1, cutoff=0.45)
    if not matches:
        matches = [n for n in bill_names if search in n or n in search]
    if not matches:
        await update.message.reply_text(
            f"Couldn't find \"{search}\".\n\nUnpaid bills:\n" +
            "\n".join(f"  {b['name']}" for b in unpaid)
        )
        return
    matched_bill = next(b for b in unpaid if b["name"].lower() == matches[0])
    keyboard = [[
        InlineKeyboardButton(f"Yes — mark {matched_bill['name']} paid", callback_data=f"pay:{matched_bill['id']}:{matched_bill['name']}"),
        InlineKeyboardButton("Cancel", callback_data="pay:cancel")
    ]]
    await update.message.reply_text(
        f"Mark {matched_bill['name']} (${float(matched_bill['amount']):.2f}) as paid?",
        reply_markup=InlineKeyboardMarkup(keyboard),
    )


async def handle_pay_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "pay:cancel":
        await query.edit_message_text("Cancelled.")
        return
    _, bill_id, bill_name = query.data.split(":", 2)
    try:
        billybot_api.mark_paid(update.effective_chat.id, int(bill_id))
        await query.edit_message_text(f"{bill_name} marked as paid!")
    except Exception as e:
        logger.error(f"mark_paid: {e}")
        await query.edit_message_text("Couldn't mark as paid. Try again.")


async def cmd_ask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return
    if not context.args:
        await update.message.reply_text("Usage: /ask <question>\nExample: /ask which bill should I pay first?")
        return
    chat_id = update.effective_chat.id
    question = " ".join(context.args)
    if chat_id not in chat_histories:
        chat_histories[chat_id] = []
    chat_histories[chat_id].append({"role": "user", "content": question})
    if len(chat_histories[chat_id]) > 20:
        chat_histories[chat_id] = chat_histories[chat_id][-20:]
    await context.bot.send_chat_action(chat_id=chat_id, action="typing")
    try:
        reply = billybot_api.chat(chat_id, chat_histories[chat_id])
        chat_histories[chat_id].append({"role": "assistant", "content": reply})
        await update.message.reply_text(f"BillyBot: {reply}")
    except Exception as e:
        logger.error(f"cmd_ask: {e}")
        await update.message.reply_text("AI is unavailable right now. Try again.")


async def cmd_remind(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = await get_linked_user(update)
    if not user:
        return
    await update.message.reply_text(
        f"Telegram reminders are active.\nChat ID: {update.effective_chat.id}\n\n"
        f"To adjust settings, go to your dashboard Settings tab."
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.startswith("/"):
        return
    context.args = text.split()
    await cmd_ask(update, context)


async def run_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN environment variable is required")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("help",    cmd_help))
    app.add_handler(CommandHandler("bills",   cmd_bills))
    app.add_handler(CommandHandler("all",     cmd_all))
    app.add_handler(CommandHandler("owe",     cmd_owe))
    app.add_handler(CommandHandler("summary", cmd_summary))
    app.add_handler(CommandHandler("paid",    cmd_paid))
    app.add_handler(CommandHandler("ask",     cmd_ask))
    app.add_handler(CommandHandler("remind",  cmd_remind))
    app.add_handler(CallbackQueryHandler(handle_pay_callback, pattern="^pay:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("🤖 BillyBot Telegram bot starting...")

    async with app:
        from scheduler import start_scheduler
        await start_scheduler(app.bot)
        await app.start()
        await app.updater.start_polling(drop_pending_updates=True)
        logger.info("✅ Bot is running and polling for updates")
        await asyncio.Event().wait()
        await app.updater.stop()
        await app.stop()


if __name__ == "__main__":
    asyncio.run(run_bot())

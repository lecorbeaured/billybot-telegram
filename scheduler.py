"""
BillyBot Reminder Scheduler
Runs daily at 8 AM ET, checks for bills due soon, sends Telegram messages.
"""
import logging
from datetime import datetime
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import api as billybot_api

logger = logging.getLogger(__name__)

CAT_EMOJI = {
    "Housing": "🏠", "Utilities": "⚡", "Insurance": "🛡️",
    "Subscriptions": "📺", "Transport": "🚗", "Food": "🍕",
    "Health": "💊", "Debt": "💳", "Other": "📌",
}


def days_until_due(due_day: int) -> int:
    today = datetime.now().day
    days = due_day - today
    if days < 0:
        days += 30
    return days


def format_reminder_message(user_name: str, due_bills: list) -> str:
    lines = [f"🤖 *BillyBot Morning Reminder*\n"]
    lines.append(f"Hey {user_name or 'there'}! You have {len(due_bills)} bill{'s' if len(due_bills) > 1 else ''} coming up:\n")

    for b in due_bills:
        days = days_until_due(b["due_day"])
        emoji = CAT_EMOJI.get(b.get("category", "Other"), "📌")
        amt = f"${float(b['amount']):.2f}"

        if days == 0:
            urgency = "⚠️ *Due TODAY*"
        elif days == 1:
            urgency = "🔴 Due *tomorrow*"
        elif days <= 3:
            urgency = f"🟠 Due in *{days} days*"
        else:
            urgency = f"📅 Due in *{days} days*"

        lines.append(f"{emoji} *{b['name']}* — {amt}\n   {urgency}")

    total = sum(float(b["amount"]) for b in due_bills)
    lines.append(f"\n💰 Total due soon: *${total:.2f}*")
    lines.append("\nUse /paid <bill name> to mark as paid, or /bills to see all.")
    return "\n".join(lines)


async def run_reminders(bot):
    """Called daily by scheduler. Sends reminders to all eligible users."""
    logger.info("[Scheduler] Running daily reminder check...")

    try:
        users = billybot_api.get_users_for_reminders()
    except Exception as e:
        logger.error(f"[Scheduler] Failed to fetch reminder users: {e}")
        return

    sent = 0
    for user in users:
        chat_id = user.get("telegram_chat_id")
        if not chat_id:
            continue

        days_before = [int(d) for d in user.get("days_before", "7,3,1").split(",")]

        try:
            bills = billybot_api.get_bills(int(chat_id))
        except Exception as e:
            logger.error(f"[Scheduler] Failed to get bills for chat_id {chat_id}: {e}")
            continue

        # Filter: unpaid bills whose days_until_due matches a reminder day
        due_bills = [
            b for b in bills
            if b.get("payment_count", 0) == 0
            and days_until_due(b["due_day"]) in days_before
        ]

        if not due_bills:
            continue

        msg = format_reminder_message(user.get("name", ""), due_bills)
        try:
            await bot.send_message(
                chat_id=int(chat_id),
                text=msg,
                parse_mode="Markdown"
            )
            sent += 1
            logger.info(f"[Scheduler] Sent reminder to {chat_id} for {len(due_bills)} bills")
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send to {chat_id}: {e}")

    logger.info(f"[Scheduler] Done. Sent {sent} reminders.")


def start_scheduler(bot):
    """Initialize and start the APScheduler."""
    scheduler = AsyncIOScheduler(timezone=pytz.timezone("America/New_York"))
    scheduler.add_job(
        run_reminders,
        trigger=CronTrigger(hour=8, minute=0),
        args=[bot],
        id="daily_reminders",
        name="Daily Bill Reminders",
        replace_existing=True,
        misfire_grace_time=3600,  # fire within 1hr if missed
    )
    scheduler.start()
    logger.info("[Scheduler] Daily reminders scheduled at 8:00 AM ET")
    return scheduler

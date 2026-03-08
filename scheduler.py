"""
BillyBot Reminder Scheduler - APScheduler 4.x compatible
"""
import logging
from datetime import datetime
from apscheduler import AsyncScheduler
from apscheduler.triggers.cron import CronTrigger
import api as billybot_api

logger = logging.getLogger(__name__)

CAT_EMOJI = {
    "Housing": "🏠", "Utilities": "⚡", "Insurance": "🛡️",
    "Subscriptions": "📺", "Transport": "🚗", "Food": "🍕",
    "Health": "💊", "Debt": "💳", "Other": "📌",
}


def days_until_due(due_day: int) -> int:
    today = datetime.now().day
    d = due_day - today
    return d if d >= 0 else d + 30


async def run_reminders(bot):
    logger.info("[Scheduler] Running daily reminder check...")
    try:
        users = billybot_api.get_users_for_reminders()
    except Exception as e:
        logger.error(f"[Scheduler] Failed to fetch users: {e}")
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
            logger.error(f"[Scheduler] Failed to get bills for {chat_id}: {e}")
            continue

        due_bills = [
            b for b in bills
            if b.get("payment_count", 0) == 0
            and days_until_due(b["due_day"]) in days_before
        ]
        if not due_bills:
            continue

        lines = [f"BillyBot Reminder\n\nHey {user.get('name', 'there')}! Bills coming up:\n"]
        for b in due_bills:
            days = days_until_due(b["due_day"])
            emoji = CAT_EMOJI.get(b.get("category", "Other"), "📌")
            lines.append(f"{emoji} {b['name']} — ${float(b['amount']):.2f} ({'due TODAY' if days == 0 else f'in {days} day(s)'})")
        total = sum(float(b["amount"]) for b in due_bills)
        lines.append(f"\nTotal: ${total:.2f}\nUse /paid <n> to mark as paid.")

        try:
            await bot.send_message(chat_id=int(chat_id), text="\n".join(lines))
            sent += 1
        except Exception as e:
            logger.error(f"[Scheduler] Failed to send to {chat_id}: {e}")

    logger.info(f"[Scheduler] Done. Sent {sent} reminders.")


async def start_scheduler(bot):
    """Start APScheduler 4.x async scheduler."""
    scheduler = AsyncScheduler()
    await scheduler.add_schedule(
        run_reminders,
        CronTrigger(hour=8, minute=0, timezone="America/New_York"),
        args=[bot],
        id="daily_reminders",
    )
    await scheduler.start_in_background()
    logger.info("[Scheduler] Daily reminders scheduled at 8:00 AM ET")
    return scheduler

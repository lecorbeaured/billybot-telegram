"""
BillyBot Telegram → Backend API Client
Handles all HTTP calls to the BillyBot Express backend.
"""
import os
import requests
from typing import Optional

API_BASE = os.getenv("BILLYBOT_API_URL", "http://localhost:3000")
BOT_SECRET = os.getenv("BOT_SECRET")  # shared secret between bot and backend


def _headers():
    return {
        "Content-Type": "application/json",
        "X-Bot-Secret": BOT_SECRET or "",
    }


def _get(path: str, params: dict = None) -> dict:
    r = requests.get(f"{API_BASE}{path}", headers=_headers(), params=params, timeout=10)
    r.raise_for_status()
    return r.json()


def _post(path: str, body: dict = None) -> dict:
    r = requests.post(f"{API_BASE}{path}", headers=_headers(), json=body or {}, timeout=10)
    r.raise_for_status()
    return r.json()


def _put(path: str, body: dict = None) -> dict:
    r = requests.put(f"{API_BASE}{path}", headers=_headers(), json=body or {}, timeout=10)
    r.raise_for_status()
    return r.json()


# ── Telegram auth linking ──────────────────────────────────────────────────────

def get_user_by_chat_id(chat_id: int) -> Optional[dict]:
    """Return the user record linked to this Telegram chat_id, or None."""
    try:
        data = _get(f"/api/telegram/user/{chat_id}")
        return data.get("user")
    except requests.HTTPError as e:
        if e.response.status_code == 404:
            return None
        raise


def generate_link_token(chat_id: int, username: str = "") -> str:
    """Generate a one-time link token for this chat_id."""
    data = _post("/api/telegram/token", {"chat_id": chat_id, "username": username})
    return data["token"]


# ── Bills ──────────────────────────────────────────────────────────────────────

def get_bills(chat_id: int) -> list:
    """Get all active bills for the user linked to chat_id."""
    data = _get(f"/api/telegram/bills/{chat_id}")
    return data.get("bills", [])


def mark_paid(chat_id: int, bill_id: int) -> dict:
    """Mark a bill as paid."""
    return _post(f"/api/telegram/bills/{bill_id}/pay", {"chat_id": chat_id})


def get_summary(chat_id: int) -> dict:
    """Get monthly summary for the user."""
    return _get(f"/api/telegram/summary/{chat_id}")


# ── AI Chat ────────────────────────────────────────────────────────────────────

def chat(chat_id: int, messages: list) -> str:
    """Send messages to BillyBot AI, return reply text."""
    data = _post(f"/api/telegram/chat/{chat_id}", {"messages": messages})
    return data.get("reply", "Sorry, I had trouble with that.")


# ── Reminders ─────────────────────────────────────────────────────────────────

def get_users_for_reminders() -> list:
    """Get all users with telegram reminders enabled (called by scheduler)."""
    data = _get("/api/telegram/reminder-users", {"secret": BOT_SECRET})
    return data.get("users", [])

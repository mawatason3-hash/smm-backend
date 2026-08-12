import asyncio
import httpx
from config import settings


async def send_email(to_email: str, subject: str, html: str) -> bool:
    """Send an email via Brevo (if configured). Returns True on success."""
    if not settings.BREVO_API_KEY:
        print("Brevo API key not configured; skipping email")
        return False

    payload = {
        "sender": {"name": settings.FROM_NAME, "email": settings.FROM_EMAIL},
        "to": [{"email": to_email}],
        "subject": subject,
        "htmlContent": html,
    }
    headers = {"api-key": settings.BREVO_API_KEY, "Content-Type": "application/json"}
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.post("https://api.brevo.com/v3/smtp/email", json=payload, headers=headers)
            resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Failed to send email via Brevo: {e}")
        return False


async def notify_admins(ticket):
    """Notify configured admin emails about a new ticket."""
    try:
        targets = [e.strip() for e in settings.ADMIN_NOTIFICATION_EMAILS.split(',') if e.strip()]
        if not targets:
            targets = [settings.FROM_EMAIL]

        subject = f"New ticket #{ticket.id} — Order {ticket.order_id}"
        html = f"<p>New ticket created:</p><ul><li>Order: {ticket.order_id}</li><li>Issue: {ticket.issue_type}</li><li>User: {ticket.user_id}</li><li>Description: {ticket.description}</li></ul>"
        for email in targets:
            await send_email(email, subject, html)
        await asyncio.sleep(0)
    except Exception as e:
        print(f"Failed to notify admins: {e}")

    return True
import os
import httpx

TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')


async def send_telegram_message(text: str) -> bool:
    """Send a message to the configured Telegram chat. Returns True on success."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text}

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.post(url, json=payload)
            return resp.status_code == 200
    except Exception:
        return False
        

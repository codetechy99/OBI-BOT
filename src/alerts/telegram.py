import os
import logging
import json
import urllib.request
import urllib.error

logger = logging.getLogger("telegram_alerts")

def is_telegram_connected() -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    return bool(token and chat_id)

def send_alert(msg: str) -> bool:
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not token or not chat_id:
        logger.info(f"[Telegram Alert - Console Fallback]: {msg}")
        print(f"[ALERT]: {msg}")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({"chat_id": chat_id, "text": msg}).encode("utf-8")
    headers = {"Content-Type": "application/json"}

    req = urllib.request.Request(url, data=payload, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                logger.info(f"Telegram alert sent successfully: {msg}")
                return True
            else:
                logger.warning(f"Failed to send Telegram alert, status code: {resp.status}")
                return False
    except Exception as e:
        logger.error(f"Error sending Telegram alert: {e}")
        return False

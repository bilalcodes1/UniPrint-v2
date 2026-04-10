import os
import ssl
import smtplib
import logging
import threading
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

import requests as http

logger = logging.getLogger(__name__)


def _smtp_email() -> str:
    return os.environ.get('SMTP_EMAIL', '')


def _smtp_password() -> str:
    return os.environ.get('SMTP_PASSWORD', '')


def _tg_token() -> str:
    return os.environ.get('TELEGRAM_BOT_TOKEN', '')


# ── Low-level senders ────────────────────────────────────────────────────────

def send_telegram(chat_id: str, text: str) -> bool:
    token = _tg_token()
    if not token:
        logger.warning('[notify] TELEGRAM_BOT_TOKEN not set')
        return False
    try:
        url = f'https://api.telegram.org/bot{token}/sendMessage'
        resp = http.post(url, json={
            'chat_id': chat_id.lstrip('@'),
            'text': text,
            'parse_mode': 'HTML',
        }, timeout=10)
        if resp.ok:
            return True
        logger.warning(f'[notify] Telegram error: {resp.status_code} {resp.text[:200]}')
        return False
    except Exception as e:
        logger.error(f'[notify] Telegram exception: {e}')
        return False


def send_email(to_email: str, subject: str, html_body: str) -> bool:
    email = _smtp_email()
    password = _smtp_password()
    if not email or not password:
        logger.warning('[notify] SMTP credentials not set')
        return False
    try:
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f'UniPrint \U0001f5a8\ufe0f <{email}>'
        msg['To'] = to_email
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))

        ctx = ssl.create_default_context()
        with smtplib.SMTP('smtp.gmail.com', 587) as server:
            server.ehlo()
            server.starttls(context=ctx)
            server.login(email, password)
            server.sendmail(email, to_email, msg.as_string())
        logger.info(f'[notify] Email sent to {to_email}')
        return True
    except Exception as e:
        logger.error(f'[notify] Email exception: {e}')
        return False


# ── High-level notification ───────────────────────────────────────────────────

def notify_ready(
    student_name: str,
    verification_code: str,
    contact: str,
    method: str,
    request_id: str,
) -> None:
    """
    Send 'ready for pickup' notification in a background thread.
    method: 'telegram' | 'email' | 'none'
    contact: chat_id / @username for Telegram, or email address
    """
    if method in ('none', '') or not contact:
        return

    first_name = student_name.split()[0] if student_name else 'الطالب'
    short_id = request_id[:8].upper()

    if method == 'telegram':
        text = (
            f'\U0001f5a8\ufe0f <b>UniPrint</b>\n\n'
            f'\u0623\u0647\u0644\u0627\u064b {first_name}! \u0637\u0644\u0628\u0643 \u062c\u0627\u0647\u0632 \u0644\u0644\u0627\u0633\u062a\u0644\u0627\u0645 \U0001f389\n\n'
            f'\u0631\u0645\u0632 \u0627\u0644\u062a\u062d\u0642\u0642: <code>{verification_code}</code>\n'
            f'\u0627\u0639\u0631\u0636\u0647 \u0644\u0633\u0639\u062f \u0639\u0646\u062f \u0627\u0644\u0643\u0627\u0648\u0646\u062a\u0631.\n\n'
            f'<i>\u0631\u0642\u0645 \u0627\u0644\u0637\u0644\u0628: {short_id}</i>'
        )
        threading.Thread(
            target=send_telegram, args=(contact, text), daemon=True
        ).start()

    elif method == 'email':
        subject = '\u0637\u0644\u0628\u0643 \u062c\u0627\u0647\u0632 \u0644\u0644\u0627\u0633\u062a\u0644\u0627\u0645 \u2013 UniPrint \U0001f5a8\ufe0f'
        html_body = f'''<!DOCTYPE html>
<html lang="ar" dir="rtl">
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F2F2F7;font-family:Arial,Helvetica,sans-serif;">
  <div style="max-width:480px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.10);">
    <div style="background:#2D6BE4;padding:24px;text-align:center;">
      <p style="margin:0;font-size:28px;">\U0001f5a8\ufe0f</p>
      <h1 style="margin:6px 0 0;color:#fff;font-size:20px;font-weight:700;">UniPrint</h1>
    </div>
    <div style="padding:28px 24px;">
      <p style="margin:0 0 8px;font-size:16px;color:#1C1C1E;">\u0623\u0647\u0644\u0627\u064b <strong>{first_name}</strong>،</p>
      <p style="margin:0 0 20px;font-size:15px;color:#3a3a3c;">\u0637\u0644\u0628\u0643 \u062c\u0627\u0647\u0632 \u0644\u0644\u0627\u0633\u062a\u0644\u0627\u0645 \U0001f389</p>
      <div style="background:#F2F2F7;border-radius:12px;padding:20px;text-align:center;margin-bottom:20px;">
        <p style="margin:0 0 6px;font-size:12px;color:#6C6C70;">\u0631\u0645\u0632 \u0627\u0644\u062a\u062d\u0642\u0642</p>
        <p style="margin:0;font-size:44px;font-weight:800;color:#2D6BE4;letter-spacing:10px;line-height:1.1;">{verification_code}</p>
        <p style="margin:8px 0 0;font-size:12px;color:#6C6C70;">\u0627\u0639\u0631\u0636\u0647 \u0644\u0633\u0639\u062f \u0639\u0646\u062f \u0627\u0644\u0643\u0627\u0648\u0646\u062a\u0631</p>
      </div>
      <p style="margin:0;font-size:12px;color:#AEAEB2;">\u0631\u0642\u0645 \u0627\u0644\u0637\u0644\u0628: {short_id}</p>
    </div>
  </div>
</body>
</html>'''
        threading.Thread(
            target=send_email, args=(contact, subject, html_body), daemon=True
        ).start()

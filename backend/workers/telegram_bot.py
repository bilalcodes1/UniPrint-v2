"""
UniPrint Telegram Bot Worker
Polls for /start commands, records chat_ids so students can receive notifications.
"""
import os
import logging
import threading
import time

import requests as http

logger = logging.getLogger(__name__)

_offset = 0
_running = False


def _token() -> str:
    return os.environ.get('TELEGRAM_BOT_TOKEN', '')


def _get_updates(offset: int, timeout: int = 20) -> list:
    token = _token()
    if not token:
        return []
    try:
        resp = http.get(
            f'https://api.telegram.org/bot{token}/getUpdates',
            params={'offset': offset, 'timeout': timeout, 'allowed_updates': ['message']},
            timeout=timeout + 5,
        )
        if resp.ok:
            return resp.json().get('result', [])
    except Exception as e:
        logger.debug(f'[bot] getUpdates error: {e}')
    return []


def _send(chat_id, text: str) -> None:
    token = _token()
    if not token:
        return
    try:
        http.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            json={'chat_id': chat_id, 'text': text, 'parse_mode': 'HTML'},
            timeout=10,
        )
    except Exception as e:
        logger.debug(f'[bot] send error: {e}')


def _handle_update(update: dict, db_path: str) -> None:
    from models import db_cursor

    msg = update.get('message') or update.get('edited_message')
    if not msg:
        return

    chat_id  = str(msg['chat']['id'])
    username = msg['chat'].get('username', '')
    text     = (msg.get('text') or '').strip()

    if text.startswith('/start'):
        with db_cursor(db_path) as cur:
            cur.execute(
                'INSERT OR REPLACE INTO telegram_chats(chat_id, username) VALUES(?,?)',
                (chat_id, username)
            )
        reply = (
            f'\U0001f5a8\ufe0f <b>UniPrint Bot</b>\n\n'
            f'\u0623\u0647\u0644\u0627\u064b \u0628\u0643! \u062a\u0645 \u062a\u0633\u062c\u064a\u0644\u0643 \u0628\u0646\u062c\u0627\u062d \u2705\n\n'
            f'\u0644\u062a\u0644\u0642\u064a \u0625\u0634\u0639\u0627\u0631\u0627\u062a \u0637\u0644\u0628\u0627\u062a\u0643\u060c \u0627\u0633\u062a\u062e\u062f\u0645 \u0647\u0630\u0627 \u0627\u0644\u0631\u0642\u0645 \u0639\u0646\u062f \u0625\u0631\u0633\u0627\u0644 \u0637\u0644\u0628\u0643:\n\n'
            f'<code>{chat_id}</code>\n\n'
            f'<i>\u0627\u0646\u0633\u062e \u0647\u0630\u0627 \u0627\u0644\u0631\u0642\u0645 \u0648\u0627\u0644\u0635\u0642\u0647 \u0641\u064a \u062e\u0627\u0646\u0629 Chat ID \u0639\u0646\u062f \u0627\u062e\u062a\u064a\u0627\u0631 \u0625\u0634\u0639\u0627\u0631 \u062a\u0644\u064a\u062c\u0631\u0627\u0645.</i>'
        )
        _send(chat_id, reply)
        logger.info(f'[bot] Registered chat_id={chat_id} username=@{username}')


def _poll_loop(db_path: str) -> None:
    global _offset, _running
    _running = True
    logger.info('[bot] Telegram polling started')
    while _running:
        if not _token():
            time.sleep(30)
            continue
        try:
            updates = _get_updates(_offset, timeout=20)
            for update in updates:
                _offset = update['update_id'] + 1
                _handle_update(update, db_path)
        except Exception as e:
            logger.error(f'[bot] poll loop error: {e}')
            time.sleep(5)


def start_bot(db_path: str) -> None:
    if not _token():
        logger.info('[bot] No TELEGRAM_BOT_TOKEN — bot disabled')
        return
    t = threading.Thread(target=_poll_loop, args=(db_path,), daemon=True)
    t.start()


def stop_bot() -> None:
    global _running
    _running = False

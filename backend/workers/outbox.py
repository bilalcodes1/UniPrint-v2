"""
Outbox Worker — polls unprocessed outbox events and emits Socket.IO notifications.
Run as a background thread inside the Flask app.
"""
import json
import time
import threading
import logging

logger = logging.getLogger('outbox')


def process_outbox(db_path, socketio):
    """Continuously poll the outbox table and emit pending events."""
    from models import db_cursor

    while True:
        try:
            with db_cursor(db_path) as cur:
                cur.execute('''SELECT id, event_type, payload FROM outbox
                               WHERE processed = 0 AND retries < 5
                               ORDER BY id ASC LIMIT 20''')
                rows = cur.fetchall()

            for row in rows:
                event_id   = row['id']
                event_type = row['event_type']
                try:
                    payload = json.loads(row['payload'])
                except Exception:
                    payload = {}

                try:
                    socketio.emit(event_type, payload)
                    with db_cursor(db_path) as cur:
                        cur.execute('UPDATE outbox SET processed = 1 WHERE id = ?', (event_id,))
                except Exception as e:
                    logger.warning(f'Outbox event {event_id} failed: {e}')
                    with db_cursor(db_path) as cur:
                        cur.execute('UPDATE outbox SET retries = retries + 1 WHERE id = ?', (event_id,))

        except Exception as e:
            logger.error(f'Outbox worker error: {e}')

        time.sleep(3)


def start_outbox_worker(db_path, socketio):
    t = threading.Thread(target=process_outbox, args=(db_path, socketio), daemon=True)
    t.start()
    return t

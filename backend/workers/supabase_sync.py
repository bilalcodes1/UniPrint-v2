"""
Supabase Sync Worker
- Polls Supabase every 10s for new 'online' requests → imports to SQLite
- Pushes status updates from outbox to Supabase
"""
import threading
import time
import json
import uuid
import random
import string
import os

_thread = None


def _gen_code():
    return ''.join(random.choices(string.digits, k=4))


def _poll_online_requests(db_path, sio):
    from supabase_client import get_supabase
    from models import db_cursor

    sb = get_supabase()
    if not sb:
        return

    try:
        # Fetch online requests not yet in SQLite (check by id)
        res = sb.table('print_requests') \
                .select('*') \
                .eq('source', 'online') \
                .eq('status', 'received') \
                .execute()

        for req in (res.data or []):
            req_id = req.get('id')
            if not req_id:
                continue

            with db_cursor(db_path) as cur:
                cur.execute('SELECT id FROM print_requests WHERE id = ?', (req_id,))
                if cur.fetchone():
                    continue  # already imported

                # upsert student
                h = req.get('student_national_id_hash', '')
                if h:
                    cur.execute('SELECT national_id_hash FROM students WHERE national_id_hash = ?', (h,))
                    if not cur.fetchone():
                        cur.execute('''INSERT INTO students (national_id_hash, name, last_seen)
                                       VALUES (?, ?, datetime('now'))''',
                                    (h, req.get('student_name', '')))

                # insert request
                cur.execute('''INSERT INTO print_requests
                               (id, student_national_id_hash, status, verification_code,
                                notes, notification_method, contact, source)
                               VALUES (?, ?, 'received', ?, ?, ?, ?, 'online')''',
                            (req_id,
                             h or None,
                             req.get('verification_code') or _gen_code(),
                             req.get('notes', ''),
                             req.get('notification_method', 'none'),
                             req.get('contact', '')))

            # Notify dashboard via socketio
            if sio:
                sio.emit('new_request', {
                    'request_id':        req_id,
                    'student_name':      req.get('student_name', 'طالب عبر الإنترنت'),
                    'source':            'online',
                    'verification_code': req.get('verification_code', ''),
                    'queue_position':    1,
                    'total_pages':       req.get('total_pages', 0),
                    'files_count':       0,
                })

            print(f'[supabase-sync] imported online request: {req_id}')

    except Exception as e:
        print(f'[supabase-sync] poll error: {e}')


def _sync_loop(db_path, sio):
    while True:
        try:
            _poll_online_requests(db_path, sio)
        except Exception as e:
            print(f'[supabase-sync] loop error: {e}')
        time.sleep(10)


def start_supabase_sync(db_path, sio=None):
    global _thread
    if os.environ.get('SUPABASE_URL') and os.environ.get('SUPABASE_SERVICE_KEY'):
        _thread = threading.Thread(target=_sync_loop, args=(db_path, sio), daemon=True)
        _thread.start()
        print('[supabase-sync] started (polling every 10s)')
    else:
        print('[supabase-sync] skipped (no SUPABASE_URL/SERVICE_KEY in env)')

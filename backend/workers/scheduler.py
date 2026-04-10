"""
APScheduler Worker
  - Scheduled library open/close (checks open_time / close_time from settings every minute)
  - Auto-delete files older than retention_days (runs daily at 03:00)
"""
import os
import shutil
import threading
import time
from datetime import datetime, timedelta


def _get_setting(db_path, key, default=''):
    from models import db_cursor
    try:
        with db_cursor(db_path) as cur:
            cur.execute("SELECT value FROM settings WHERE key=?", (key,))
            row = cur.fetchone()
            return row['value'] if row else default
    except Exception:
        return default


# ── Scheduled close ──────────────────────────────────────────────────────────
def _check_schedule(db_path, sio):
    import closed_state as cs
    try:
        enabled    = _get_setting(db_path, 'schedule_enabled', '0')
        if enabled != '1':
            return

        open_time  = _get_setting(db_path, 'open_time',  '08:00')
        close_time = _get_setting(db_path, 'close_time', '17:00')
        close_msg  = _get_setting(db_path, 'close_message', 'المكتبة مغلقة – يفتح الساعة ' + open_time)

        now = datetime.now().strftime('%H:%M')
        should_close = not (open_time <= now < close_time)

        current = cs.get()
        if current['closed'] != should_close:
            cs.set_closed(
                closed  = should_close,
                message = close_msg if should_close else 'المكتبة مفتوحة • تستقبل طلبات',
                sio     = sio,
            )
            state = 'مغلقة' if should_close else 'مفتوحة'
            print(f'[scheduler] library auto-{state} at {now}')
    except Exception as e:
        print(f'[scheduler] schedule check error: {e}')


# ── Retention (auto-delete) ───────────────────────────────────────────────────
def _run_retention(db_path, upload_folder):
    from models import db_cursor
    try:
        days = int(_get_setting(db_path, 'retention_days', '30'))
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()

        with db_cursor(db_path) as cur:
            cur.execute(
                "SELECT id FROM print_requests WHERE status='delivered' AND delivered_at < ?",
                (cutoff,)
            )
            old_ids = [r['id'] for r in cur.fetchall()]

        if not old_ids:
            return

        deleted = 0
        for req_id in old_ids:
            req_folder = os.path.join(upload_folder, req_id)
            if os.path.isdir(req_folder):
                shutil.rmtree(req_folder, ignore_errors=True)
                deleted += 1

        with db_cursor(db_path) as cur:
            placeholders = ','.join('?' * len(old_ids))
            cur.execute(f"DELETE FROM request_files WHERE request_id IN ({placeholders})", old_ids)
            cur.execute(f"DELETE FROM print_requests WHERE id IN ({placeholders})", old_ids)

        print(f'[retention] deleted {deleted} request folders ({days}-day policy)')
    except Exception as e:
        print(f'[retention] error: {e}')


# ── Main loop ────────────────────────────────────────────────────────────────
def _scheduler_loop(db_path, upload_folder, sio):
    last_retention_day = None
    while True:
        try:
            # Check schedule every 60 seconds
            _check_schedule(db_path, sio)

            # Run retention once per day at 03:xx
            now = datetime.now()
            if now.hour == 3 and last_retention_day != now.date():
                last_retention_day = now.date()
                _run_retention(db_path, upload_folder)

        except Exception as e:
            print(f'[scheduler] loop error: {e}')

        time.sleep(60)


def start_scheduler(db_path, upload_folder, sio=None):
    t = threading.Thread(
        target=_scheduler_loop,
        args=(db_path, upload_folder, sio),
        daemon=True,
    )
    t.start()
    print('[scheduler] started (schedule check every 60s, retention daily at 03:00)')

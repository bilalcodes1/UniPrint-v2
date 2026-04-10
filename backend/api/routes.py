import os
import uuid
import json
import random
import string
import hashlib
import mimetypes
import threading
from datetime import datetime, date

from flask import current_app, request, jsonify, send_file
from api import bp
from api.notifications import notify_ready
from models import db_cursor, row_to_dict
from extensions import socketio
from supabase_client import supabase_update_status, supabase_upsert_request
import closed_state as _cs

ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx', 'jpg', 'jpeg', 'png'}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB
MAX_FILES = 5


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def gen_verification_code():
    return ''.join(random.choices(string.digits, k=4))


def gen_id():
    return str(uuid.uuid4())


def db_path():
    return current_app.config['DB_PATH']


def count_pages(filepath, mime_type):
    try:
        if mime_type == 'application/pdf' or filepath.lower().endswith('.pdf'):
            import PyPDF2
            with open(filepath, 'rb') as f:
                reader = PyPDF2.PdfReader(f)
                return len(reader.pages)
    except Exception:
        pass
    return 1


def upsert_student(cur, national_id_hash, name=None, device_fingerprint=None):
    cur.execute('SELECT national_id_hash FROM students WHERE national_id_hash = ?', (national_id_hash,))
    if cur.fetchone():
        cur.execute('''UPDATE students SET last_seen = datetime('now'), updated_at = datetime('now')
                       WHERE national_id_hash = ?''', (national_id_hash,))
    else:
        cur.execute('''INSERT INTO students (national_id_hash, name, device_fingerprint, last_seen)
                       VALUES (?, ?, ?, datetime('now'))''',
                    (national_id_hash, name or '', device_fingerprint or ''))


def update_daily_stats(cur, pages=0):
    today = date.today().isoformat()
    cur.execute('''INSERT INTO daily_stats (date, total_pages_printed, total_requests)
                   VALUES (?, ?, 1)
                   ON CONFLICT(date) DO UPDATE SET
                       total_pages_printed = total_pages_printed + ?,
                       total_requests = total_requests + 1''',
                (today, pages, pages))


# ── POST /submit ─────────────────────────────────────────────────────────────
@bp.route('/submit', methods=['POST'])
def submit_request():
    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        return jsonify({'error': 'لم يتم إرفاق أي ملف'}), 400
    if len(files) > MAX_FILES:
        return jsonify({'error': f'الحد الأقصى {MAX_FILES} ملفات'}), 400

    national_id_hash = request.form.get('national_id_hash', '')
    student_name     = request.form.get('student_name', '')
    device_fp        = request.form.get('device_fingerprint', '')
    notif_method     = request.form.get('notification_method', 'none')
    contact          = request.form.get('contact', '')
    notes            = request.form.get('notes', '')

    if not national_id_hash:
        return jsonify({'error': 'الرقم الوطني مطلوب'}), 400

    copies_list = request.form.getlist('copies[]')
    color_list  = request.form.getlist('color[]')
    sides_list  = request.form.getlist('sides[]')

    request_id        = gen_id()
    verification_code = gen_verification_code()
    upload_folder     = current_app.config['UPLOAD_FOLDER']
    req_folder        = os.path.join(upload_folder, request_id)
    os.makedirs(req_folder, exist_ok=True)

    saved_files = []
    total_pages = 0

    for i, file in enumerate(files):
        if file.filename == '':
            continue
        if not allowed_file(file.filename):
            return jsonify({'error': f'نوع الملف غير مدعوم: {file.filename}'}), 400

        ext = file.filename.rsplit('.', 1)[1].lower()
        stored_name = f'{gen_id()}.{ext}'
        stored_path = os.path.join(req_folder, stored_name)
        file.save(stored_path)

        file_size = os.path.getsize(stored_path)
        if file_size > MAX_FILE_SIZE:
            os.remove(stored_path)
            return jsonify({'error': f'حجم الملف يتجاوز 20 MB: {file.filename}'}), 400

        mime_type = mimetypes.guess_type(file.filename)[0] or 'application/octet-stream'
        pages = count_pages(stored_path, mime_type)
        copies = int(copies_list[i]) if i < len(copies_list) else 1
        color  = 1 if (color_list[i].lower() in ('true', '1', 'yes') if i < len(color_list) else False) else 0
        sides  = sides_list[i] if i < len(sides_list) else 'single'

        total_pages += pages * copies
        saved_files.append({
            'id':            gen_id(),
            'original_name': file.filename,
            'stored_path':   stored_path,
            'pages':         pages,
            'copies':        copies,
            'color':         color,
            'sides':         sides,
            'file_size':     file_size,
            'mime_type':     mime_type,
        })

    with db_cursor(db_path()) as cur:
        upsert_student(cur, national_id_hash, student_name, device_fp)

        cur.execute('''INSERT INTO print_requests
                       (id, student_national_id_hash, status, verification_code,
                        notes, notification_method, contact)
                       VALUES (?, ?, 'received', ?, ?, ?, ?)''',
                    (request_id, national_id_hash, verification_code,
                     notes, notif_method, contact))

        for f in saved_files:
            cur.execute('''INSERT INTO request_files
                           (id, request_id, original_name, stored_path, pages,
                            copies, color, sides, file_size, mime_type)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                        (f['id'], request_id, f['original_name'], f['stored_path'],
                         f['pages'], f['copies'], f['color'], f['sides'],
                         f['file_size'], f['mime_type']))

        cur.execute('SELECT COUNT(*) as pos FROM print_requests WHERE status = "received"')
        queue_pos = cur.fetchone()['pos']

        cur.execute('''INSERT INTO outbox (event_type, payload) VALUES (?, ?)''',
                    ('new_request', json.dumps({'request_id': request_id})))

        update_daily_stats(cur, total_pages)

    payload = {
        'request_id':        request_id,
        'verification_code': verification_code,
        'queue_position':    queue_pos,
        'total_pages':       total_pages,
        'files_count':       len(saved_files),
        'student_name':      student_name,
    }
    socketio.emit('new_request', payload)

    return jsonify({
        'success':           True,
        'request_id':        request_id,
        'verification_code': verification_code,
        'queue_position':    queue_pos,
        'total_pages':       total_pages,
    }), 201


# ── GET /status/<id> ─────────────────────────────────────────────────────────
@bp.route('/status/<request_id>', methods=['GET'])
def get_status(request_id):
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT * FROM print_requests WHERE id = ?', (request_id,))
        req = row_to_dict(cur.fetchone())
        if not req:
            return jsonify({'error': 'الطلب غير موجود'}), 404

        cur.execute('SELECT * FROM request_files WHERE request_id = ?', (request_id,))
        files = [row_to_dict(r) for r in cur.fetchall()]

        cur.execute('''SELECT COUNT(*) as pos FROM print_requests
                       WHERE status = 'received'
                       AND created_at <= (SELECT created_at FROM print_requests WHERE id = ?)''',
                    (request_id,))
        queue_pos = cur.fetchone()['pos']

    req['files']          = files
    req['queue_position'] = queue_pos
    return jsonify(req)


# ── POST /print/<id> ─────────────────────────────────────────────────────────
@bp.route('/print/<request_id>', methods=['POST'])
def print_request(request_id):
    data = request.get_json(silent=True) or {}
    verification_code = data.get('verification_code', '')

    with db_cursor(db_path()) as cur:
        cur.execute('SELECT * FROM print_requests WHERE id = ?', (request_id,))
        req = row_to_dict(cur.fetchone())
        if not req:
            return jsonify({'error': 'الطلب غير موجود'}), 404
        if req['verification_code'] != verification_code:
            return jsonify({'error': 'رمز التحقق غير صحيح'}), 400
        if req['status'] not in ('received',):
            return jsonify({'error': f'حالة الطلب الحالية: {req["status"]}'}), 400

        cur.execute('''UPDATE print_requests SET status = 'waiting',
                       updated_at = datetime('now'), row_version = row_version + 1
                       WHERE id = ?''', (request_id,))

        cur.execute('INSERT INTO outbox (event_type, payload) VALUES (?, ?)',
                    ('print_started', json.dumps({'request_id': request_id})))

    socketio.emit('status_update', {'request_id': request_id, 'status': 'waiting'})
    threading.Thread(target=supabase_update_status, args=(request_id, 'waiting'), daemon=True).start()
    return jsonify({'success': True, 'status': 'waiting'})


# ── POST /ready/<id> ─────────────────────────────────────────────────────────
@bp.route('/ready/<request_id>', methods=['POST'])
def mark_ready(request_id):
    req = None
    student_name = ''
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT * FROM print_requests WHERE id = ?', (request_id,))
        req = row_to_dict(cur.fetchone())
        if not req:
            return jsonify({'error': 'الطلب غير موجود'}), 404
        if req['status'] != 'waiting':
            return jsonify({'error': f'حالة الطلب الحالية: {req["status"]}'}), 400

        cur.execute('SELECT name FROM students WHERE national_id_hash = ?',
                    (req['student_national_id_hash'],))
        row = cur.fetchone()
        student_name = row[0] if row else ''

        cur.execute('''UPDATE print_requests SET status = 'ready',
                       updated_at = datetime('now'), row_version = row_version + 1
                       WHERE id = ?''', (request_id,))
        cur.execute('INSERT INTO outbox (event_type, payload) VALUES (?, ?)',
                    ('print_ready', json.dumps({'request_id': request_id})))

    socketio.emit('status_update', {'request_id': request_id, 'status': 'ready'})
    threading.Thread(target=supabase_update_status, args=(request_id, 'ready'), daemon=True).start()

    notify_ready(
        student_name=student_name,
        verification_code=req['verification_code'],
        contact=req.get('contact', ''),
        method=req.get('notification_method', 'none'),
        request_id=request_id,
    )

    return jsonify({'success': True, 'status': 'ready'})


# ── POST /deliver/<id> ────────────────────────────────────────────────────────
@bp.route('/deliver/<request_id>', methods=['POST'])
def deliver_request(request_id):
    data = request.get_json(silent=True) or {}
    verification_code = data.get('verification_code', '')

    with db_cursor(db_path()) as cur:
        cur.execute('SELECT * FROM print_requests WHERE id = ?', (request_id,))
        req = row_to_dict(cur.fetchone())
        if not req:
            return jsonify({'error': 'الطلب غير موجود'}), 404
        if req['verification_code'] != verification_code:
            return jsonify({'error': 'رمز التحقق غير صحيح'}), 400
        if req['status'] not in ('ready', 'waiting'):  # accept both for backward compat
            return jsonify({'error': f'حالة غير متوقعة: {req["status"]}'}), 400

        cur.execute('''UPDATE print_requests SET status = 'delivered',
                       delivered_at = datetime('now'),
                       updated_at = datetime('now'),
                       row_version = row_version + 1
                       WHERE id = ?''', (request_id,))

        cur.execute('''UPDATE students SET total_prints = total_prints + 1
                       WHERE national_id_hash = (
                           SELECT student_national_id_hash FROM print_requests WHERE id = ?
                       )''', (request_id,))

        cur.execute('INSERT INTO outbox (event_type, payload) VALUES (?, ?)',
                    ('delivered', json.dumps({'request_id': request_id})))

    socketio.emit('status_update', {'request_id': request_id, 'status': 'delivered'})
    threading.Thread(target=supabase_update_status, args=(request_id, 'delivered'), daemon=True).start()
    return jsonify({'success': True, 'status': 'delivered'})


# ── POST /reject/<id> ────────────────────────────────────────────────────────
@bp.route('/reject/<request_id>', methods=['POST'])
def reject_request(request_id):
    data   = request.get_json(silent=True) or {}
    reason = data.get('reason', '').strip() or 'رُفض الطلب من قِبل المشرف'

    with db_cursor(db_path()) as cur:
        cur.execute('SELECT * FROM print_requests WHERE id = ?', (request_id,))
        req = row_to_dict(cur.fetchone())
        if not req:
            return jsonify({'error': 'الطلب غير موجود'}), 404
        if req['status'] in ('delivered', 'rejected'):
            return jsonify({'error': f'لا يمكن رفض طلب بحالة: {req["status"]}'}), 400

        cur.execute('''UPDATE print_requests SET status = 'rejected', updated_at = CURRENT_TIMESTAMP
                       WHERE id = ?''', (request_id,))
        cur.execute('INSERT INTO outbox (event_type, payload) VALUES (?, ?)',
                    ('rejected', json.dumps({'request_id': request_id, 'reason': reason})))

    socketio.emit('status_update', {'request_id': request_id, 'status': 'rejected', 'reason': reason})
    threading.Thread(target=supabase_update_status, args=(request_id, 'rejected'), daemon=True).start()
    return jsonify({'success': True, 'status': 'rejected'})


# ── GET /stats ────────────────────────────────────────────────────────────────
@bp.route('/stats', methods=['GET'])
def get_stats():
    today = date.today().isoformat()
    with db_cursor(db_path()) as cur:
        cur.execute('''SELECT COUNT(*) as total FROM print_requests
                       WHERE date(created_at) = ?''', (today,))
        today_total = cur.fetchone()['total']

        cur.execute('''SELECT COUNT(*) as done FROM print_requests
                       WHERE date(created_at) = ? AND status = 'delivered' ''', (today,))
        today_done = cur.fetchone()['done']

        cur.execute('''SELECT COUNT(*) as waiting FROM print_requests
                       WHERE status IN ('received', 'waiting')''')
        pending = cur.fetchone()['waiting']

        cur.execute('SELECT COALESCE(SUM(total_pages_printed), 0) as pages FROM daily_stats WHERE date = ?',
                    (today,))
        today_pages = cur.fetchone()['pages']

        cur.execute('SELECT COUNT(*) as students FROM students')
        total_students = cur.fetchone()['students']

    return jsonify({
        'today_total':    today_total,
        'today_done':     today_done,
        'pending':        pending,
        'today_pages':    today_pages,
        'total_students': total_students,
    })


# ── GET /requests/recent ─────────────────────────────────────────────────────
@bp.route('/requests/recent', methods=['GET'])
def recent_requests():
    per_page = min(int(request.args.get('per_page', request.args.get('limit', 20))), 100)
    page     = max(int(request.args.get('page', 1)), 1)
    offset   = (page - 1) * per_page
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT COUNT(*) as total FROM print_requests')
        total = cur.fetchone()['total']
        cur.execute('''SELECT r.*, s.name as student_name,
                       (SELECT COUNT(*) FROM request_files WHERE request_id = r.id) as files_count,
                       (SELECT COALESCE(SUM(pages * copies), 0) FROM request_files WHERE request_id = r.id) as total_pages
                       FROM print_requests r
                       LEFT JOIN students s ON r.student_national_id_hash = s.national_id_hash
                       ORDER BY r.created_at DESC LIMIT ? OFFSET ?''', (per_page, offset))
        rows = [row_to_dict(r) for r in cur.fetchall()]
    return jsonify({'items': rows, 'total': total, 'page': page,
                    'per_page': per_page, 'has_more': offset + len(rows) < total})


# ── GET /requests/search ─────────────────────────────────────────────────────
@bp.route('/requests/search', methods=['GET'])
def search_requests():
    q      = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip()
    limit  = min(int(request.args.get('limit', 50)), 200)

    conditions, params = [], []
    if q:
        conditions.append('(s.name LIKE ? OR r.id LIKE ? OR r.verification_code LIKE ?)')
        params += [f'%{q}%', f'%{q}%', f'%{q}%']
    if status:
        conditions.append('r.status = ?')
        params.append(status)

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    params.append(limit)

    with db_cursor(db_path()) as cur:
        cur.execute(f'''SELECT r.*, s.name as student_name,
                        (SELECT COUNT(*) FROM request_files WHERE request_id = r.id) as files_count,
                        (SELECT COALESCE(SUM(pages * copies), 0) FROM request_files WHERE request_id = r.id) as total_pages
                        FROM print_requests r
                        LEFT JOIN students s ON r.student_national_id_hash = s.national_id_hash
                        {where}
                        ORDER BY r.created_at DESC LIMIT ?''', params)
        rows = [row_to_dict(r) for r in cur.fetchall()]
    return jsonify(rows)


# ── GET /requests/<id> ────────────────────────────────────────────────────────
@bp.route('/requests/<request_id>', methods=['GET'])
def get_request(request_id):
    with db_cursor(db_path()) as cur:
        cur.execute('''SELECT r.*, s.name as student_name,
                       (SELECT COUNT(*) FROM request_files WHERE request_id = r.id) as files_count,
                       (SELECT COALESCE(SUM(pages * copies), 0) FROM request_files WHERE request_id = r.id) as total_pages
                       FROM print_requests r
                       LEFT JOIN students s ON r.student_national_id_hash = s.national_id_hash
                       WHERE r.id = ?''', (request_id,))
        req = row_to_dict(cur.fetchone())
        if not req:
            return jsonify({'error': 'الطلب غير موجود'}), 404
        cur.execute('SELECT * FROM request_files WHERE request_id = ?', (request_id,))
        req['files'] = [row_to_dict(r) for r in cur.fetchall()]
    return jsonify(req)


# ── GET /requests/<id>/files ──────────────────────────────────────────────────
@bp.route('/requests/<request_id>/files', methods=['GET'])
def get_request_files(request_id):
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT * FROM request_files WHERE request_id = ?', (request_id,))
        files = [row_to_dict(r) for r in cur.fetchall()]
    return jsonify(files)


# ── GET /files/<file_id>/preview ──────────────────────────────────────────────
@bp.route('/files/<file_id>/preview', methods=['GET'])
def preview_file(file_id):
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT * FROM request_files WHERE id = ?', (file_id,))
        f = row_to_dict(cur.fetchone())
    if not f or not os.path.exists(f['stored_path']):
        return jsonify({'error': 'الملف غير موجود'}), 404
    mime = f.get('mime_type') or 'application/octet-stream'
    return send_file(
        f['stored_path'],
        mimetype=mime,
        as_attachment=False,
        download_name=f.get('original_name', 'file'),
    )


# ── GET /student/<hash> ───────────────────────────────────────────────────────
@bp.route('/student/<national_id_hash>', methods=['GET'])
def get_student(national_id_hash):
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT * FROM students WHERE national_id_hash = ?', (national_id_hash,))
        student = row_to_dict(cur.fetchone())
    if not student:
        return jsonify({'error': 'الطالب غير موجود'}), 404
    return jsonify(student)


# ── POST /extract-national-id ─────────────────────────────────────────────────
@bp.route('/extract-national-id', methods=['POST'])
def extract_national_id():
    if 'image' not in request.files:
        return jsonify({'error': 'لم يتم إرفاق صورة'}), 400

    image_file = request.files['image']
    tmp_path = os.path.join('/tmp', f'ocr_{gen_id()}.jpg')
    image_file.save(tmp_path)

    try:
        try:
            import pytesseract
            from PIL import Image
            img = Image.open(tmp_path)
            text = pytesseract.image_to_string(img, lang='ara+eng', config='--psm 6 --oem 3')
        except ImportError:
            return jsonify({'success': False, 'error': 'OCR غير متاح على الخادم — استخدم Tesseract.js في المتصفح'}), 501

        import re
        digits = re.sub(r'\D', '', text)
        matches = re.findall(r'\d{12}', digits)
        national_id = matches[0] if matches else ''

        if national_id:
            id_hash = hashlib.sha256(national_id.encode()).hexdigest()
            return jsonify({'success': True, 'national_id': national_id, 'hash': id_hash})
        return jsonify({'success': False, 'error': 'لم يتم العثور على رقم وطني'}), 422
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)


# ── GET /disk ─────────────────────────────────────────────────────────────────
@bp.route('/disk', methods=['GET'])
def disk_info():
    import shutil
    upload_folder = current_app.config.get('UPLOAD_FOLDER', '.')
    try:
        total, used, free = shutil.disk_usage(upload_folder)
        pct_used = round(used / total * 100, 1)
        pct_free = round(free / total * 100, 1)
        return jsonify({
            'total_gb':  round(total / (1024**3), 2),
            'used_gb':   round(used  / (1024**3), 2),
            'free_gb':   round(free  / (1024**3), 2),
            'pct_used':  pct_used,
            'pct_free':  pct_free,
            'warning':   pct_free < 10,
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# ── GET/POST /closed ──────────────────────────────────────────────────────
@bp.route('/closed', methods=['GET'])
def get_closed():
    return jsonify(_cs.get())

@bp.route('/closed', methods=['POST'])
def set_closed():
    data = request.get_json(force=True, silent=True) or {}
    _cs.set_closed(
        closed=bool(data.get('closed', False)),
        message=data.get('message', 'المكتبة مغلقة حالياً'),
        sio=socketio,
    )
    return jsonify(_cs.get())


# ── POST /rating/<id> ─────────────────────────────────────────────────────
@bp.route('/rating/<request_id>', methods=['POST'])
def save_rating(request_id):
    data   = request.get_json(force=True, silent=True) or {}
    rating = int(data.get('rating', 0))
    if not 1 <= rating <= 5:
        return jsonify({'error': 'التقييم يجب أن يكون بين 1 و 5'}), 400
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT id FROM print_requests WHERE id = ?', (request_id,))
        if not cur.fetchone():
            return jsonify({'error': 'الطلب غير موجود'}), 404
        cur.execute('UPDATE print_requests SET rating = ? WHERE id = ?', (rating, request_id))
    return jsonify({'success': True, 'rating': rating})


# ── GET/POST /settings ────────────────────────────────────────────────────
@bp.route('/settings', methods=['GET'])
def get_settings():
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT key, value FROM settings')
        settings = {row['key']: row['value'] for row in cur.fetchall()}
    return jsonify(settings)

@bp.route('/settings', methods=['POST'])
def update_settings():
    data = request.get_json(force=True, silent=True) or {}
    if not data:
        return jsonify({'error': 'no data'}), 400
    with db_cursor(db_path()) as cur:
        for key, value in data.items():
            cur.execute(
                'INSERT INTO settings(key,value,updated_at) VALUES(?,?,datetime(\'now\')) '
                'ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at',
                (str(key), str(value))
            )
    return jsonify({'success': True})


# ── GET /setup/status ─────────────────────────────────────────────────────
@bp.route('/setup/status', methods=['GET'])
def setup_status():
    with db_cursor(db_path()) as cur:
        cur.execute("SELECT value FROM settings WHERE key='setup_complete'")
        row = cur.fetchone()
    complete = row and row['value'] == '1'
    return jsonify({'setup_complete': complete})


# ── GET /library/files ────────────────────────────────────────────────────
@bp.route('/library/files', methods=['GET'])
def library_files():
    page       = max(int(request.args.get('page', 1)), 1)
    per_page   = min(int(request.args.get('per_page', 30)), 100)
    department = request.args.get('department', '')
    stage      = request.args.get('stage', '')
    offset     = (page - 1) * per_page

    conditions, params = [], []
    if department:
        conditions.append('department = ?'); params.append(department)
    if stage:
        conditions.append('stage = ?');      params.append(stage)

    where = ('WHERE ' + ' AND '.join(conditions)) if conditions else ''
    with db_cursor(db_path()) as cur:
        cur.execute(f'SELECT COUNT(*) as total FROM library_files {where}', params)
        total = cur.fetchone()['total']
        cur.execute(
            f'SELECT * FROM library_files {where} ORDER BY department,stage,name LIMIT ? OFFSET ?',
            params + [per_page, offset]
        )
        rows = [row_to_dict(r) for r in cur.fetchall()]

    cur2_params = []
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT DISTINCT department FROM library_files WHERE department != \'\' ORDER BY department')
        departments = [r[0] for r in cur.fetchall()]
        cur.execute('SELECT DISTINCT stage FROM library_files WHERE stage != \'\' ORDER BY stage')
        stages = [r[0] for r in cur.fetchall()]

    return jsonify({'items': rows, 'total': total, 'page': page,
                    'per_page': per_page, 'has_more': offset + len(rows) < total,
                    'departments': departments, 'stages': stages})


# ── GET /library/search ────────────────────────────────────────────────────
@bp.route('/library/search', methods=['GET'])
def library_search():
    q        = request.args.get('q', '').strip()
    per_page = min(int(request.args.get('per_page', 20)), 50)
    if not q:
        return jsonify({'items': [], 'total': 0})
    like = f'%{q}%'
    with db_cursor(db_path()) as cur:
        cur.execute(
            '''SELECT * FROM library_files
               WHERE name LIKE ? OR subject LIKE ? OR professor LIKE ? OR department LIKE ?
               ORDER BY name LIMIT ?''',
            (like, like, like, like, per_page)
        )
        rows = [row_to_dict(r) for r in cur.fetchall()]
    return jsonify({'items': rows, 'total': len(rows)})


# ── POST /library/scan ─────────────────────────────────────────────────────
@bp.route('/library/scan', methods=['POST'])
def library_scan():
    from workers.library_indexer import start_index_async, is_indexing
    if is_indexing():
        return jsonify({'error': 'الفحص جارٍ بالفعل، يرجى الانتظار'}), 409

    with db_cursor(db_path()) as cur:
        cur.execute("SELECT value FROM settings WHERE key='library_path'")
        row = cur.fetchone()
    library_path = row['value'] if row else ''

    data = request.get_json(force=True, silent=True) or {}
    if data.get('path'):
        library_path = data['path']
        with db_cursor(db_path()) as cur:
            cur.execute(
                "INSERT INTO settings(key,value) VALUES('library_path',?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (library_path,)
            )

    if not library_path:
        return jsonify({'error': 'لم يتم تحديد مسار المكتبة'}), 400

    start_index_async(db_path(), library_path)
    return jsonify({'success': True, 'message': 'بدأ الفحص في الخلفية…', 'library_path': library_path})


# ── GET /library/scan/status ───────────────────────────────────────────────
@bp.route('/library/scan/status', methods=['GET'])
def library_scan_status():
    from workers.library_indexer import is_indexing
    with db_cursor(db_path()) as cur:
        cur.execute('SELECT COUNT(*) as total FROM library_files')
        total = cur.fetchone()['total']
    return jsonify({'indexing': is_indexing(), 'total_indexed': total})

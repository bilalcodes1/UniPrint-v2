"""
Library File Indexer
Scans LIBRARY_PATH recursively for PDF/DOCX files, counts pages,
and stores metadata in the library_files table.
"""
import os
import hashlib
import logging
import threading
import uuid
from datetime import datetime

logger = logging.getLogger(__name__)

_indexing = False
_lock = threading.Lock()


def _hash_file(path: str, chunk=65536) -> str:
    h = hashlib.md5()
    try:
        with open(path, 'rb') as f:
            while True:
                buf = f.read(chunk)
                if not buf:
                    break
                h.update(buf)
    except OSError:
        pass
    return h.hexdigest()


def _count_pages(path: str) -> int:
    ext = path.rsplit('.', 1)[-1].lower()
    try:
        if ext == 'pdf':
            import PyPDF2
            with open(path, 'rb') as f:
                return len(PyPDF2.PdfReader(f).pages)
    except Exception:
        pass
    return 1


def _parse_path_metadata(rel_path: str) -> dict:
    """
    Best-effort parse of folder structure:
    department/stage/subject/professor/filename
    e.g. علوم_الحاسوب/المرحلة_الثالثة/قواعد_البيانات/د_احمد/ملاحظات.pdf
    """
    parts = rel_path.replace('\\', '/').split('/')
    return {
        'department': parts[0] if len(parts) > 1 else '',
        'stage':      parts[1] if len(parts) > 2 else '',
        'subject':    parts[2] if len(parts) > 3 else '',
        'professor':  parts[3] if len(parts) > 4 else '',
    }


SUPPORTED = {'.pdf', '.doc', '.docx', '.ppt', '.pptx', '.xls', '.xlsx'}


def index_library(db_path: str, library_path: str, progress_cb=None) -> dict:
    """
    Walk library_path, index all supported files into library_files table.
    Returns {'indexed': N, 'skipped': N, 'errors': N}
    """
    global _indexing
    with _lock:
        if _indexing:
            return {'error': 'indexing already running'}
        _indexing = True

    from models import db_cursor

    stats = {'indexed': 0, 'skipped': 0, 'errors': 0}
    try:
        if not os.path.isdir(library_path):
            logger.error(f'[indexer] Library path not found: {library_path}')
            return {'error': f'المسار غير موجود: {library_path}'}

        all_files = []
        for root, _, files in os.walk(library_path):
            for fname in files:
                ext = os.path.splitext(fname)[1].lower()
                if ext in SUPPORTED:
                    all_files.append(os.path.join(root, fname))

        total = len(all_files)
        logger.info(f'[indexer] Found {total} files in {library_path}')

        for i, full_path in enumerate(all_files):
            try:
                rel_path = os.path.relpath(full_path, library_path)
                stat = os.stat(full_path)
                file_hash = _hash_file(full_path)

                with db_cursor(db_path) as cur:
                    cur.execute('SELECT hash FROM library_files WHERE path = ?', (rel_path,))
                    row = cur.fetchone()
                    if row and row[0] == file_hash:
                        stats['skipped'] += 1
                        continue

                    pages = _count_pages(full_path)
                    meta  = _parse_path_metadata(rel_path)
                    now   = datetime.utcnow().isoformat()

                    if row:
                        cur.execute('''UPDATE library_files
                            SET name=?,pages=?,size=?,modified=?,hash=?,
                                department=?,stage=?,subject=?,professor=?,indexed_at=?
                            WHERE path=?''',
                            (os.path.basename(full_path), pages, stat.st_size,
                             datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
                             file_hash, meta['department'], meta['stage'],
                             meta['subject'], meta['professor'], now, rel_path))
                    else:
                        cur.execute('''INSERT INTO library_files
                            (id,path,name,pages,size,modified,department,stage,
                             subject,professor,hash,indexed_at)
                            VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''',
                            (str(uuid.uuid4()), rel_path, os.path.basename(full_path),
                             pages, stat.st_size,
                             datetime.utcfromtimestamp(stat.st_mtime).isoformat(),
                             file_hash, meta['department'], meta['stage'],
                             meta['subject'], meta['professor'], now))

                stats['indexed'] += 1
                if progress_cb:
                    progress_cb(i + 1, total)

            except Exception as e:
                logger.error(f'[indexer] Error indexing {full_path}: {e}')
                stats['errors'] += 1

        logger.info(f'[indexer] Done: {stats}')
    finally:
        with _lock:
            _indexing = False

    return stats


def is_indexing() -> bool:
    return _indexing


def start_index_async(db_path: str, library_path: str) -> None:
    threading.Thread(
        target=index_library,
        args=(db_path, library_path),
        daemon=True
    ).start()

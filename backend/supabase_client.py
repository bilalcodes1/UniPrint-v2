"""Singleton Supabase client — uses service_role key for full access."""
import os
from functools import lru_cache

_client = None

def get_supabase():
    global _client
    if _client is not None:
        return _client
    url = os.environ.get('SUPABASE_URL', '')
    key = os.environ.get('SUPABASE_SERVICE_KEY', '')
    if not url or not key:
        return None
    try:
        from supabase import create_client
        _client = create_client(url, key)
        return _client
    except Exception as e:
        print(f'[supabase] client init failed: {e}')
        return None


def supabase_upsert_request(req_dict):
    """Push a request row to Supabase (fire-and-forget)."""
    sb = get_supabase()
    if not sb:
        return
    try:
        data = {
            'id':                       req_dict.get('id'),
            'student_national_id_hash': req_dict.get('student_national_id_hash'),
            'student_name':             req_dict.get('student_name', ''),
            'source':                   req_dict.get('source', 'lan'),
            'status':                   req_dict.get('status', 'received'),
            'verification_code':        req_dict.get('verification_code'),
            'notes':                    req_dict.get('notes', ''),
            'notification_method':      req_dict.get('notification_method', 'none'),
            'contact':                  req_dict.get('contact', ''),
            'total_pages':              req_dict.get('total_pages', 0),
            'created_at':               req_dict.get('created_at'),
            'updated_at':               req_dict.get('updated_at'),
        }
        sb.table('print_requests').upsert(data).execute()
    except Exception as e:
        print(f'[supabase] upsert_request failed: {e}')


def supabase_update_status(request_id: str, status: str):
    """Update status of a request in Supabase."""
    sb = get_supabase()
    if not sb:
        return
    try:
        from datetime import datetime, timezone
        sb.table('print_requests').update({
            'status':     status,
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }).eq('id', request_id).execute()
    except Exception as e:
        print(f'[supabase] update_status failed: {e}')

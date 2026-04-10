"""Shared in-memory library closed state (imported by routes + scheduler)."""
_state = {'closed': False, 'message': 'المكتبة مغلقة حالياً'}

def get():
    return dict(_state)

def set_closed(closed: bool, message: str = None, sio=None):
    _state['closed'] = closed
    if message is not None:
        _state['message'] = message
    if sio:
        sio.emit('closed_state', dict(_state))

"""
mDNS Worker — registers uniprint.local on the local network.
Requires: pip install zeroconf
On macOS/Windows with Bonjour: works out of the box.
"""
import socket
import threading
import time

_zeroconf = None
_info     = None


def _get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return '127.0.0.1'


def start_mdns(port: int = 5001):
    global _zeroconf, _info
    try:
        from zeroconf import ServiceInfo, Zeroconf
        import ipaddress

        ip_str = _get_local_ip()
        ip_bytes = socket.inet_aton(ip_str)

        _info = ServiceInfo(
            type_    = '_http._tcp.local.',
            name     = 'UniPrint._http._tcp.local.',
            addresses= [ip_bytes],
            port     = port,
            properties={
                b'path': b'/',
                b'version': b'2.0',
            },
            server   = 'uniprint.local.',
        )
        _zeroconf = Zeroconf()
        _zeroconf.register_service(_info)
        print(f'[mDNS] uniprint.local registered → http://{ip_str}:{port}')

    except ImportError:
        print('[mDNS] zeroconf not installed — skipping (pip install zeroconf)')
    except Exception as e:
        print(f'[mDNS] failed to register: {e}')


def stop_mdns():
    global _zeroconf, _info
    if _zeroconf and _info:
        try:
            _zeroconf.unregister_service(_info)
            _zeroconf.close()
        except Exception:
            pass

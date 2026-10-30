"""
Servidor local de blender-steroids: escucha en 127.0.0.1 y ejecuta cada pedido en el hilo
principal de Blender (un timer de bpy), que es el único donde bpy es seguro.

Protocolo: una conexión por pedido, una línea JSON {"cmd": "...", "args": {...}} y una línea JSON
de respuesta. Solo acepta conexiones de esta PC.
"""
import bpy
import json
import os
import socket

from . import ops

PORT = int(os.environ.get('BLENDER_STEROIDS_PORT', '9777'))
_sock = None


def running():
    return _sock is not None


def _handle(conn):
    conn.settimeout(15)
    data = b''
    while not data.endswith(b'\n'):
        chunk = conn.recv(1 << 16)
        if not chunk:
            break
        data += chunk
    try:
        req = json.loads(data.decode('utf-8'))
        if not isinstance(req, dict):
            raise ValueError
    except ValueError:
        # p. ej. un navegador que prueba el puerto: no es un pedido de blender-steroids
        conn.close()
        return
    resp = ops.dispatch(req)
    try:
        conn.settimeout(None)
        conn.sendall(json.dumps(resp, ensure_ascii=False, default=str).encode('utf-8') + b'\n')
    finally:
        conn.close()


def _tick():
    if _sock is None:
        return None
    try:
        conn, _ = _sock.accept()
    except (BlockingIOError, socket.timeout):
        return 0.1
    except OSError:
        return 0.5
    try:
        conn.setblocking(True)
        _handle(conn)
    except Exception as e:  # un pedido roto no debe matar el servidor
        print('blender-steroids:', e)
    return 0.01


def start(port=None):
    global _sock, PORT
    if _sock is not None:
        return PORT
    PORT = int(port or PORT)
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    if hasattr(socket, 'SO_EXCLUSIVEADDRUSE'):
        s.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
    s.bind(('127.0.0.1', PORT))
    s.listen(8)
    s.setblocking(False)
    _sock = s
    if not bpy.app.timers.is_registered(_tick):
        bpy.app.timers.register(_tick, first_interval=0.1, persistent=True)
    print('blender-steroids: escuchando en 127.0.0.1:%d' % PORT)
    return PORT


def stop():
    global _sock
    if bpy.app.timers.is_registered(_tick):
        bpy.app.timers.unregister(_tick)
    if _sock is not None:
        try:
            _sock.close()
        finally:
            _sock = None

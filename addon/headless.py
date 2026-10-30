"""
Modo sin interfaz: blender-cli lo ejecuta con
  blender -b [archivo.blend] --python headless.py -- <pedido.json> <respuesta.json>

El pedido es {"cmd", "args", "new": bool, "save": ruta|null}. Con "new" se parte de una escena
vacía; con "save" se guarda el .blend al terminar (solo si la operación salió bien).
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
from blender_steroids import ops  # noqa: E402

argv = sys.argv[sys.argv.index('--') + 1:]
req = json.load(open(argv[0], encoding='utf-8'))

if req.get('new'):
    bpy.ops.wm.read_homefile(use_empty=True, use_factory_startup=True)

resp = ops.dispatch(req)
if resp.get('ok') and req.get('save'):
    path = os.path.abspath(req['save'])
    os.makedirs(os.path.dirname(path), exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=path)
    resp['saved'] = path

with open(argv[1], 'w', encoding='utf-8') as f:
    json.dump(resp, f, ensure_ascii=False, default=str)

"""
Arranca el puente en un Blender abierto por `blender-cli launch` (blender --python startup.py),
aunque el add-on no esté instalado. Si el add-on ya está activo, no hace nada más.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import bpy  # noqa: E402
from blender_steroids import server  # noqa: E402


def _go():
    try:
        server.start()
    except OSError as e:
        print('blender-steroids: no se pudo abrir el puerto %d (%s)' % (server.PORT, e))
    return None


bpy.app.timers.register(_go, first_interval=0.5)

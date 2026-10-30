"""
blender-steroids: deja que tu agente de IA trabaje en el Blender que tienes abierto.

Al activarse abre un puerto local (127.0.0.1:9777) por el que blender-cli envía pedidos.
Panel en la Vista 3D -> barra lateral (N) -> pestaña «Steroids».
"""
bl_info = {
    'name': 'blender-steroids',
    'author': 'kennedy122112',
    'version': (1, 10, 0),
    'blender': (4, 2, 0),
    'location': 'Vista 3D > Barra lateral > Steroids',
    'description': 'Puente local entre tu agente de IA (Claude Code, Codex...) y Blender',
    'category': 'Development',
}

import bpy

from . import server


class BS_OT_toggle(bpy.types.Operator):
    bl_idname = 'blender_steroids.toggle'
    bl_label = 'Activar / detener el puente'
    bl_description = 'Abre o cierra el puerto local por el que habla el agente'

    def execute(self, context):
        if server.running():
            server.stop()
            self.report({'INFO'}, 'blender-steroids detenido')
        else:
            try:
                server.start()
                self.report({'INFO'}, 'blender-steroids escuchando en el puerto %d' % server.PORT)
            except OSError as e:
                self.report({'ERROR'}, 'No se pudo abrir el puerto %d: %s' % (server.PORT, e))
        return {'FINISHED'}


class BS_PT_panel(bpy.types.Panel):
    bl_label = 'blender-steroids'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Steroids'

    def draw(self, context):
        col = self.layout.column()
        if server.running():
            col.label(text='Conectado: puerto %d' % server.PORT, icon='LINKED')
            col.operator(BS_OT_toggle.bl_idname, text='Detener', icon='PAUSE')
        else:
            col.label(text='Detenido', icon='UNLINKED')
            col.operator(BS_OT_toggle.bl_idname, text='Activar', icon='PLAY')


def _autostart():
    if bpy.app.background:
        return None
    try:
        server.start()
    except OSError as e:
        # el puerto ya lo usa otro Blender abierto: este se queda sin puente
        print('blender-steroids: no se pudo abrir el puerto %d (%s)' % (server.PORT, e))
    return None


def register():
    bpy.utils.register_class(BS_OT_toggle)
    bpy.utils.register_class(BS_PT_panel)
    bpy.app.timers.register(_autostart, first_interval=1.0)


def unregister():
    server.stop()
    bpy.utils.unregister_class(BS_PT_panel)
    bpy.utils.unregister_class(BS_OT_toggle)

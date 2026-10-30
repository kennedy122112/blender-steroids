"""
Operaciones de blender-steroids dentro de Blender (bpy).

Las mismas funciones las usa el servidor en vivo (server.py, con Blender abierto) y el modo sin
interfaz (headless.py, con `blender -b`). Cada operación recibe un dict y devuelve un dict JSON.
"""
import bpy
import bmesh
import contextlib
import io
import json
import math
import os
import sys
import traceback
from mathutils import Vector

# ----------------------------------------------------------------------------------- utilidades

def _scene():
    return bpy.context.scene or bpy.data.scenes[0]


def _lin(c):
    # sRGB (lo que se ve en un selector de color) -> lineal (lo que guardan los nodos y las luces)
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _srgb(c):
    c = max(0.0, min(1.0, c))
    return c * 12.92 if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def color(v, alpha=1.0):
    """'#rrggbb', '#rgb', '#rrggbbaa' o [r, g, b(, a)] en 0-1 sRGB -> RGBA lineal."""
    if isinstance(v, str):
        h = v.strip().lstrip('#')
        if len(h) in (3, 4):
            h = ''.join(ch * 2 for ch in h)
        r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
        a = int(h[6:8], 16) / 255 if len(h) == 8 else alpha
    else:
        r, g, b = v[:3]
        a = v[3] if len(v) > 3 else alpha
    return (_lin(r), _lin(g), _lin(b), a)


def hexcolor(c):
    return '#' + ''.join('%02x' % round(_srgb(x) * 255) for x in c[:3])


def vec3(v, default=(0.0, 0.0, 0.0)):
    if v is None:
        return tuple(default)
    if isinstance(v, (int, float)):
        return (float(v),) * 3
    v = list(v)
    return tuple(float(x) for x in (v + list(default)[len(v):])[:3])


def r3(v, n=4):
    return [round(x, n) for x in v]


def _ctx():
    """Contexto con ventana para operadores (un timer del servidor no tiene ventana)."""
    wm = bpy.context.window_manager
    if wm and wm.windows and not bpy.context.window:
        win = wm.windows[0]
        return bpy.context.temp_override(window=win, screen=win.screen)
    return contextlib.nullcontext()


def _set_engine(scene, name):
    aliases = {
        'eevee': ['BLENDER_EEVEE', 'BLENDER_EEVEE_NEXT'],
        'cycles': ['CYCLES'],
        'workbench': ['BLENDER_WORKBENCH'],
    }
    for cand in aliases.get(name.lower(), [name]):
        try:
            scene.render.engine = cand
            return cand
        except TypeError:
            continue
    raise ValueError('Motor de render desconocido: %s (usa eevee, cycles o workbench)' % name)


def _snake(k):
    return ''.join('_' + c.lower() if c.isupper() else c for c in k)


def _path(p, base_dir):
    """Rutas de imágenes del spec: relativas a la carpeta del spec."""
    p = os.path.expanduser(p)
    if not os.path.isabs(p) and base_dir:
        p = os.path.join(base_dir, p)
    if not os.path.exists(p):
        raise FileNotFoundError('No existe la imagen %s' % p)
    return p


def _obj(name, required=True):
    o = bpy.data.objects.get(name)
    if o is None and required:
        raise KeyError('No existe el objeto «%s»' % name)
    return o


# ----------------------------------------------------------------------------------- lectura

def op_info(args):
    s = _scene()
    return {
        'blender': bpy.app.version_string,
        'background': bpy.app.background,
        'file': bpy.data.filepath or None,
        'unsaved': bpy.data.is_dirty,
        'scene': s.name,
        'engine': s.render.engine,
        'resolution': [s.render.resolution_x, s.render.resolution_y],
        'fps': s.render.fps,
        'frames': [s.frame_start, s.frame_end],
        'camera': s.camera.name if s.camera else None,
        'counts': {
            'objects': len(s.objects),
            'meshes': sum(1 for o in s.objects if o.type == 'MESH'),
            'lights': sum(1 for o in s.objects if o.type == 'LIGHT'),
            'cameras': sum(1 for o in s.objects if o.type == 'CAMERA'),
            'materials': len(bpy.data.materials),
            'collections': len(bpy.data.collections),
        },
    }


def _principled(mat):
    if not mat or not mat.node_tree:
        return None
    for n in mat.node_tree.nodes:
        if n.type == 'BSDF_PRINCIPLED':
            return n
    return None


def _mat_info(m):
    d = {'name': m.name, 'users': m.users}
    p = _principled(m)
    if p:
        d['color'] = hexcolor(p.inputs['Base Color'].default_value)
        d['metallic'] = round(p.inputs['Metallic'].default_value, 3)
        d['roughness'] = round(p.inputs['Roughness'].default_value, 3)
        es = p.inputs['Emission Strength'].default_value
        if es:
            d['emission'] = hexcolor(p.inputs['Emission Color'].default_value)
            d['emissionStrength'] = round(es, 3)
        tex = [n.image.filepath for n in m.node_tree.nodes if n.type == 'TEX_IMAGE' and n.image]
        if tex:
            d['textures'] = tex
    else:
        d['color'] = hexcolor(m.diffuse_color)
    return d


def _obj_info(o, detail=False):
    d = {
        'name': o.name,
        'type': o.type,
        'location': r3(o.location),
        'rotation': r3([math.degrees(a) for a in o.rotation_euler], 2),
        'scale': r3(o.scale),
        'dimensions': r3(o.dimensions),
        'collection': o.users_collection[0].name if o.users_collection else None,
    }
    if o.parent:
        d['parent'] = o.parent.name
    if o.hide_get() if bpy.context.view_layer.objects.get(o.name) else False:
        d['hidden'] = True
    if o.hide_render:
        d['hideRender'] = True
    mats = [s.material.name for s in o.material_slots if s.material]
    if mats:
        d['materials'] = mats
    if o.modifiers:
        d['modifiers'] = [{'name': m.name, 'type': m.type} for m in o.modifiers]
    if o.type == 'MESH':
        d['mesh'] = {'verts': len(o.data.vertices), 'faces': len(o.data.polygons)}
    elif o.type == 'LIGHT':
        d['light'] = {'type': o.data.type, 'energy': o.data.energy, 'color': hexcolor(o.data.color)}
    elif o.type == 'CAMERA':
        d['camera'] = {'lens': round(o.data.lens, 2), 'type': o.data.type}
    elif o.type == 'FONT':
        d['text'] = o.data.body
    if o.animation_data and o.animation_data.action:
        d['action'] = o.animation_data.action.name
    if detail:
        d['custom'] = {k: (v if isinstance(v, (int, float, str)) else str(v)) for k, v in o.items()}
        d['constraints'] = [{'name': c.name, 'type': c.type} for c in o.constraints]
        if o.modifiers:
            mods = []
            for m in o.modifiers:
                props = {}
                for p in m.bl_rna.properties:
                    if p.identifier in ('rna_type', 'name', 'type') or p.type in ('POINTER', 'COLLECTION'):
                        continue
                    try:
                        v = getattr(m, p.identifier)
                        props[p.identifier] = list(v) if hasattr(v, '__len__') and not isinstance(v, str) else v
                    except Exception:
                        pass
                mods.append({'name': m.name, 'type': m.type, 'props': props})
            d['modifiers'] = mods
    return d


def _coll_tree(c):
    return {'name': c.name, 'objects': len(c.objects), 'children': [_coll_tree(ch) for ch in c.children]}


def op_scene(args):
    s = _scene()
    if args.get('object'):
        return {'object': _obj_info(_obj(args['object']), detail=True)}
    world = None
    if s.world:
        world = {'name': s.world.name}
        bg = s.world.node_tree.nodes.get('Background') if s.world.node_tree else None
        if bg:
            world['color'] = hexcolor(bg.inputs['Color'].default_value)
            world['strength'] = round(bg.inputs['Strength'].default_value, 3)
            env = [n.image.filepath for n in s.world.node_tree.nodes if n.type == 'TEX_ENVIRONMENT' and n.image]
            if env:
                world['hdri'] = env[0]
    return {
        'info': op_info(args),
        'collections': _coll_tree(s.collection),
        'objects': [_obj_info(o) for o in s.objects],
        'materials': [_mat_info(m) for m in bpy.data.materials],
        'world': world,
    }


# ----------------------------------------------------------------------------------- geometría

GEOM_KEYS = ('type', 'size', 'radius', 'radius2', 'depth', 'segments', 'rings', 'subdivisions',
             'majorRadius', 'minorRadius', 'minorSegments', 'fill', 'vertices', 'edges', 'faces',
             'origin', 'xSegments', 'ySegments')

PRIMITIVES = {'cube', 'plane', 'grid', 'uv_sphere', 'sphere', 'ico_sphere', 'cylinder', 'cone',
              'torus', 'circle', 'monkey', 'mesh'}


def _fit(bm, target):
    """Escala la malla para que su caja mida exactamente `target` (None = no tocar ese eje)."""
    lo = [min(v.co[i] for v in bm.verts) for i in range(3)]
    hi = [max(v.co[i] for v in bm.verts) for i in range(3)]
    k = [(t / (hi[i] - lo[i])) if (t is not None and hi[i] - lo[i] > 1e-9) else 1.0 for i, t in enumerate(target)]
    bmesh.ops.scale(bm, vec=k, verts=bm.verts)


def _torus(bm, R, r, M, N):
    rows = []
    for i in range(M):
        th = 2 * math.pi * i / M
        row = []
        for j in range(N):
            ph = 2 * math.pi * j / N
            row.append(bm.verts.new(((R + r * math.cos(ph)) * math.cos(th),
                                     (R + r * math.cos(ph)) * math.sin(th),
                                     r * math.sin(ph))))
        rows.append(row)
    for i in range(M):
        for j in range(N):
            a, b = rows[i][j], rows[(i + 1) % M][j]
            c, d = rows[(i + 1) % M][(j + 1) % N], rows[i][(j + 1) % N]
            bm.faces.new((a, b, c, d))


def build_mesh(o, name):
    t = o.get('type', 'cube').lower()
    bm = bmesh.new()
    seg = int(o.get('segments', 32))
    r = float(o.get('radius', 0.5))
    if t == 'cube':
        bmesh.ops.create_cube(bm, size=1.0)
        _fit(bm, vec3(o.get('size', 1.0), (1, 1, 1)))
    elif t in ('plane', 'grid'):
        bmesh.ops.create_grid(bm, x_segments=int(o.get('xSegments', 1 if t == 'plane' else 10)),
                              y_segments=int(o.get('ySegments', 1 if t == 'plane' else 10)), size=1.0)
        s = o.get('size', 1.0)
        s = (s, s) if isinstance(s, (int, float)) else s
        _fit(bm, (s[0], s[1], None))
    elif t in ('uv_sphere', 'sphere'):
        bmesh.ops.create_uvsphere(bm, u_segments=seg, v_segments=int(o.get('rings', 16)), radius=r)
    elif t == 'ico_sphere':
        bmesh.ops.create_icosphere(bm, subdivisions=int(o.get('subdivisions', 2)), radius=r)
    elif t in ('cylinder', 'cone'):
        r2 = float(o.get('radius2', r if t == 'cylinder' else 0.0))
        bmesh.ops.create_cone(bm, cap_ends=True, cap_tris=False, segments=seg, radius1=r, radius2=r2,
                              depth=float(o.get('depth', 1.0)))
    elif t == 'circle':
        bmesh.ops.create_circle(bm, cap_ends=bool(o.get('fill', False)), segments=seg, radius=r)
    elif t == 'torus':
        _torus(bm, float(o.get('majorRadius', 0.5)), float(o.get('minorRadius', 0.15)),
               seg if 'segments' in o else 48, int(o.get('minorSegments', 12)))
    elif t == 'monkey':
        bmesh.ops.create_monkey(bm)
    elif t == 'mesh':
        vs = [bm.verts.new(vec3(v)) for v in o.get('vertices', [])]
        for e in o.get('edges', []):
            bm.edges.new((vs[e[0]], vs[e[1]]))
        for f in o.get('faces', []):
            bm.faces.new([vs[i] for i in f])
    else:
        bm.free()
        raise ValueError('Tipo de objeto desconocido: %s' % t)
    if o.get('origin') == 'bottom' and bm.verts:
        zmin = min(v.co.z for v in bm.verts)
        bmesh.ops.translate(bm, vec=(0, 0, -zmin), verts=bm.verts)
    bm.normal_update()
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me)
    bm.free()
    return me


def _geom_sig(o):
    return json.dumps({k: o[k] for k in GEOM_KEYS if k in o}, sort_keys=True)


# ----------------------------------------------------------------------------------- materiales

def _socket(node, *names):
    for n in names:
        if n in node.inputs:
            return node.inputs[n]
    return None


def build_material(spec, base_dir):
    m = bpy.data.materials.get(spec['name'])
    created = m is None
    if created:
        m = bpy.data.materials.new(spec['name'])
    if not m.node_tree:
        import warnings
        with warnings.catch_warnings():
            warnings.simplefilter('ignore')
            m.use_nodes = True
    nt = m.node_tree
    p = _principled(m)
    if p is None:
        p = nt.nodes.new('ShaderNodeBsdfPrincipled')
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_MATERIAL'), None) or nt.nodes.new('ShaderNodeOutputMaterial')
        nt.links.new(p.outputs[0], out.inputs['Surface'])
    vals = {
        'color': ('Base Color',), 'metallic': ('Metallic',), 'roughness': ('Roughness',),
        'ior': ('IOR',), 'alpha': ('Alpha',), 'transmission': ('Transmission Weight', 'Transmission'),
        'emission': ('Emission Color', 'Emission'), 'emissionStrength': ('Emission Strength',),
        'coat': ('Coat Weight',), 'sheen': ('Sheen Weight',), 'subsurface': ('Subsurface Weight',),
        'specular': ('Specular IOR Level',),
    }
    for key, names in vals.items():
        if key not in spec:
            continue
        sock = _socket(p, *names)
        if sock is None:
            continue
        v = spec[key]
        sock.default_value = color(v) if key in ('color', 'emission') else float(v)
    if 'emission' in spec and 'emissionStrength' not in spec:
        _socket(p, 'Emission Strength').default_value = 1.0
    if 'color' in spec:
        m.diffuse_color = color(spec['color'])   # color en el visor sólido
    if spec.get('alpha', 1) < 1 or spec.get('transmission', 0) > 0:
        for attr, val in (('surface_render_method', 'BLENDED'), ('blend_method', 'BLEND')):
            if hasattr(m, attr):
                try:
                    setattr(m, attr, val)
                except Exception:
                    pass
    if spec.get('texture'):
        path = _path(spec['texture'], base_dir)
        tex =next((n for n in nt.nodes if n.type == 'TEX_IMAGE' and n.label == 'bs_texture'), None)
        if tex is None:
            tex = nt.nodes.new('ShaderNodeTexImage')
            tex.label = 'bs_texture'
            tex.location = (p.location.x - 320, p.location.y)
        tex.image = bpy.data.images.load(path, check_existing=True)
        nt.links.new(tex.outputs['Color'], p.inputs['Base Color'])
    return m, created


# ----------------------------------------------------------------------------------- objetos

def _collection(name, parent=None):
    s = _scene()
    if not name:
        return s.collection
    c = bpy.data.collections.get(name)
    if c is None:
        c = bpy.data.collections.new(name)
        (bpy.data.collections.get(parent) if parent else s.collection).children.link(c)
    elif not any(c.name == ch.name for ch in s.collection.children_recursive):
        s.collection.children.link(c)
    return c


def _move_to(o, coll):
    if coll not in o.users_collection:
        coll.objects.link(o)
    for c in list(o.users_collection):
        if c != coll:
            c.objects.unlink(o)


def _new_object(spec, name):
    t = spec.get('type', 'cube').lower()
    if t in PRIMITIVES:
        return bpy.data.objects.new(name, build_mesh(spec, name)), 'MESH'
    if t == 'empty':
        o = bpy.data.objects.new(name, None)
        o.empty_display_type = spec.get('display', 'PLAIN_AXES').upper()
        o.empty_display_size = float(spec.get('size', 1.0))
        return o, 'EMPTY'
    if t == 'text':
        return bpy.data.objects.new(name, bpy.data.curves.new(name, 'FONT')), 'FONT'
    if t == 'light':
        return bpy.data.objects.new(name, bpy.data.lights.new(name, spec.get('light', 'POINT').upper())), 'LIGHT'
    if t == 'camera':
        return bpy.data.objects.new(name, bpy.data.cameras.new(name)), 'CAMERA'
    raise ValueError('Tipo de objeto desconocido: %s' % t)


def _apply_data(o, spec, warnings):
    t = {'FONT': 'text', 'LIGHT': 'light', 'CAMERA': 'camera'}.get(o.type)
    if t == 'text':
        cu = o.data
        if not cu.body:  # recién creado
            cu.align_y = 'CENTER'
        if 'text' in spec or not cu.body:
            cu.body = str(spec.get('text', spec.get('name')))
        for k, attr in (('size', 'size'), ('extrude', 'extrude'), ('bevelDepth', 'bevel_depth')):
            if k in spec:
                setattr(cu, attr, float(spec[k]))
        if 'align' in spec:
            cu.align_x = spec['align'].upper()
        if 'alignY' in spec:
            cu.align_y = spec['alignY'].upper()
    elif t == 'light':
        li = o.data
        want = spec.get('light', li.type).upper()
        if li.type != want:
            li.type = want
            li = o.data
        if 'energy' in spec:
            li.energy = float(spec['energy'])
        if 'color' in spec:
            li.color = color(spec['color'])[:3]
        if 'size' in spec:
            if li.type == 'AREA':
                li.size = float(spec['size'])
            elif li.type == 'SUN':
                li.angle = math.radians(float(spec['size']))
            else:
                li.shadow_soft_size = float(spec['size'])
        if li.type == 'SPOT':
            if 'spotSize' in spec:
                li.spot_size = math.radians(float(spec['spotSize']))
            if 'spotBlend' in spec:
                li.spot_blend = float(spec['spotBlend'])
    elif t == 'camera':
        ca = o.data
        if 'lens' in spec:
            ca.lens = float(spec['lens'])
        if spec.get('ortho'):
            ca.type = 'ORTHO'
            ca.ortho_scale = float(spec.get('orthoScale', ca.ortho_scale))
        if 'clipEnd' in spec:
            ca.clip_end = float(spec['clipEnd'])
        if 'focus' in spec:
            ca.dof.use_dof = True
            tgt = bpy.data.objects.get(spec['focus']) if isinstance(spec['focus'], str) else None
            if tgt:
                ca.dof.focus_object = tgt
            else:
                ca.dof.focus_distance = float(spec['focus'])
            ca.dof.aperture_fstop = float(spec.get('fstop', 2.8))
        if spec.get('active', True):
            _scene().camera = o


def _apply_transform(o, spec):
    if 'location' in spec:
        o.location = vec3(spec['location'])
    if 'rotation' in spec:
        o.rotation_mode = 'XYZ'
        o.rotation_euler = [math.radians(a) for a in vec3(spec['rotation'])]
    if 'scale' in spec:
        o.scale = vec3(spec['scale'], (1, 1, 1))


def _apply_materials(o, spec, warnings):
    names = spec.get('materials') or ([spec['material']] if spec.get('material') else None)
    if not names or o.type not in ('MESH', 'FONT', 'CURVE'):
        return
    mats = []
    for n in names:
        m = bpy.data.materials.get(n)
        if m is None:
            warnings.append('«%s»: material «%s» no existe' % (o.name, n))
        mats.append(m)
    data = o.data
    while len(data.materials) < len(mats):
        data.materials.append(None)
    for i, m in enumerate(mats):
        data.materials[i] = m
    # "faceMaterials": [indice de material por cara], para mallas con varios materiales
    if spec.get('faceMaterials') and o.type == 'MESH':
        for poly, idx in zip(data.polygons, spec['faceMaterials']):
            poly.material_index = int(idx)


def _look_at(o, target):
    tgt = Vector(vec3(target)) if not isinstance(target, str) else _obj(target).matrix_world.translation
    d = tgt - o.location
    if d.length > 1e-9:
        o.rotation_mode = 'XYZ'
        o.rotation_euler = d.to_track_quat('-Z', 'Y').to_euler()


def _bounds(objs):
    pts = [o.matrix_world @ Vector(c) for o in objs for c in o.bound_box]
    if not pts:
        return Vector((0, 0, 0)), 1.0
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    center = (lo + hi) / 2
    return center, max((p - center).length for p in pts)


VIEWS = {'iso': (1, -1, 0.8), 'front': (0, -1, 0.05), 'back': (0, 1, 0.05), 'right': (1, 0, 0.05),
         'left': (-1, 0, 0.05), 'top': (0, -0.001, 1)}


def frame_camera(cam, targets=None, direction='iso', margin=1.1):
    """Coloca la cámara para que se vean enteros los objetos indicados (o todas las mallas)."""
    s = _scene()
    if not targets or targets == 'all':
        objs = [o for o in s.objects if o.type in ('MESH', 'FONT', 'CURVE') and not o.hide_render]
    else:
        objs = [_obj(n) for n in targets]
    center, radius = _bounds(objs)
    d = Vector(VIEWS.get(direction, (1, -1, 0.8)) if isinstance(direction, str) else vec3(direction)).normalized()
    ca = cam.data
    rx, ry = s.render.resolution_x, s.render.resolution_y
    fov = ca.angle if ca.type != 'ORTHO' else None
    if fov is not None:
        # el lado corto de la imagen limita el campo de visión
        half = math.atan(math.tan(fov / 2) * (min(rx, ry) / max(rx, ry)))
        dist = radius * margin / math.sin(half)
    else:
        ca.ortho_scale = radius * 2 * margin * (max(rx, ry) / min(rx, ry))
        dist = radius * 4
    cam.location = center + d * dist
    ca.clip_end = max(ca.clip_end, dist + radius * 4)
    _look_at(cam, tuple(center))


def _fcurve_bag(o):
    ad = o.animation_data
    if not ad or not ad.action:
        return None
    try:
        from bpy_extras.anim_utils import action_get_channelbag_for_slot
        return action_get_channelbag_for_slot(ad.action, ad.action_slot)
    except Exception:
        return ad.action if hasattr(ad.action, 'fcurves') else None


def _apply_modifiers(o, specs, warnings):
    prev = list(o.get('bs_mods', []))
    names = []
    for i, ms in enumerate(specs):
        mtype = ms['type'].upper()
        mtype = {'SUBDIVISION': 'SUBSURF', 'SUBSURFACE': 'SUBSURF'}.get(mtype, mtype)
        name = ms.get('name', mtype.title() if i == 0 or mtype not in [s['type'].upper() for s in specs[:i]] else '%s.%d' % (mtype.title(), i))
        m = o.modifiers.get(name)
        if m is not None and m.type != mtype:
            o.modifiers.remove(m)
            m = None
        if m is None:
            m = o.modifiers.new(name, mtype)
        names.append(name)
        for k, v in ms.items():
            if k in ('type', 'name'):
                continue
            if k == 'object':
                m.object = _obj(v)
                continue
            if mtype == 'ARRAY' and k == 'offset':
                m.use_relative_offset = True
                m.relative_offset_displace = vec3(v)
                continue
            if mtype == 'ARRAY' and k == 'constantOffset':
                m.use_constant_offset = True
                m.use_relative_offset = False
                m.constant_offset_displace = vec3(v)
                continue
            if mtype == 'MIRROR' and k == 'axis':
                m.use_axis = [a in v.upper() for a in 'XYZ']
                continue
            if k == 'mirrorObject':
                m.mirror_object = _obj(v)
                continue
            attr = _snake(k)
            if not hasattr(m, attr):
                warnings.append('«%s»: el modificador %s no tiene «%s»' % (o.name, mtype, k))
                continue
            cur = getattr(m, attr)
            if isinstance(cur, float):
                v = math.radians(v) if attr.endswith('angle') or attr == 'angle_limit' else float(v)
            elif isinstance(cur, str) and isinstance(v, str):
                v = v.upper()
            setattr(m, attr, v)
    for old in prev:
        if old not in names and o.modifiers.get(old):
            o.modifiers.remove(o.modifiers[old])
    o['bs_mods'] = names


def _apply_animation(anims, warnings):
    out = 0
    for a in anims:
        o = _obj(a['object'])
        prop = a.get('property', 'location')
        target, path = (o.data, prop[5:]) if prop.startswith('data.') else (o, prop)
        if path == 'rotation':
            path = 'rotation_euler'
        # rehacer la animación de esa propiedad: se quitan sus claves anteriores
        bag = _fcurve_bag(o) if target is o else None
        if bag is not None:
            for fc in [fc for fc in bag.fcurves if fc.data_path == path]:
                bag.fcurves.remove(fc)
        for k in a['keys']:
            v = k['value']
            if path == 'rotation_euler':
                v = [math.radians(x) for x in vec3(v)]
            elif path in ('location', 'scale'):
                v = vec3(v, (1, 1, 1) if path == 'scale' else (0, 0, 0))
            elif path == 'color' or path.endswith('color'):
                v = color(v)[:3]
            setattr(target, path, v)
            target.keyframe_insert(data_path=path, frame=float(k['frame']))
            out += 1
        interp = a.get('interpolation', '').upper()
        bag = _fcurve_bag(o) if target is o else None
        if interp and bag is not None:
            for fc in bag.fcurves:
                if fc.data_path == path:
                    for kp in fc.keyframe_points:
                        kp.interpolation = interp
    return out


def _apply_scene(cfg, warnings, base_dir=None):
    s = _scene()
    if 'engine' in cfg:
        _set_engine(s, cfg['engine'])
    if 'resolution' in cfg:
        s.render.resolution_x, s.render.resolution_y = (int(x) for x in cfg['resolution'])
    if 'percentage' in cfg:
        s.render.resolution_percentage = int(cfg['percentage'])
    if 'fps' in cfg:
        s.render.fps = int(cfg['fps'])
    if 'frames' in cfg:
        s.frame_start, s.frame_end = (int(x) for x in cfg['frames'])
    if 'samples' in cfg:
        if s.render.engine == 'CYCLES':
            s.cycles.samples = int(cfg['samples'])
        else:
            s.eevee.taa_render_samples = int(cfg['samples'])
    if 'transparent' in cfg:
        s.render.film_transparent = bool(cfg['transparent'])
    if 'viewTransform' in cfg:
        s.view_settings.view_transform = cfg['viewTransform']
    if 'look' in cfg:
        s.view_settings.look = cfg['look']
    if 'unitScale' in cfg:
        s.unit_settings.scale_length = float(cfg['unitScale'])
    w = cfg.get('world')
    if w:
        world = s.world or bpy.data.worlds.new('World')
        s.world = world
        if not world.node_tree:
            import warnings as _w
            with _w.catch_warnings():
                _w.simplefilter('ignore')
                world.use_nodes = True
        nt = world.node_tree
        bg = nt.nodes.get('Background') or nt.nodes.new('ShaderNodeBackground')
        out = next((n for n in nt.nodes if n.type == 'OUTPUT_WORLD'), None) or nt.nodes.new('ShaderNodeOutputWorld')
        if not bg.outputs[0].links:
            nt.links.new(bg.outputs[0], out.inputs['Surface'])
        if 'color' in w:
            bg.inputs['Color'].default_value = color(w['color'])
        if 'strength' in w:
            bg.inputs['Strength'].default_value = float(w['strength'])
        if w.get('hdri'):
            env = nt.nodes.get('bs_hdri') or nt.nodes.new('ShaderNodeTexEnvironment')
            env.name = 'bs_hdri'
            env.image = bpy.data.images.load(_path(w['hdri'], base_dir), check_existing=True)
            nt.links.new(env.outputs['Color'], bg.inputs['Color'])


DEFAULT_OBJECTS = {'Cube': 'MESH', 'Light': 'LIGHT', 'Camera': 'CAMERA'}


def op_build(spec):
    """Crea o actualiza (por nombre) materiales, colecciones, objetos, luces, cámaras y animación."""
    warnings, created, updated, removed = [], [], [], []
    base_dir = spec.get('_baseDir')

    if spec.get('removeDefaults'):
        for n, t in DEFAULT_OBJECTS.items():
            o = bpy.data.objects.get(n)
            if o and o.type == t and 'bs_geom' not in o and 'bs_spec' not in o:
                bpy.data.objects.remove(o, do_unlink=True)
                removed.append(n)
    for n in spec.get('delete', []):
        o = bpy.data.objects.get(n)
        if o:
            bpy.data.objects.remove(o, do_unlink=True)
            removed.append(n)

    _apply_scene(spec.get('scene', {}), warnings, base_dir)

    mats_new = []
    for ms in spec.get('materials', []):
        _, was_new = build_material(ms, base_dir)
        if was_new:
            mats_new.append(ms['name'])

    for cs in spec.get('collections', []):
        cs = {'name': cs} if isinstance(cs, str) else cs
        _collection(cs['name'], cs.get('parent'))

    # 1ª pasada: crear/actualizar cada objeto con su geometría, transformación y material
    objs = []
    for os_ in spec.get('objects', []):
        name = os_['name']
        o = bpy.data.objects.get(name)
        t = os_.get('type', '').lower()
        if o is not None:
            # Un objeto existente conserva su malla salvo que el spec traiga parámetros de geometría:
            # así se le pueden cambiar material, posición o modificadores sin rehacerlo.
            if t:
                want = 'MESH' if t in PRIMITIVES else {'empty': 'EMPTY', 'text': 'FONT', 'light': 'LIGHT', 'camera': 'CAMERA'}.get(t)
                if o.type != want:
                    warnings.append('«%s» ya existe y es %s, no %s: se omite' % (name, o.type, want))
                    continue
            if t in PRIMITIVES and any(k in os_ for k in GEOM_KEYS if k != 'type') \
                    and o.get('bs_geom') != _geom_sig(os_):
                old = o.data
                o.data = build_mesh(os_, name)
                for m in old.materials:
                    o.data.materials.append(m)
                if old.users == 0:
                    bpy.data.meshes.remove(old)
                o['bs_geom'] = _geom_sig(os_)
            updated.append(name)
        else:
            t = t or 'cube'
            os_ = dict(os_, type=t)
            o, _ = _new_object(os_, name)
            if t in PRIMITIVES:
                o['bs_geom'] = _geom_sig(os_)
            created.append(name)
        o['bs_spec'] = 1
        if os_.get('collection') or not o.users_collection:
            _move_to(o, _collection(os_.get('collection')))
        _apply_data(o, os_, warnings)
        _apply_transform(o, os_)
        _apply_materials(o, os_, warnings)
        if o.type == 'MESH' and 'smooth' in os_:
            if os_['smooth']:
                o.data.shade_smooth()
            else:
                o.data.shade_flat()
        if 'hidden' in os_:
            o.hide_set(bool(os_['hidden'])) if bpy.context.view_layer.objects.get(o.name) else None
        if 'hideRender' in os_:
            o.hide_render = bool(os_['hideRender'])
        if os_.get('cutter'):
            o.display_type = 'WIRE'
            o.hide_render = True
        elif 'display' in os_ and t != 'empty':
            o.display_type = os_['display'].upper()
        objs.append((o, os_))

    # 2ª pasada: lo que depende de otros objetos (padre, booleanos, mirar a, encuadre).
    # Sin este update, los objetos recién creados tienen matrix_world en cero y al emparentarlos
    # perderían su posición.
    bpy.context.view_layer.update()
    for o, os_ in objs:
        if 'parent' in os_:
            p = _obj(os_['parent']) if os_['parent'] else None
            if o.parent != p:
                mw = o.matrix_world.copy()
                o.parent = p
                if p is not None:
                    o.matrix_parent_inverse = p.matrix_world.inverted()
                o.matrix_world = mw
        if 'dimensions' in os_:
            bpy.context.view_layer.update()
            o.dimensions = vec3(os_['dimensions'])
        if 'modifiers' in os_:
            _apply_modifiers(o, os_['modifiers'], warnings)
        for c in [c for c in o.constraints if c.name == 'bs_track']:
            o.constraints.remove(c)
        if os_.get('lookAt') is not None:
            if os_.get('track') and isinstance(os_['lookAt'], str):
                c = o.constraints.new('TRACK_TO')
                c.name = 'bs_track'
                c.target = _obj(os_['lookAt'])
                c.track_axis, c.up_axis = 'TRACK_NEGATIVE_Z', 'UP_Y'
            else:
                bpy.context.view_layer.update()
                _look_at(o, os_['lookAt'])

    bpy.context.view_layer.update()
    for o, os_ in objs:
        if o.type == 'CAMERA' and os_.get('frame'):
            frame_camera(o, os_['frame'], os_.get('view', 'iso'), float(os_.get('margin', 1.1)))

    keys = _apply_animation(spec.get('animation', []), warnings)

    if not bpy.app.background:
        try:
            with _ctx():
                bpy.ops.ed.undo_push(message='blender-steroids: build')
        except Exception:
            pass
    res = {'created': created, 'updated': updated, 'materialsCreated': mats_new, 'keyframes': keys}
    if removed:
        res['removed'] = removed
    if warnings:
        res['warnings'] = warnings
    res['camera'] = _scene().camera.name if _scene().camera else None
    return res


# ----------------------------------------------------------------------------------- archivo, código

def op_save(args):
    path = args.get('path') or bpy.data.filepath
    if not path:
        raise ValueError('El archivo no tiene nombre todavía: indica la ruta del .blend')
    path = os.path.abspath(path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _ctx():
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=bool(args.get('copy')))
    return {'saved': path, 'copy': bool(args.get('copy'))}


def op_open(args):
    path = os.path.abspath(args['path'])
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    with _ctx():
        bpy.ops.wm.open_mainfile(filepath=path)
    return {'opened': path}


def op_exec(args):
    """Ejecuta código Python con bpy. El script puede dejar su respuesta en la variable `result`."""
    ns = {'bpy': bpy, 'bmesh': bmesh, 'math': math, 'Vector': Vector, 'ops': sys.modules[__name__], 'result': None}
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        exec(compile(args['code'], args.get('filename', '<blender-steroids>'), 'exec'), ns)
    res = ns.get('result')
    try:
        json.dumps(res)
    except TypeError:
        res = repr(res)
    return {'result': res, 'stdout': buf.getvalue()[-20000:]}


# ----------------------------------------------------------------------------------- render, export
# Se ejecutan en una copia sin interfaz (headless.py): no congelan el Blender del usuario.

def op_render(args):
    s = _scene()
    path = os.path.abspath(args['path'])
    if args.get('engine'):
        _set_engine(s, args['engine'])
    if args.get('preview'):
        _set_engine(s, args.get('engine') or 'workbench')
        s.render.resolution_percentage = int(args.get('percentage', 50))
        if s.render.engine == 'BLENDER_WORKBENCH':
            sh = s.display.shading
            sh.light, sh.color_type = 'STUDIO', 'MATERIAL'
            sh.show_shadows = sh.show_cavity = True
    if args.get('samples'):
        if s.render.engine == 'CYCLES':
            s.cycles.samples = int(args['samples'])
        elif s.render.engine == 'BLENDER_EEVEE':
            s.eevee.taa_render_samples = int(args['samples'])
    if args.get('resolution'):
        s.render.resolution_x, s.render.resolution_y = (int(x) for x in args['resolution'])
    if args.get('percentage'):
        s.render.resolution_percentage = int(args['percentage'])
    if 'transparent' in args:
        s.render.film_transparent = bool(args['transparent'])
    if args.get('camera'):
        s.camera = _obj(args['camera'])
    if args.get('view') or s.camera is None:
        cam = bpy.data.objects.new('bs_vista', bpy.data.cameras.new('bs_vista'))
        s.collection.objects.link(cam)
        bpy.context.view_layer.update()
        frame_camera(cam, args.get('objects'), args.get('view') or 'iso')
        s.camera = cam
    if args.get('frame') is not None:
        s.frame_set(int(args['frame']))
    s.render.image_settings.file_format = 'JPEG' if path.lower().endswith(('.jpg', '.jpeg')) else 'PNG'
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    if args.get('animation'):
        if args.get('frames'):
            s.frame_start, s.frame_end = (int(x) for x in args['frames'])
        base, _ = os.path.splitext(path)
        s.render.filepath = base + '_####'
        bpy.ops.render.render(animation=True)
        return {'frames': [s.frame_start, s.frame_end], 'pattern': base + '_####.png', 'engine': s.render.engine,
                'camera': s.camera.name}
    s.render.filepath = path
    bpy.ops.render.render(write_still=True)
    pct = s.render.resolution_percentage / 100
    return {'image': path, 'engine': s.render.engine, 'camera': s.camera.name,
            'size': [int(s.render.resolution_x * pct), int(s.render.resolution_y * pct)]}


def op_export(args):
    path = os.path.abspath(args['path'])
    ext = os.path.splitext(path)[1].lower()
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    names = args.get('objects')
    sel = bool(names)
    if sel:
        for o in bpy.context.view_layer.objects:
            o.select_set(o.name in names)
        missing = [n for n in names if n not in bpy.data.objects]
        if missing:
            raise KeyError('No existen: %s' % ', '.join(missing))
    if ext in ('.glb', '.gltf'):
        bpy.ops.export_scene.gltf(filepath=path, export_format='GLB' if ext == '.glb' else 'GLTF_SEPARATE',
                                  use_selection=sel, export_apply=True)
    elif ext == '.fbx':
        bpy.ops.export_scene.fbx(filepath=path, use_selection=sel, apply_scale_options='FBX_SCALE_ALL')
    elif ext == '.obj':
        bpy.ops.wm.obj_export(filepath=path, export_selected_objects=sel, apply_modifiers=True)
    elif ext == '.stl':
        bpy.ops.wm.stl_export(filepath=path, export_selected_objects=sel, apply_modifiers=True)
    elif ext == '.ply':
        bpy.ops.wm.ply_export(filepath=path, export_selected_objects=sel, apply_modifiers=True)
    elif ext in ('.usd', '.usdc', '.usda', '.usdz'):
        bpy.ops.wm.usd_export(filepath=path, selected_objects_only=sel)
    else:
        raise ValueError('Formato no soportado: %s (glb, gltf, fbx, obj, stl, ply, usd)' % ext)
    return {'exported': path, 'bytes': os.path.getsize(path) if os.path.exists(path) else None}


# ----------------------------------------------------------------------------------- despacho

OPS = {
    'ping': lambda a: {'pong': True},
    'info': op_info,
    'scene': op_scene,
    'build': op_build,
    'exec': op_exec,
    'save': op_save,
    'open': op_open,
    'render': op_render,
    'export': op_export,
}


def dispatch(req):
    cmd = req.get('cmd')
    fn = OPS.get(cmd)
    if fn is None:
        return {'ok': False, 'error': 'Comando desconocido: %s' % cmd}
    try:
        out = fn(req.get('args') or {})
        return dict({'ok': True}, **out)
    except Exception as e:
        return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e), 'trace': traceback.format_exc()[-4000:]}

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
from mathutils import Euler, Vector

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
             'origin', 'xSegments', 'ySegments', 'points', 'radii', 'flat', 'cap', 'profile', 'roundness',
             'balls', 'resolution', 'threshold', 'curve', 'twist', 'thickness', 'onSurface')

PRIMITIVES = {'cube', 'plane', 'grid', 'uv_sphere', 'sphere', 'ico_sphere', 'cylinder', 'cone',
              'torus', 'circle', 'monkey', 'mesh', 'tube', 'lathe', 'superellipsoid', 'blobby', 'decal'}


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


def _curve_points(o):
    """Puntos de un tubo: `points` tal cual, o `curve` = [p0, p1, p2(, p3)] como Bézier (`segments` tramos)."""
    if o.get('curve'):
        c = [Vector(vec3(p)) for p in o['curve']]
        n = int(o.get('steps', 24))
        out = []
        for k in range(n + 1):
            t = k / n
            if len(c) == 3:
                out.append((1 - t) ** 2 * c[0] + 2 * (1 - t) * t * c[1] + t * t * c[2])
            else:
                out.append((1 - t) ** 3 * c[0] + 3 * (1 - t) ** 2 * t * c[1] + 3 * (1 - t) * t * t * c[2]
                           + t ** 3 * c[3])
        return out
    return [Vector(vec3(p)) for p in o.get('points', [])]


def _radii(o, n):
    """Radio por punto: `radii` lista (se interpola si tiene otro largo) o [inicio, fin], o `radius`."""
    rr = o.get('radii')
    if rr is None:
        return [float(o.get('radius', 0.05))] * n
    rr = [float(x) for x in rr]
    if len(rr) == n:
        return rr
    out = []
    for k in range(n):
        t = k / max(1, n - 1) * (len(rr) - 1)
        i = min(int(t), len(rr) - 2)
        out.append(rr[i] + (rr[i + 1] - rr[i]) * (t - i))
    return out


def _tube(bm, o):
    """Tubo por una curva con radio variable: colas, cuernos, mechones, cables, asas, tentáculos.
    `flat` < 1 lo aplana (cintas, hojas); `twist` gira la sección (grados de inicio a fin)."""
    pts = _curve_points(o)
    if len(pts) < 2:
        raise ValueError('tube necesita al menos 2 puntos (points o curve)')
    seg = int(o.get('segments', 16))
    radii = _radii(o, len(pts))
    flat = float(o.get('flat', 1.0))
    twist = math.radians(float(o.get('twist', 0.0)))
    up = Vector(vec3(o.get('up', (0, 0, 1))))
    rings, prev_side = [], None
    for i, p in enumerate(pts):
        tg = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
        if prev_side is None:
            side = tg.cross(up)
            if side.length < 1e-4:
                side = tg.cross(Vector((1, 0, 0)))
        else:   # transporte paralelo: la sección no se retuerce sola en las curvas
            side = prev_side - tg * prev_side.dot(tg)
        side.normalize()
        prev_side = side
        nrm = side.cross(tg).normalized()
        a0 = twist * i / max(1, len(pts) - 1)
        ring = []
        for j in range(seg):
            a = 2 * math.pi * j / seg
            x, y = math.cos(a) * radii[i], math.sin(a) * radii[i] * flat
            ring.append(bm.verts.new(p + (x * math.cos(a0) - y * math.sin(a0)) * side
                                     + (x * math.sin(a0) + y * math.cos(a0)) * nrm))
        rings.append(ring)
    for r0, r1 in zip(rings, rings[1:]):
        for j in range(seg):
            bm.faces.new((r0[j], r0[(j + 1) % seg], r1[(j + 1) % seg], r1[j]))
    if o.get('cap', True):
        for ring, p in ((rings[0], pts[0]), (rings[-1], pts[-1])):
            c = bm.verts.new(p)
            for j in range(seg):
                bm.faces.new((c, ring[j], ring[(j + 1) % seg]))


def _lathe(bm, o):
    """Perfil girado alrededor de Z: `profile` = [[radio, z], ...] de abajo arriba (jarrones, troncos,
    botellas, peones, lámparas). Un radio 0 cierra en un punto."""
    prof = [(float(r), float(z)) for r, z in o['profile']]
    seg = int(o.get('segments', 48))
    rings = []
    for r, z in prof:
        if r < 1e-6:
            rings.append([bm.verts.new((0, 0, z))])
        else:
            rings.append([bm.verts.new((r * math.cos(2 * math.pi * j / seg), r * math.sin(2 * math.pi * j / seg), z))
                          for j in range(seg)])
    for r0, r1 in zip(rings, rings[1:]):
        if len(r0) == 1 and len(r1) == 1:
            continue
        for j in range(seg):
            if len(r0) == 1:
                bm.faces.new((r0[0], r1[j], r1[(j + 1) % seg]))
            elif len(r1) == 1:
                bm.faces.new((r0[j], r0[(j + 1) % seg], r1[0]))
            else:
                bm.faces.new((r0[j], r0[(j + 1) % seg], r1[(j + 1) % seg], r1[j]))
    if o.get('cap', True):
        for ring in (rings[0], rings[-1]):
            if len(ring) > 1:
                bm.faces.new(ring)


def _superellipsoid(bm, o):
    """Caja redondeada / esfera / almohada: `size` [x, y, z] total y `roundness` [lados, arriba-abajo]
    entre 0 (caja) y 1 (elipsoide); >1 la vuelve más puntiaguda. Cabezas y cuerpos de vinilo, cojines, rocas."""
    sx, sy, sz = vec3(o.get('size', 1.0), (1, 1, 1))
    rd = o.get('roundness', 0.5)
    e2, e1 = (rd, rd) if isinstance(rd, (int, float)) else (rd[0], rd[1])
    e1, e2 = max(0.08, float(e1)), max(0.08, float(e2))
    nu, nv = int(o.get('segments', 64)), int(o.get('rings', 32))

    def f(w, e):
        return math.copysign(abs(w) ** e, w)
    rows = []
    for i in range(1, nv):
        v = -math.pi / 2 + math.pi * i / nv
        rows.append([bm.verts.new((sx / 2 * f(math.cos(v), e1) * f(math.cos(u), e2),
                                   sy / 2 * f(math.cos(v), e1) * f(math.sin(u), e2),
                                   sz / 2 * f(math.sin(v), e1)))
                     for u in (2 * math.pi * j / nu for j in range(nu))])
    for r0, r1 in zip(rows, rows[1:]):
        for j in range(nu):
            bm.faces.new((r0[j], r0[(j + 1) % nu], r1[(j + 1) % nu], r1[j]))
    bot, top = bm.verts.new((0, 0, -sz / 2)), bm.verts.new((0, 0, sz / 2))
    for j in range(nu):
        bm.faces.new((bot, rows[0][(j + 1) % nu], rows[0][j]))
        bm.faces.new((top, rows[-1][j], rows[-1][(j + 1) % nu]))


def _blobby(o, name):
    """Forma orgánica de bolas que se funden (metaballs) convertida en malla: `balls` =
    [[x, y, z, radio], ...] o [{"at": [x, y, z], "radius": r, "size": [sx, sy, sz]}]."""
    mb = bpy.data.metaballs.new(name + '_meta')
    mb.resolution = mb.render_resolution = float(o.get('resolution', 0.02))
    mb.threshold = float(o.get('threshold', 0.6))
    for b in o['balls']:
        e = mb.elements.new()
        if isinstance(b, dict):
            e.co, e.radius = vec3(b['at']), float(b.get('radius', 0.1))
            if b.get('size'):
                e.type = 'ELLIPSOID'
                e.size_x, e.size_y, e.size_z = vec3(b['size'])
        else:
            e.co, e.radius = b[:3], float(b[3])
        e.stiffness = 2.0
    tmp = bpy.data.objects.new(name + '_meta', mb)
    _scene().collection.objects.link(tmp)
    bpy.context.view_layer.update()
    me = bpy.data.meshes.new_from_object(tmp.evaluated_get(bpy.context.evaluated_depsgraph_get()))
    bpy.data.objects.remove(tmp, do_unlink=True)
    bpy.data.metaballs.remove(mb)
    if not me.vertices:
        raise ValueError('blobby no generó superficie: aumenta los radios o baja el threshold')
    return me


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
    elif t == 'tube':
        _tube(bm, o)
    elif t == 'lathe':
        _lathe(bm, o)
    elif t == 'superellipsoid':
        _superellipsoid(bm, o)
    elif t == 'blobby':
        bm.free()
        me = _blobby(o, name)
        if o.get('origin') == 'bottom':
            zmin = min(v.co.z for v in me.vertices)
            for v in me.vertices:
                v.co.z -= zmin
        me.name = name
        return me
    elif t == 'decal':
        # mancha de pintura: un disco muy fino que attach + shrinkwrap pegan a una superficie
        w, h = (o.get('size', 0.05),) * 2 if isinstance(o.get('size', 0.05), (int, float)) else o['size'][:2]
        bmesh.ops.create_uvsphere(bm, u_segments=int(o.get('segments', 40)), v_segments=16, radius=1.0)
        bmesh.ops.scale(bm, vec=(w / 2, h / 2, float(o.get('thickness', 0.0015))), verts=bm.verts)
    elif t == 'mesh':
        vs = [bm.verts.new(vec3(v)) for v in o.get('vertices', [])]
        for e in o.get('edges', []):
            bm.edges.new((vs[e[0]], vs[e[1]]))
        for f in o.get('faces', []):
            bm.faces.new([vs[i] for i in f])
        # caras escritas a mano: orientarlas todas hacia afuera
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    else:
        bm.free()
        raise ValueError('Tipo de objeto desconocido: %s' % t)
    if o.get('origin') == 'bottom' and bm.verts:
        zmin = min(v.co.z for v in bm.verts)
        bmesh.ops.translate(bm, vec=(0, 0, -zmin), verts=bm.verts)
    if t in ('tube', 'lathe', 'superellipsoid'):
        bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-6)
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
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


SIDES = {'front': (0, -1, 0), 'back': (0, 1, 0), 'left': (-1, 0, 0), 'right': (1, 0, 0), 'top': (0, 0, 1),
         'bottom': (0, 0, -1)}


def surface_hit(target, at, side='front'):
    """Punto y normal (mundo) de la superficie de `target` (con sus modificadores) vista desde `side`
    en el punto `at`: se lanza un rayo paralelo a `side` que pasa por `at`. None si no toca."""
    d = Vector(SIDES[side] if isinstance(side, str) else vec3(side)).normalized()
    at = Vector(vec3(at))
    center, radius = _bounds([target])
    origin = at - d * d.dot(at - center) + d * (radius * 4 + 1)
    inv = target.matrix_world.inverted()
    o_l = inv @ origin
    d_l = (inv.to_3x3() @ -d).normalized()
    hit, loc, nor, _ = target.ray_cast(o_l, d_l, depsgraph=bpy.context.evaluated_depsgraph_get())
    if not hit:
        return None, None
    return target.matrix_world @ loc, (target.matrix_world.to_3x3().inverted().transposed() @ nor).normalized()


def _attach(o, spec, warnings):
    """Coloca el objeto sobre la superficie de otro: ojos, botones, nubes, remaches, parches.
    `attach`: {to, side (front|back|left|right|top|bottom|[x,y,z]), at [x,y,z] (punto aproximado, por
    defecto la location), offset (separación), align (por defecto sí: su eje Z sigue la normal), spin (°)}."""
    a = spec['attach']
    tgt = _obj(a['to'])
    side = a.get('side', 'front')
    at = a.get('at', spec.get('location', list(o.location)))
    p, n = surface_hit(tgt, at, side)
    if p is None:
        warnings.append('«%s»: no toca a «%s» desde %s en %s' % (o.name, tgt.name, side, at))
        return
    off = float(a.get('offset', 0.0))
    if a.get('anchor') == 'base' and o.type == 'MESH' and o.data.vertices:
        # la base de la pieza (su punto más bajo en Z local) queda sobre la superficie: garras, cuernos,
        # botones y orejas sobresalen enteros sin calcular a mano la mitad de su largo
        off -= min(v.co.z for v in o.data.vertices) * o.scale.z
    if a.get('align', True):
        o.rotation_mode = 'XYZ'
        q = n.to_track_quat('Z', 'Y')
        if a.get('spin'):
            q = q @ Euler((0, 0, math.radians(float(a['spin']))), 'XYZ').to_quaternion()
        o.rotation_euler = q.to_euler()
    if o.parent:
        o.location = o.parent.matrix_world.inverted() @ (p + n * off)
    else:
        o.location = p + n * off
    if spec.get('type', '').lower() == 'decal' or a.get('wrap'):
        # se pega a la curva de la superficie, apilado sobre lo que haya debajo según offset
        # proyectado por su propio eje Z (la normal): conserva la forma; «el punto más cercano» la
        # rompía saltando a otras partes del cuerpo
        m = o.modifiers.get('bs_wrap') or o.modifiers.new('bs_wrap', 'SHRINKWRAP')
        m.target, m.wrap_method, m.offset = tgt, 'PROJECT', max(off, 0.0005)
        m.use_project_x = m.use_project_y = False
        m.use_project_z = True
        m.use_negative_direction = m.use_positive_direction = True
        o.modifiers.move(o.modifiers.find('bs_wrap'), 0)


def _on_surface(o, spec, warnings):
    """Tubo dibujado sobre una superficie (boca, líneas de la cara, costuras, ribetes): proyecta cada punto
    de `points`/`curve` sobre `onSurface.to` desde `side` y rehace la malla."""
    a = spec['onSurface']
    tgt = _obj(a['to'])
    side = a.get('side', 'front')
    off = float(a.get('offset', 0.0))
    pts = []
    for p in _curve_points(spec):
        q, n = surface_hit(tgt, p, side)
        if q is not None:
            pts.append(list(q + n * off))
    if len(pts) < 2:
        warnings.append('«%s»: la línea no toca a «%s» desde %s' % (o.name, tgt.name, side))
        return
    o.location, o.rotation_euler, o.scale = (0, 0, 0), (0, 0, 0), (1, 1, 1)
    old = o.data
    o.data = build_mesh(dict(spec, points=pts, curve=None), o.name)
    for m in old.materials:
        o.data.materials.append(m)
    if spec.get('smooth', True):
        o.data.shade_smooth()
    if old.users == 0:
        bpy.data.meshes.remove(old)


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
            prop = m.bl_rna.properties[attr]
            if prop.type == 'POINTER' and prop.fixed_type.identifier == 'Object':
                # cualquier propiedad que apunta a un objeto (target del shrinkwrap, offset_object...)
                setattr(m, attr, _obj(v) if v else None)
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

    # 3ª pasada: colocar sobre superficies ya evaluadas (con sus modificadores), en el orden del spec
    for o, os_ in objs:
        if os_.get('attach'):
            bpy.context.view_layer.update()
            _attach(o, os_, warnings)
        if os_.get('onSurface') and o.type == 'MESH':
            bpy.context.view_layer.update()
            _on_surface(o, os_, warnings)

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


def _load_pixels(path, h=None):
    """Imagen como array (alto, ancho, 4) de abajo arriba, opcionalmente escalada a la altura h."""
    import numpy as np
    im = bpy.data.images.load(path, check_existing=False)
    w0, h0 = im.size
    if h0 == 0:
        bpy.data.images.remove(im)
        raise ValueError('No se pudo leer la imagen %s' % path)
    if h and h != h0:
        im.scale(max(1, round(w0 * h / h0)), h)
    w, hh = im.size
    px = np.empty(w * hh * 4, dtype=np.float32)
    im.pixels.foreach_get(px)
    bpy.data.images.remove(im)
    return px.reshape(hh, w, 4)


def _resize(px, w, h):
    """Escala un array de imagen usando Blender (sin dependencias)."""
    import numpy as np
    im = bpy.data.images.new('bs_tmp', px.shape[1], px.shape[0], alpha=True, float_buffer=True)
    im.pixels.foreach_set(px.ravel())
    im.scale(max(1, w), max(1, h))
    nw, nh = im.size
    out = np.empty(nw * nh * 4, dtype=np.float32)
    im.pixels.foreach_get(out)
    bpy.data.images.remove(im)
    return out.reshape(nh, nw, 4)


def _subject_mask(px):
    """Figura de la referencia: lo que se aparta del color de fondo (la mediana del borde), sin líneas
    sueltas (cuadrícula del visor, gizmos): solo filas y columnas con suficiente figura."""
    import numpy as np
    if px[..., 3].min() < 0.5:                     # imagen con transparencia: el alfa ya es la figura
        return _fill_rows(px[..., 3] > 0.5)
    h, w = px.shape[:2]
    # fondo por fila (los visores y estudios suelen tener degradado vertical): mediana de los bordes
    b = max(4, w // 40)
    borde = np.concatenate([px[:, :b, :3], px[:, -b:, :3]], axis=1)
    fondo = np.median(borde, axis=1)                                   # (h, 3)
    ruido = np.abs(borde - fondo[:, None]).max(axis=2)
    m = np.abs(px[..., :3] - fondo[:, None]).max(axis=2) > max(0.035, float(np.percentile(ruido, 95)) * 1.5)
    # fuera las líneas sueltas (cuadrícula, gizmos): solo filas y columnas con bastante figura
    filas = m.sum(axis=1) > 0.06 * w
    cols = m.sum(axis=0) > 0.06 * h
    return _fill_rows(m & filas[:, None] & cols[None, :])


def _fill_rows(m):
    """Silueta llena: en cada fila, de la primera a la última columna de figura (tapa los huecos que
    dejan las zonas del mismo color que el fondo)."""
    import numpy as np
    out = np.zeros_like(m)
    salto = max(3, int(0.06 * m.shape[1]))          # huecos mayores separan la figura de líneas sueltas
    for y in np.nonzero(m.any(axis=1))[0]:
        xs = np.nonzero(m[y])[0]
        cortes = np.nonzero(np.diff(xs) > salto)[0]
        tramos = np.split(xs, cortes + 1)
        mayor = max(tramos, key=len)                # la figura es el tramo con más píxeles de la fila
        out[y, mayor[0]:mayor[-1] + 1] = True
    return out


def _bbox(mask):
    import numpy as np
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return None
    # recorte del 0.5 % para no depender de un píxel suelto
    return (int(np.percentile(xs, 0.5)), int(np.percentile(ys, 0.5)),
            int(np.percentile(xs, 99.5)), int(np.percentile(ys, 99.5)))


def _edges(mask):
    import numpy as np
    e = np.zeros_like(mask)
    e[1:-1, 1:-1] = mask[1:-1, 1:-1] & ~(mask[:-2, 1:-1] & mask[2:, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:])
    return e | np.roll(e, 1, 0) | np.roll(e, 1, 1)


def op_compose(args):
    """Referencia | render alineado | siluetas superpuestas, con guías cada 10 % del alto de la figura.
    El render se escala y se mueve para que su figura ocupe la misma caja que la de la referencia
    (alto igual, centrada en x, apoyada en la misma base). Devuelve medidas para comparar sin adivinar."""
    import numpy as np
    h = int(args.get('height', 800))
    ref = _load_pixels(args['reference'], h)
    ren = _load_pixels(args['render'])
    rmask = _subject_mask(ref)
    rb = _bbox(rmask)
    gmask_full = ren[..., 3] > 0.5
    gb = _bbox(gmask_full)
    info = {}
    if args.get('align', True) and rb and gb:
        k = (rb[3] - rb[1] + 1) / (gb[3] - gb[1] + 1)
        ren = _resize(ren, round(ren.shape[1] * k), round(ren.shape[0] * k))
        gmask_full = ren[..., 3] > 0.5
        gb = _bbox(gmask_full)
        canvas = np.zeros((h, ref.shape[1], 4), dtype=np.float32)
        dx = round((rb[0] + rb[2]) / 2 - (gb[0] + gb[2]) / 2)
        dy = rb[1] - gb[1]                              # misma base (filas de abajo arriba)
        ys, xs = slice(max(0, dy), min(h, ren.shape[0] + dy)), slice(max(0, dx), min(ref.shape[1], ren.shape[1] + dx))
        canvas[ys, xs] = ren[ys.start - dy:ys.stop - dy, xs.start - dx:xs.stop - dx]
        ren = canvas
        info['scale'] = round(k, 3)
    elif ren.shape[0] != h:
        ren = _resize(ren, round(ren.shape[1] * h / ren.shape[0]), h)
    gmask = ren[..., 3] > 0.5
    gb = _bbox(gmask)
    # el render va sobre gris medio; la referencia, si era transparente, sobre blanco
    a = ren[..., 3:4]
    ren[..., :3] = ren[..., :3] * a + 0.35 * (1 - a)
    ren[..., 3] = 1
    ra = ref[..., 3:4]
    ref[..., :3] = ref[..., :3] * ra + (1 - ra)
    ref[..., 3] = 1

    paneles = [ref, ren]
    if args.get('overlay', True) and rb and gb:
        ov = ref.copy()
        ov[..., :3] = ov[..., :3] * 0.45 + 0.3
        ov[_edges(rmask), :3] = (0.0, 0.85, 1.0)      # cian: referencia
        ov[_edges(gmask), :3] = (1.0, 0.2, 0.75)      # magenta: render
        paneles.append(ov)
    gap = 12
    W = sum(p.shape[1] for p in paneles) + gap * (len(paneles) - 1)
    canvas = np.full((h, W, 4), 0.5, dtype=np.float32)
    canvas[..., 3] = 1
    x = 0
    for p_ in paneles:
        canvas[:, x:x + p_.shape[1]] = p_
        x += p_.shape[1] + gap
    if args.get('guides', True):
        # guías cada 10 % del alto de la figura de la referencia (o de la imagen, si no se detectó)
        y0, y1 = (rb[1], rb[3]) if rb else (0, h - 1)
        for k in range(0, 11):
            y = int(y1 - (y1 - y0) * k / 10)
            canvas[y, :, :3] = canvas[y, :, :3] * 0.4 + np.array([0.0, 0.75, 1.0]) * 0.6
    out = os.path.abspath(args['path'])
    img = bpy.data.images.new('bs_compare', W, h, alpha=False)
    img.pixels.foreach_set(canvas.ravel())
    img.filepath_raw = out
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)

    res = {'image': out, 'size': [W, h], 'panels': ['referencia', 'render', 'siluetas'][:len(paneles)]}
    if rb and gb:
        rw_, rh_ = rb[2] - rb[0] + 1, rb[3] - rb[1] + 1
        gw_, gh_ = gb[2] - gb[0] + 1, gb[3] - gb[1] + 1
        inter = (rmask & gmask).sum()
        union = (rmask | gmask).sum()
        info.update({
            'aspectReference': round(rw_ / rh_, 3), 'aspectRender': round(gw_ / gh_, 3),
            'silhouetteIoU': round(float(inter / union), 3) if union else None,
            # ancho de la figura cada 10 % del alto (de abajo arriba), en fracción del alto
            'widthByGuideReference': [round(float(rmask[int(rb[1] + rh_ * (k + 0.5) / 10)].sum()) / rh_, 3)
                                      for k in range(10)],
            'widthByGuideRender': [round(float(gmask[int(gb[1] + gh_ * (k + 0.5) / 10)].sum()) / gh_, 3)
                                   for k in range(10)],
        })
    else:
        info['note'] = 'No se detectó la figura en la referencia o en el render: sin alineación ni medidas.'
    res['alignment'] = info
    return res


def _mask_crop(mask, h):
    """Silueta recortada a su caja y escalada (vecino más cercano) a la altura h."""
    import numpy as np
    b = _bbox(mask)
    if not b:
        return None
    m = mask[b[1]:b[3] + 1, b[0]:b[2] + 1]
    w = max(1, round(m.shape[1] * h / m.shape[0]))
    ys = (np.arange(h) * m.shape[0] / h).astype(int)
    xs = (np.arange(w) * m.shape[1] / w).astype(int)
    return m[ys][:, xs]


def _iou_aligned(a, b):
    """IoU de dos siluetas ya escaladas a la misma altura, centradas en x."""
    import numpy as np
    W = max(a.shape[1], b.shape[1])
    A = np.zeros((a.shape[0], W), bool)
    B = np.zeros((b.shape[0], W), bool)
    A[:, (W - a.shape[1]) // 2:(W - a.shape[1]) // 2 + a.shape[1]] = a
    B[:, (W - b.shape[1]) // 2:(W - b.shape[1]) // 2 + b.shape[1]] = b
    u = (A | B).sum()
    return float((A & B).sum() / u) if u else 0.0


def _fit_view(args, ref_mask):
    """Prueba ángulos de cámara (azimut y elevación) con renders rápidos de silueta y devuelve la
    dirección cuya silueta se parece más a la de la referencia."""
    import tempfile
    s = _scene()
    guardado = (s.render.engine, s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage,
                s.render.film_transparent, s.camera, s.render.filepath)
    H = 160
    ref_c = _mask_crop(ref_mask, H)
    rw = s.render.resolution_x * 220 / s.render.resolution_y
    s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = max(16, round(rw)), 220, 100
    _set_engine(s, 'workbench')
    s.render.film_transparent = True
    s.render.image_settings.file_format = 'PNG'
    cam = bpy.data.objects.new('bs_fit', bpy.data.cameras.new('bs_fit'))
    s.collection.objects.link(cam)
    s.camera = cam
    tmp = os.path.join(tempfile.mkdtemp(prefix='bs-fit-'), 'v.png')
    pruebas = []
    try:
        azs = args.get('fitAzimuths') or list(range(-75, 76, 15))
        els = args.get('fitElevations') or [0.0, 15.0, 30.0]
        for el in els:
            for az in azs:
                a, e = math.radians(az), math.radians(el)
                d = [math.sin(a) * math.cos(e), -math.cos(a) * math.cos(e), math.sin(e)]
                bpy.context.view_layer.update()
                frame_camera(cam, args.get('objects'), d)
                s.render.filepath = tmp
                bpy.ops.render.render(write_still=True)
                px = _load_pixels(tmp)
                m = _mask_crop(px[..., 3] > 0.5, H)
                iou = _iou_aligned(ref_c, m) if m is not None else 0.0
                pruebas.append((iou, az, el, d))
    finally:
        bpy.data.objects.remove(cam, do_unlink=True)
        (eng, s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage,
         s.render.film_transparent, s.camera, s.render.filepath) = guardado
        s.render.engine = eng
    pruebas.sort(key=lambda t: -t[0])
    iou, az, el, d = pruebas[0]
    return {'view': [round(x, 4) for x in d], 'azimuth': az, 'elevation': el, 'fitIoU': round(iou, 3),
            'tried': len(pruebas), 'top3': [{'azimuth': t[1], 'elevation': t[2], 'iou': round(t[0], 3)}
                                            for t in pruebas[:3]]}


def _z_by_guide(render_path, objs_names):
    """Altura del mundo (z) que cae en cada guía de la figura del render: 0 = base de la figura,
    10 = su punto más alto. Traduce «la guía 7» a «z = 0.62 m» sin adivinar."""
    from bpy_extras.object_utils import world_to_camera_view
    s = _scene()
    px = _load_pixels(render_path)
    b = _bbox(px[..., 3] > 0.5)
    cam = s.camera
    if not b or cam is None:
        return None
    if objs_names:
        objs = [_obj(n) for n in objs_names]
    else:
        objs = [o for o in s.objects if o.type in ('MESH', 'FONT', 'CURVE') and not o.hide_render]
    center, radius = _bounds(objs)
    lo = min((o.matrix_world @ Vector(c)).z for o in objs for c in o.bound_box)
    hi = max((o.matrix_world @ Vector(c)).z for o in objs for c in o.bound_box)
    h = px.shape[0]
    zs = [lo - 0.2 * (hi - lo) + (hi - lo) * 1.4 * i / 600 for i in range(601)]
    vs = [world_to_camera_view(s, cam, Vector((center.x, center.y, z))).y for z in zs]
    out = []
    for k in range(11):
        v = (b[1] + (b[3] - b[1]) * k / 10) / h
        i = min(range(len(vs)), key=lambda j: abs(vs[j] - v))
        out.append(round(zs[i], 3))
    return out


def op_compare(args):
    """Render con fondo transparente y el formato de la referencia, alineado a su figura."""
    ref = bpy.data.images.load(os.path.abspath(args['reference']), check_existing=False)
    rw, rh = ref.size
    bpy.data.images.remove(ref)
    if not rw or not rh:
        raise ValueError('No se pudo leer la referencia %s' % args['reference'])
    k = 900 / max(rw, rh)
    s = _scene()
    s.render.resolution_x, s.render.resolution_y = max(16, round(rw * k)), max(16, round(rh * k))
    s.render.resolution_percentage = 100
    out = os.path.abspath(args['path'])
    tmp = os.path.splitext(out)[0] + '_render.png'
    fit = None
    if args.get('fitView'):
        fit = _fit_view(args, _subject_mask(_load_pixels(os.path.abspath(args['reference']), 400)))
        args = dict(args, view=fit['view'])
    # transparente: así la figura del render se separa del fondo sin adivinar
    r = op_render(dict(args, path=tmp, percentage=100, transparent=True))
    zg = _z_by_guide(tmp, args.get('objects'))
    c = op_compose({'reference': os.path.abspath(args['reference']), 'render': tmp, 'path': out,
                    'height': int(args.get('height', 800)), 'guides': args.get('guides', True),
                    'align': args.get('align', True), 'overlay': args.get('overlay', True)})
    if zg:
        c['alignment']['zByGuide'] = zg
    if fit:
        c['fitView'] = fit
    return dict(c, render=tmp, camera=r.get('camera'), engine=r.get('engine'))


# ----------------------------------------------------------------------------------- revisión geométrica

def _world_bvh(o, dg):
    """BVH de la malla evaluada (con modificadores) en coordenadas del mundo, y una muestra de vértices."""
    from mathutils.bvhtree import BVHTree
    e = o.evaluated_get(dg)
    me = e.to_mesh()
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.transform(o.matrix_world)
    e.to_mesh_clear()
    bmesh.ops.triangulate(bm, faces=bm.faces)
    tree = BVHTree.FromBMesh(bm)
    # puntos repartidos por ÁREA de la superficie, no por vértices: un cono tiene casi todos sus
    # vértices en la base y contarlos daba por «enterrada» una garra que sale de la mano
    import random
    rnd = random.Random(0)
    tris = [[v.co.copy() for v in f.verts] for f in bm.faces]
    bm.free()
    areas = [((b - a).cross(c - a)).length / 2 for a, b, c in tris]
    total = sum(areas) or 1.0
    samples = []
    for (a, b, c), ar in zip(tris, areas):
        n = ar / total * 500
        k = int(n) + (1 if rnd.random() < n - int(n) else 0)
        for _ in range(k):
            u, v = rnd.random(), rnd.random()
            if u + v > 1:
                u, v = 1 - u, 1 - v
            samples.append(a + (b - a) * u + (c - a) * v)
    if not samples:
        samples = [t[0] for t in tris[:50]]
    return tree, samples


def _inside_fraction(samples, tree):
    """Fracción de los puntos que quedan dentro de una malla cerrada (normal del punto más cercano)."""
    if not samples:
        return 0.0
    dentro = 0
    for v in samples:
        loc, nor, _, dist = tree.find_nearest(v)
        if loc is not None and (v - loc).dot(nor) < -1e-5:
            dentro += 1
    return dentro / len(samples)


def op_check(args):
    """Busca problemas de armado: piezas que flotan sin tocar nada, piezas enterradas dentro de otra
    (no se ven) y piezas que se atraviesan. Ignora cámaras, luces, cortadores y lo oculto en el render."""
    tol = float(args.get('tolerance', 0.004))
    nombres = args.get('objects')
    s = _scene()
    dg = bpy.context.evaluated_depsgraph_get()
    objs = [o for o in s.objects if o.type in ('MESH', 'FONT', 'CURVE') and not o.hide_render
            and o.display_type not in ('WIRE', 'BOUNDS')]
    if nombres:
        objs = [o for o in objs if o.name in nombres] + [o for o in objs if o.name not in nombres]
    data = {}
    for o in objs:
        try:
            data[o.name] = _world_bvh(o, dg)
        except Exception:
            continue
    names = [o.name for o in objs if o.name in data]
    decal = {o.name for o in objs if o.get('bs_geom') and '"decal"' in o['bs_geom']}
    boxes = {}
    for n in names:
        pts = data[n][1]
        lo = Vector([min(p[i] for p in pts) for i in range(3)])
        hi = Vector([max(p[i] for p in pts) for i in range(3)])
        boxes[n] = (lo, hi)

    def cerca(a, b, m):
        (la, ha), (lb, hb) = boxes[a], boxes[b]
        return all(la[i] - m <= hb[i] and lb[i] - m <= ha[i] for i in range(3))

    tocando = {n: set() for n in names}
    cruces = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            if not cerca(a, b, tol):
                continue
            ta, sa = data[a]
            tb, sb = data[b]
            toca = bool(ta.overlap(tb))
            if not toca:
                # ¿a menos de tol? distancia mínima aproximada con la muestra de vértices
                toca = any((tb.find_nearest(v)[3] or 1e9) <= tol for v in sa) or \
                    any((ta.find_nearest(v)[3] or 1e9) <= tol for v in sb)
            if not toca:
                continue
            tocando[a].add(b)
            tocando[b].add(a)
            if a in decal or b in decal:
                continue
            fa, fb = _inside_fraction(sa, tb), _inside_fraction(sb, ta)
            if max(fa, fb) >= 0.02:
                cruces.append((a, b, fa, fb))

    enterrados, atraviesan = [], []
    for a, b, fa, fb in cruces:
        for x, y, f in ((a, b, fa), (b, a, fb)):
            if f >= 0.9:
                enterrados.append({'object': x, 'inside': y, 'fraction': round(f, 2)})
        if max(fa, fb) < 0.9:
            atraviesan.append({'a': a, 'b': b, 'aInsideB': round(fa, 2), 'bInsideA': round(fb, 2)})
    atraviesan.sort(key=lambda c: -max(c['aInsideB'], c['bInsideA']))

    suelo = min((boxes[n][0].z for n in names), default=0.0)
    flotan = [{'object': n, 'bottom': round(boxes[n][0].z, 4)} for n in names
              if not tocando[n] and boxes[n][0].z > suelo + tol]
    if nombres:
        sel = set(nombres)
        flotan = [f for f in flotan if f['object'] in sel]
        enterrados = [e for e in enterrados if e['object'] in sel]
        atraviesan = [c for c in atraviesan if c['a'] in sel or c['b'] in sel]
    return {'checked': len(names), 'floating': flotan, 'buried': enterrados,
            'intersecting': atraviesan[:40],
            'note': 'intersecting incluye uniones a propósito (orejas en la cabeza, manos en las mangas): '
                    'revisa sobre todo las fracciones altas y las piezas que deberían ir por fuera.'}


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
    'compare': op_compare,
    'compose': op_compose,
    'check': op_check,
}


def _bridge():
    """Versión y carpeta del add-on cargado: blender-cli las compara con las suyas."""
    from .version import VERSION
    return {'version': VERSION, 'path': os.path.dirname(os.path.realpath(__file__))}


def dispatch(req):
    cmd = req.get('cmd')
    fn = OPS.get(cmd)
    if fn is None:
        return {'ok': False, 'error': 'Comando desconocido: %s' % cmd, '_bridge': _bridge()}
    try:
        out = fn(req.get('args') or {})
        return dict({'ok': True}, **out, _bridge=_bridge())
    except Exception as e:
        return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e), 'trace': traceback.format_exc()[-4000:],
                '_bridge': _bridge()}

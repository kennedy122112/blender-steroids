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
from mathutils import Euler, Matrix, Vector
from mathutils.geometry import tessellate_polygon

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
             'balls', 'resolution', 'threshold', 'curve', 'twist', 'thickness', 'onSurface', 'root', 'tip',
             'fingers', 'scallop', 'bend', 'bones', 'image', 'holes', 'width', 'height', 'tolerance', 'method',
             'plane', 'side', 'profileRings', 'output', 'range', 'color', 'colorTolerance', 'front', 'top',
             'thin', 'view', 'pick', 'inView', 'blobs', 'near', 'exclude', 'excludeTolerance', 'paint',
             'pickFront', 'pickSide', 'paintRefine')

PRIMITIVES = {'cube', 'plane', 'grid', 'uv_sphere', 'sphere', 'ico_sphere', 'cylinder', 'cone',
              'torus', 'circle', 'monkey', 'mesh', 'tube', 'lathe', 'superellipsoid', 'blobby', 'decal', 'membrane',
              'outline', 'views', 'stroke'}

# build deja aquí la carpeta del spec (rutas de imágenes de outline), las medidas de cada outline o
# lathe con imagen, y su fuente para guardarla en el objeto
_BUILD = {'baseDir': None, 'outlines': {}, 'sources': {}, 'motions': [], 'viewAt': {}}


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


def _lathe(bm, o, name=None):
    """Perfil girado alrededor de Z: `profile` = [[radio, z], ...] de abajo arriba (jarrones, troncos,
    botellas, peones, lámparas). Un radio 0 cierra en un punto. O `image`: la silueta del objeto visto
    de lado, de la que se mide el perfil (`height` o `width` en metros, `tolerance` % del alto, `side`
    both/left/right si de un lado hay un asa, `threshold`, `range` [desde, hasta] en fracción del alto para
    hacer solo una franja: así cada parte lleva su material); las medidas van a `outlines` de build."""
    if o.get('image'):
        from . import contours
        px, ruta = _image_px(o)
        size, axis = (o['height'], 'height') if o.get('height') else (o.get('width'), 'width')
        perfil, info = contours.lathe_profile(px, size=size, axis=axis,
                                              tolerance=float(o.get('tolerance', 0.25)),
                                              side=o.get('side', 'both'), threshold=o.get('threshold'),
                                              rings=int(o.get('profileRings', 64)), z_range=o.get('range'))
        info['profile'] = [[round(float(r), 4), round(float(z), 4)] for r, z in perfil]
        _record(name, o, info, ruta)
        o = dict(o, profile=info['profile'])
    elif not o.get('profile'):
        raise ValueError('lathe necesita profile [[radio, z], ...] o image (la silueta vista de lado)')
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


def _views(bm, o, name):
    """Cuerpo desde dos vistas del objeto (`front`: de frente, X a la derecha; `side`: la vista derecha,
    Y a la derecha), sin sus partes finas (asas, picos, alambres: se hacen con `stroke`). En cada altura
    la sección es una elipse (`roundness` 2; más = más cuadrada) o la forma de la vista de arriba (`top`,
    imagen), inscrita en lo que miden las dos vistas a esa altura, así el cuerpo calza con las dos
    siluetas. `height`: alto de la silueta entera en metros (con asas; las dos imágenes lo comparten);
    `thin`: ancho máximo en % del alto de lo que cuenta como parte fina (10). El origen queda abajo, en el
    centro del cuerpo; las medidas van a `outlines` de build."""
    from . import contours
    if not (o.get('front') and o.get('side')):
        raise ValueError('views necesita front y side: dos imágenes del objeto (de frente y de costado)')
    fr, ruta_f = _image_px(o, 'front')
    sd, ruta_s = _image_px(o, 'side')
    niveles, info = contours.views_body(fr, sd, float(o.get('height', 1.0)), thin=float(o.get('thin', 10)),
                                        tolerance=float(o.get('tolerance', 0.25)),
                                        rings=int(o.get('rings', 240 if o.get('paint') else 64)),
                                        threshold=o.get('threshold'), exclude=o.get('exclude'),
                                        exclude_tol=float(o.get('excludeTolerance', 0.1)), color=o.get('color'),
                                        color_tol=float(o.get('colorTolerance', 0.15)), pick_front=o.get('pickFront'),
                                        pick_side=o.get('pickSide'))
    top, ruta_t = (_image_px(o, 'top') if o.get('top') else (None, None))
    # pintado, cada cara es un "píxel" de color: más caras para que el borde del pelo no se escalone
    forma = contours.section_shape(int(o.get('segments', 192 if o.get('paint') else 48)),
                                   float(o.get('roundness', 2.0)), top, o.get('threshold'))
    anillos = []
    for z, x0, x1, y0, y1 in niveles:
        cx, a, cy, b = (x0 + x1) / 2, (x1 - x0) / 2, (y0 + y1) / 2, (y1 - y0) / 2
        anillos.append([bm.verts.new((cx + a * u, cy + b * v, z)) for u, v in forma])
    n = len(forma)
    for r0, r1 in zip(anillos, anillos[1:]):
        for j in range(n):
            bm.faces.new((r0[j], r0[(j + 1) % n], r1[(j + 1) % n], r1[j]))
    if o.get('cap', True):
        bm.faces.new(anillos[0][::-1])
        bm.faces.new(anillos[-1])
    if o.get('paint'):
        info['painted'] = _pintar_vistas(bm, o, fr, sd, info['_frames'])
    _record(name, o, info, None, [('front', ruta_f), ('side', ruta_s), ('top', ruta_t)])


def _pintar_vistas(bm, o, fr, sd, marcos):
    """`paint` {"#rrggbb": "Material", ...}: cada cara del cuerpo toma el material del color más cercano
    de la vista que la mira: las de adelante, del frente; las de los costados, atrás y arriba, del costado
    (el pelo cubre la nuca y deja la cara). Los materiales quedan en `materials` (el de `material`
    primero) y cada cara con su índice. Devuelve cuántas caras quedaron de cada material."""
    import numpy as np
    from . import contours
    pinta = o['paint']
    colores = list(pinta)
    rgb = np.array([contours.hex_rgb(c) for c in colores])
    nombres = ([o['material']] if o.get('material') else []) + [n for n in dict.fromkeys(pinta.values())
                                                                  if n != o.get('material')]
    o['materials'] = o.get('materials') or nombres
    indice = {c: o['materials'].index(pinta[c]) if pinta[c] in o['materials'] else 0 for c in colores}

    def de_paleta(px):
        d = ((rgb - px) ** 2).sum(1)
        j = int(np.argmin(d))
        return j, d[j] <= 0.12 ** 2 * 3                    # (cerca de un color de la paleta)

    def muestra(img, marco, u, z):
        f = marco['f']
        h, w = f.shape
        col = u / marco['k'] + marco['x0']
        fila = marco['abajo'] - z / marco['k']
        # en el borde de la silueta la cara cae sobre el fondo: se corre hacia el centro del cuerpo
        paso = -1.0 if col > marco['x0'] else 1.0
        for _ in range(12):
            ci, fi = int(round(col)), int(round(fila))
            if 0 <= ci < w and 0 <= fi < h and f[fi, ci] > 0.5:
                break
            col += paso
        ci, fi = int(np.clip(round(col), 0, w - 1)), int(np.clip(round(fila), 0, h - 1))
        j, cerca = de_paleta(img[fi, ci, :3])
        # un detalle de otro color (un ojo, un botón: van aparte) toma el color de la paleta que lo rodea
        r = 2
        while not cerca and r <= 40:
            for dy, dx in ((-r, 0), (r, 0), (0, -r), (0, r), (-r, -r), (-r, r), (r, -r), (r, r)):
                y_, x_ = fi + dy, ci + dx
                if 0 <= y_ < h and 0 <= x_ < w and f[y_, x_] > 0.5:
                    j2, cerca2 = de_paleta(img[y_, x_, :3])
                    if cerca2:
                        return j2
            r += 2
        return j
    def pintar(caras):
        for cara in caras:
            cara.normal_update()
            c, n = cara.calc_center_median(), cara.normal
            if n.y < 0 and abs(n.y) >= abs(n.x) and abs(n.y) >= 0.5 * abs(n.z):
                j = muestra(fr, marcos['front'], c.x, c.z)
            else:
                j = muestra(sd, marcos['side'], c.y, c.z)
            cara.material_index = indice[colores[j]]
    pintar(list(bm.faces))
    # el borde entre dos colores (la línea del pelo) sale en escalera de a una cara: se subdividen solo
    # las caras del borde, dos veces, y se vuelven a pintar
    for _ in range(int(o.get('paintRefine', 2))):
        borde = {f for e in bm.edges if len(e.link_faces) == 2
                 and e.link_faces[0].material_index != e.link_faces[1].material_index for f in e.link_faces}
        if not borde:
            break
        aristas = list({e for f in borde for e in f.edges})
        res = bmesh.ops.subdivide_edges(bm, edges=aristas, cuts=1, use_grid_fill=True)
        nuevas = {f for f in res['geom'] if isinstance(f, bmesh.types.BMFace)}
        pintar(list(nuevas | {f for f in borde if f.is_valid}))
    cuenta = {}
    for cara in bm.faces:
        nombre = o['materials'][cara.material_index]
        cuenta[nombre] = cuenta.get(nombre, 0) + 1
    return cuenta


def _profundidad(t, otros):
    """La parte de la otra vista que ocupa las mismas alturas que el trazo t (casi el mismo tramo de z, y
    que sube o baja sin volver): en cada punto de t su centro en la otra vista, y cuánto más fino o
    grueso es ahí (la mediana de sus radios sobre la de t). None si ninguna calza."""
    import numpy as np
    z = np.array(t['points'])[:, 1]

    def puntas(tr):
        """Altura de la punta pegada al cuerpo y de la libre (o la más baja y la más alta)."""
        zz = np.array(tr['points'])[:, 1]
        if tr['attached'] == ['start']:
            return zz[0], zz[-1]
        if tr['attached'] == ['end']:
            return zz[-1], zz[0]
        return zz.min(), zz.max()

    def largo(tr):
        return float(np.linalg.norm(np.diff(np.array(tr['points']), axis=0), axis=1).sum())
    mejor, solape_max = None, 0.6
    for j, u in enumerate(otros):
        q = np.array(u['points'])
        zq = q[:, 1]
        dz = np.diff(zq)
        if len(dz) < 2 or max((dz > 0).mean(), (dz < 0).mean()) < 0.9:
            continue                                        # vuelve sobre sí misma: no se lee por altura
        # la misma parte se pega al cuerpo y termina a las mismas alturas en las dos vistas (una cola y
        # un brazo pueden solaparse en altura y no ser la misma cosa)
        if max(abs(a_ - b_) for a_, b_ in zip(puntas(t), puntas(u))) > 0.3 * max(largo(t), largo(u)):
            continue
        solape = min(z.max(), zq.max()) - max(z.min(), zq.min())
        solape /= max(z.max() - z.min(), zq.max() - zq.min(), 1e-9)
        if solape > solape_max:
            mejor, solape_max = j, solape
    if mejor is None:
        return None
    u = otros[mejor]
    q = np.array(u['points'])
    orden = np.argsort(q[:, 1])
    rq, rt = np.array(u['radii']), np.array(t['radii'])
    dentro = (z >= q[:, 1].min()) & (z <= q[:, 1].max())
    ratio = float(np.median(rq)) / max(float(np.median(rt[dentro] if dentro.any() else rt)), 1e-9)
    centro = np.interp(z, q[orden, 1], q[orden, 0])

    def fraccion(tr):
        """Fracción del largo de cada punto, desde la punta pegada al cuerpo."""
        pp = np.array(tr['points'])
        s_ = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pp, axis=0), axis=1))])
        s_ = s_ / max(s_[-1], 1e-12)
        return 1 - s_ if tr['attached'] == ['end'] else s_
    # una parte casi horizontal (un brazo estirado hacia adelante) casi no cambia de altura: por altura,
    # un poco de diferencia entre las vistas lleva a otro punto del brazo. Se empareja por la fracción del
    # largo desde donde se pega al cuerpo
    pt = np.array(t['points'])
    largo_t = float(np.linalg.norm(np.diff(pt, axis=0), axis=1).sum())
    if np.ptp(z) < 0.5 * largo_t and len(t['attached']) == 1 and len(u['attached']) == 1:
        su = fraccion(u)
        o_ = np.argsort(su)
        centro = np.interp(fraccion(t), su[o_], q[o_, 0])
    return {'indice': mejor, 'ratio': ratio, 'centro': centro.tolist()}


def _stroke_bolas(bm, o, name, info, ruta):
    """stroke con `blobs: true`: las partes redondas de la vista (un pompón, un botón, una nariz de bola)
    como esferas, con el centro y el radio del círculo que sigue su borde."""
    bolas = info.get('blobs') or []
    if not bolas:
        raise ValueError('stroke: no hay partes redondas (blobs) en la imagen; mira contour -Strokes')
    pick = o.get('pick')
    idx = list(range(len(bolas))) if pick is None else [int(i) for i in (pick if isinstance(pick, list) else [pick])]
    if any(not 0 <= i < len(bolas) for i in idx):
        raise ValueError('pick fuera de rango: hay %d bolas (0..%d)' % (len(bolas), len(bolas) - 1))
    de_lado = str(o.get('view', 'front')).lower() == 'side'
    for i in idx:
        b = bolas[i]
        x, z = b['center']
        geo = bmesh.ops.create_uvsphere(bm, u_segments=int(o.get('segments', 32)), v_segments=16, radius=b['radius'])
        bmesh.ops.translate(bm, vec=Vector((0, x, z) if de_lado else (x, 0, z)), verts=geo['verts'])
    _record(name, o, {'blobs': [dict(b, index=i) for i, b in enumerate(bolas)], 'picked': idx,
                      'thinPercent': info['thinPercent'], 'targetMet': all(bolas[i]['iou'] >= 0.8 for i in idx),
                      'tolerancePercent': None, 'elapsedMs': info['elapsedMs']}, ruta)


def _stroke(bm, o, name):
    """Tubos desde las partes finas de una vista (asas, picos, alambres, antenas, ramas, patas): de la
    imagen (`image`, la vista donde el trazo se ve a lo largo; `view` front o side) se mide el eje de
    cada parte fina y su ancho en cada punto, y se hace un tubo que lo sigue y se mete en el cuerpo
    donde lo toca. Con la misma imagen, `height` y `location` que el `views` del cuerpo, encaja con él.
    `pick` [i, ...] elige trazos (del más largo al más corto; sin pick, todos); `color` toma solo los
    de ese color; `flat` < 1 aplana la sección de canto (un asa de chapa: 0.4). Con la otra vista
    (`side` si view es front, `front` si es side) la profundidad sale de ella: cada trazo toma de la
    parte que ocupa las mismas alturas en la otra vista su posición (una oreja que se inclina hacia
    atrás, una pata que va hacia adelante) y su grosor (una oreja plana), en vez de quedar en el plano
    de la vista y redondo. `near` [[x, z], ...] elige por posición (el trazo que pasa más cerca de cada
    punto); `blobs: true` hace esferas con las partes redondas (un pompón) en vez de tubos."""
    from . import contours
    px, ruta = _image_px(o)
    medir = dict(height=float(o.get('height', 1.0)), thin=float(o.get('thin', 10)), threshold=o.get('threshold'),
                 color=o.get('color'), color_tol=float(o.get('colorTolerance', 0.15)), exclude=o.get('exclude'),
                 exclude_tol=float(o.get('excludeTolerance', 0.1)))
    trazos, info = contours.strokes(px, **medir)
    if o.get('blobs'):
        return _stroke_bolas(bm, o, name, info, ruta)
    if not trazos:
        raise ValueError('stroke: no hay partes finas en la imagen (sube thin, ahora %s %% del alto, o revisa '
                         'color)' % o.get('thin', 10))
    pick = o.get('pick')
    idx = list(range(len(trazos))) if pick is None else [int(i) for i in (pick if isinstance(pick, list) else [pick])]
    if any(not 0 <= i < len(trazos) for i in idx):
        raise ValueError('pick fuera de rango: hay %d trazos (0..%d)' % (len(trazos), len(trazos) - 1))
    if o.get('near'):
        # por posición: para cada punto [x, z] (en el marco de la vista, como start/end), el trazo que pasa
        # más cerca. No depende del orden por largo, que cambia entre partes de casi el mismo largo
        cerca = o['near'] if isinstance(o['near'][0], (list, tuple)) else [o['near']]

        def distancia(t, c):
            pp = [(x - c[0]) ** 2 + (z - c[1]) ** 2 for x, z in t['points']]
            return min(pp)
        idx = [min(range(len(trazos)), key=lambda i: distancia(trazos[i], c)) for c in cerca]
    lado = str(o.get('view', 'front')).lower()
    if lado not in ('front', 'side'):
        raise ValueError('view debe ser front o side')
    flat = float(o.get('flat', 1.0))
    otra = 'side' if lado == 'front' else 'front'
    otros, ruta_otra = [], None
    if o.get(otra):
        px2, ruta_otra = _image_px(o, otra)
        otros, _ = contours.strokes(px2, **medir)
    seg = int(o.get('segments', 16))
    resumen = [dict({k: v for k, v in t.items() if k not in ('points', 'radii')}, index=i)
               for i, t in enumerate(trazos)]
    for i in idx:
        t = trazos[i]
        pts = [(x, 0.0, z) if lado == 'front' else (0.0, x, z) for x, z in t['points']]
        hondo = _profundidad(t, otros)
        n0 = len(bm.verts)
        _tube(bm, {'points': pts, 'radii': t['radii'], 'segments': seg})
        bm.verts.ensure_lookup_table()
        nuevos = [bm.verts[k] for k in range(n0, len(bm.verts))]
        eje = 1 if lado == 'front' else 0                   # la coordenada de profundidad: y de frente
        for k, v in enumerate(nuevos):
            anillo = min(k // seg, len(pts) - 1) if k < seg * len(pts) else (0 if k == seg * len(pts) else len(pts) - 1)
            if hondo:
                v.co[eje] = v.co[eje] * hondo['ratio'] + hondo['centro'][anillo]
            elif flat != 1.0:
                v.co[eje] *= flat
        if hondo:
            resumen[i]['depthFrom'] = hondo['indice']
    _record(name, o, {'strokes': resumen, 'picked': idx, 'thinPercent': info['thinPercent'],
                      'targetMet': all(trazos[i]['iou'] >= 0.85 for i in idx), 'tolerancePercent': None,
                      'elapsedMs': info['elapsedMs']}, ruta, [(otra, ruta_otra)])
    _BUILD['sources'][name]['result']['strokes'] = [dict(r, points=t['points'], radii=t['radii'])
                                                    for r, t in zip(resumen, trazos)]


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


def _membrane(bm, o):
    """Membrana entre huesos (alas de murciélago o dragón, aletas, velas, abanicos): `root` (donde nace),
    `tip` (punta del hueso principal), `fingers` (puntas de los dedos, en orden) y entre cada par de puntas
    un festón que se mete hacia la raíz (`scallop`, 0 = borde recto). `bend` curva la membrana hacia
    atrás (+Y) como una vela. `bones`: radio de los huesos (0 = sin huesos); van en la misma malla."""
    root, tip = Vector(vec3(o['root'])), Vector(vec3(o['tip']))
    fingers = [Vector(vec3(f)) for f in o.get('fingers', [])]
    if not fingers:
        raise ValueError('membrane necesita fingers: las puntas de los dedos del borde')
    sc = float(o.get('scallop', 0.18))
    bend = float(o.get('bend', 0.0))
    span = max((f - root).length for f in [tip] + fingers) or 1.0

    def doblar(p):
        d = (p - root).length / span
        return p + Vector((0, bend * d * d, 0))

    borde, prev = [tip], tip
    for f in fingers:
        for t in (0.2, 0.4, 0.6, 0.8):
            borde.append(prev.lerp(f, t).lerp(root, math.sin(math.pi * t) * sc))
        borde.append(f)
        prev = f
    R = int(o.get('rings', 5))
    centro = bm.verts.new(doblar(root))
    anillos = [[bm.verts.new(doblar(root.lerp(e, k / R))) for e in borde] for k in range(1, R + 1)]
    for i in range(len(borde) - 1):
        bm.faces.new((centro, anillos[0][i], anillos[0][i + 1]))
    for k in range(R - 1):
        for i in range(len(borde) - 1):
            bm.faces.new((anillos[k][i], anillos[k + 1][i], anillos[k + 1][i + 1], anillos[k][i + 1]))
    # grosor: se extruye la membrana a lo largo de su normal (sin depender de un modificador)
    th = float(o.get('thickness', 0.006))
    if th > 0:
        caras = list(bm.faces)
        geo = bmesh.ops.extrude_face_region(bm, geom=caras)
        nuevos = [g for g in geo['geom'] if isinstance(g, bmesh.types.BMVert)]
        nrm = (tip - root).cross(fingers[len(fingers) // 2] - root).normalized()
        bmesh.ops.translate(bm, vec=nrm * th, verts=nuevos)
    rb = float(o.get('bones', 0.0))
    if rb > 0:
        # hueso principal raíz -> punta y un dedo desde el hueso hasta cada punta
        huesos = [([doblar(root.lerp(tip, t / 8)) for t in range(9)], rb, rb * 0.55)]
        n = len(fingers)
        for i, f in enumerate(fingers):
            desde = tip if i == 0 else root.lerp(tip, max(0.25, 1 - (i + 0.3) / (n + 0.3)))
            huesos.append(([doblar(desde.lerp(f, t / 6)) for t in range(7)], rb * 0.6, rb * 0.25))
        for pts, r0, r1 in huesos:
            _tube(bm, {'points': [list(p) for p in pts], 'radii': [r0, r1], 'segments': 12})


def _image_px(o, clave='image'):
    """Imagen de outline/lathe/views/stroke (filas de arriba abajo, hasta 1024 px de alto) y su ruta."""
    ruta = _path(o[clave], _BUILD['baseDir'])
    px = _load_pixels(ruta)
    if px.shape[0] > 1024:
        px = _load_pixels(ruta, 1024)
    return px[::-1], ruta


def _public(info):
    """Medidas para el resultado (sin coeficientes ni marcos internos, que empiezan con _)."""
    def limpio(d):
        return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()
                if not k.startswith('_') and k not in ('hausdorff', 'maxCorrespondenceError')}
    pub = limpio(info)
    if 'loops' in info:
        pub['loops'] = [limpio(l) for l in info['loops']]
    return pub


def _record(name, o, info, ruta=None, otras=()):
    """Guarda las medidas para el resultado de build y la fuente completa para el objeto (bs_source):
    con qué se generó (parámetros, imagen y su sha1, versión) y qué salió (con los coeficientes de
    Fourier de cada contorno), para poder reproducirlo o explicarlo después."""
    import hashlib
    from .version import VERSION
    pub = _public(info)
    _BUILD['outlines'][name] = pub
    res = dict(pub)
    if 'loops' in info:
        res['loops'] = [dict(l, **({'coefficients': c['_coef']} if '_coef' in c else {}))
                        for l, c in zip(pub['loops'], info['loops'])]
    fuente = {'generator': o.get('type'), 'version': VERSION,
              'params': {k: o[k] for k in GEOM_KEYS if k in o and k not in ('image', 'profile')
                         and not (o.get('type') in ('views', 'stroke') and k in ('front', 'side', 'top'))},
              'result': res}
    for clave, r in [('image', ruta)] + list(otras):
        if r:
            with open(r, 'rb') as f:
                fuente[clave] = {'path': r, 'sha1': hashlib.sha1(f.read()).hexdigest()}
    _BUILD['sources'][name] = fuente


def _outline_loops(o):
    """Regiones simplificadas de outline (en metros, plano local XY) y sus medidas."""
    from . import contours
    ruta = None
    if o.get('image'):
        fuente, ruta = _image_px(o)
    elif o.get('points'):
        fuente = [{'outer': o['points'], 'holes': o.get('holes', [])}]
    else:
        raise ValueError('outline necesita image (una silueta) o points')
    size, axis = (o['height'], 'height') if o.get('height') else (o.get('width'), 'width')
    escala = vista = None
    if o.get('inView') and o.get('image'):
        # en el marco de la vista, como views y stroke: `height` es el alto de la silueta entera
        vista = contours._vista(fuente, float(o.get('thin', 10)), o.get('threshold'), o.get('exclude'),
                                float(o.get('excludeTolerance', 0.1)))
        escala = float(o.get('height', 1.0)) / vista['alto']
    regs, info = contours.outline(fuente, size=size, axis=axis, tolerance=float(o.get('tolerance', 0.25)),
                                  method=o.get('method', 'auto'), threshold=o.get('threshold'),
                                  color=o.get('color') if o.get('image') else None,
                                  color_tol=float(o.get('colorTolerance', 0.15)), pick=o.get('pick'), scale=escala)
    if vista is not None:
        cx, cy = info['_frame']['center']                  # en píxeles, y hacia arriba (= -fila)
        info['at'] = [round((cx - vista['x0']) * escala, 5), round((vista['abajo'] + cy) * escala, 5)]
    return regs, info, ruta


def _outline(bm, o, name):
    """Silueta plana o extruida a partir de una imagen (`image`: figura sobre fondo liso, o PNG con
    transparencia) o de puntos (`points` [[x, y], ...] en metros, con `holes` [[[x, y], ...], ...]).
    Cada contorno se simplifica con Fourier (curvas suaves) o como polígono (esquinas vivas) según
    `method` (auto | fourier | polygon), con un error máximo de `tolerance` % de la diagonal (0.25).
    Tamaño con `width` o `height` en metros (una imagen, si no, mide 1 m de ancho). `thickness` 0.02
    (0 = solo la cara); `plane` 'XZ' (de pie, de frente a -Y como la vista front) o 'XY' (en el piso).
    `output: "curve"` da una curva de Blender en vez de malla (_outline_curve). Las medidas quedan en
    el resultado de build (`outlines`) y la fuente en la propiedad bs_source del objeto."""
    regs, info, ruta = _outline_loops(o)
    _record(name, o, info, ruta)
    if 'at' in info:
        _BUILD['viewAt'][name] = info['at']
    xz = str(o.get('plane', 'XZ')).upper() == 'XZ'
    for r in regs:
        polis = [[Vector((x, 0.0, y) if xz else (x, y, 0.0)) for x, y in lazo]
                 for lazo in [r['outer']] + r['holes']]
        vs = [bm.verts.new(v) for pol in polis for v in pol]
        # tessellate_polygon acepta exterior + huecos: triángulos con índices sobre la lista aplanada
        for tri in tessellate_polygon(polis):
            try:
                bm.faces.new([vs[i] for i in tri])
            except ValueError:
                pass
    frente = Vector((0, -1, 0)) if xz else Vector((0, 0, 1))
    for f in bm.faces:
        f.normal_update()
        if f.normal.dot(frente) < 0:
            f.normal_flip()
    th = float(o.get('thickness', 0.02))
    if th > 0:
        geo = bmesh.ops.extrude_face_region(bm, geom=list(bm.faces))
        atras = [g for g in geo['geom'] if isinstance(g, bmesh.types.BMVert)]
        bmesh.ops.translate(bm, vec=-frente * th, verts=atras)
        bmesh.ops.translate(bm, vec=frente * (th / 2), verts=bm.verts)   # centrada en su grosor
        bmesh.ops.recalc_face_normals(bm, faces=bm.faces)


def _outline_curve(o, name):
    """outline como curva 2D de Blender (editable por puntos de control, rellena y con grosor): los
    contornos suaves son Bézier con asas tangentes exactas (pocos puntos), los angulosos son polilíneas.
    La curva vive en el plano XY local; con plane XZ, build la pone de pie girando el objeto 90° en X."""
    from . import contours
    regs, info, ruta = _outline_loops(o)
    if o.get('origin') == 'bottom':
        y0 = min(float(r['outer'][:, 1].min()) for r in regs)
        regs = [{'outer': r['outer'] - [0, y0], 'holes': [hh - [0, y0] for hh in r['holes']]} for r in regs]
    tol = info['tolerance']
    cu = bpy.data.curves.new(name, 'CURVE')
    cu.dimensions = '2D'
    cu.fill_mode = 'BOTH'
    cu.resolution_u = int(o.get('resolution', 12))
    cu.extrude = float(o.get('thickness', 0.02)) / 2
    lazos = [l for r in regs for l in [r['outer']] + r['holes']]
    for lazo, l_info in zip(lazos, info['loops']):
        if l_info['method'] == 'fourier':
            pts, izq, der, err = contours.bezier(lazo, tol * 0.5)
            l_info['bezierPoints'] = int(len(pts))
            sp = cu.splines.new('BEZIER')
            sp.bezier_points.add(len(pts) - 1)
            for bp, p_, a, b in zip(sp.bezier_points, pts, izq, der):
                bp.co = (p_[0], p_[1], 0)
                bp.handle_left_type = bp.handle_right_type = 'FREE'
                bp.handle_left = (a[0], a[1], 0)
                bp.handle_right = (b[0], b[1], 0)
        else:
            sp = cu.splines.new('POLY')
            sp.points.add(len(lazo) - 1)
            for pt, (x, y) in zip(sp.points, lazo):
                pt.co = (x, y, 0, 1)
        sp.use_cyclic_u = True
    _record(name, o, info, ruta)
    return cu


def _geom_data(o, name):
    """Geometría de un tipo de PRIMITIVES: malla, o curva para outline con output curve."""
    if o.get('type', '').lower() == 'outline' and o.get('output') == 'curve':
        return _outline_curve(o, name)
    return build_mesh(o, name)


def _copy_props(src, dst):
    """Copia las propiedades editables de un modificador o restricción a otro del mismo tipo."""
    for p in src.bl_rna.properties:
        if p.is_readonly or p.identifier in ('rna_type', 'name', 'type'):
            continue
        try:
            setattr(dst, p.identifier, getattr(src, p.identifier))
        except Exception:
            pass


def _replace_object(o, spec, name, warnings):
    """Un objeto de Blender no cambia de tipo: para pasar un outline de malla a curva (o al revés) se
    crea uno nuevo con la geometría nueva y se le pasa todo lo del viejo (colecciones, padre e hijos,
    transformación, materiales, modificadores y restricciones que admita, animación y propiedades).
    Si algo falla antes de borrar el viejo, el nuevo se descarta y la escena queda como estaba."""
    data = _geom_data(spec, name)
    nuevo = bpy.data.objects.new(name + '.bs_nuevo', data)
    try:
        for c in o.users_collection:
            c.objects.link(nuevo)
        nuevo.parent = o.parent
        nuevo.matrix_parent_inverse = o.matrix_parent_inverse.copy()
        nuevo.location, nuevo.rotation_mode = o.location.copy(), o.rotation_mode
        nuevo.rotation_euler, nuevo.scale = o.rotation_euler.copy(), o.scale.copy()
        if o.type == 'CURVE' and nuevo.type == 'MESH' and 'rotation' not in spec                 and str(spec.get('plane', 'XZ')).upper() == 'XZ':
            nuevo.rotation_euler.x -= math.pi / 2       # la curva estaba girada para quedar de pie; la malla ya lo está
        for m in o.data.materials:
            data.materials.append(m)
        for m in o.modifiers:
            try:
                _copy_props(m, nuevo.modifiers.new(m.name, m.type))
            except (TypeError, RuntimeError):
                warnings.append('«%s»: el modificador %s (%s) no existe para %s y no se pasó'
                                % (name, m.name, m.type, nuevo.type))
        for c in o.constraints:
            _copy_props(c, nuevo.constraints.new(c.type))
        if o.animation_data and o.animation_data.action:
            ad = nuevo.animation_data_create()
            ad.action = o.animation_data.action
            if hasattr(ad, 'action_slot') and getattr(o.animation_data, 'action_slot', None):
                ad.action_slot = o.animation_data.action_slot
        for k in o.keys():
            if k != 'bs_geom':
                nuevo[k] = o[k]
        for hijo in list(o.children):
            mw = hijo.matrix_world.copy()
            hijo.parent = nuevo
            hijo.matrix_world = mw
    except Exception:
        bpy.data.objects.remove(nuevo, do_unlink=True)
        if data.users == 0:
            (bpy.data.meshes if isinstance(data, bpy.types.Mesh) else bpy.data.curves).remove(data)
        raise
    viejo = o.data
    bpy.data.objects.remove(o, do_unlink=True)
    if viejo is not None and viejo.users == 0:
        (bpy.data.meshes if isinstance(viejo, bpy.types.Mesh) else bpy.data.curves).remove(viejo)
    nuevo.name = name
    return nuevo


def _geom_kind(t, o):
    return 'CURVE' if t == 'outline' and o.get('output') == 'curve' else 'MESH'


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
        _lathe(bm, o, name)
    elif t == 'superellipsoid':
        _superellipsoid(bm, o)
    elif t == 'membrane':
        _membrane(bm, o)
    elif t == 'outline':
        _outline(bm, o, name)
    elif t == 'views':
        _views(bm, o, name)
    elif t == 'stroke':
        _stroke(bm, o, name)
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
    if t in ('tube', 'lathe', 'superellipsoid', 'membrane', 'views', 'stroke'):
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


def _texture_maps(m, p, maps, base_dir, scale):
    """Mapas de imagen (color, normal, rugosidad, metálico, ao) con proyección de caja desde las
    coordenadas del objeto: no hace falta desplegar UV en las piezas de build."""
    nt = m.node_tree
    for n in [n for n in nt.nodes if n.label.startswith('bs_map')]:
        nt.nodes.remove(n)
    coord = nt.nodes.new('ShaderNodeTexCoord')
    mapping = nt.nodes.new('ShaderNodeMapping')
    coord.label, mapping.label = 'bs_map_coord', 'bs_map_mapping'
    mapping.inputs['Scale'].default_value = (scale, scale, scale)
    nt.links.new(coord.outputs['Object'], mapping.inputs['Vector'])
    x0, y = p.location.x - 700, p.location.y + 300

    def imagen(clave, no_color):
        tex = nt.nodes.new('ShaderNodeTexImage')
        tex.label = 'bs_map_' + clave
        tex.image = bpy.data.images.load(_path(maps[clave], base_dir), check_existing=True)
        if no_color:
            tex.image.colorspace_settings.name = 'Non-Color'
        tex.projection, tex.projection_blend = 'BOX', 0.25
        nt.links.new(mapping.outputs['Vector'], tex.inputs['Vector'])
        return tex

    k = 0
    for clave in ('color', 'roughness', 'metallic', 'ao', 'normal'):
        if not maps.get(clave):
            continue
        tex = imagen(clave, clave != 'color')
        tex.location = (x0, y - 280 * k)
        k += 1
        if clave == 'color':
            nt.links.new(tex.outputs['Color'], p.inputs['Base Color'])
        elif clave == 'roughness':
            nt.links.new(tex.outputs['Color'], p.inputs['Roughness'])
        elif clave == 'metallic':
            nt.links.new(tex.outputs['Color'], p.inputs['Metallic'])
        elif clave == 'normal':
            nm = nt.nodes.new('ShaderNodeNormalMap')
            nm.label = 'bs_map_normalnode'
            nm.location = (x0 + 300, y - 280 * k)
            nt.links.new(tex.outputs['Color'], nm.inputs['Color'])
            nt.links.new(nm.outputs['Normal'], p.inputs['Normal'])
    coord.location, mapping.location = (x0 - 500, y), (x0 - 300, y)


def _pixel_texture(m, p, nombre, px_spec, emision):
    """Pixel art dibujado en el spec: `rows` (cadenas de arriba abajo, un carácter por píxel) y `palette`
    ({carácter: "#rrggbb"}). Se filtra sin suavizar (Closest) y se proyecta plano sobre la pieza con sus
    coordenadas locales: `plane` [ancho, alto] del área que cubre la imagen (en metros), `axes` "XZ" (frente)
    o "XY" (arriba), `repeat` para baldosas. Estilo consola de 32 bits, carteles, caras de pantalla."""
    import numpy as np
    filas, paleta = px_spec['rows'], px_spec['palette']
    h, w = len(filas), max(len(f) for f in filas)
    arr = np.zeros((h, w, 4), np.float32)
    for y, fila in enumerate(filas):
        for x, ch in enumerate(fila.ljust(w, fila[-1] if fila else ' ')):
            c = paleta.get(ch)
            if c is None:
                raise ValueError('pixels: el carácter %r no está en palette' % ch)
            hx = c.lstrip('#')
            arr[h - 1 - y, x] = [int(hx[i:i + 2], 16) / 255 for i in (0, 2, 4)] + [1.0]
    img = bpy.data.images.get('px_' + nombre) or bpy.data.images.new('px_' + nombre, w, h, alpha=True)
    if tuple(img.size) != (w, h):
        img.scale(w, h)
    img.pixels.foreach_set(arr.ravel())
    img.pack()
    nt = m.node_tree
    for n in [n for n in nt.nodes if n.label.startswith('bs_px')]:
        nt.nodes.remove(n)
    coord = nt.nodes.new('ShaderNodeTexCoord')
    sep = nt.nodes.new('ShaderNodeSeparateXYZ')
    comb = nt.nodes.new('ShaderNodeCombineXYZ')
    coord.label, sep.label, comb.label = 'bs_px_coord', 'bs_px_sep', 'bs_px_comb'
    nt.links.new(coord.outputs['Object'], sep.inputs['Vector'])
    ejes = px_spec.get('axes', 'XZ').upper()
    ancho, alto = (px_spec.get('plane') or [1.0, 1.0])[:2]
    repetir = bool(px_spec.get('repeat'))
    for eje, tam, entrada in ((ejes[0], ancho, 'X'), (ejes[1], alto, 'Y')):
        mul = nt.nodes.new('ShaderNodeMath')
        mul.label = 'bs_px_' + entrada
        mul.operation = 'MULTIPLY_ADD'
        mul.inputs[1].default_value = 1.0 / float(tam)
        mul.inputs[2].default_value = 0.0 if repetir else 0.5
        nt.links.new(sep.outputs[eje], mul.inputs[0])
        nt.links.new(mul.outputs['Value'], comb.inputs[entrada])
    tex = nt.nodes.new('ShaderNodeTexImage')
    tex.label = 'bs_px_tex'
    tex.image, tex.interpolation = img, 'Closest'
    tex.extension = 'REPEAT' if repetir else 'EXTEND'
    nt.links.new(comb.outputs['Vector'], tex.inputs['Vector'])
    nt.links.new(tex.outputs['Color'], p.inputs['Base Color'])
    if emision > 0:
        nt.links.new(tex.outputs['Color'], p.inputs['Emission Color'])
        p.inputs['Emission Strength'].default_value = emision
    for i, n in enumerate((coord, sep, comb, tex)):
        n.location = (p.location.x - 900 + 220 * i, p.location.y + 300)


def build_material(spec, base_dir):
    m = bpy.data.materials.get(spec['name'])
    created = m is None
    if created:
        m = bpy.data.materials.new(spec['name'])
    # un material definido en el spec se conserva aunque todavía nadie lo use: Blender borra al guardar
    # los que no tienen usuarios, y un `asset get --apply` crea el material antes de asignarlo
    m.use_fake_user = True
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
    if spec.get('maps'):
        _texture_maps(m, p, spec['maps'], base_dir, float(spec.get('textureScale', 1.0)))
    if spec.get('pixels'):
        _pixel_texture(m, p, spec['name'], spec['pixels'], float(spec.get('emissionStrength', 0.0)))
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
        return bpy.data.objects.new(name, _geom_data(spec, name)), _geom_kind(t, spec)
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
    defecto la location), offset (separación), align (por defecto sí: su eje Z sigue la normal), spin (°),
    wrap (true: curvada sobre la superficie; "bake": curvada una vez, sin modificadores), project ("view":
    como un calco a lo largo de side, para detalles pintados en una vista)}."""
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
    # se fija la matriz de MUNDO y Blender deduce la local: con padre (y su matrix_parent_inverse) poner
    # location/rotation a mano aplicaba dos veces la transformación del padre
    bpy.context.view_layer.update()
    loc, rot, esc = o.matrix_world.decompose()
    if a.get('project') == 'view':
        # como un calco: proyectada a lo largo de la vista (side), no girada hacia la normal de su centro.
        # Así los detalles pintados en una vista coinciden entre sí como en el dibujo (el brillo de un ojo
        # en su hueco, aunque sean dos piezas con centros distintos). Para piezas chicas que miran a esa
        # vista: una grande que da la vuelta al cuerpo (un ala) queda plana donde el rayo no lo toca.
        n = Vector(SIDES[side] if isinstance(side, str) else vec3(side)).normalized()
    if a.get('align', True):
        o.rotation_mode = 'XYZ'
        rot = n.to_track_quat('Z', 'Y')
        if a.get('spin'):
            rot = rot @ Euler((0, 0, math.radians(float(a['spin']))), 'XYZ').to_quaternion()
    o.matrix_world = Matrix.Translation(p + n * off) @ rot.to_matrix().to_4x4() @ Matrix.Diagonal(esc.to_4d())
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
        niveles = 0
        if o.type == 'MESH' and o.data.edges:
            # un triángulo largo y plano (un outline) no tiene puntos que pegar a la curva: queda como una
            # cuerda por debajo de la superficie y la superficie lo atraviesa (un ojo con el cuerpo asomando
            # por el medio). Se subdivide hasta que la flecha de su arista más larga sobre la curvatura del
            # cuerpo (radio ~ su medida más chica / 2) quede bajo la separación.
            larga = max((o.data.vertices[e.vertices[0]].co - o.data.vertices[e.vertices[1]].co).length
                        for e in o.data.edges) * max(esc)
            radio = max(min(tgt.dimensions) / 2, 1e-6)
            cuerda = math.sqrt(4 * radio * max(off, 0.0005))     # flecha c²/8R = separación/2
            # (+1: la curvatura local puede ser más cerrada que la media, y una pieza que se curva mucho,
            # como un ala, necesita más puntos para seguirla)
            niveles = max(0, min(4, 1 + math.ceil(math.log2(max(larga / cuerda, 1.0)))))
        if niveles:
            sub = o.modifiers.get('bs_wrap_sub') or o.modifiers.new('bs_wrap_sub', 'SUBSURF')
            sub.subdivision_type, sub.levels, sub.render_levels = 'SIMPLE', niveles, niveles
            o.modifiers.move(o.modifiers.find('bs_wrap_sub'), 0)
        elif o.modifiers.get('bs_wrap_sub'):
            o.modifiers.remove(o.modifiers['bs_wrap_sub'])
        if o.type == 'MESH':
            # pegada a 1 mm la pieza copia las facetas del cuerpo, y su propio sombreado las marca como
            # franjas: toma las normales del cuerpo, como si estuviera pintada sobre él
            # (solo la cara de afuera: la de atrás mira al cuerpo, y con la normal de afuera Workbench la
            # ve de espaldas y la oscurece)
            zs = [v.co.z for v in o.data.vertices]
            medio = (min(zs) + max(zs)) / 2 if zs else 0.0
            vg = o.vertex_groups.get('bs_frente') or o.vertex_groups.new(name='bs_frente')
            vg.remove([v.index for v in o.data.vertices])
            vg.add([v.index for v in o.data.vertices if v.co.z >= medio], 1.0, 'REPLACE')
            nm = o.modifiers.get('bs_wrap_normales') or o.modifiers.new('bs_wrap_normales', 'DATA_TRANSFER')
            nm.object, nm.use_loop_data, nm.vertex_group = tgt, True, 'bs_frente'
            nm.data_types_loops = {'CUSTOM_NORMAL'}
            nm.loop_mapping = 'POLYINTERP_NEAREST'
            o.modifiers.move(o.modifiers.find('bs_wrap_normales'), len(o.modifiers) - 1)
        if a.get('wrap') == 'bake' and o.type == 'MESH':
            # la forma curvada queda en la malla y se quitan los modificadores: así la pieza se puede
            # animar (un ala que aletea desde el hombro); con el modificador vivo se volvería a pegar al
            # cuerpo en cada cuadro. Toma la pose del cuadro actual.
            bpy.context.view_layer.update()
            me = bpy.data.meshes.new_from_object(o.evaluated_get(bpy.context.evaluated_depsgraph_get()))
            for n in ('bs_wrap', 'bs_wrap_sub', 'bs_wrap_normales'):
                if o.modifiers.get(n):
                    o.modifiers.remove(o.modifiers[n])
            viejo, o.data = o.data, me
            me.name = viejo.name
            if viejo.users == 0:
                bpy.data.meshes.remove(viejo)


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
    # los puntos están en coordenadas del mundo: la matriz de mundo queda en identidad (con padre,
    # poner la local en cero no alcanza)
    bpy.context.view_layer.update()
    o.matrix_world = Matrix.Identity(4)
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


_MOTION_PROPS = ('location', 'rotation_euler', 'scale')


def _apply_motion(a, warnings):
    """Una entrada de animation con `motion`: calcula el valor de cada fotograma con dynamics y lo
    hornea como claves lineales en UN canal (property + axis), sumado a su valor de reposo. Las demás
    claves del objeto no se tocan. Deja en el objeto (bs_motion) el modelo, sus parámetros y el modo
    (kinematic / ode_simulated)."""
    from . import dynamics
    o = _obj(a['object'])
    prop = a.get('property', 'rotation')
    target, path = (o.data, prop[5:]) if prop.startswith('data.') else (o, prop)
    if path == 'rotation':
        path = 'rotation_euler'
    if target is o and path not in _MOTION_PROPS:
        raise ValueError('motion anima location, rotation, scale o un dato con data. (no %s)' % prop)
    if not hasattr(target, path) or callable(getattr(target, path)):
        raise ValueError('«%s» no tiene la propiedad %s' % (o.name, prop))
    actual = getattr(target, path)
    vector = hasattr(actual, '__len__')
    if not vector and not isinstance(actual, (int, float)):
        raise ValueError('%s no es numérica' % prop)
    eje = str(a.get('axis', 'z')).lower()
    if vector and eje not in ('x', 'y', 'z'):
        raise ValueError('axis debe ser x, y o z')
    idx = 'xyz'.index(eje) if vector else -1
    canal = '%s[%s]' % (prop, eje) if vector else prop
    s = _scene()
    fps = s.render.fps / s.render.fps_base
    f0, f1 = (int(x) for x in a.get('frames', (s.frame_start, s.frame_end)))
    if f1 < f0:
        raise ValueError('frames: el final (%d) es menor que el inicio (%d)' % (f1, f0))
    frames = list(range(f0, f1 + 1))
    times = [(f - f0) / fps for f in frames]
    # uno o varios movimientos (lista) que se suman en el mismo canal: p. ej. oscillate + noise
    ms = [dict(x) for x in (a['motion'] if isinstance(a['motion'], list) else [a['motion']])]
    if not ms:
        raise ValueError('motion vacío')
    vals, infos, avisos = [0.0] * len(times), [], []
    for m in ms:
        error, aviso = dynamics.aliasing(dynamics.natural_frequency(m), fps)
        if error:
            raise ValueError('«%s»: %s' % (o.name, error))
        accel = None
        if m.get('kind') == 'follow':
            guia = _obj(m.get('leader') or '')
            ge = 'xyz'.index(str(m.get('leaderAxis', 'z')).lower())
            antes = s.frame_current
            pos = []
            for f in range(f0 - 1, f1 + 2):
                s.frame_set(f)
                pos.append(guia.matrix_world.translation[ge])
            s.frame_set(antes)
            dt = 1 / fps
            accel = [(pos[i + 1] - 2 * pos[i] + pos[i - 1]) / (dt * dt) for i in range(1, len(pos) - 1)]
        v, inf = dynamics.simulate(m, times, accel)
        vals = [x + y for x, y in zip(vals, v)]
        infos.append(inf)
        if aviso:
            avisos.append(aviso)
            warnings.append('«%s» %s: %s' % (o.name, canal, aviso))
    simulado = any(x['mode'] == 'ode_simulated' for x in infos)
    info = {'kind': '+'.join(m.get('kind', '?') for m in ms), 'mode': 'ode_simulated' if simulado else 'kinematic',
            'frames': len(vals), 'maxAbs': round(max(abs(v) for v in vals), 6), 'warnings': avisos,
            'elapsedMs': round(sum(x['elapsedMs'] for x in infos), 1)}
    if simulado:
        info['substeps'] = sum(x.get('substeps', 0) for x in infos)
    # valor de reposo: el que tenía antes del primer motion de ese canal (guardado), o `base`
    bases = json.loads(o.get('bs_motion_base', '{}'))
    if 'base' in a:
        base = float(a['base'])
    elif canal in bases:
        base = bases[canal]
    else:
        v = actual[idx] if vector else actual
        base = math.degrees(v) if path == 'rotation_euler' else float(v)
    bases[canal] = base
    o['bs_motion_base'] = json.dumps(bases)
    bag = _fcurve_bag(target)
    if bag is not None:
        for fc in [fc for fc in bag.fcurves if fc.data_path == path and (not vector or fc.array_index == idx)]:
            bag.fcurves.remove(fc)
    for f, v in zip(frames, vals):
        valor = base + v
        if path == 'rotation_euler':
            valor = math.radians(valor)
        if vector:
            vec = list(getattr(target, path))
            vec[idx] = valor
            setattr(target, path, vec)
            target.keyframe_insert(data_path=path, index=idx, frame=f)
        else:
            setattr(target, path, valor)
            target.keyframe_insert(data_path=path, frame=f)
    bag = _fcurve_bag(target)
    if bag is not None:
        for fc in bag.fcurves:
            if fc.data_path == path and (not vector or fc.array_index == idx):
                for kp in fc.keyframe_points:
                    kp.interpolation = 'LINEAR'
    registro = json.loads(o.get('bs_motion', '{}'))
    registro[canal] = {'kind': info['kind'], 'mode': info['mode'], 'params': ms if len(ms) > 1 else ms[0], 'base': base,
                       'frames': [f0, f1], 'fps': fps}
    o['bs_motion'] = json.dumps(registro, ensure_ascii=False)
    return dict(info, object=o.name, channel=canal, frameRange=[f0, f1], fps=fps)


def _apply_animation(anims, warnings):
    out = 0
    for a in anims:
        if 'motion' in a:
            r = _apply_motion(a, warnings)
            _BUILD['motions'].append(r)
            out += r['frames']
            continue
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


def _con_nombre(name, fn, *args):
    """fn(*args); si falla, el error dice de qué objeto del spec es."""
    try:
        return fn(*args)
    except Exception as e:
        e.args = ('«%s»: %s' % (name, e.args[0] if e.args else e),) + tuple(e.args[1:])
        raise


def op_build(spec):
    """Crea o actualiza (por nombre) materiales, colecciones, objetos, luces, cámaras y animación."""
    warnings, created, updated, removed, replaced = [], [], [], [], []
    base_dir = spec.get('_baseDir')
    _BUILD['baseDir'] = base_dir
    _BUILD['outlines'] = {}
    _BUILD['viewAt'] = {}
    _BUILD['sources'] = {}
    _BUILD['motions'] = []

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
                want = _geom_kind(t, os_) if t in PRIMITIVES else {'empty': 'EMPTY', 'text': 'FONT', 'light': 'LIGHT', 'camera': 'CAMERA'}.get(t)
                if o.type != want and t == 'outline' and {o.type, want} == {'MESH', 'CURVE'}:
                    o = _replace_object(o, os_, name, warnings)
                    o['bs_geom'] = _geom_sig(os_)
                    replaced.append(name)
                elif o.type != want:
                    warnings.append('«%s» ya existe y es %s, no %s: se omite' % (name, o.type, want))
                    continue
            if t in PRIMITIVES and any(k in os_ for k in GEOM_KEYS if k != 'type') \
                    and o.get('bs_geom') != _geom_sig(os_):
                old = o.data
                o.data = _con_nombre(name, _geom_data, os_, name)
                for m in old.materials:
                    o.data.materials.append(m)
                if old.users == 0:
                    (bpy.data.meshes if isinstance(old, bpy.types.Mesh) else bpy.data.curves).remove(old)
                o['bs_geom'] = _geom_sig(os_)
            updated.append(name)
        else:
            t = t or 'cube'
            os_ = dict(os_, type=t)
            o, _ = _con_nombre(name, _new_object, os_, name)
            if t in PRIMITIVES:
                o['bs_geom'] = _geom_sig(os_)
            created.append(name)
        o['bs_spec'] = 1
        if os_.get('collection') or not o.users_collection:
            _move_to(o, _collection(os_.get('collection')))
        _apply_data(o, os_, warnings)
        _apply_transform(o, os_)
        if t == 'outline' and os_.get('inView'):
            # la pieza va donde está en la vista (su centro), sumado a `location` (la del cuerpo)
            if name in _BUILD['viewAt']:
                o['bs_view_at'] = _BUILD['viewAt'][name]
            if o.get('bs_view_at'):
                x, z = o['bs_view_at']
                de_lado = str(os_.get('view', 'front')).lower() == 'side'
                o.location = Vector(vec3(os_.get('location', (0, 0, 0)))) + Vector((0, x, z) if de_lado else (x, 0, z))
                if de_lado and o.type == 'MESH' and 'rotation' not in os_ and not os_.get('attach') \
                        and str(os_.get('plane', 'XZ')).upper() == 'XZ':
                    o.rotation_euler = (0, 0, math.pi / 2)  # de pie en el plano de esa vista (YZ, de frente a +X)
        if o.type == 'CURVE' and t == 'outline' and 'rotation' not in os_ \
                and str(os_.get('plane', 'XZ')).upper() == 'XZ':
            o.rotation_euler = (math.pi / 2, 0, 0)          # la curva 2D vive en XY: de pie, de frente a -Y
        if name in _BUILD['sources']:
            o['bs_source'] = json.dumps(_BUILD['sources'][name], ensure_ascii=False)
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
    if _BUILD['motions']:
        res['motions'] = _BUILD['motions']
    if _BUILD['outlines']:
        res['outlines'] = _BUILD['outlines']
        for n, inf in _BUILD['outlines'].items():
            if 'strokes' in inf:
                for t in inf['strokes']:
                    if t['index'] in inf['picked'] and t['iou'] < 0.85:
                        warnings.append('«%s»: el trazo %d calza poco con la imagen (IoU %s): ¿es una parte fina? '
                                        'Mira outlines y la vista previa de contour -Strokes' % (n, t['index'], t['iou']))
            elif not inf['targetMet']:
                warnings.append('«%s»: algún contorno no llegó a la tolerancia de %s %% (mira outlines)'
                                % (n, inf['tolerancePercent']))
            if inf.get('viewsMismatchPercent', 0) > 2:
                warnings.append('«%s»: el cuerpo no mide lo mismo de alto en las dos vistas (%s %% del alto): '
                                '¿son del mismo objeto, a la misma escala y con el mismo height?'
                                % (n, inf['viewsMismatchPercent']))
            if inf.get('side') == 'both' and inf.get('asymmetryPercent', 0) > 3:
                warnings.append('«%s»: las dos mitades de la silueta difieren %s %% del alto; si de un lado '
                                'hay un asa o un pico usa side left/right, o la foto no está de lado'
                                % (n, inf['asymmetryPercent']))
    if removed:
        res['removed'] = removed
    if replaced:
        res['replaced'] = replaced
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

def _retro_file(path, out_path, bits=5, scale=4, dither=True):
    """Look de consola de 32 bits: color de `bits` por canal (5 = 15 bits) con tramado ordenado 4x4 y
    ampliación x`scale` con píxeles duros (vecino más cercano)."""
    import numpy as np
    im = bpy.data.images.load(path, check_existing=False)
    w, h = im.size
    px = np.empty(w * h * 4, np.float32)
    im.pixels.foreach_get(px)
    bpy.data.images.remove(im)
    px = px.reshape(h, w, 4)
    niveles = float(2 ** int(bits) - 1)
    um = 0.0
    if dither:
        bayer = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]], np.float32) / 16 - 0.5
        um = np.tile(bayer, (h // 4 + 1, w // 4 + 1))[:h, :w, None] * 0.9
    px[..., :3] = np.clip(np.floor(px[..., :3] * niveles + 0.5 + um) / niveles, 0, 1)
    px[..., 3] = 1
    k = max(1, int(scale))
    g = px.repeat(k, axis=0).repeat(k, axis=1)
    out = bpy.data.images.new('bs_retro', w * k, h * k, alpha=False)
    out.pixels.foreach_set(g.ravel())
    out.filepath_raw = out_path
    out.file_format = 'PNG'
    out.save()
    bpy.data.images.remove(out)


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
        vista = args.get('view') or 'iso'
        if args.get('ortho'):
            # ortográfica, como un plano o una vista de frente/costado dibujada: sin perspectiva y, en las
            # vistas con nombre, justo de frente (sin la leve elevación que se usa para ver el piso)
            cam.data.type = 'ORTHO'
            if isinstance(vista, str) and vista in ('front', 'back', 'right', 'left'):
                vista = [VIEWS[vista][0], VIEWS[vista][1], 0.0]
        frame_camera(cam, args.get('objects'), vista)
        s.camera = cam
    if args.get('frame') is not None:
        s.frame_set(int(args['frame']))
    retro = args.get('retro')
    if retro:
        # se renderiza chico (p. ej. 320 de ancho) y después se amplía con píxeles duros
        rw = int(retro.get('width', 320))
        ar = s.render.resolution_y / s.render.resolution_x
        s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage = rw, max(16, round(rw * ar)), 100
        s.render.filter_size = 0.5      # bordes más duros, como el hardware de la época
    s.render.image_settings.file_format = 'JPEG' if path.lower().endswith(('.jpg', '.jpeg')) and not retro else 'PNG'
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    if args.get('animation'):
        if args.get('frames'):
            s.frame_start, s.frame_end = (int(x) for x in args['frames'])
        base, _ = os.path.splitext(path)
        s.render.filepath = base + '_####'
        bpy.ops.render.render(animation=True)
        if retro:
            for f in range(s.frame_start, s.frame_end + 1):
                fp = base + '_%04d.png' % f
                if os.path.exists(fp):
                    _retro_file(fp, fp, retro.get('bits', 5), retro.get('scale', 4), retro.get('dither', True))
        return {'frames': [s.frame_start, s.frame_end], 'pattern': base + '_####.png', 'engine': s.render.engine,
                'camera': s.camera.name, 'retro': bool(retro)}
    s.render.filepath = path
    bpy.ops.render.render(write_still=True)
    if retro:
        _retro_file(path, path, retro.get('bits', 5), retro.get('scale', 4), retro.get('dither', True))
        k = int(retro.get('scale', 4))
        return {'image': path, 'engine': s.render.engine, 'camera': s.camera.name, 'retro': True,
                'size': [s.render.resolution_x * k, s.render.resolution_y * k]}
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


def _subject_mask(px, holes='fill'):
    """Figura de la referencia: lo que se aparta del color de fondo (la mediana del borde, por fila), sin
    líneas sueltas (cuadrícula del visor, gizmos) ni recortes de la interfaz. Conserva las partes finas
    y separadas de una misma fila (dientes, cuernos, dedos, brazos sueltos del torso). Los huecos
    cerrados se tapan con holes='fill' (la zona del mismo color que el fondo, p. ej. una barriga blanca
    sobre fondo blanco, no se confunde con un agujero) o se conservan con holes='keep'."""
    import numpy as np
    if px[..., 3].min() < 0.5:                     # imagen con transparencia: el alfa ya es la figura
        return _holes(_largest_component(px[..., 3] > 0.5), holes)
    h, w = px.shape[:2]
    # fondo por fila (los visores y estudios suelen tener degradado vertical): mediana de los bordes
    b = max(4, w // 40)
    borde = np.concatenate([px[:, :b, :3], px[:, -b:, :3]], axis=1)
    fondo = np.median(borde, axis=1)                                   # (h, 3)
    ruido = np.abs(borde - fondo[:, None]).max(axis=2)
    m = np.abs(px[..., :3] - fondo[:, None]).max(axis=2) > max(0.035, float(np.percentile(ruido, 95)) * 1.5)
    # fuera las líneas de 1-2 px (cuadrícula, gizmos) y lo que no está unido a la figura
    return _holes(_largest_component(_opening(m)), holes)


def _dilate(m, n=1):
    """Dilatación con una cruz 3x3, n veces."""
    for _ in range(n):
        d = m.copy()
        d[1:] |= m[:-1]
        d[:-1] |= m[1:]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        m = d
    return m


def _erode(m, n=1):
    return ~_dilate(~m, n)


def _opening(m):
    """Erosión y dilatación con una cruz 3x3: borra líneas de hasta 2 px y deja intacto lo demás."""
    return _dilate(_erode(m)) & m


def _filled(m):
    """La silueta con sus huecos cerrados tapados: se rellena cada contorno exterior por separado, así
    una isla dentro de un hueco no vacía a su contenedor."""
    from . import contours
    out = m.copy()
    for r in contours.regions(contours.trace(m.astype('float64'))):
        out |= contours.rasterize([r['outer'] * [1, -1]], m.shape, (0.0, 0.0), 1.0)
    return out


def _holes(m, mode='fill'):
    """Tapa los huecos de una silueta (mode='fill') o la deja como está ('keep'). Además de los huecos
    cerrados, tapa las zonas interiores que solo se abren al fondo por una rendija de hasta ~6 px (una
    parte del mismo color que el fondo pegada al borde), sin rellenar las muescas del contorno."""
    if mode == 'keep' or not m.any():
        return m
    if mode != 'fill':
        raise ValueError('holes debe ser fill o keep')
    cerrado = _erode(_dilate(m, 3), 3)
    interior = _filled(cerrado) & ~cerrado
    rendijas = cerrado & ~m & _dilate(interior)
    return _filled(m) | interior | rendijas


def _largest_component(m, keep=0.1):
    """Se queda con la región conectada más grande y con las que miden al menos `keep` de ella (una
    figura con partes sueltas), sin iconos ni botones chicos (en una versión reducida, para ir rápido)."""
    import numpy as np
    from collections import deque
    h, w = m.shape
    k = max(1, int(math.ceil(max(h, w) / 240)))
    hh, ww = int(math.ceil(h / k)), int(math.ceil(w / k))
    pad = np.zeros((hh * k, ww * k), bool)
    pad[:h, :w] = m
    small = pad.reshape(hh, k, ww, k).any(axis=(1, 3))
    lab = np.zeros(small.shape, np.int32)
    tam, n = {}, 0
    for y0, x0 in zip(*np.nonzero(small)):
        if lab[y0, x0]:
            continue
        n += 1
        lab[y0, x0] = n
        q, c = deque([(y0, x0)]), 0
        while q:
            y, x = q.popleft()
            c += 1
            for dy, dx in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                yy, xx = y + dy, x + dx
                if 0 <= yy < hh and 0 <= xx < ww and small[yy, xx] and not lab[yy, xx]:
                    lab[yy, xx] = n
                    q.append((yy, xx))
        tam[n] = c
    if not tam:
        return m
    mayor = max(tam.values())
    grandes = [n_ for n_, c in tam.items() if c >= keep * mayor]
    quedan = np.repeat(np.repeat(np.isin(lab, grandes), k, axis=0), k, axis=1)[:h, :w]
    return m & quedan


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
    (alto igual, centrada en x, apoyada en la misma base). Devuelve medidas para comparar sin adivinar.
    holes: 'fill' (por defecto) o 'keep', igual para la referencia y para el render."""
    import numpy as np
    h = int(args.get('height', 800))
    holes = args.get('holes', 'fill')
    ref = _load_pixels(args['reference'], h)
    ren = _load_pixels(args['render'])
    rmask = _subject_mask(ref, holes)
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
    gmask = _holes(ren[..., 3] > 0.5, holes)
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
                m = _mask_crop(_holes(px[..., 3] > 0.5, args.get('holes', 'fill')), H)
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
    """Para cada décimo del alto de la figura en el render (de abajo arriba): la altura media del mundo (z)
    de lo que se ve ahí, y qué piezas forman su borde izquierdo y derecho. Usa los vértices reales
    proyectados por la cámara, así que vale también en perspectiva."""
    from bpy_extras.object_utils import world_to_camera_view
    s = _scene()
    px = _load_pixels(render_path)
    b = _bbox(px[..., 3] > 0.5)
    cam = s.camera
    if not b or cam is None:
        return None, None
    h = px.shape[0]
    v0, v1 = b[1] / h, b[3] / h
    dg = bpy.context.evaluated_depsgraph_get()
    objs = [_obj(n) for n in objs_names] if objs_names else \
        [o for o in s.objects if o.type in ('MESH', 'FONT', 'CURVE') and not o.hide_render
         and o.display_type not in ('WIRE', 'BOUNDS')]
    bandas = [[] for _ in range(10)]
    for o in objs:
        e = o.evaluated_get(dg)
        try:
            me = e.to_mesh()
        except RuntimeError:
            continue
        mw = o.matrix_world
        vs = me.vertices
        step = max(1, len(vs) // 1500)
        for i in range(0, len(vs), step):
            w = mw @ vs[i].co
            c = world_to_camera_view(s, cam, w)
            if c.z <= 0 or not (v0 <= c.y <= v1):
                continue
            k = min(9, int((c.y - v0) / max(1e-9, v1 - v0) * 10))
            bandas[k].append((c.x, w.z, o.name))
        e.to_mesh_clear()
    zs, bordes = [], []
    for bd in bandas:
        if not bd:
            zs.append(None)
            bordes.append(None)
            continue
        zz = sorted(t[1] for t in bd)
        zs.append(round(zz[len(zz) // 2], 3))
        bordes.append({'left': min(bd)[2], 'right': max(bd)[2]})
    return zs, bordes


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
    # con `objects` solo esas piezas cuentan como figura: lo demás (un piso, una mesa, el fondo) se oculta
    # mientras se renderiza, si no su silueta se suma a la del objeto
    ocultos = []
    if args.get('objects'):
        quedan = {_obj(n).name for n in args['objects']}
        for o in s.objects:
            if o.type in ('MESH', 'FONT', 'CURVE', 'SURFACE', 'META') and o.name not in quedan and not o.hide_render:
                o.hide_render = True
                ocultos.append(o)
    try:
        if args.get('fitView'):
            fit = _fit_view(args, _subject_mask(_load_pixels(os.path.abspath(args['reference']), 400),
                                                args.get('holes', 'fill')))
            args = dict(args, view=fit['view'])
        # transparente: así la figura del render se separa del fondo sin adivinar
        r = op_render(dict(args, path=tmp, percentage=100, transparent=True))
    finally:
        for o in ocultos:
            o.hide_render = False
    zg, bordes = _z_by_guide(tmp, args.get('objects'))
    c = op_compose({'reference': os.path.abspath(args['reference']), 'render': tmp, 'path': out,
                    'height': int(args.get('height', 800)), 'guides': args.get('guides', True),
                    'align': args.get('align', True), 'overlay': args.get('overlay', True),
                    'holes': args.get('holes', 'fill')})
    if zg:
        c['alignment']['zByGuide'] = zg
        c['alignment']['edgesByGuide'] = bordes
    if fit:
        c['fitView'] = fit
    return dict(c, render=tmp, camera=r.get('camera'), engine=r.get('engine'))


def _palette():
    """Colores de material (como se ven en pantalla) de lo visible en el render: la paleta de clases."""
    import numpy as np
    s = _scene()
    vistos = []
    for o in s.objects:
        if o.type not in ('MESH', 'FONT', 'CURVE') or o.hide_render or o.display_type in ('WIRE', 'BOUNDS'):
            continue
        for slot in o.material_slots:
            m = slot.material
            if m is None:
                continue
            c = tuple(round(_srgb(x), 3) for x in m.diffuse_color[:3])
            if c not in [v[1] for v in vistos]:
                vistos.append((m.name, c))
    return [v[0] for v in vistos], np.array([v[1] for v in vistos], dtype=np.float32)


def _classify(px, mask, pal):
    """Asigna cada píxel de la figura al color de la paleta más parecido, sin depender del brillo
    (la referencia tiene luz y sombra; el render de ajuste es plano)."""
    import numpy as np
    rgb = px[..., :3]
    val = rgb.max(axis=2)
    nrm = rgb / (val[..., None] + 0.06)
    pv = pal.max(axis=1)
    pn = pal / (pv[:, None] + 0.06)
    d = ((nrm[..., None, :] - pn[None, None]) ** 2).sum(axis=3) + 0.35 * (val[..., None] - pv[None, None]) ** 2
    lab = d.argmin(axis=2).astype(np.int16)
    lab[~mask] = -1
    return lab


def _crop_labels(lab, mask, h):
    """Etiquetas recortadas a la caja de la figura y escaladas (vecino más cercano) a la altura h."""
    import numpy as np
    b = _bbox(mask)
    if not b:
        return None
    m = lab[b[1]:b[3] + 1, b[0]:b[2] + 1]
    w = max(1, round(m.shape[1] * h / m.shape[0]))
    ys = (np.arange(h) * m.shape[0] / h).astype(int)
    xs = (np.arange(w) * m.shape[1] / w).astype(int)
    return m[ys][:, xs]


def _iou_classes(a, b, clases):
    """IoU de cada clase entre dos mapas de etiquetas ya escalados a la misma altura, centrados en x."""
    import numpy as np
    W = max(a.shape[1], b.shape[1])
    A = np.full((a.shape[0], W), -1, np.int16)
    B = np.full((b.shape[0], W), -1, np.int16)
    A[:, (W - a.shape[1]) // 2:(W - a.shape[1]) // 2 + a.shape[1]] = a
    B[:, (W - b.shape[1]) // 2:(W - b.shape[1]) // 2 + b.shape[1]] = b
    out = {}
    for c in clases:
        ma, mb = A == c, B == c
        u = (ma | mb).sum()
        out[c] = float((ma & mb).sum() / u) if u else 0.0
    return out


def _parse_view(v):
    if isinstance(v, str) and ',' in v:
        return [float(x) for x in v.strip('[]').split(',')]
    return v


def op_fit(args):
    """Ajuste automático de proporciones: mueve y escala las piezas indicadas hasta que la silueta del
    render se parezca lo más posible a la de la referencia (IoU tras alinear las figuras).

    Con varias referencias (`references`: [{path, view}], p. ej. tres cuartos + perfil) maximiza el
    promedio: una sola vista oblicua confunde ancho con profundidad y la segunda lo resuelve.
    `view` de cada referencia: front|back|left|right|top|iso, un vector, o «fit» para buscarla.

    args: reference(s), parts [{name, params ("sx sy sz x y z"), mirror, maxScale (1.6), maxMove}],
    view o fitView (para una sola referencia), budget (renders, 400), rounds, resolution (320)."""
    import tempfile
    s = _scene()
    # alto de la silueta comparada: más alto = las piezas chicas pesan más (y cada render cuesta más)
    H = int(args.get('detail', 160))
    entrada = args.get('references') or [{'path': args['reference'], 'view': args.get('view')}]
    refs = []
    for r in entrada:
        r = {'path': r} if isinstance(r, str) else dict(r)
        mask = _subject_mask(_load_pixels(os.path.abspath(r['path']), 400), args.get('holes', 'fill'))
        crop = _mask_crop(mask, H)
        if crop is None:
            raise ValueError('No se detectó la figura en la referencia %s' % r['path'])
        v = _parse_view(r.get('view'))
        busca = v == 'fit' or (v is None and args.get('fitView'))
        refs.append({'path': os.path.abspath(r['path']), 'mask': mask, 'c': crop,
                     'view': v if not busca and v else 'front', 'fit': bool(busca), 'vistas': [], 'iou': None,
                     'px': _load_pixels(os.path.abspath(r['path']), 400) if args.get('colors') else None})

    # regiones de color: cada píxel de la referencia se asigna al material más parecido. Así cuentan
    # las piezas chicas que casi no cambian la silueta (alas pegadas al cuerpo, patas, adornos)
    colores = bool(args.get('colors'))
    if colores:
        nombres_mat, pal = _palette()
        if len(pal) < 2:
            colores = False
        else:
            for ref in refs:
                lab = _classify(ref['px'], ref['mask'], pal)
                ref['lab'] = _crop_labels(lab, ref['mask'], H)
                total = max(1, int(ref['mask'].sum()))
                ref['clases'] = [c for c in range(len(pal)) if (lab == c).sum() / total >= 0.01]
                ref['px'] = None

    guardado = (s.render.engine, s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage,
                s.render.film_transparent, s.camera, s.render.filepath)
    sh = s.display.shading
    guardado_sh = (sh.light, sh.color_type, sh.show_shadows, sh.show_cavity, s.view_settings.view_transform,
                   s.view_settings.look)
    RES = int(args.get('resolution', 320))   # cuanto más cerca de la de compare, menos sorpresas

    def formato(ref):
        rh, rw = ref['mask'].shape
        s.render.resolution_y, s.render.resolution_x = RES, max(16, round(RES * rw / rh))
        s.render.resolution_percentage = 100

    def buscar_vista(ref, azs=None, els=None):
        formato(ref)
        s.camera = guardado[5]
        a_ = dict(args)
        if azs:
            a_['fitAzimuths'], a_['fitElevations'] = azs, els
        info = _fit_view(a_, ref['mask'])
        ref['view'] = info['view']
        ref['vistas'].append(dict(info, round=len(ref['vistas']) + 1))

    for ref in refs:
        if ref['fit']:
            buscar_vista(ref)

    _set_engine(s, 'workbench')
    s.render.film_transparent = True
    s.render.image_settings.file_format = 'PNG'
    if colores:
        # render plano con el color exacto de cada material: la clase de cada píxel es inequívoca
        sh.light, sh.color_type = 'FLAT', 'MATERIAL'
        sh.show_shadows = sh.show_cavity = False
        s.view_settings.view_transform = 'Standard'
        s.view_settings.look = 'None'
    cam = bpy.data.objects.new('bs_fitcam', bpy.data.cameras.new('bs_fitcam'))
    s.collection.objects.link(cam)
    s.camera = cam
    tmp = os.path.join(tempfile.mkdtemp(prefix='bs-fit-'), 'f.png')

    def medir():
        """Promedio del IoU de silueta en todas las vistas de referencia."""
        bpy.context.view_layer.update()
        total = 0.0
        for ref in refs:
            formato(ref)
            frame_camera(cam, None, ref['view'])
            s.render.filepath = tmp
            bpy.ops.render.render(write_still=True)
            px = _load_pixels(tmp)
            alfa = px[..., 3] > 0.5
            m = _mask_crop(_holes(alfa, args.get('holes', 'fill')), H)
            ref['iou'] = _iou_aligned(ref['c'], m) if m is not None else 0.0
            valor = ref['iou']
            if colores and m is not None and ref['clases']:
                lab = _crop_labels(_classify(px, alfa, pal), alfa, H)
                ref['clsIou'] = _iou_classes(ref['lab'], lab, ref['clases'])
                cw = float(args.get('colorWeight', 0.3))
                valor = (1 - cw) * ref['iou'] + cw * sum(ref['clsIou'].values()) / len(ref['clsIou'])
            total += valor
        return total / len(refs)

    # variables: escala (multiplicador, en escala logarítmica) y desplazamiento de cada pieza
    figura = [o for o in s.objects if o.type in ('MESH', 'FONT', 'CURVE') and not o.hide_render]
    _, radio = _bounds(figura)
    partes, vars_ = [], []
    for pd in args['parts']:
        pd = {'name': pd} if isinstance(pd, str) else pd
        o = _obj(pd['name'])
        espejo = _obj(pd['mirror']) if pd.get('mirror') else None
        partes.append({'o': o, 'loc': o.location.copy(), 'scale': o.scale.copy(), 'mirror': espejo,
                       'mloc': espejo.location.copy() if espejo else None,
                       'mscale': espejo.scale.copy() if espejo else None})
        for q in (pd.get('params') or 'sx sy sz x y z').split():
            es_escala = q.startswith('s')
            lim = math.log(float(pd.get('maxScale', 1.6))) if es_escala else float(pd.get('maxMove', radio * 0.25))
            vars_.append({'p': len(partes) - 1, 'q': q, 'v': 0.0, 'lim': lim,
                          'step': 0.18 if es_escala else radio * 0.06})

    def aplicar():
        for i, pt in enumerate(partes):
            sc, mv = [1.0, 1.0, 1.0], [0.0, 0.0, 0.0]
            for v in vars_:
                if v['p'] != i:
                    continue
                ax = 'xyz'.index(v['q'][-1])
                if v['q'].startswith('s'):
                    sc[ax] = math.exp(v['v'])
                else:
                    mv[ax] = v['v']
            pt['o'].scale = Vector([pt['scale'][k] * sc[k] for k in range(3)])
            pt['o'].location = pt['loc'] + Vector(mv)
            if pt['mirror'] is not None:
                pt['mirror'].scale = Vector([pt['mscale'][k] * sc[k] for k in range(3)])
                pt['mirror'].location = pt['mloc'] + Vector((-mv[0], mv[1], mv[2]))

    presupuesto = int(args.get('budget', 400))
    alguna_busca = any(r['fit'] for r in refs)
    rondas = int(args.get('rounds', 3 if alguna_busca else 1))
    paso0 = {id(v): v['step'] for v in vars_}

    def buscar(limite, r):
        """Búsqueda por coordenadas con pasos que se achican cuando una pasada no mejora."""
        nonlocal mejor, evals
        for v in vars_:
            v['step'] = paso0[id(v)] * (0.5 if r > 0 else 1.0)
        while evals < limite:
            mejoro = False
            for v in vars_:
                if evals >= limite:
                    break
                for signo in (1, -1):
                    viejo = v['v']
                    v['v'] = max(-v['lim'], min(v['lim'], viejo + signo * v['step']))
                    if v['v'] == viejo:
                        continue
                    aplicar()
                    val = medir()
                    evals += 1
                    if val > mejor + 1e-4:
                        mejor, mejoro = val, True
                        break
                    v['v'] = viejo
                    aplicar()
                    if evals >= limite:
                        break
            historial.append(round(mejor, 4))
            if not mejoro:
                for v in vars_:
                    v['step'] *= 0.5
                if all(v['step'] < (0.01 if v['q'].startswith('s') else radio * 0.003) for v in vars_):
                    break

    try:
        aplicar()
        inicio = mejor = medir()
        inicio_por_vista = [round(r['iou'], 3) for r in refs]
        evals, historial = 1, [round(inicio, 4)]
        for r in range(rondas):
            if r > 0:
                # con las proporciones ya ajustadas, la vista se distingue mejor: buscar cerca y en espejo
                for ref in refs:
                    if not ref['fit']:
                        continue
                    az, el = ref['vistas'][-1]['azimuth'], ref['vistas'][-1]['elevation']
                    azs = sorted({max(-85, min(85, a_)) for a_ in
                                  [az + d for d in (-10, -5, 0, 5, 10)] + [-az + d for d in (-10, -5, 0, 5, 10)]})
                    els = sorted({max(0.0, min(45.0, el + d)) for d in (-10.0, -5.0, 0.0, 5.0, 10.0)})
                    buscar_vista(ref, azs, els)
                s.camera = cam
                _set_engine(s, 'workbench')
                s.render.film_transparent = True
                mejor = medir()
                evals += 1
            buscar(evals + (presupuesto - evals) // (rondas - r), r)
        aplicar()
        mejor = medir()
    finally:
        bpy.data.objects.remove(cam, do_unlink=True)
        (eng, s.render.resolution_x, s.render.resolution_y, s.render.resolution_percentage,
         s.render.film_transparent, s.camera, s.render.filepath) = guardado
        s.render.engine = eng
        (sh.light, sh.color_type, sh.show_shadows, sh.show_cavity, s.view_settings.view_transform,
         s.view_settings.look) = guardado_sh
    if not bpy.app.background:
        try:
            with _ctx():
                bpy.ops.ed.undo_push(message='blender-steroids: fit')
        except Exception:
            pass
    resultado = {}
    for pt in partes:
        for o in [pt['o']] + ([pt['mirror']] if pt['mirror'] is not None else []):
            resultado[o.name] = {'location': r3(o.location), 'scale': r3(o.scale)}
    vistas = []
    for ref, i0 in zip(refs, inicio_por_vista):
        v = ref['view']
        extra = {}
        if colores and ref.get('clsIou'):
            extra['colorIoU'] = {nombres_mat[c]: round(x, 3) for c, x in ref['clsIou'].items()}
        vistas.append(dict(extra, reference=ref['path'], view=[round(x, 4) for x in v] if not isinstance(v, str) else v,
                       iouStart=i0, iouEnd=round(ref['iou'], 3),
                       search=[{'round': x['round'], 'azimuth': x['azimuth'], 'elevation': x['elevation']}
                               for x in ref['vistas']]))
    return {'iouStart': round(inicio, 3), 'iouEnd': round(mejor, 3), 'evals': evals, 'passes': historial,
            'references': vistas, 'parts': resultado,
            'score': 'silueta + regiones de color' if colores else 'silueta',
            'note': 'iouStart/iouEnd es la puntuación que se maximiza (promedio de las vistas). Escribe parts en el spec (location y scale) y vuelve a '
                    'correr build (o build -Patch): las calcomanías y lo colocado con attach se recolocan.'}


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


def op_import(args):
    """Importa un modelo (glb, gltf, fbx, obj, stl, ply, usd) como base editable: agrupa sus piezas bajo un
    vacío con nombre, opcionalmente lo escala a una altura, lo apoya en el suelo y lo coloca."""
    path = os.path.abspath(args['path'])
    if not os.path.exists(path):
        raise FileNotFoundError(path)
    ext = os.path.splitext(path)[1].lower()
    antes = set(bpy.data.objects)
    with _ctx():
        if ext in ('.glb', '.gltf'):
            bpy.ops.import_scene.gltf(filepath=path)
        elif ext == '.fbx':
            bpy.ops.import_scene.fbx(filepath=path)
        elif ext == '.obj':
            bpy.ops.wm.obj_import(filepath=path)
        elif ext == '.stl':
            bpy.ops.wm.stl_import(filepath=path)
        elif ext == '.ply':
            bpy.ops.wm.ply_import(filepath=path)
        elif ext in ('.usd', '.usdc', '.usda', '.usdz'):
            bpy.ops.wm.usd_import(filepath=path)
        else:
            raise ValueError('Formato no soportado: %s (glb, gltf, fbx, obj, stl, ply, usd)' % ext)
    nuevos = [o for o in bpy.data.objects if o not in antes]
    if not nuevos:
        raise ValueError('El archivo no trajo objetos')
    nombre = args.get('name') or os.path.splitext(os.path.basename(path))[0]
    raiz = bpy.data.objects.new(nombre, None)
    raiz.empty_display_type, raiz['bs_spec'] = 'PLAIN_AXES', 1
    coll = _collection(args.get('collection') or nombre)
    coll.objects.link(raiz)
    for o in nuevos:
        _move_to(o, coll)
        if o.parent is None or o.parent not in nuevos:
            mw = o.matrix_world.copy()
            o.parent = raiz
            o.matrix_world = mw
    bpy.context.view_layer.update()
    mallas = [o for o in nuevos if o.type == 'MESH'] or nuevos
    lo = Vector([min((o.matrix_world @ Vector(c))[i] for o in mallas for c in o.bound_box) for i in range(3)])
    hi = Vector([max((o.matrix_world @ Vector(c))[i] for o in mallas for c in o.bound_box) for i in range(3)])
    k = 1.0
    if args.get('height') and hi.z - lo.z > 1e-9:
        k = float(args['height']) / (hi.z - lo.z)
    # el vacío queda en el centro de la base del modelo: así location lo apoya donde se pida
    pivote = Vector(((lo.x + hi.x) / 2, (lo.y + hi.y) / 2, lo.z))
    for o in nuevos:
        if o.parent == raiz:
            o.matrix_world = Matrix.Translation(-pivote) @ o.matrix_world
    raiz.scale = (k, k, k)
    raiz.location = vec3(args.get('location', (0, 0, 0)))
    if args.get('rotation'):
        raiz.rotation_euler = [math.radians(a) for a in vec3(args['rotation'])]
    bpy.context.view_layer.update()
    d = (hi - lo) * k
    return {'root': raiz.name, 'objects': [o.name for o in nuevos], 'meshes': sum(1 for o in nuevos if o.type == 'MESH'),
            'dimensions': r3(d), 'scale': round(k, 4), 'collection': coll.name}


def op_walk(args):
    """Ciclo de caminata sin huesos para personajes hechos de piezas.

    args: legs [{pivot [x,y,z] (cadera), parts [...], foot (pieza que apoya)}] (2 o más, alternan),
    body {pivot, parts} (sube, baja y se mece), head {pivot, parts} (asiente), arms [{pivot, parts}]
    (balanceo opuesto a la pierna del mismo lado; omítelos si sostiene algo), follow (cámara que lo
    sigue), cycle (fotogramas por ciclo, 24), cycles (2), angle (apertura en grados, 22), lift (cuánto sube
    el pie en el aire, m), sway (°), nod (°), armAngle (°), direction ([x,y] hacia dónde camina; el
    personaje debe mirar a -Y en su pose de reposo). Pies planos y rebote medido en cada fotograma: el
    pie de apoyo toca el piso, nunca lo atraviesa."""
    s = _scene()
    C = int(args.get('cycle', 24))
    N = int(args.get('cycles', 2))
    A = math.radians(float(args.get('angle', 22)))
    ALZA = float(args.get('lift', 0.035))
    s.frame_start, s.frame_end = 1, C * N

    def vacio(nombre, loc, padre=None):
        o = bpy.data.objects.get(nombre) or bpy.data.objects.new(nombre, None)
        if o.name not in s.collection.objects:
            s.collection.objects.link(o)
        o.empty_display_type, o.empty_display_size = 'PLAIN_AXES', 0.1
        o.animation_data_clear()
        o.parent = None
        o.location, o.rotation_euler = vec3(loc), (0, 0, 0)
        bpy.context.view_layer.update()
        if padre:
            colgar(o, padre)
        return o

    def colgar(o, padre):
        bpy.context.view_layer.update()
        mw = o.matrix_world.copy()
        o.parent = padre
        o.matrix_parent_inverse = padre.matrix_world.inverted()
        o.matrix_world = mw

    def clave(o, prop, valor, f):
        setattr(o, prop, valor)
        o.keyframe_insert(data_path=prop, frame=f)

    raiz = vacio('bs_walk_raiz', (0, 0, 0))
    rebote = vacio('bs_walk_rebote', (0, 0, 0), raiz)
    piernas = []
    for i, lg in enumerate(args['legs']):
        cad = vacio('bs_walk_pierna%d' % i, lg['pivot'], rebote)
        for n in lg['parts']:
            colgar(_obj(n), cad)
        pie = _obj(lg.get('foot') or lg['parts'][0])
        pie.animation_data_clear()
        piernas.append((cad, pie, Vector(vec3(lg['pivot'])), 1 if i % 2 == 0 else -1))
    cuerpo = cabeza = None
    if args.get('body'):
        cuerpo = vacio('bs_walk_cuerpo', args['body']['pivot'], rebote)
        for n in args['body']['parts']:
            colgar(_obj(n), cuerpo)
    if args.get('head'):
        cabeza = vacio('bs_walk_cabeza', args['head']['pivot'], cuerpo or rebote)
        for n in args['head']['parts']:
            colgar(_obj(n), cabeza)
    brazos = []
    for i, ar in enumerate(args.get('arms', [])):
        b = vacio('bs_walk_brazo%d' % i, ar['pivot'], cuerpo or rebote)
        for n in ar['parts']:
            colgar(_obj(n), b)
        lado = -1 if vec3(ar['pivot'])[0] < 0 else 1
        brazos.append((b, lado))
    if args.get('follow'):
        colgar(_obj(args['follow']), raiz)

    # largo de pierna medido: de la cadera a la suela del pie
    bpy.context.view_layer.update()
    L = max(0.01, sum(cad.matrix_world.translation.z - min((pie.matrix_world @ v.co).z for v in pie.data.vertices)
                      for cad, pie, _, _ in piernas) / len(piernas))
    PASO = 2 * L * math.sin(A)
    d = args.get('direction', [0, -1])
    raiz.rotation_euler = (0, 0, math.atan2(d[0], -d[1]))
    avance = Vector((d[0], d[1], 0)).normalized()

    for f in range(1, C * N + 1):
        fase = 2 * math.pi * (f - 1) / C
        for cad, pie, piv, sg in piernas:
            th = A * math.sin(fase) * sg
            clave(cad, 'rotation_euler', (-th, 0, 0), f)          # +X lleva la pierna hacia atrás (+Y)
            clave(pie, 'rotation_euler', (th, 0, 0), f)           # el pie queda plano
            alza = ALZA * max(0.0, math.cos(fase) * sg) ** 2      # sube el que va hacia adelante
            clave(cad, 'location', (piv.x, piv.y, piv.z + alza), f)
        if cuerpo:
            clave(cuerpo, 'rotation_euler', (math.radians(2), math.radians(float(args.get('sway', 3))) *
                                            math.sin(fase), 0), f)
        if cabeza:
            nod = math.radians(float(args.get('nod', 2)))
            clave(cabeza, 'rotation_euler', (nod * math.sin(2 * fase), 0, nod * math.sin(fase)), f)
        for b, lado in brazos:
            clave(b, 'rotation_euler', (math.radians(float(args.get('armAngle', 18))) * math.sin(fase) * lado, 0, 0), f)
        clave(raiz, 'location', tuple(avance * (2 * PASO * (f - 1) / C)), f)

    # rebote medido: en cada fotograma el pie más bajo toca el piso (z = 0)
    pies = [pie for _, pie, _, _ in piernas]
    minimos = []
    for f in range(1, C * N + 1):
        rebote.location = (0, 0, 0)
        s.frame_set(f)
        rebote.location = (0, 0, 0)
        bpy.context.view_layer.update()
        mn = min((p.matrix_world @ v.co).z for p in pies for v in p.data.vertices)
        clave(rebote, 'location', (0, 0, -mn), f)
    for f in range(1, C * N + 1, max(1, C // 8)):
        s.frame_set(f)
        minimos.append(round(min((p.matrix_world @ v.co).z for p in pies for v in p.data.vertices), 4))

    for o in [raiz, rebote, cuerpo, cabeza] + [x[0] for x in piernas] + pies + [b for b, _ in brazos]:
        bag = _fcurve_bag(o) if o is not None else None     # ranuras (4.4+) o Action.fcurves (4.2-4.3)
        if bag is None:
            continue
        for fc in bag.fcurves:
            for k in fc.keyframe_points:
                k.interpolation = 'LINEAR'
    s.frame_set(1)
    return {'frames': [1, C * N], 'legLength': round(L, 3), 'stride': round(PASO, 3),
            'distance': round(2 * PASO * N, 3), 'footMinZ': min(minimos), 'note':
            'footMinZ debe ser 0 (el pie de apoyo toca el piso). El ciclo se repite sin cortes.'}


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

def _draw_polyline(img, pts, color, closed=True, width=1):
    """Dibuja una polilínea (en píxeles, filas de arriba abajo) sobre img (h, w, 4)."""
    import numpy as np
    h, w = img.shape[:2]
    q = np.vstack([pts, pts[:1]]) if closed else pts
    for a, b in zip(q[:-1], q[1:]):
        n = int(max(abs(b[0] - a[0]), abs(b[1] - a[1])) * 2) + 2
        t = np.linspace(0, 1, n)[:, None]
        p = a + (b - a) * t
        for dx in range(-width + 1, width):
            for dy in range(-width + 1, width):
                xs = np.clip(np.round(p[:, 0]).astype(int) + dx, 0, w - 1)
                ys = np.clip(np.round(p[:, 1]).astype(int) + dy, 0, h - 1)
                img[ys, xs, :3] = color


_COLORES_TRAZO = [(1, 0.85, 0), (1, 0.2, 0.75), (0.2, 0.9, 0.2), (1, 0.45, 0), (0.6, 0.4, 1), (1, 1, 1)]


def _contour_strokes(args):
    """contour con strokes: las partes finas de una vista como trazos (eje, ancho, si tocan el cuerpo)."""
    import numpy as np
    from . import contours
    _BUILD['baseDir'] = None
    px, ruta = _image_px(args)
    excluir = args.get('exclude')
    if isinstance(excluir, str):
        excluir = [c for c in excluir.split(',') if c]
    trazos, info = contours.strokes(px, height=args.get('height'), thin=float(args.get('thin', 10)), exclude=excluir,
                                    threshold=args.get('threshold'), color=args.get('color'),
                                    color_tol=float(args.get('colorTolerance', 0.15)))
    nombres = ['amarillo', 'magenta', 'verde', 'naranja', 'violeta', 'blanco']
    res = {'strokes': [dict({k: v for k, v in t.items() if k not in ('points', 'radii')}, index=i,
                            previewColor=nombres[i % len(nombres)]) for i, t in enumerate(trazos)],
           'blobs': info.get('blobs', []), 'thinPercent': info['thinPercent'], 'elapsedMs': info['elapsedMs'],
           'image': {'path': ruta, 'size': [int(px.shape[1]), int(px.shape[0])]}}
    if args.get('preview'):
        img = px.copy()
        img[..., :3] = img[..., :3] * 0.55 + 0.4
        img[..., 3] = 1
        fr = info['_frame']
        _draw_polyline(img, info['_body'], (0, 0.8, 1), True, 2)
        for i, t in enumerate(trazos):
            p = np.array(t['points'])
            q = np.column_stack([p[:, 0] / fr['k'] + fr['x0'], fr['abajo'] - p[:, 1] / fr['k']])
            col = _COLORES_TRAZO[i % len(_COLORES_TRAZO)]
            _draw_polyline(img, q, col, False, 2)
            tg = np.gradient(q, axis=0)
            tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-9)
            nrm = np.column_stack([-tg[:, 1], tg[:, 0]]) * (np.array(t['radii']) / fr['k'])[:, None]
            _draw_polyline(img, q + nrm, col, False)
            _draw_polyline(img, q - nrm, col, False)
        for b in info.get('blobs', []):                    # las bolas, en blanco
            t = np.linspace(0, 2 * np.pi, 64)
            c = np.array([b['center'][0] / fr['k'] + fr['x0'], fr['abajo'] - b['center'][1] / fr['k']])
            _draw_polyline(img, c + np.column_stack([np.cos(t), np.sin(t)]) * b['radius'] / fr['k'], (1, 1, 1), True, 2)
        out = os.path.abspath(args['preview'])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im = bpy.data.images.new('bs_contour', img.shape[1], img.shape[0], alpha=False)
        try:
            im.pixels.foreach_set(np.ascontiguousarray(img[::-1], dtype=np.float32).ravel())
            im.filepath_raw = out
            im.file_format = 'PNG'
            im.save()
        finally:
            bpy.data.images.remove(im)
        res['preview'] = out
    return res


def op_contour(args):
    """Analiza una imagen sin construir nada: qué contornos tiene, qué método y orden elige cada uno y
    con qué error (outline), o qué perfil de torno sale (lathe: true). Con `preview` dibuja el
    resultado sobre la imagen: cian = Fourier, magenta = polígono (con sus vértices en amarillo),
    para lathe el eje en amarillo y el perfil en cian a los dos lados. Con strokes: true, las partes finas
    (asas, picos, alambres) que haría `stroke`, en orden y con su color en la vista previa, y el cuerpo
    que haría `views` (en cian)."""
    import numpy as np
    from . import contours
    if args.get('strokes'):
        return _contour_strokes(args)
    o = dict(args, type='lathe' if args.get('lathe') else 'outline')
    _BUILD['baseDir'] = None
    px, ruta = _image_px(o)
    size, axis = (o['height'], 'height') if o.get('height') else (o.get('width'), 'width')
    tol = float(o.get('tolerance', 0.25))
    if o['type'] == 'lathe':
        perfil, info = contours.lathe_profile(px, size=size, axis=axis, tolerance=tol, side=o.get('side', 'both'),
                                              threshold=o.get('threshold'), rings=int(o.get('profileRings', 64)),
                                              z_range=o.get('range'))
        res = dict(_public(info), profile=[[round(float(r), 4), round(float(z), 4)] for r, z in perfil])
    else:
        regs, info = contours.outline(px, size=size, axis=axis, tolerance=tol, method=o.get('method', 'auto'),
                                      threshold=o.get('threshold'), color=o.get('color'),
                                      color_tol=float(o.get('colorTolerance', 0.15)))
        res = _public(info)
        if args.get('coefficients'):
            for l, c in zip(res['loops'], info['loops']):
                if '_coef' in c:
                    l['coefficients'] = c['_coef']
    res['image'] = {'path': ruta, 'size': [int(px.shape[1]), int(px.shape[0])]}
    if args.get('preview'):
        img = px.copy()
        img[..., :3] = img[..., :3] * 0.55 + 0.4
        img[..., 3] = 1
        fr = info['_frame']
        if o['type'] == 'lathe':
            k, eje, y0 = fr['k'], fr['axis'], fr['y0']
            filas = -(y0 + perfil[:, 1] / k)
            _draw_polyline(img, np.array([[eje, filas.min()], [eje, filas.max()]]), (1, 0.85, 0), False)
            for lado in (-1, 1):
                _draw_polyline(img, np.column_stack([eje + lado * perfil[:, 0] / k, filas]), (0, 0.8, 1), False, 2)
            for b in info['bands'][1:]:                     # límites de las franjas de color, en verde
                fila = -(y0 + b['from'] * info['height'] / k)
                ancho = info['maxRadius'] / k * 1.15
                _draw_polyline(img, np.array([[eje - ancho, fila], [eje + ancho, fila]]), (0.2, 0.9, 0.2), False)
        else:
            k, c = fr['k'], np.array(fr['center'])
            lazos = [l for r in regs for l in [r['outer']] + r['holes']]
            for lazo, l in zip(lazos, info['loops']):
                pxs = (lazo / k + c) * [1, -1]
                fourier = l['method'] == 'fourier'
                _draw_polyline(img, pxs, (0, 0.8, 1) if fourier else (1, 0.2, 0.75), True, 2)
                if not fourier:
                    for v in pxs:
                        _draw_polyline(img, np.array([v - 2, v + 2]), (1, 0.85, 0), False, 2)
        out = os.path.abspath(args['preview'])
        os.makedirs(os.path.dirname(out), exist_ok=True)
        im = bpy.data.images.new('bs_contour', img.shape[1], img.shape[0], alpha=False)
        im.pixels.foreach_set(np.ascontiguousarray(img[::-1], dtype=np.float32).ravel())
        im.filepath_raw = out
        im.file_format = 'PNG'
        im.save()
        bpy.data.images.remove(im)
        res['preview'] = out
    return res


OPS = {
    'ping': lambda a: {'pong': True},
    'info': op_info,
    'scene': op_scene,
    'build': op_build,
    'contour': op_contour,
    'exec': op_exec,
    'save': op_save,
    'open': op_open,
    'render': op_render,
    'export': op_export,
    'compare': op_compare,
    'compose': op_compose,
    'check': op_check,
    'fit': op_fit,
    'import': op_import,
    'walk': op_walk,
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

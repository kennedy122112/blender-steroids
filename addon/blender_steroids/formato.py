"""Lo que se lee de un spec sin tocar Blender: colores, vectores, rutas de imágenes, las claves que se
usan (para avisar de un error de tipeo) y la hoja de vistas que heredan las piezas. Se prueba con
tests/test_formato.py."""
import json
import os


def lin(c):
    # sRGB (lo que se ve en un selector de color) -> lineal (lo que guardan los nodos y las luces)
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def srgb(c):
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
    return (lin(r), lin(g), lin(b), a)


def hexcolor(c):
    return '#' + ''.join('%02x' % round(srgb(x) * 255) for x in c[:3])


def vec3(v, default=(0.0, 0.0, 0.0)):
    if v is None:
        return tuple(default)
    if isinstance(v, (int, float)):
        return (float(v),) * 3
    v = list(v)
    return tuple(float(x) for x in (v + list(default)[len(v):])[:3])


def r3(v, n=4):
    return [round(x, n) for x in v]


def snake(k):
    return ''.join('_' + c.lower() if c.isupper() else c for c in k)


def ruta(p, base_dir):
    """Rutas de imágenes del spec: relativas a la carpeta del spec."""
    p = os.path.expanduser(p)
    if not os.path.isabs(p) and base_dir:
        p = os.path.join(base_dir, p)
    if not os.path.exists(p):
        raise FileNotFoundError('No existe la imagen %s' % p)
    return p


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


# los módulos que leen el spec: de su código salen las claves que se usan
_LEEN_SPEC = ('ops.py', 'formato.py')
_CLAVES = set()


def claves_conocidas():
    """Las claves que el código lee de un spec (`x.get('clave')`, `x['clave']`), sacadas de los módulos
    que lo leen: así no hay una lista que mantener aparte. Una clave que no está es casi siempre un error
    de tipeo que se ignoraría en silencio."""
    import re
    if not _CLAVES:
        for nombre in _LEEN_SPEC:
            with open(os.path.join(os.path.dirname(__file__), nombre), encoding='utf-8') as f:
                src = f.read()
            _CLAVES.update(re.findall(r"\.get\('([A-Za-z][A-Za-z0-9_]*)'", src))
            _CLAVES.update(re.findall(r"\['([A-Za-z][A-Za-z0-9_]*)'\]", src))
        _CLAVES.update(GEOM_KEYS)
    return _CLAVES


def claves_raras(d, donde, warnings):
    """Avisa de las claves de `d` que el código no lee, con la más parecida que sí lee."""
    import difflib
    conocidas = claves_conocidas()
    for k in d:
        if k.startswith('_') or k in conocidas:
            continue
        cerca = difflib.get_close_matches(k, conocidas, 1, 0.75)
        warnings.append('%s: «%s» no es una clave que se use%s; se ignora'
                        % (donde, k, ' (¿%s?)' % cerca[0] if cerca else ''))


# lo que una pieza toma de la hoja de vistas si no lo dice ella: todas las piezas de una misma hoja
# tienen que medirse con el mismo marco (alto, ancho de parte fina, lo que no es figura) para encajar
HOJA_COMUNES = ('height', 'thin', 'threshold', 'exclude', 'excludeTolerance')


def con_hoja(os_, hoja):
    """El objeto completado con la hoja de vistas del spec (`sheet`: {"front", "side", "height", "thin",
    "threshold", "exclude", "excludeTolerance"}): `views` toma las dos imágenes; `stroke` y `outline`
    con `inView`, la imagen de su `view` (y `stroke`, la otra vista para su profundidad); y todas, lo
    común que no digan. Lo que el objeto dice manda."""
    t = str(os_.get('type', '')).lower()
    if not hoja or not (t in ('views', 'stroke') or (t == 'outline' and os_.get('inView'))):
        return os_
    o = dict(os_)
    for k in HOJA_COMUNES:
        if k in hoja and k not in o:
            o[k] = hoja[k]
    if t == 'views':
        for k in ('front', 'side'):
            if k not in o and hoja.get(k):
                o[k] = hoja[k]
        return o
    vista = str(o.get('view', 'front')).lower()
    otra = 'side' if vista == 'front' else 'front'
    if 'image' not in o and hoja.get(vista):
        o['image'] = hoja[vista]
    if t == 'stroke' and otra not in o and hoja.get(otra) and o.get('image') == hoja.get(vista):
        o[otra] = hoja[otra]
    return o


def geom_sig(o):
    return json.dumps({k: o[k] for k in GEOM_KEYS if k in o}, sort_keys=True)

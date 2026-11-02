"""Siluetas como máscaras de NumPy: separar la figura del fondo, operaciones morfológicas, tapar
huecos, recortar y medir el IoU entre una referencia y un render (también por color). Sin Blender: se
prueba con tests/test_mascaras.py."""
import math
from collections import deque

import numpy as np

try:
    from . import contours
except ImportError:              # fuera del add-on (los tests) se carga suelto
    import contours


def subject_mask(px, holes='fill'):
    """Figura de la referencia: lo que se aparta del color de fondo (la mediana del borde, por fila), sin
    líneas sueltas (cuadrícula del visor, gizmos) ni recortes de la interfaz. Conserva las partes finas
    y separadas de una misma fila (dientes, cuernos, dedos, brazos sueltos del torso). Los huecos
    cerrados se tapan con holes='fill' (la zona del mismo color que el fondo, p. ej. una barriga blanca
    sobre fondo blanco, no se confunde con un agujero) o se conservan con holes='keep'."""
    if px[..., 3].min() < 0.5:                     # imagen con transparencia: el alfa ya es la figura
        return fill_holes(largest_component(px[..., 3] > 0.5), holes)
    h, w = px.shape[:2]
    # fondo por fila (los visores y estudios suelen tener degradado vertical): mediana de los bordes
    b = max(4, w // 40)
    borde = np.concatenate([px[:, :b, :3], px[:, -b:, :3]], axis=1)
    fondo = np.median(borde, axis=1)                                   # (h, 3)
    ruido = np.abs(borde - fondo[:, None]).max(axis=2)
    m = np.abs(px[..., :3] - fondo[:, None]).max(axis=2) > max(0.035, float(np.percentile(ruido, 95)) * 1.5)
    # fuera las líneas de 1-2 px (cuadrícula, gizmos) y lo que no está unido a la figura
    return fill_holes(largest_component(opening(m)), holes)


def dilate(m, n=1):
    """Dilatación con una cruz 3x3, n veces."""
    for _ in range(n):
        d = m.copy()
        d[1:] |= m[:-1]
        d[:-1] |= m[1:]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        m = d
    return m


def erode(m, n=1):
    return ~dilate(~m, n)


def opening(m):
    """Erosión y dilatación con una cruz 3x3: borra líneas de hasta 2 px y deja intacto lo demás."""
    return dilate(erode(m)) & m


def filled(m):
    """La silueta con sus huecos cerrados tapados: se rellena cada contorno exterior por separado, así
    una isla dentro de un hueco no vacía a su contenedor."""
    out = m.copy()
    for r in contours.regions(contours.trace(m.astype('float64'))):
        out |= contours.rasterize([r['outer'] * [1, -1]], m.shape, (0.0, 0.0), 1.0)
    return out


def fill_holes(m, mode='fill'):
    """Tapa los huecos de una silueta (mode='fill') o la deja como está ('keep'). Además de los huecos
    cerrados, tapa las zonas interiores que solo se abren al fondo por una rendija de hasta ~6 px (una
    parte del mismo color que el fondo pegada al borde), sin rellenar las muescas del contorno."""
    if mode == 'keep' or not m.any():
        return m
    if mode != 'fill':
        raise ValueError('holes debe ser fill o keep')
    cerrado = erode(dilate(m, 3), 3)
    interior = filled(cerrado) & ~cerrado
    rendijas = cerrado & ~m & dilate(interior)
    return filled(m) | interior | rendijas


def largest_component(m, keep=0.1):
    """Se queda con la región conectada más grande y con las que miden al menos `keep` de ella (una
    figura con partes sueltas), sin iconos ni botones chicos (en una versión reducida, para ir rápido)."""
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


def bbox(mask):
    ys, xs = np.nonzero(mask)
    if len(ys) == 0:
        return None
    # recorte del 0.5 % para no depender de un píxel suelto
    return (int(np.percentile(xs, 0.5)), int(np.percentile(ys, 0.5)),
            int(np.percentile(xs, 99.5)), int(np.percentile(ys, 99.5)))


def edges(mask):
    e = np.zeros_like(mask)
    e[1:-1, 1:-1] = mask[1:-1, 1:-1] & ~(mask[:-2, 1:-1] & mask[2:, 1:-1] & mask[1:-1, :-2] & mask[1:-1, 2:])
    return e | np.roll(e, 1, 0) | np.roll(e, 1, 1)


def crop(mask, h):
    """Silueta recortada a su caja y escalada (vecino más cercano) a la altura h."""
    b = bbox(mask)
    if not b:
        return None
    m = mask[b[1]:b[3] + 1, b[0]:b[2] + 1]
    w = max(1, round(m.shape[1] * h / m.shape[0]))
    ys = (np.arange(h) * m.shape[0] / h).astype(int)
    xs = (np.arange(w) * m.shape[1] / w).astype(int)
    return m[ys][:, xs]


def iou_aligned(a, b):
    """IoU de dos siluetas ya escaladas a la misma altura, centradas en x."""
    W = max(a.shape[1], b.shape[1])
    A = np.zeros((a.shape[0], W), bool)
    B = np.zeros((b.shape[0], W), bool)
    A[:, (W - a.shape[1]) // 2:(W - a.shape[1]) // 2 + a.shape[1]] = a
    B[:, (W - b.shape[1]) // 2:(W - b.shape[1]) // 2 + b.shape[1]] = b
    u = (A | B).sum()
    return float((A & B).sum() / u) if u else 0.0


def classify(px, mask, pal):
    """Asigna cada píxel de la figura al color de la paleta más parecido, sin depender del brillo
    (la referencia tiene luz y sombra; el render de ajuste es plano)."""
    rgb = px[..., :3]
    val = rgb.max(axis=2)
    nrm = rgb / (val[..., None] + 0.06)
    pv = pal.max(axis=1)
    pn = pal / (pv[:, None] + 0.06)
    d = ((nrm[..., None, :] - pn[None, None]) ** 2).sum(axis=3) + 0.35 * (val[..., None] - pv[None, None]) ** 2
    lab = d.argmin(axis=2).astype(np.int16)
    lab[~mask] = -1
    return lab


def crop_labels(lab, mask, h):
    """Etiquetas recortadas a la caja de la figura y escaladas (vecino más cercano) a la altura h."""
    b = bbox(mask)
    if not b:
        return None
    m = lab[b[1]:b[3] + 1, b[0]:b[2] + 1]
    w = max(1, round(m.shape[1] * h / m.shape[0]))
    ys = (np.arange(h) * m.shape[0] / h).astype(int)
    xs = (np.arange(w) * m.shape[1] / w).astype(int)
    return m[ys][:, xs]


def iou_classes(a, b, clases):
    """IoU de cada clase entre dos mapas de etiquetas ya escalados a la misma altura, centrados en x."""
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


def draw_polyline(img, pts, color, closed=True, width=1):
    """Dibuja una polilínea (en píxeles, filas de arriba abajo) sobre img (h, w, 4)."""
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

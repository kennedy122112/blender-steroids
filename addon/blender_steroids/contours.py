"""
Contornos 2D: de una imagen (o de puntos) a lazos cerrados limpios y medidos, sin bpy.

  imagen -> cobertura 0..1 -> isolínea (marching squares, subpíxel) -> regiones con sus huecos
  -> cada lazo se remuestrea por longitud de arco y se simplifica con el método que mejor le va:
     fourier  (serie de Fourier truncada: curvas suaves, sin facetas)
     polygon  (Ramer-Douglas-Peucker: esquinas vivas con pocos vértices)
     auto     (elige por lazo: polygon si la mayor parte del giro está en esquinas de más de 45°)

Todo el error se mide en las unidades del contorno y en % de la diagonal de su caja (la convención de
la API), con targetMet honesto. Solo usa NumPy (viene con Blender); se prueba con tests/test_contours.py.
"""
import numpy as np

ESQUINA_GRADOS = 45.0        # un vértice del polígono que gira más que esto es una esquina
FRACCION_ESQUINAS = 0.5      # si más de esta parte del giro total está en esquinas, el lazo es "anguloso"


# ----------------------------------------------------------------------------------- imagen -> lazos

def coverage(rgba, threshold=None):
    """Cobertura 0..1 del sujeto. Con transparencia, el alfa; si no, la distancia al color de fondo (la
    mediana del borde) relativa a la del sujeto, para que el borde antialias dé la posición subpíxel.
    `threshold` (0..1) fija a mano la distancia de color que separa sujeto y fondo."""
    rgba = np.asarray(rgba, np.float64)
    if rgba.shape[-1] == 4 and rgba[..., 3].min() < 0.5:
        return rgba[..., 3]
    rgb = rgba[..., :3]
    borde = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    fondo = np.median(borde, axis=0)
    d = np.abs(rgb - fondo).max(axis=-1)
    if threshold:
        return np.clip(d / (2 * float(threshold)), 0, 1)
    tinta = d[d > 0.25 * d.max()]
    escala = float(np.median(tinta)) if tinta.size else 1.0
    return np.clip(d / max(escala, 1e-6), 0, 1)


_TABLA = {1: [(3, 2)], 2: [(2, 1)], 3: [(3, 1)], 4: [(0, 1)], 5: [(3, 0), (2, 1)], 6: [(0, 2)],
          7: [(3, 0)], 8: [(0, 3)], 9: [(0, 2)], 10: [(0, 1), (2, 3)], 11: [(0, 1)], 12: [(3, 1)],
          13: [(2, 1)], 14: [(3, 2)]}


def trace(f, level=0.5):
    """Lazos cerrados de la isolínea `level` de f (filas de arriba abajo), en píxeles (x, y) con el
    centro del píxel (0, 0) en (0, 0). Los bordes de la imagen cuentan como fondo: todo lazo cierra."""
    f = np.pad(np.asarray(f, np.float64), 1)
    a, b, c, d = f[:-1, :-1], f[:-1, 1:], f[1:, 1:], f[1:, :-1]
    caso = (a > level) * 8 + (b > level) * 4 + (c > level) * 2 + (d > level)
    ys, xs = np.nonzero((caso > 0) & (caso < 15))

    def punto(arista, i, j):
        # 0 arriba, 1 derecha, 2 abajo, 3 izquierda; la clave la comparten las dos celdas vecinas
        if arista in (0, 2):
            ii = i + (arista == 2)
            v0, v1 = f[ii, j], f[ii, j + 1]
            return ('h', ii, j), (j + (level - v0) / (v1 - v0), ii)
        jj = j + (arista == 1)
        v0, v1 = f[i, jj], f[i + 1, jj]
        return ('v', i, jj), (jj, i + (level - v0) / (v1 - v0))

    vecinos, coords = {}, {}
    for i, j in zip(ys.tolist(), xs.tolist()):
        for e0, e1 in _TABLA[int(caso[i, j])]:
            k0, p0 = punto(e0, i, j)
            k1, p1 = punto(e1, i, j)
            coords[k0], coords[k1] = p0, p1
            vecinos.setdefault(k0, []).append(k1)
            vecinos.setdefault(k1, []).append(k0)
    lazos, visto = [], set()
    for inicio in vecinos:
        if inicio in visto:
            continue
        lazo, prev, cur = [], None, inicio
        while cur not in visto:
            visto.add(cur)
            lazo.append(coords[cur])
            sig = [n for n in vecinos[cur] if n != prev and n not in visto]
            if not sig:
                break
            prev, cur = cur, sig[0]
        if len(lazo) >= 8:
            lazos.append(np.array(lazo) - 1.0)
    return lazos


def area(p):
    """Área con signo (positiva en sentido antihorario con y hacia arriba)."""
    x, y = p[:, 0], p[:, 1]
    return 0.5 * float(np.sum(x * np.roll(y, -1) - np.roll(x, -1) * y))


def inside(pt, pol):
    x, y = pt
    px, py = pol[:, 0], pol[:, 1]
    qx, qy = np.roll(px, -1), np.roll(py, -1)
    cruza = (py > y) != (qy > y)
    xi = px + (y - py) * (qx - px) / np.where(qy == py, 1e-12, qy - py)
    return bool(np.sum(cruza & (x < xi)) % 2)


def regions(loops, min_area=0.0):
    """Agrupa los lazos en regiones {outer, holes}: profundidad par = exterior, impar = hueco de su
    contenedor inmediato (una isla dentro de un hueco vuelve a ser exterior). Descarta motas."""
    loops = [l for l in loops if abs(area(l)) >= min_area]
    prof = [sum(inside(l[0], o) for k, o in enumerate(loops) if k != i) for i, l in enumerate(loops)]
    out = []
    for i, l in enumerate(loops):
        if prof[i] % 2 == 0:
            huecos = [m for k, m in enumerate(loops) if prof[k] == prof[i] + 1 and inside(m[0], l)]
            out.append({'outer': l, 'holes': huecos})
    return out


# ----------------------------------------------------------------------------------- un lazo

def canonical(p, ccw=True):
    """Orientación fija y arranque determinista (el punto más alto; empate: el de menor x)."""
    p = np.asarray(p, np.float64)
    if (area(p) > 0) != ccw:
        p = p[::-1]
    k = np.lexsort((p[:, 0], -p[:, 1]))[0]
    return np.roll(p, -k, axis=0)


def resample(p, n):
    """n puntos equiespaciados por longitud de arco sobre el lazo cerrado (sin repetir el inicial)."""
    q = np.vstack([p, p[:1]])
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(q, axis=0), axis=1))])
    t = np.linspace(0, s[-1], n, endpoint=False)
    return np.column_stack([np.interp(t, s, q[:, 0]), np.interp(t, s, q[:, 1])])


def coefficients(p):
    """c_k = (1/N) Σ z_j e^(-i2πkj/N) de la curva compleja z = x + iy."""
    p = np.asarray(p, np.float64)
    if p.ndim != 2 or p.shape[1] != 2 or len(p) < 3:
        raise ValueError('Se requieren al menos 3 puntos [x, y]')
    if not np.isfinite(p).all():
        raise ValueError('Las coordenadas deben ser finitas')
    return np.fft.fft(p[:, 0] + 1j * p[:, 1]) / len(p)


def reconstruct(c, order):
    """Curva con las frecuencias -order..order (2·order+1 coeficientes). Nyquist (N/2) queda fuera."""
    n = len(c)
    if not 0 <= order < n // 2:
        raise ValueError('Orden %s fuera de rango (0..%d)' % (order, n // 2 - 1))
    k = np.fft.fftfreq(n) * n
    z = np.fft.ifft(np.where(np.abs(k) <= order, c, 0) * n)
    return np.column_stack([z.real, z.imag])


def self_intersects(p):
    """¿Se cruza el lazo consigo mismo? Pares de lados no vecinos, O(n²) (n de unos cientos)."""
    a, b = p, np.roll(p, -1, axis=0)
    n = len(p)

    def lado(o, u, v):
        return np.sign((u[..., 0] - o[..., 0]) * (v[..., 1] - o[..., 1])
                       - (u[..., 1] - o[..., 1]) * (v[..., 0] - o[..., 0]))
    A, B, C, D = a[:, None], b[:, None], a[None], b[None]
    cruza = (lado(A, B, C) * lado(A, B, D) < 0) & (lado(C, D, A) * lado(C, D, B) < 0)
    i, j = np.indices((n, n))
    vecino = (np.abs(i - j) <= 1) | (np.abs(i - j) == n - 1)
    return bool(np.any(cruza & ~vecino))


def rdp_indices(p, tol):
    """Ramer-Douglas-Peucker sobre un lazo cerrado: índices de p que quedan como vértices (se parte en
    los dos puntos más alejados)."""
    n = len(p)

    def abierto(i0, i1):                             # de i0 a i1 (i1 puede pasar de n: vuelta al inicio)
        idx = np.arange(i0, i1 + 1) % n
        if len(idx) < 3:
            return [i0]
        q = p[idx]
        a, ab = q[0], q[-1] - q[0]
        L = np.linalg.norm(ab)
        d = (np.abs(ab[0] * (q[:, 1] - a[1]) - ab[1] * (q[:, 0] - a[0])) / L) if L > 0 \
            else np.linalg.norm(q - a, axis=1)
        k = int(np.argmax(d))
        if d[k] <= tol:
            return [i0]
        return abierto(i0, i0 + k) + abierto(i0 + k, i1)
    k = int(np.argmax(np.linalg.norm(p - p[0], axis=1)))
    return [i % n for i in abierto(0, k) + abierto(k, n)]


def refine_corners(p, idx, tol):
    """Las esquinas de un contorno trazado salen recortadas (el antialias las redondea): cada vértice
    pasa a ser el cruce de las rectas ajustadas (mínimos cuadrados) al tramo central de sus dos lados.
    Se queda donde estaba si los lados son casi paralelos o el cruce se aleja más de 4·tol."""
    n, m = len(p), len(idx)
    if m < 3:
        return p[idx]
    lineas = []
    for k in range(m):
        a, b = idx[k], idx[(k + 1) % m]
        largo = (b - a) % n
        tramo = p[(a + np.arange(int(largo * 0.2), int(largo * 0.8) + 1)) % n]
        if len(tramo) < 3:
            lineas.append(None)
            continue
        c = tramo.mean(0)
        _, _, vt = np.linalg.svd(tramo - c)
        lineas.append((c, vt[0]))
    out = p[idx].copy()
    for k in range(m):
        l1, l2 = lineas[k - 1], lineas[k]
        if l1 is None or l2 is None:
            continue
        (c1, d1), (c2, d2) = l1, l2
        det = d1[0] * -d2[1] + d2[0] * d1[1]
        if abs(det) < np.sin(np.radians(10)):
            continue
        t = ((c2 - c1)[0] * -d2[1] + d2[0] * (c2 - c1)[1]) / det
        x = c1 + t * d1
        if np.linalg.norm(x - out[k]) <= 4 * tol:
            out[k] = x
    return out


def rdp(p, tol):
    """Polígono simplificado de un lazo cerrado, con las esquinas reconstruidas."""
    return refine_corners(p, rdp_indices(p, tol), tol)


def hausdorff(p, q, dense=1200):
    """Hausdorff simétrico aproximado entre dos lazos, ambos remuestreados por arco a `dense` puntos."""
    P, Q = resample(p, dense), resample(q, dense)
    d1 = np.full(len(P), np.inf)
    d2 = np.full(len(Q), np.inf)
    for i in range(0, len(P), 300):                     # por bloques: poca memoria dentro de Blender
        d = np.sqrt(((P[i:i + 300, None] - Q[None]) ** 2).sum(-1))
        d1[i:i + 300] = d.min(1)
        d2 = np.minimum(d2, d.min(0))
    return float(max(d1.max(), d2.max()))


def corner_fraction(poly):
    """Parte del giro total del polígono que ocurre en esquinas de más de ESQUINA_GRADOS."""
    d = np.roll(poly, -1, axis=0) - poly
    a = np.arctan2(d[:, 1], d[:, 0])
    giro = np.degrees(np.abs(np.angle(np.exp(1j * (a - np.roll(a, 1))))))
    return float(giro[giro > ESQUINA_GRADOS].sum() / max(giro.sum(), 1e-9))


def fourier_fit(p, tol, max_order=200):
    """Menor orden cuyo error máximo por correspondencia es <= tol y que no se autointersecta. Recorre
    todos los órdenes (el error no es monótono). Sin éxito, devuelve el mejor con targetMet False."""
    c = coefficients(p)
    max_order = min(int(max_order), len(p) // 2 - 1)
    mejor = None
    for K in range(1, max_order + 1):
        q = reconstruct(c, K)
        e = float(np.linalg.norm(p - q, axis=1).max())
        if mejor is None or e < mejor[1]:
            mejor = (K, e)
        if e <= tol and not self_intersects(resample(q, 256)):
            return K, q, e, True
    K = mejor[0]
    return K, reconstruct(c, K), mejor[1], False


def simplify(p, tol, method='auto', samples=1024, max_order=200):
    """Simplifica un lazo cerrado con error <= tol (unidades del lazo). Devuelve el lazo de salida y
    sus medidas: método usado, orden o vértices, error máximo, Hausdorff y si se cumplió la tolerancia."""
    if method not in ('auto', 'fourier', 'polygon'):
        raise ValueError('method debe ser auto, fourier o polygon')
    p = resample(np.asarray(p, np.float64), samples)
    poly = rdp(p, tol)
    esquinas = corner_fraction(poly) if len(poly) >= 3 else 1.0
    if method == 'auto':
        method = 'polygon' if esquinas > FRACCION_ESQUINAS else 'fourier'
    if method == 'polygon':
        out = poly
        info = {'method': 'polygon', 'vertices': int(len(poly)), 'targetMet': len(poly) >= 3 and not self_intersects(poly)}
    else:
        K, q, e, ok = fourier_fit(p, tol, max_order)
        out = resample(q, int(np.clip(8 * K, 48, 512)))
        info = {'method': 'fourier', 'order': int(K), 'coefficients': 2 * K + 1, 'vertices': int(len(out)),
                'maxCorrespondenceError': e, 'targetMet': bool(ok)}
    info['hausdorff'] = hausdorff(p, out)
    info['cornerFraction'] = round(esquinas, 3)
    return out, info


# ----------------------------------------------------------------------------------- todo junto

def outline(loops_or_image, size=None, axis='width', tolerance=0.25, method='auto', threshold=None,
            min_area_frac=0.0005, samples=1024, max_order=200):
    """Contornos simplificados listos para construir.

    loops_or_image: imagen RGBA (h, w, 4) con filas de arriba abajo, o una lista de regiones
    {'outer': [[x, y], ...], 'holes': [[[x, y], ...], ...]} en metros con y hacia arriba.
    size: medida en metros de la caja del conjunto en `axis` ('width' o 'height'); para imágenes, si
    falta, 1 m de ancho. tolerance: % de la diagonal de la caja.

    Devuelve (regiones, info): regiones con lazos en metros (y hacia arriba, centrados en el origen;
    exterior antihorario, huecos horario) e info con las medidas por lazo."""
    if isinstance(loops_or_image, np.ndarray):
        f = coverage(loops_or_image, threshold)
        h, w = f.shape
        regs = regions(trace(f), min_area=min_area_frac * h * w)
        if not regs:
            raise ValueError('No se encontró ninguna figura en la imagen (prueba con threshold)')
        regs = [{'outer': r['outer'] * [1, -1], 'holes': [hh * [1, -1] for hh in r['holes']]} for r in regs]
    else:
        regs = [{'outer': np.asarray(r['outer'], np.float64),
                 'holes': [np.asarray(hh, np.float64) for hh in r.get('holes', [])]} for r in loops_or_image]
        for r in regs:
            for l in [r['outer']] + r['holes']:
                if l.ndim != 2 or l.shape[1] != 2 or len(l) < 3:
                    raise ValueError('Cada contorno necesita al menos 3 puntos [x, y]')
                if not np.isfinite(l).all():
                    raise ValueError('Las coordenadas deben ser finitas')
                if abs(area(l)) < 1e-12:
                    raise ValueError('Contorno degenerado: sus puntos no encierran área')
    todos = np.vstack([r['outer'] for r in regs])
    lo, hi = todos.min(0), todos.max(0)
    centro = (lo + hi) / 2
    caja = hi - lo
    if size:
        k = float(size) / float(caja[0] if axis == 'width' else caja[1])
    elif isinstance(loops_or_image, np.ndarray):
        k = 1.0 / float(caja[0])
    else:
        k = 1.0
    diag = float(np.linalg.norm(caja)) * k
    tol = float(tolerance) / 100 * diag
    salida, lazos = [], []
    for r in regs:
        nueva = {'outer': None, 'holes': []}
        for es_hueco, lazo in [(False, r['outer'])] + [(True, hh) for hh in r['holes']]:
            p = canonical((lazo - centro) * k, ccw=not es_hueco)
            q, info = simplify(p, tol, method, samples, max_order)
            q = canonical(q, ccw=not es_hueco)
            info.update({'hole': es_hueco,
                         'hausdorffPercent': round(100 * info['hausdorff'] / diag, 3)})
            if 'maxCorrespondenceError' in info:
                info['normalizedMaxErrorPercent'] = round(100 * info['maxCorrespondenceError'] / diag, 3)
            lazos.append(info)
            if es_hueco:
                nueva['holes'].append(q)
            else:
                nueva['outer'] = q
        salida.append(nueva)
    info = {'regions': len(salida), 'holes': sum(len(r['holes']) for r in salida),
            'size': [round(float(caja[0] * k), 4), round(float(caja[1] * k), 4)],
            'diagonal': round(diag, 4), 'tolerancePercent': float(tolerance), 'tolerance': tol,
            'targetMet': all(l['targetMet'] for l in lazos), 'loops': lazos}
    return salida, info


def rasterize(loops, shape, origin, scale):
    """Relleno par-impar de lazos (en metros, y hacia arriba) en una cuadrícula de `shape` píxeles cuyo
    píxel (0, 0) está en `origin` y mide `scale` metros (filas de arriba abajo). Para medir IoU."""
    h, w = shape
    yy, xx = np.mgrid[0:h, 0:w].astype(float)
    m = np.zeros((h, w), bool)
    for pol in loops:
        px = (pol[:, 0] - origin[0]) / scale
        py = (origin[1] - pol[:, 1]) / scale
        for ax, ay, bx, by in zip(px, py, np.roll(px, -1), np.roll(py, -1)):
            lo, hi = int(max(0, np.floor(min(ay, by)))), int(min(h, np.ceil(max(ay, by)) + 1))
            if hi <= lo or ay == by:
                continue
            ys = yy[lo:hi]
            cruza = (ay > ys) != (by > ys)
            xi = ax + (ys - ay) * (bx - ax) / (by - ay)
            m[lo:hi] ^= cruza & (xx[lo:hi] < xi)
    return m

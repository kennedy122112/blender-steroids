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
    Esa distancia se mide contra el sujeto que el borde tiene al lado (máximo en 7x7 px): en una foto el
    lado iluminado contrasta mucho menos con el fondo que el lado en sombra, y una escala única se come
    el borde claro. `threshold` (0..1) fija a mano la distancia de color que separa sujeto y fondo."""
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
    global_ = np.clip(d / max(escala, 1e-6), 0, 1)
    ruido = float(np.percentile(np.abs(borde - fondo).max(axis=-1), 95))
    minimo = max(0.04, 3 * ruido)                    # contraste mínimo para contar como sujeto
    h, w = d.shape
    pad = np.pad(d, 3, mode='edge')
    local = d.copy()
    for dy in range(7):
        for dx in range(7):
            np.maximum(local, pad[dy:dy + h, dx:dx + w], out=local)
    relativo = np.where(local > 2 * minimo, d / np.maximum(local, 1e-6), 0.0)
    return np.maximum(global_, relativo)


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


def dedupe(p, eps=0.0):
    """Quita puntos consecutivos repetidos (también el último si repite al primero)."""
    p = np.asarray(p, np.float64)
    if len(p) < 2:
        return p
    d = np.linalg.norm(np.diff(np.vstack([p, p[:1]]), axis=0), axis=1)
    return p[d > eps]


def _dist_punto_tramo(P, A, B):
    """Distancia de cada punto P a cada tramo AB (con broadcasting)."""
    ab = B - A
    t = np.clip(((P - A) * ab).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-300), 0, 1)
    return np.linalg.norm(P - (A + t[..., None] * ab), axis=-1)


def self_intersects(p, rel_tol=1e-9):
    """¿Se cruza o se toca el lazo consigo mismo? Pares de lados no vecinos, O(n²) (n de unos cientos):
    cruces estrictos y además contactos (un vértice apoyado en otro lado, tramos colineales que se
    superponen, un punto repetido), medidos como distancia entre tramos <= rel_tol × diagonal."""
    p = dedupe(p)
    a, b = p, np.roll(p, -1, axis=0)
    n = len(p)
    if n < 4:
        return False

    def lado(o, u, v):
        return np.sign((u[..., 0] - o[..., 0]) * (v[..., 1] - o[..., 1])
                       - (u[..., 1] - o[..., 1]) * (v[..., 0] - o[..., 0]))
    A, B, C, D = a[:, None], b[:, None], a[None], b[None]
    cruza = (lado(A, B, C) * lado(A, B, D) < 0) & (lado(C, D, A) * lado(C, D, B) < 0)
    i, j = np.indices((n, n))
    vecino = (np.abs(i - j) <= 1) | (np.abs(i - j) == n - 1)
    if np.any(cruza & ~vecino):
        return True
    # sin cruce estricto, la distancia entre dos tramos es la menor de sus extremos al otro tramo
    eps = rel_tol * float(np.linalg.norm(np.ptp(p, axis=0)))
    d = np.minimum.reduce([_dist_punto_tramo(A, C, D), _dist_punto_tramo(B, C, D),
                           _dist_punto_tramo(C, A, B), _dist_punto_tramo(D, A, B)])
    return bool(np.any((d <= eps) & ~vecino))


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
        c = coefficients(p)
        ks = np.arange(-K, K + 1)
        info = {'method': 'fourier', 'order': int(K), 'coefficients': 2 * K + 1, 'vertices': int(len(out)),
                'maxCorrespondenceError': e, 'targetMet': bool(ok),
                # c_k de k=-K..K (curva en metros, centrada, arrancando en el punto más alto)
                '_coef': [[round(float(c[k].real), 7), round(float(c[k].imag), 7)] for k in ks]}
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
    import time
    inicio = time.perf_counter()
    if isinstance(loops_or_image, np.ndarray):
        f = coverage(loops_or_image, threshold)
        h, w = f.shape
        regs = regions(trace(f), min_area=min_area_frac * h * w)
        if not regs:
            raise ValueError('No se encontró ninguna figura en la imagen (prueba con threshold)')
        regs = [{'outer': r['outer'] * [1, -1], 'holes': [hh * [1, -1] for hh in r['holes']]} for r in regs]
    else:
        regs = [{'outer': dedupe(r['outer']), 'holes': [dedupe(hh) for hh in r.get('holes', [])]}
                for r in loops_or_image]
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
    info = {'_frame': {'k': k, 'center': [float(centro[0]), float(centro[1])]},
            'regions': len(salida), 'holes': sum(len(r['holes']) for r in salida),
            'size': [round(float(caja[0] * k), 4), round(float(caja[1] * k), 4)],
            'diagonal': round(diag, 4), 'tolerancePercent': float(tolerance), 'tolerance': tol,
            'targetMet': all(l['targetMet'] for l in lazos), 'loops': lazos,
            'elapsedMs': round(1000 * (time.perf_counter() - inicio), 1)}
    return salida, info


def _cortes(pol, y):
    """x donde el lazo cerrado cruza la horizontal y (ordenadas)."""
    a, b = pol, np.roll(pol, -1, axis=0)
    cruza = (a[:, 1] > y) != (b[:, 1] > y)
    t = (y - a[cruza, 1]) / (b[cruza, 1] - a[cruza, 1])
    return np.sort(a[cruza, 0] + t * (b[cruza, 0] - a[cruza, 0]))


def _rdp_abierto(q, tol):
    """Ramer-Douglas-Peucker de una polilínea abierta (conserva los extremos)."""
    if len(q) < 3:
        return q
    a, ab = q[0], q[-1] - q[0]
    L = np.linalg.norm(ab)
    d = (np.abs(ab[0] * (q[:, 1] - a[1]) - ab[1] * (q[:, 0] - a[0])) / L) if L > 0 \
        else np.linalg.norm(q - a, axis=1)
    k = int(np.argmax(d))
    if d[k] <= tol:
        return np.array([q[0], q[-1]])
    return np.vstack([_rdp_abierto(q[:k + 1], tol)[:-1], _rdp_abierto(q[k:], tol)])


def lathe_profile(rgba, size=None, axis='height', tolerance=0.25, side='both', threshold=None, levels=600,
                  rings=64):
    """Perfil de torno [[radio, z], ...] (de abajo arriba, en metros, z desde 0) a partir de la silueta de
    un objeto de revolución visto de lado (jarrón, botella, farol, peón).

    El eje es la vertical que mejor centra la silueta (mediana de los centros de cada altura). `side`:
    'both' promedia las dos mitades; 'left' o 'right' usa solo esa (cuando del otro lado hay un asa o un
    pico que no es de revolución). size: medida en metros en `axis` ('height' o 'width'; si falta, 1 m de
    alto). tolerance: % del alto. rings: puntos del perfil de salida (suave entre esquinas; 0 = solo los
    vértices clave). Devuelve (perfil, info) con la asimetría medida: si las dos mitades
    difieren mucho, la figura no es de revolución (o la foto no está de lado) y el aviso lo dice."""
    if side not in ('both', 'left', 'right'):
        raise ValueError('side debe ser both, left o right')
    f = coverage(rgba, threshold)
    h, w = f.shape
    regs = regions(trace(f), min_area=0.0005 * h * w)
    if not regs:
        raise ValueError('No se encontró ninguna figura en la imagen (prueba con threshold)')
    pol = max((r['outer'] for r in regs), key=lambda l: abs(area(l))) * [1, -1]      # y hacia arriba
    y0, y1 = pol[:, 1].min(), pol[:, 1].max()
    alto = y1 - y0
    ys = np.linspace(y0, y1, int(levels))
    ys[0] += 1e-6 * alto
    ys[-1] -= 1e-6 * alto
    filas = []
    for y in ys:
        xs = _cortes(pol, y)
        if len(xs) >= 2:
            filas.append((y, xs[0], xs[-1]))
    filas = np.array(filas)
    eje = float(np.median((filas[:, 1] + filas[:, 2]) / 2))
    izq, der = eje - filas[:, 1], filas[:, 2] - eje
    ancho = float(2 * max(izq.max(), der.max()))
    k = float(size) / (alto if axis == 'height' else ancho) if size else 1.0 / alto
    r = {'both': (izq + der) / 2, 'left': izq, 'right': der}[side]
    perfil = np.column_stack([np.clip(r, 0, None) * k, (filas[:, 0] - y0) * k])
    tol = float(tolerance) / 100 * alto * k
    simple = _rdp_abierto(perfil, tol)
    salida = _suave(perfil, simple, int(rings)) if rings else simple
    asim = float(np.abs(izq - der).max() * k)
    err = _desvio(perfil, salida)
    info = {'height': round(float(alto * k), 4), 'maxRadius': round(float(perfil[:, 0].max()), 4),
            'points': int(len(salida)), 'keyPoints': int(len(simple)), 'side': side,
            'tolerancePercent': float(tolerance),
            'maxErrorPercent': round(float(100 * err / (alto * k)), 3), 'targetMet': bool(err <= tol + 1e-12),
            'asymmetryPercent': round(float(100 * asim / (alto * k)), 2),
            '_frame': {'k': k, 'axis': eje, 'y0': float(y0)}}
    return salida, info


def _desvio(medido, poli):
    """Distancia máxima de los puntos medidos a la polilínea (perpendicular, así vale también en hombros
    casi horizontales)."""
    a, b = poli[:-1], poli[1:]
    ab = b - a
    t = np.clip(((medido[:, None] - a[None]) * ab[None]).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-18), 0, 1)
    return float(np.linalg.norm(medido[:, None] - (a[None] + t[..., None] * ab[None]), axis=-1).min(1).max())


def _suave(perfil, simple, rings):
    """Un perfil con pocos puntos se ve facetado al girarlo (anillos de luz). Entre esquina y esquina
    (vértices de `simple` que giran más de 35°) toma el perfil medido, lo suaviza un poco y lo
    remuestrea a unos `rings` puntos en total; las esquinas quedan exactas (borde de una boca, base)."""
    d = np.diff(simple, axis=0)
    ang = np.arctan2(d[:, 1], d[:, 0])
    giro = np.degrees(np.abs(np.angle(np.exp(1j * np.diff(ang)))))
    claves = [0] + [i + 1 for i in np.nonzero(giro > 35)[0]] + [len(simple) - 1]
    idx = [int(np.argmin(np.linalg.norm(perfil - simple[i], axis=1))) for i in claves]
    total = np.linalg.norm(np.diff(perfil, axis=0), axis=1).sum()
    partes = []
    for i0, i1 in zip(idx, idx[1:]):
        tramo = perfil[i0:i1 + 1].copy()
        if len(tramo) > 6:                          # media móvil de 5, con los extremos fijos
            for c in (0, 1):
                tramo[2:-2, c] = np.convolve(tramo[:, c], np.ones(5) / 5, mode='valid')
        largo = np.linalg.norm(np.diff(tramo, axis=0), axis=1)
        s = np.concatenate([[0], np.cumsum(largo)])
        n = max(2, int(round(rings * s[-1] / max(total, 1e-12))) + 1)
        t = np.linspace(0, s[-1], n)
        pts = np.column_stack([np.interp(t, s, tramo[:, 0]), np.interp(t, s, tramo[:, 1])])
        partes.append(pts if not partes else pts[1:])
    return np.vstack(partes)


def _bezier_error(S, p0, p1, p2, p3):
    """Distancia máxima de las muestras S a la Bézier (densificada): error geométrico, no al punto de
    igual parámetro (la Bézier no recorre la curva a la misma velocidad)."""
    u = np.linspace(0, 1, 48)
    b = (1 - u) ** 3 * p0 + 3 * (1 - u) ** 2 * u * p1 + 3 * (1 - u) * u ** 2 * p2 + u ** 3 * p3
    B = np.column_stack([b.real, b.imag])
    a_, ab = B[:-1], B[1:] - B[:-1]
    t = np.clip(((S[:, None] - a_[None]) * ab[None]).sum(-1) / np.maximum((ab * ab).sum(-1), 1e-18), 0, 1)
    return float(np.linalg.norm(S[:, None] - (a_[None] + t[..., None] * ab[None]), axis=-1).min(1).max())


def bezier(loop, tol, min_segments=4):
    """Bézier cerrado que pasa por un lazo suave con error <= tol, con los menos tramos que alcanzan.
    La dirección de las asas sale de la derivada de la interpolación trigonométrica del lazo (cada
    tramo es tangente a la curva en sus dos puntos); su largo, de la regla que mejor calza en ese
    tramo. Devuelve (puntos, asa_izq, asa_der, error) como arrays (n, 2)."""
    z = loop[:, 0] + 1j * loop[:, 1]
    n = len(z)
    c = np.fft.fft(z) / n
    k = np.fft.fftfreq(n) * n
    # derivada solo con las frecuencias bajas: las altas son el escalonado del muestreo y, multiplicadas
    # por k, harían temblar las tangentes (también deja fuera a Nyquist, que no tiene pareja)
    dz = np.fft.ifft(np.where(np.abs(k) <= n // 6, c, 0) * 2j * np.pi * k) * n   # dz/dt, t de 0 a 1
    mejor = None
    for segs in range(min_segments, n + 1):
        idx = np.unique(np.round(np.linspace(0, n, segs + 1)).astype(int))
        err = 0.0
        pts, izq, der = [], [], []
        for i0, i1 in zip(idx[:-1], idx[1:]):
            dt = (i1 - i0) / n
            p0, p3 = z[i0 % n], z[i1 % n]
            t0, t1 = dz[i0 % n] / abs(dz[i0 % n]), dz[i1 % n] / abs(dz[i1 % n])
            S = np.column_stack([z[np.arange(i0, i1 + 1) % n].real, z[np.arange(i0, i1 + 1) % n].imag])
            # dos largos de asa y se queda el que mejor calza: el de Hermite (dt·|dz|/3), bueno en tramos en
            # S, y el de un arco con esas tangentes (cuerda / 3cos²(φ/4)), bueno en tramos que solo giran
            phi = abs(np.angle(t1 / t0))
            L_arco = abs(p3 - p0) / (3 * np.cos(phi / 4) ** 2)
            opciones = [(dz[i0 % n] * dt / 3, dz[i1 % n] * dt / 3), (t0 * L_arco, t1 * L_arco)]
            e_tramo = None
            for h0, h1 in opciones:
                q1, q2 = p0 + h0, p3 - h1
                e = _bezier_error(S, p0, q1, q2, p3)
                if e_tramo is None or e < e_tramo:
                    e_tramo, p1, p2 = e, q1, q2
            err = max(err, e_tramo)
            pts.append(p0)
            der.append(p1)
            izq.append(p2)                          # asa de entrada del punto siguiente
        izq = [izq[-1]] + izq[:-1]
        mejor = (pts, izq, der, err)
        if err <= tol:
            break
    a = [np.column_stack([np.real(v), np.imag(v)]) for v in map(np.array, mejor[:3])]
    return a[0], a[1], a[2], mejor[3]


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

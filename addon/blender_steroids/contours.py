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

def hex_rgb(h):
    """'#rrggbb' -> (r, g, b) en 0..1 (los mismos valores que trae la imagen)."""
    h = str(h).lstrip('#')
    if len(h) != 6:
        raise ValueError('color debe ser #rrggbb')
    return np.array([int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)])


def _max_local(d, r=3):
    h, w = d.shape
    pad = np.pad(d, r, mode='edge')
    out = d.copy()
    for dy in range(2 * r + 1):
        for dx in range(2 * r + 1):
            np.maximum(out, pad[dy:dy + h, dx:dx + w], out=out)
    return out


def color_coverage(rgba, color, tol=0.15):
    """Cobertura 0..1 de lo que es de un color (una estrella amarilla sobre papel rojo), subpíxel. Cada
    píxel se mira como mezcla del color buscado y del color más distinto que tiene al lado (7x7): vale la
    parte que tiene del color buscado, pero solo si de verdad es esa mezcla y el color buscado está a uno
    o dos píxeles (un dorado junto al fondo o junto al rojo no es "algo de amarillo", es otro color).
    Donde todo alrededor se parece al color, cuenta la distancia."""
    rgb = np.asarray(rgba, np.float64)[..., :3]
    c = hex_rgb(color)
    tol = float(tol)
    d = np.abs(rgb - c).max(axis=-1)
    h, w = d.shape
    pd, pr = np.pad(d, 3, mode='edge'), np.pad(rgb, ((3, 3), (3, 3), (0, 0)), mode='edge')
    otro_d, otro = d.copy(), rgb.copy()
    for dy in range(7):
        for dx in range(7):
            cand = pd[dy:dy + h, dx:dx + w]
            m = cand > otro_d
            otro_d[m] = cand[m]
            otro[m] = pr[dy:dy + h, dx:dx + w][m]
    co = c - otro
    L2 = (co * co).sum(-1)
    alfa = ((rgb - otro) * co).sum(-1) / np.maximum(L2, 1e-12)
    resto = np.abs(rgb - (otro + alfa[..., None] * co)).max(axis=-1)
    # un borde de verdad tiene el color buscado a uno o dos píxeles: sin eso, un dorado pegado al rojo
    # pasaría por "mezcla de rojo y amarillo"
    junto = -_max_local(-d, 2) <= tol
    mezcla = np.where((resto <= tol) & junto, np.clip(alfa, 0, 1), 0.0)
    cerca = np.clip(1 - d / (2 * tol), 0, 1)
    return np.where(L2 > (2 * tol) ** 2, mezcla, cerca)


def coverage(rgba, threshold=None, color=None, color_tol=0.15):
    """Cobertura 0..1 del sujeto. Con transparencia, el alfa; si no, la distancia al color de fondo (la
    mediana del borde) relativa a la del sujeto, para que el borde antialias dé la posición subpíxel.
    Esa distancia se mide contra el sujeto que el borde tiene al lado (máximo en 7x7 px): en una foto el
    lado iluminado contrasta mucho menos con el fondo que el lado en sombra, y una escala única se come
    el borde claro. `threshold` (0..1) fija a mano la distancia de color que separa sujeto y fondo.
    Con `color` ('#rrggbb') el sujeto es lo que tiene ese color (color_coverage)."""
    if color:
        # una parte de un color está dentro de la figura: el fondo nunca cuenta, aunque su color quede
        # dentro de la tolerancia (una panza crema sobre un fondo gris claro). Dentro = dentro del contorno
        # de afuera: lo que la figura encierra cuenta aunque se parezca al fondo (el brillo de un ojo).
        # (un hueco chico; uno grande, como el fondo entre unas patas y la rama, sigue siendo fondo)
        dentro = coverage(rgba, threshold)
        regs = regions(trace(dentro))
        if not regs:
            return np.zeros(dentro.shape)
        filas = np.concatenate([r['outer'][:, 1] for r in regs])
        lleno = _tapar(regs, dentro.shape, 0.002 * (filas.max() - filas.min()) ** 2)
        return np.minimum(color_coverage(rgba, color, color_tol), np.maximum(dentro, lleno))
    rgba = np.asarray(rgba, np.float64)
    if rgba.shape[-1] == 4 and rgba[..., 3].min() < 0.5:
        return rgba[..., 3]
    rgb = rgba[..., :3]
    borde = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    fondo = np.median(borde, axis=0)
    # fondo con degradado vertical (un estudio, una ilustración): el color del fondo de cada fila, de los
    # costados (mediana móvil de 31 filas, por si el sujeto toca un costado en algunas). Con uno solo,
    # una parte clara (una panza crema) se confunde con el fondo de arriba o de abajo.
    b = max(2, rgb.shape[1] // 60)
    filas = np.median(np.concatenate([rgb[:, :b], rgb[:, -b:]], axis=1), axis=1)            # (h, 3)
    filas = np.median(np.lib.stride_tricks.sliding_window_view(
        np.pad(filas, ((15, 15), (0, 0)), mode='edge'), 31, axis=0), axis=-1)
    if np.abs(filas - fondo).max() > 0.03:
        d = np.abs(rgb - filas[:, None, :]).max(axis=-1)
        fondo = np.median(filas, axis=0)
        borde = np.concatenate([rgb[0] - filas[0], rgb[-1] - filas[-1], rgb[:, 0] - filas,
                                rgb[:, -1] - filas]) + fondo                       # lo que se aparta de su fila
    else:
        d = np.abs(rgb - fondo).max(axis=-1)
    if threshold:
        return np.clip(d / (2 * float(threshold)), 0, 1)
    tinta = d[d > 0.25 * d.max()]
    escala = float(np.median(tinta)) if tinta.size else 1.0
    global_ = np.clip(d / max(escala, 1e-6), 0, 1)
    ruido = float(np.percentile(np.abs(borde - fondo).max(axis=-1), 95))
    minimo = max(0.04, 3 * ruido)                    # contraste mínimo para contar como sujeto
    local = _max_local(d)
    relativo = np.where(local > 2 * minimo, d / np.maximum(local, 1e-6), 0.0)
    cob = np.maximum(global_, relativo)
    # dentro de la figura, una parte clara junto a una oscura (una panza crema junto al plumaje) no es
    # borde: su contraste relativo sale bajo y abriría una ranura. Lo que se aparta del fondo y no tiene
    # fondo a 2 px cuenta entero; los bordes contra el fondo quedan con su valor subpíxel.
    cerca_fondo = _max_local((d < minimo).astype(np.float64), 2) > 0
    return np.where((d > 2 * minimo) & ~cerca_fondo, 1.0, cob)


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
            min_area_frac=0.0005, samples=1024, max_order=200, color=None, color_tol=0.15, pick=None,
            scale=None):
    """Contornos simplificados listos para construir.

    loops_or_image: imagen RGBA (h, w, 4) con filas de arriba abajo, o una lista de regiones
    {'outer': [[x, y], ...], 'holes': [[[x, y], ...], ...]} en metros con y hacia arriba.
    size: medida en metros de la caja del conjunto en `axis` ('width' o 'height'); para imágenes, si
    falta, 1 m de ancho. tolerance: % de la diagonal de la caja. pick: qué regiones (índices, de la de
    más área a la de menos; una parte del mismo color que otra). scale: metros por píxel fijos (el marco
    de una vista, ver ops), en vez de `size`.

    Devuelve (regiones, info): regiones con lazos en metros (y hacia arriba, centrados en el origen;
    exterior antihorario, huecos horario) e info con las medidas por lazo."""
    import time
    inicio = time.perf_counter()
    if isinstance(loops_or_image, np.ndarray):
        f = coverage(loops_or_image, threshold, color, color_tol)
        h, w = f.shape
        # por color se piden detalles a propósito (el brillo de un ojo, un botón): se aceptan más chicos
        regs = regions(trace(f), min_area=min_area_frac * h * w * (0.2 if color else 1.0))
        if not regs:
            raise ValueError('No se encontró ninguna figura en la imagen (%s)' % (
                'revisa color y colorTolerance' if color else 'prueba con threshold'))
        regs = [{'outer': r['outer'] * [1, -1], 'holes': [hh * [1, -1] for hh in r['holes']]} for r in regs]
        regs.sort(key=lambda r: -abs(area(r['outer'])))
        if pick is not None:
            idx = [int(i) for i in (pick if isinstance(pick, (list, tuple)) else [pick])]
            if any(not 0 <= i < len(regs) for i in idx):
                raise ValueError('pick fuera de rango: hay %d regiones (0..%d, de la más grande a la más chica)'
                                 % (len(regs), len(regs) - 1))
            regs = [regs[i] for i in idx]
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
    if scale:
        k = float(scale)
    elif size:
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
                  rings=64, z_range=None):
    """Perfil de torno [[radio, z], ...] (de abajo arriba, en metros, z desde 0) a partir de la silueta de
    un objeto de revolución visto de lado (jarrón, botella, farol, peón).

    El eje es la vertical que mejor centra la silueta (mediana de los centros de cada altura). `side`:
    'both' promedia las dos mitades; 'left' o 'right' usa solo esa (cuando del otro lado hay un asa o un
    pico que no es de revolución). size: medida en metros en `axis` ('height' o 'width'; si falta, 1 m de
    alto). tolerance: % del alto. rings: puntos del perfil de salida (suave entre esquinas; 0 = solo los
    vértices clave). z_range: [desde, hasta] en fracción del alto (0 = abajo): solo esa franja, con la
    misma escala y el mismo eje que el todo, para hacer cada parte con su material. Devuelve (perfil,
    info) con la asimetría medida (si las dos mitades difieren mucho, la figura no es de revolución o la
    foto no está de lado) y `bands`: las franjas de color a lo largo del alto (de abajo arriba)."""
    if side not in ('both', 'left', 'right'):
        raise ValueError('side debe ser both, left o right')
    f = coverage(rgba, threshold)
    rgb = np.asarray(rgba, np.float64)[..., :3]
    h, w = f.shape
    regs = regions(trace(f), min_area=0.0005 * h * w)
    if not regs:
        raise ValueError('No se encontró ninguna figura en la imagen (prueba con threshold)')
    pol = max((r['outer'] for r in regs), key=lambda l: abs(area(l))) * [1, -1]      # y hacia arriba
    y0, y1 = pol[:, 1].min(), pol[:, 1].max()
    alto = y1 - y0
    # medio píxel hacia adentro en los extremos: una base plana justo en y0 solo se toca en una esquina
    ys = np.linspace(y0 + 0.5, y1 - 0.5, int(levels))
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
    bandas = _bands(rgb, filas, y0, alto, k, perfil)
    medido, dif = perfil, np.abs(izq - der)
    if z_range is not None:
        a_, b_ = (float(x) for x in z_range)
        if not 0 <= a_ < b_ <= 1:
            raise ValueError('range debe ser [desde, hasta] con 0 <= desde < hasta <= 1')
        z0, z1 = a_ * alto * k, b_ * alto * k
        salida = _recortar(salida, z0, z1)
        # error y asimetría de esa franja, no del objeto entero
        dentro = (perfil[:, 1] >= z0) & (perfil[:, 1] <= z1)
        medido, dif = perfil[dentro], dif[dentro]
    asim = float(dif.max() * k) if len(dif) else 0.0
    err = _desvio(medido, salida) if len(medido) else 0.0
    info = {'height': round(float(alto * k), 4), 'maxRadius': round(float(salida[:, 0].max()), 4),
            'points': int(len(salida)), 'keyPoints': int(len(simple)), 'side': side,
            'tolerancePercent': float(tolerance),
            'maxErrorPercent': round(float(100 * err / (alto * k)), 3), 'targetMet': bool(err <= tol + 1e-12),
            'asymmetryPercent': round(float(100 * asim / (alto * k)), 2), 'bands': bandas,
            '_frame': {'k': k, 'axis': eje, 'y0': float(y0)}}
    return salida, info


def _recortar(perfil, z0, z1):
    """La parte del perfil entre las alturas z0 y z1, con los extremos interpolados."""
    z = perfil[:, 1]
    dentro = perfil[(z > z0) & (z < z1)]
    ini = [np.interp(z0, z, perfil[:, 0]), z0]
    fin = [np.interp(z1, z, perfil[:, 0]), z1]
    return np.vstack([[ini], dentro, [fin]])


def _bands(rgb, filas, y0, alto, k, perfil, salto=0.12, minimo=0.015):
    """Franjas de color a lo largo del alto: el color mediano de cada fila dentro de la silueta, cortado
    donde cambia más de `salto` y sin franjas de menos de `minimo` del alto (se unen a la vecina más
    parecida). Para hacer cada parte del torno con su material (tapas doradas, cuerpo rojo...)."""
    h, w = rgb.shape[:2]
    cols = []
    for y, xa, xb in filas:
        fila = int(round(-y))
        a, b = int(np.ceil(xa)), int(np.floor(xb))
        if 0 <= fila < h and b >= a:
            cols.append(np.median(rgb[fila, max(0, a):min(w, b + 1)], axis=0))
        else:
            cols.append(cols[-1] if cols else np.zeros(3))
    cols = np.array(cols)
    frac = (filas[:, 0] - y0) / alto
    tramos = [[0, 1]]
    for i in range(1, len(cols)):
        ref = np.median(cols[tramos[-1][0]:i], axis=0)
        if np.abs(cols[i] - ref).max() > salto:
            tramos.append([i, i + 1])
        else:
            tramos[-1][1] = i + 1
    while len(tramos) > 1:
        largos = [frac[min(b, len(frac) - 1)] - frac[a] for a, b in tramos]
        i = int(np.argmin(largos))
        if largos[i] >= minimo:
            break
        med = np.median(cols[tramos[i][0]:tramos[i][1]], axis=0)
        vec = [j for j in (i - 1, i + 1) if 0 <= j < len(tramos)]
        j = min(vec, key=lambda j: np.abs(np.median(cols[tramos[j][0]:tramos[j][1]], axis=0) - med).max())
        a, b = min(tramos[i][0], tramos[j][0]), max(tramos[i][1], tramos[j][1])
        tramos[min(i, j)] = [a, b]
        del tramos[max(i, j)]
    # franjas vecinas del mismo color (las separaba una más chica que ya se unió) van juntas
    i = 0
    while i < len(tramos) - 1:
        ca = np.median(cols[tramos[i][0]:tramos[i][1]], axis=0)
        cb = np.median(cols[tramos[i + 1][0]:tramos[i + 1][1]], axis=0)
        if np.abs(ca - cb).max() <= salto / 2:
            tramos[i] = [tramos[i][0], tramos[i + 1][1]]
            del tramos[i + 1]
        else:
            i += 1
    out = []
    for a, b in tramos:
        c = np.median(cols[a:b], axis=0)
        r = perfil[a:b, 0]
        out.append({'from': round(float(frac[a]), 4), 'to': round(float(frac[min(b, len(frac) - 1)]), 4),
                    'color': '#%02x%02x%02x' % tuple(int(round(255 * x)) for x in np.clip(c, 0, 1)),
                    'maxRadius': round(float(r.max()), 4)})
    out[0]['from'], out[-1]['to'] = 0.0, 1.0
    for x, y in zip(out, out[1:]):
        x['to'] = y['from']
    return out


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


# ----------------------------------------------------------------------------------- vistas y trazos

def _crecer(m, n):
    """Dilatación n veces alternando cruz y cuadrado 3x3: un octágono, casi un disco (con solo la cruz
    sería un rombo, que cabe en una franja diagonal más angosta que en una recta)."""
    m = np.asarray(m, bool)
    for i in range(int(n)):
        d = m.copy()
        d[1:] |= m[:-1]
        d[:-1] |= m[1:]
        d[:, 1:] |= m[:, :-1]
        d[:, :-1] |= m[:, 1:]
        if i % 2:
            d[1:, 1:] |= m[:-1, :-1]
            d[1:, :-1] |= m[:-1, 1:]
            d[:-1, 1:] |= m[1:, :-1]
            d[:-1, :-1] |= m[1:, 1:]
        m = d
    return m


def _encoger(m, n):
    return ~_crecer(~np.asarray(m, bool), n)


def _rellenar(reg, shape):
    """Máscara de una región {outer, holes} trazada en píxeles (x, fila)."""
    return rasterize([reg['outer'] * [1, -1]] + [hh * [1, -1] for hh in reg['holes']], shape, (0.0, 0.0), 1.0)


def _tapar(regs, shape, area_max):
    """Máscara de las regiones con sus huecos de menos de `area_max` px² rellenos: un brillo, un botón
    claro. Cada figura se rellena por su contorno de afuera menos sus huecos grandes (el anillo de
    antialias de un brillo se traza en pedazos sueltos: no se pueden rellenar los chicos uno por uno)."""
    m = np.zeros(shape, bool)
    for reg in regs:
        grandes = [hh * [1, -1] for hh in reg['holes'] if abs(area(hh)) >= area_max]
        m |= rasterize([reg['outer'] * [1, -1]] + grandes, shape, (0.0, 0.0), 1.0)
    return m


def split_thin(f, width):
    """Separa el cuerpo de las partes finas que le salen (asas, picos, alambres, patas finas): lo que
    queda al abrir la silueta con un disco de `width` px de diámetro es el cuerpo (su región más grande),
    con las esquinas que la apertura le redondea y cortado en cada unión por la recta entre sus dos
    esquinas. Devuelve (cuerpo, finos)."""
    m = np.asarray(f) > 0.5
    h, w = m.shape
    r = max(1, int(round(width / 2)))
    # un hueco chico (el brillo de un ojo, un botón claro) es un detalle pintado: la apertura lo agrandaría
    # y se comería el borde entre él y el contorno. Se rellena solo para separar las partes.
    lleno = m | _tapar(regions(trace(m.astype(np.float64))), m.shape, r * r)
    abierto = _crecer(_encoger(lleno, r), r) & lleno
    regs = regions(trace(abierto.astype(np.float64)))
    if not regs:
        return np.zeros_like(m), m
    mayor = max(regs, key=lambda g: abs(area(g['outer'])))
    base = _rellenar(mayor, m.shape) & abierto
    resto = m & ~base
    # partes finas de verdad; las astillas que la apertura le quita a cada esquina vuelven al cuerpo. Una
    # astilla queda pegada al cuerpo; una parte fina, aunque sea chica (una oreja de canto), sobresale lejos
    finas = np.zeros_like(m)
    cerca_base = _crecer(base, max(1, int(0.6 * r)))
    for reg in regions(trace(resto.astype(np.float64))):
        parte = _rellenar(reg, m.shape) & resto
        if abs(area(reg['outer'])) >= 1.5 * r * r or (parte & ~cerca_base).sum() > r:
            finas |= parte
    cuerpo = m & ~finas
    # en cada unión el borde de la apertura no sigue el del cuerpo: sigue los lados de la parte fina un
    # trecho y la cruza con un arco (un muñón). Se corta por la recta entre las dos esquinas entrantes
    # donde la parte fina sale del cuerpo.
    lazo = mayor['outer']
    n = len(lazo)
    cerca = _crecer(finas, 2)
    cerca_fina = _crecer(finas, r + 2)
    junto = cerca[np.clip(np.round(lazo[:, 1]).astype(int), 0, h - 1),
                  np.clip(np.round(lazo[:, 0]).astype(int), 0, w - 1)]

    def esquina(i, paso):
        """Desde el extremo i del arco, por el borde hacia afuera: la primera esquina marcada (la unión)."""
        mejor, giro_max, d_mejor = i, 35.0, None
        for d in range(6, int(1.5 * r) + 6):
            k = (i + paso * d) % n
            if junto[k]:
                break                                       # llegó a otra unión (unas piernas juntas)
            u, v = lazo[k] - lazo[(k - 4) % n], lazo[(k + 4) % n] - lazo[k]
            giro = abs(np.degrees(np.arctan2(u[0] * v[1] - u[1] * v[0], u @ v)))
            if giro > giro_max:
                mejor, giro_max, d_mejor = k, giro, d
            elif d_mejor is not None and d > d_mejor + 6:
                break                                       # pasó la esquina: se queda con su punto de más giro
        return mejor
    if junto.any() and not junto.all():
        k = int(np.argmin(junto))                               # arranca fuera de una unión
        lazo, junto = np.roll(lazo, -k, axis=0), np.roll(junto, -k)
        i = 0
        while i < n:
            if not junto[i]:
                i += 1
                continue
            j = i
            while j + 1 < n and junto[j + 1]:
                j += 1
            if j - i >= 2:
                a_, b_ = esquina(i, -1), esquina(j, 1)
                idx = np.arange(a_, a_ + ((b_ - a_) % n) + 1) % n
                # entre las dos esquinas el cuerpo sigue su curva, no la recta: con la recta, unas patas
                # cortas bajo un cuerpo redondo se llevaban una cuña de su panza. Una curva de Hermite con
                # la dirección del borde al llegar a cada esquina (la recta si el borde va casi de costado)
                p0, p1 = lazo[a_], lazo[b_]
                ta, tb = p0 - lazo[(a_ - 8) % n], lazo[(b_ + 8) % n] - p1
                largo = np.linalg.norm(p1 - p0)
                ta, tb = ta / max(np.linalg.norm(ta), 1e-9), tb / max(np.linalg.norm(tb), 1e-9)
                cuerda = (p1 - p0) / max(largo, 1e-9)
                tt = np.linspace(1, 0, 24)[1:-1, None]
                if min(ta @ cuerda, tb @ cuerda) > 0.25:
                    cierre = ((2 * tt ** 3 - 3 * tt ** 2 + 1) * p0 + (tt ** 3 - 2 * tt ** 2 + tt) * largo * ta
                              + (-2 * tt ** 3 + 3 * tt ** 2) * p1 + (tt ** 3 - tt ** 2) * largo * tb)
                else:
                    cierre = np.zeros((0, 2))
                # solo cerca de la parte fina: si una esquina se buscó lejos, no se lleva un trozo del cuerpo
                munon = rasterize([np.vstack([lazo[idx], cierre]) * [1, -1]], m.shape, (0.0, 0.0), 1.0) \
                    & cuerpo & cerca_fina
                cuerpo &= ~munon
                finas |= munon
            i = j + 1
    return cuerpo, finas


def _quitar_colores(rgba, f, exclude, tol=0.1):
    """La cobertura f sin lo que es de los colores `exclude` (una base de exhibición, unas alas plegadas
    al costado: piezas que se hacen aparte y no son parte del cuerpo)."""
    if not exclude:
        return f
    colores = [exclude] if isinstance(exclude, str) else list(exclude)
    quitar = np.max([color_coverage(rgba, c, tol) for c in colores], axis=0)
    return f * (1 - quitar)


def _vista(rgba, thin=10, threshold=None, exclude=None, exclude_tol=0.1):
    """Lo común a una vista: cobertura, cuerpo y partes finas, y el marco de la vista (en píxeles): abajo
    de toda la silueta (z = 0), su alto (el `height` del spec) y el centro del cuerpo (x = 0). Lo de los
    colores `exclude` no cuenta como figura, pero el marco es el de la silueta entera (con ello)."""
    f = coverage(rgba, threshold)
    lazos = trace(f)
    if not lazos:
        raise ValueError('No se encontró ninguna figura en la imagen (prueba con threshold)')
    filas = np.concatenate([l[:, 1] for l in lazos])
    arriba, abajo = float(filas.min()), float(filas.max())
    alto = abajo - arriba
    f = _quitar_colores(rgba, f, exclude, exclude_tol)
    cuerpo, finos = split_thin(f, float(thin) / 100 * alto)
    if not cuerpo.any():
        raise ValueError('No queda cuerpo al quitar las partes finas: baja thin (ahora %s%% del alto)' % thin)
    fc = f * _crecer(cuerpo, 1)
    pol = max(trace(fc), key=lambda l: abs(area(l)))
    # centro: la mediana de los centros de cada altura (un detalle de un lado no lo corre)
    ys = np.linspace(pol[:, 1].min() + 0.5, pol[:, 1].max() - 0.5, 200)
    centros = [(c[0] + c[-1]) / 2 for c in (_cortes(pol * [1, -1], -y) for y in ys) if len(c) >= 2]
    x0 = float(np.median(centros))
    return {'f': f, 'cuerpo': cuerpo, 'finos': finos, 'pol': pol, 'x0': x0, 'abajo': abajo, 'alto': alto}


def view_profile(rgba, thin=10, threshold=None, levels=600, exclude=None, exclude_tol=0.1, color=None,
                 color_tol=0.15, pick=None):
    """El cuerpo de una vista (sin asas ni picos): por cada altura, dónde empieza y dónde termina. Devuelve
    (z, izquierda, derecha) en píxeles, z desde abajo de la silueta entera y x desde el centro del
    cuerpo, y la vista (_vista). Con `color`, en vez del cuerpo, las regiones de ese color (una bota, un
    gorro), enteras y en el mismo marco: `pick` elige regiones, de la de más área a la de menos."""
    v = _vista(rgba, thin, threshold, exclude, exclude_tol)
    pols = [v['pol'] * [1, -1]]                            # y hacia arriba
    if color:
        regs = sorted(regions(trace(coverage(rgba, threshold, color, color_tol)), min_area=(0.004 * v['alto']) ** 2),
                      key=lambda g: -abs(area(g['outer'])))
        if not regs:
            raise ValueError('No hay nada de color %s en la vista' % color)
        idx = range(len(regs)) if pick is None else [int(i) for i in (pick if isinstance(pick, (list, tuple)) else [pick])]
        if any(not 0 <= i < len(regs) for i in idx):
            raise ValueError('pick fuera de rango: hay %d regiones de color %s (0..%d)' % (len(regs), color, len(regs) - 1))
        pols = [regs[i]['outer'] * [1, -1] for i in idx]
    y0, y1 = min(p[:, 1].min() for p in pols), max(p[:, 1].max() for p in pols)
    z, iz, de = [], [], []
    for y in np.linspace(y0 + 0.5, y1 - 0.5, int(levels)):
        xs = sorted(x for p in pols for x in _cortes(p, y))
        if len(xs) >= 2:
            z.append(y + v['abajo'])
            iz.append(xs[0] - v['x0'])
            de.append(xs[-1] - v['x0'])
    # donde se cortó una parte fina el borde es escalonado (sin antialias): medio píxel de ida y vuelta
    # que en la malla se ve como anillos. Una media de 5 niveles (unos 2 px) lo alisa.
    bordes = _media_movil(np.column_stack([iz, de]), 5)
    return np.array(z), bordes[:, 0], bordes[:, 1], v


def section_shape(segments=48, roundness=2.0, top=None, threshold=None):
    """Forma de la sección horizontal en el cuadrado [-1, 1]²: una superelipse (roundness 2 = elipse,
    más = más cuadrada, 1 = rombo) o el contorno de la vista de arriba (`top`, imagen) escalado."""
    n = int(segments)
    if top is not None:
        f = coverage(top, threshold)
        lazos = trace(f)
        if not lazos:
            raise ValueError('top: no se encontró ninguna figura en la imagen')
        p = canonical(max(lazos, key=lambda l: abs(area(l))) * [1, -1])
        lo, hi = p.min(0), p.max(0)
        q = resample((p - (lo + hi) / 2) / ((hi - lo) / 2), n)
        k = int(np.argmax(q[:, 0] - 1e-6 * np.abs(q[:, 1])))       # arranca a la derecha (ángulo 0)
        return np.roll(q, -k, axis=0)
    e = 2.0 / max(float(roundness), 0.2)
    t = 2 * np.pi * np.arange(n) / n
    c, s = np.cos(t), np.sin(t)
    return np.column_stack([np.sign(c) * np.abs(c) ** e, np.sign(s) * np.abs(s) ** e])


def views_body(front, side, height, thin=10, tolerance=0.25, rings=64, threshold=None, levels=400, exclude=None,
               exclude_tol=0.1, color=None, color_tol=0.15, pick_front=None, pick_side=None):
    """Cuerpo a partir de dos vistas (frente: X a la derecha; costado, la vista derecha: Y a la derecha),
    sin sus partes finas: en cada altura el frente da dónde empieza y termina en X y el costado en Y, y
    la sección es una forma (section_shape) inscrita en ese rectángulo, así el cuerpo calza con las dos
    siluetas. Para lo que no es plano ni de revolución: una regadera, un ratón, un zapato, un auto de
    juguete, el cuerpo de un pájaro. `height` es el alto de la silueta entera (con asas) en las dos
    imágenes. Devuelve (niveles [[z, x0, x1, y0, y1], ...] en metros, info)."""
    zf, xl, xr, vf = view_profile(front, thin, threshold, exclude=exclude, exclude_tol=exclude_tol, color=color,
                                  color_tol=color_tol, pick=pick_front)
    zs, yl, yr, vs = view_profile(side, thin, threshold, exclude=exclude, exclude_tol=exclude_tol, color=color,
                                  color_tol=color_tol, pick=pick_side)
    kf, ks = float(height) / vf['alto'], float(height) / vs['alto']
    zf, xl, xr = zf * kf, xl * kf, xr * kf
    zs, yl, yr = zs * ks, yl * ks, yr * ks
    z0, z1 = max(zf.min(), zs.min()), min(zf.max(), zs.max())
    if z1 <= z0:
        raise ValueError('Las dos vistas no se solapan en altura: ¿son del mismo objeto y del mismo alto?')
    Z = np.linspace(z0, z1, int(levels))
    curvas = [np.interp(Z, zf, xl), np.interp(Z, zf, xr), np.interp(Z, zs, yl), np.interp(Z, zs, yr)]
    tol = float(tolerance) / 100 * float(height)
    claves = {0, len(Z) - 1}
    for c in curvas:
        simple = _rdp_abierto(np.column_stack([c, Z]), tol / 2)
        claves |= {int(np.argmin(np.abs(Z - z))) for z in simple[:, 1]}
    claves = sorted(claves)
    paso = max(1, int(np.ceil((len(Z) - 1) / max(int(rings), 2))))
    for a_, b_ in zip(list(claves), list(claves)[1:]):
        claves += list(range(a_ + paso, b_, paso))
    claves = sorted(set(claves))
    # error perpendicular (un hombro casi horizontal entre dos niveles no es un error de la silueta)
    err = max(_desvio(np.column_stack([c, Z]), np.column_stack([c[claves], Z[claves]])) for c in curvas)
    salida = [[float(Z[i])] + [float(c[i]) for c in curvas] for i in claves]
    desfase = abs(zf.min() - zs.min()) + abs(zf.max() - zs.max())
    info = {'height': round(float(height), 4),
            'size': [round(float(curvas[1].max() - curvas[0].min()), 4),
                     round(float(curvas[3].max() - curvas[2].min()), 4), round(float(z1 - z0), 4)],
            'levels': len(salida), 'tolerancePercent': float(tolerance),
            'maxErrorPercent': round(100 * err / float(height), 3), 'targetMet': bool(err <= tol + 1e-12),
            'viewsMismatchPercent': round(100 * float(desfase) / float(height), 2), 'thinPercent': float(thin),
            # el marco de cada vista (metros por píxel, centro y abajo en píxeles) y su cobertura, para pintar
            '_frames': {'front': {'k': kf, 'x0': vf['x0'], 'abajo': vf['abajo'], 'f': vf['f']},
                        'side': {'k': ks, 'x0': vs['x0'], 'abajo': vs['abajo'], 'f': vs['f']}}}
    return salida, info


def _esqueleto(m):
    """Eje de una figura, de un píxel de ancho (Zhang-Suen, vectorizado)."""
    s = np.pad(np.asarray(m, bool), 1).astype(np.uint8)
    while True:
        cambio = False
        for paso in (0, 1):
            p2, p3, p4, p5 = s[:-2, 1:-1], s[:-2, 2:], s[1:-1, 2:], s[2:, 2:]
            p6, p7, p8, p9 = s[2:, 1:-1], s[2:, :-2], s[1:-1, :-2], s[:-2, :-2]
            vec = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            B = sum(v.astype(np.int16) for v in vec[:8])
            A = sum(((vec[i] == 0) & (vec[i + 1] == 1)).astype(np.int16) for i in range(8))
            if paso == 0:
                c = (p2 * p4 * p6 == 0) & (p4 * p6 * p8 == 0)
            else:
                c = (p2 * p4 * p8 == 0) & (p2 * p6 * p8 == 0)
            quitar = (s[1:-1, 1:-1] == 1) & (B >= 2) & (B <= 6) & (A == 1) & c
            if quitar.any():
                s[1:-1, 1:-1][quitar] = 0
                cambio = True
        if not cambio:
            return s[1:-1, 1:-1].astype(bool)


def _vecinos(m):
    p = np.pad(m, 1).astype(np.int16)
    h, w = m.shape
    return sum(p[1 + dy:1 + dy + h, 1 + dx:1 + dx + w] for dy in (-1, 0, 1) for dx in (-1, 0, 1)
               if dy or dx) * m


def _camino_mas_largo(sk):
    """El camino más largo del esqueleto (dos recorridos en anchura), como puntos (x, fila)."""
    from collections import deque
    pix = set(zip(*[a.tolist() for a in np.nonzero(sk)]))
    if not pix:
        return np.zeros((0, 2))

    def recorrer(inicio):
        padre, q, ultimo = {inicio: None}, deque([inicio]), inicio
        while q:
            p = q.popleft()
            ultimo = p
            for dy in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    n = (p[0] + dy, p[1] + dx)
                    if n in pix and n not in padre:
                        padre[n] = p
                        q.append(n)
        return ultimo, padre
    a, _ = recorrer(min(pix))
    b, padre = recorrer(a)
    camino = [b]
    while padre[camino[-1]] is not None:
        camino.append(padre[camino[-1]])
    return np.array([[x, y] for y, x in camino], np.float64)


def _muestrear(g, pts):
    """Valor bilineal de g en puntos (x, fila); 0 fuera de la imagen."""
    h, w = g.shape
    x, y = pts[:, 0], pts[:, 1]
    fuera = (x < 0) | (y < 0) | (x > w - 1) | (y > h - 1)
    x, y = np.clip(x, 0, w - 1.0001), np.clip(y, 0, h - 1.0001)
    i, j = y.astype(int), x.astype(int)
    fy, fx = y - i, x - j
    v = (g[i, j] * (1 - fx) * (1 - fy) + g[i, j + 1] * fx * (1 - fy) + g[i + 1, j] * (1 - fx) * fy
         + g[i + 1, j + 1] * fx * fy)
    return np.where(fuera, 0.0, v)


def _por_arco(p, n):
    """n puntos equiespaciados sobre la polilínea abierta p (con sus extremos)."""
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(p[:, :2], axis=0), axis=1))])
    t = np.linspace(0, s[-1], int(n))
    return np.column_stack([np.interp(t, s, p[:, c]) for c in range(p.shape[1])])


def _media_movil(v, k):
    """Media móvil de k (impar) por columna, con los extremos fijos."""
    if len(v) <= k:
        return v
    out = v.copy()
    m = k // 2
    for c in range(v.shape[1]):
        out[m:-m, c] = np.convolve(v[:, c], np.ones(k) / k, mode='valid')
    return out


def _secciones(g, p, cuerpo, grosor, junto=None):
    """Ancho de la parte fina en cada punto de su eje (la integral de la cobertura a lo largo de la
    normal: subpíxel) y cuánto está corrido el punto del medio de esa sección. NaN donde no se puede
    medir: dentro del cuerpo o junto a él, donde la parte fina se ensancha en el rincón de la unión."""
    tg = np.gradient(p, axis=0)
    tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-9)
    nrm = np.column_stack([-tg[:, 1], tg[:, 0]])
    R = 0.75 * grosor + 3
    ts = np.arange(-R, R + 1e-9, 0.25)
    k0 = len(ts) // 2
    anchos, desvio = np.full(len(p), np.nan), np.full(len(p), np.nan)
    if junto is None:
        junto = _crecer(cuerpo, max(1, int(0.4 * grosor)))
    h, w = cuerpo.shape

    def en(m, c):
        yi, xi = int(round(c[1])), int(round(c[0]))
        return 0 <= yi < h and 0 <= xi < w and m[yi, xi]
    lejos = [not en(junto, c) for c in p]
    if sum(lejos) < 3:
        lejos = [True] * len(p)
    for i, (c, n) in enumerate(zip(p, nrm)):
        if not lejos[i] or en(cuerpo, c):
            continue
        v = _muestrear(g, c[None] + ts[:, None] * n[None])
        if v[k0] <= 0.02:
            continue
        lo = hi = k0
        while lo > 0 and v[lo - 1] > 0.02:
            lo -= 1
        while hi < len(ts) - 1 and v[hi + 1] > 0.02:
            hi += 1
        tramo = v[lo:hi + 1]
        anchos[i] = tramo.sum() * 0.25
        desvio[i] = float((tramo * ts[lo:hi + 1]).sum() / max(tramo.sum(), 1e-9))
    return anchos, desvio


def _trazo(comp, g, cuerpo, grosor):
    """Eje y ancho de una parte fina: el esqueleto podado (sin las ramitas de las esquinas), su camino
    más largo suavizado y alargado por la tangente hasta salir de la parte (o entrar al cuerpo), y el
    ancho de cada punto como la integral de la cobertura a lo largo de la normal (subpíxel)."""
    sk = _esqueleto(comp)
    poda = max(1, int(round(0.6 * grosor)))
    for _ in range(poda):
        fin = sk & (_vecinos(sk) <= 1)
        if not fin.any() or fin.sum() >= sk.sum():
            break
        sk &= ~fin
    p = _camino_mas_largo(sk)
    # una parte corta y gruesa (un brazo, una pata, una oreja de un personaje) casi no tiene esqueleto: sus
    # ramitas a las esquinas lo doblan en V. Su eje es la dirección principal de sus píxeles.
    # (la dirección, del núcleo grueso de la parte: una pata corta bajo un cuerpo redondo asoma también
    # como una astilla por su costado, que la torcía)
    q = int(0.3 * grosor)
    nucleo = _crecer(_encoger(comp, q), q) & comp if q >= 2 else comp
    ys_, xs_ = np.nonzero(nucleo if nucleo.sum() >= 3 else comp)
    if len(xs_) >= 3:
        xy = np.column_stack([xs_, ys_]).astype(np.float64)
        centro = xy.mean(0)
        _, sv, ejes = np.linalg.svd(xy - centro, full_matrices=False)
        # casi tan ancha como larga (una pierna corta entre el cuerpo y una bota): su dirección principal
        # sale cualquiera. Va de donde se pega al cuerpo hacia su centro
        union = comp & _crecer(cuerpo, 2)
        if len(sv) > 1 and sv[0] < 1.2 * sv[1] and union.sum() >= 3:
            yu, xu = np.nonzero(union)
            d_ = centro - np.array([xu.mean(), yu.mean()])
            if np.linalg.norm(d_) > 1e-6:
                ejes = np.array([d_ / np.linalg.norm(d_)])
        t_ = (xy - centro) @ ejes[0]
        if t_.max() - t_.min() < 3.5 * grosor:
            p = centro + np.outer(np.linspace(t_.min(), t_.max(), max(3, int(t_.max() - t_.min()))), ejes[0])
    if len(p) < 3:
        return None
    largo = np.linalg.norm(np.diff(p, axis=0), axis=1).sum()
    p = _media_movil(_por_arco(p, max(3, int(np.ceil(largo / 1.5)))), 7)
    # junto al cuerpo el ancho no se mide (el rincón de la unión lo ensancha); en una parte corta (una pata
    # que apenas asoma) esa franja se achica, si no la cubriría entera
    junto = _crecer(cuerpo, max(1, int(min(0.4 * grosor, 0.25 * largo))))
    # las puntas del esqueleto se doblan hacia las esquinas (o hacia el ancho de un remate): se cortan
    # y el trazo se alarga recto, con la dirección del tramo anterior
    s = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(p, axis=0), axis=1))])
    if s[-1] > 4 * poda:
        p = p[(s >= poda) & (s <= s[-1] - poda)]
    # el esqueleto se corre hacia un lado donde la parte fina cambia de forma (cerca de una unión): cada
    # punto se lleva al medio de su sección, medido en la imagen
    for _ in range(2):
        _, desvio = _secciones(g, p, cuerpo, grosor, junto)
        desvio = np.nan_to_num(desvio)
        # mediana móvil de un ancho: donde sale otra rama el medio de la sección se corre de golpe hacia
        # ella; eso no es el eje y se ignora
        v_ = max(3, int(grosor / 1.5) | 1)
        if len(desvio) > v_:
            m_ = v_ // 2
            desvio[m_:-m_] = np.median(np.lib.stride_tricks.sliding_window_view(desvio, v_), axis=1)
        tg = np.gradient(p, axis=0)
        tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-9)
        p = p + np.column_stack([-tg[:, 1], tg[:, 0]]) * desvio[:, None]
        p = _media_movil(p, 7)
    pegado = []
    # los puntos junto al cuerpo no se pudieron centrar: se quitan y se llega al cuerpo siguiendo la parte
    afuera = np.array([not (0 <= int(round(c[1])) < junto.shape[0] and 0 <= int(round(c[0])) < junto.shape[1]
                            and junto[int(round(c[1])), int(round(c[0]))]) for c in p])
    if afuera.sum() >= 3:
        i0, i1 = int(np.argmax(afuera)), len(p) - int(np.argmax(afuera[::-1]))
        p = p[i0:i1]
    for lado in (0, 1):
        q = p if lado else p[::-1]                          # el extremo a alargar queda al final
        tramo = q[-min(len(q), max(3, int(2 * poda / 1.5))):]
        _, _, vt = np.linalg.svd(tramo - tramo.mean(0))
        t = vt[0] if np.dot(vt[0], tramo[-1] - tramo[0]) >= 0 else -vt[0]
        # se sigue la parte fina de a medio píxel, volviendo al medio de la sección en cada paso (así
        # sigue la curva de un asa); junto al cuerpo, donde el rincón la ensancha, sigue recto
        x, pasos, toca, hechos = q[-1].copy(), 0, False, [q[-1].copy()]
        t0, giro_max = t.copy(), 0.5 / (0.5 * grosor)       # no dobla más cerrado que su ancho
        while pasos < 2 * (4 * poda + 2 * grosor):
            sig = x + 0.5 * t
            yi, xi = int(round(sig[1])), int(round(sig[0]))
            if 0 <= yi < cuerpo.shape[0] and 0 <= xi < cuerpo.shape[1] and cuerpo[yi, xi]:
                toca = True
                break
            if _muestrear(g, sig[None])[0] < 0.5:
                break
            if not (0 <= yi < junto.shape[0] and 0 <= xi < junto.shape[1] and junto[yi, xi]):
                _, d = _secciones(g, np.array([sig - 0.5 * t, sig, sig + 0.5 * t]), cuerpo, grosor, junto)
                if np.isfinite(d[1]):
                    # de a poco: sigue una curva suave, pero no dobla hacia el ancho de un remate
                    sig = sig + np.array([-t[1], t[0]]) * float(np.clip(d[1], -0.15, 0.15))
                    hechos.append(sig)
                    t_ = sig - hechos[max(0, len(hechos) - 8)]
                    if np.linalg.norm(t_) > 1e-6:
                        giro = np.arctan2(t[0] * t_[1] - t[1] * t_[0], t @ t_)
                        giro = float(np.clip(giro, -giro_max, giro_max))
                        t = np.array([t[0] * np.cos(giro) - t[1] * np.sin(giro),
                                      t[0] * np.sin(giro) + t[1] * np.cos(giro)])
            x, pasos = sig, pasos + 1
            if t @ t0 < 0.25:
                break                                       # en un remate redondo (una mano) daría la vuelta
        if not toca:
            # se salió por un costado justo al llegar (un asa que se apoya en un hombro redondeado)
            ys_, xs_ = np.nonzero(cuerpo)
            if len(ys_) and np.hypot(xs_ - x[0], ys_ - x[1]).min() <= 0.75 * grosor:
                toca = True
        extra = [x] if pasos else []
        if toca:                                            # entra en el cuerpo: el tubo queda metido
            extra.append(x + t * grosor)
        q = np.vstack([q, np.array(extra)]) if extra else q
        p = q if lado else q[::-1]
        if toca:
            pegado.append('end' if lado else 'start')
    largo = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
    p = _por_arco(p, max(4, int(np.ceil(largo))))
    anchos, _ = _secciones(g, p, cuerpo, grosor, junto)
    # dentro del cuerpo (o donde no se pudo medir) vale el ancho medido más cercano
    ok = np.isfinite(anchos)
    if not ok.any():
        return None
    idx = np.arange(len(p))
    anchos = np.interp(idx, idx[ok], anchos[ok])
    if len(anchos) > 9:                                     # mediana (sin picos sueltos) y media móvil
        anchos[4:-4] = np.median(np.lib.stride_tricks.sliding_window_view(anchos, 9), axis=1)
    anchos = _media_movil(np.column_stack([anchos]), 5)[:, 0]
    return p, anchos, pegado


def _bola(comp, cuerpo):
    """Círculo que mejor sigue el borde libre de una parte (lo que no toca el cuerpo): (centro, radio,
    IoU del disco contra la parte, fuera del cuerpo), o None si la parte no es redonda. Se busca el
    círculo que sigue la mayor parte del borde (RANSAC con semilla fija): una astilla pegada a la bola
    (un pompón junto a la espalda) no lo tuerce."""
    borde = comp & ~_encoger(comp, 1) & ~_crecer(cuerpo, 2)
    ys, xs = np.nonzero(borde)
    if len(xs) < 20:
        return None
    pts = np.column_stack([xs, ys]).astype(np.float64)

    def ajustar(q):
        A = np.column_stack([q, np.ones(len(q))])
        sol = np.linalg.lstsq(A, -(q ** 2).sum(1), rcond=None)[0]
        c = -sol[:2] / 2
        r2 = c @ c - sol[2]
        return (c, float(np.sqrt(r2))) if r2 > 0 else (None, 0.0)
    rng = np.random.default_rng(0)
    mejor, dentro_max = None, 0
    for _ in range(200):
        c, r = ajustar(pts[rng.choice(len(pts), 3, replace=False)])
        if c is None or r > max(comp.shape):
            continue
        dentro = np.abs(np.hypot(*(pts - c).T) - r) < max(1.5, 0.04 * r)
        if dentro.sum() > dentro_max:
            mejor, dentro_max = dentro, int(dentro.sum())
    if mejor is None or dentro_max < max(20, 0.5 * len(pts)):
        return None
    c, r = ajustar(pts[mejor])
    if c is None:
        return None
    # que el arco seguido dé al menos media vuelta (si no, es el borde de otra cosa)
    ang = np.sort(np.arctan2(*(pts[mejor] - c).T[::-1]))
    if 2 * np.pi - np.diff(np.concatenate([ang, ang[:1] + 2 * np.pi])).max() < np.pi:
        return None
    yy, xx = np.mgrid[:comp.shape[0], :comp.shape[1]]
    disco = (np.hypot(xx - c[0], yy - c[1]) <= r) & ~cuerpo
    iou = float((disco & comp).sum() / max((disco | comp).sum(), 1))
    return (float(c[0]), float(c[1])), r, iou


def _direccion(a, b):
    d = np.asarray(b, float) - np.asarray(a, float)
    return [round(float(x), 4) for x in d / max(float(np.linalg.norm(d)), 1e-12)]


def strokes(rgba, height=None, thin=10, threshold=None, color=None, color_tol=0.15, min_length=2.0, exclude=None,
            exclude_tol=0.1):
    """Partes finas de una vista (asas, picos, alambres, antenas, patas, ramas) como trazos: su eje y su
    ancho en cada punto, en el marco de la vista (x desde el centro del cuerpo, z desde abajo de la
    silueta; en metros si hay `height`, el alto de la silueta entera). Con `color`, solo las partes de
    ese color. Una parte que se ramifica (unas patas sobre una rama, una rama con ramitas) da un trazo
    por rama: primero el más largo y después las ramas que salen de él (`parent`), que se meten en su
    tubo. Devuelve (trazos, info), del más largo al más corto, cada uno con `points` [[x, z], ...],
    `radii`, en qué extremo toca el cuerpo u otro trazo (`attached`: start/end) y el IoU de su silueta
    reconstruida contra la de la imagen."""
    import time
    inicio = time.perf_counter()
    v = _vista(rgba, thin, threshold, exclude, exclude_tol)
    k = float(height) / v['alto'] if height else 1.0 / v['alto']
    grosor_max = float(thin) / 100 * v['alto']
    fuente = np.minimum(color_coverage(rgba, color, color_tol), v['f']) if color else v['f']
    finos = v['finos'] & (fuente > 0.5)
    g = fuente * ~v['cuerpo']
    salida, bolas = [], []
    h, w = finos.shape
    area_min = (0.008 * v['alto']) ** 2
    pad = int(grosor_max) + 4
    for reg in regions(trace(finos.astype(np.float64)), min_area=area_min):
        comp = _rellenar(reg, finos.shape) & finos
        # cada rama se apoya en lo ya hecho (el cuerpo y los trazos anteriores de esta parte)
        apoyo = v['cuerpo'].copy()
        pendientes = [(comp, None, None)] if comp.any() else []
        vueltas = 0
        while pendientes and vueltas < 8:
            c, padre, ancho_padre = pendientes.pop(0)
            vueltas += 1
            ys, xs = np.nonzero(c)
            y0, y1 = max(0, ys.min() - pad), min(h, ys.max() + pad + 1)
            x0, x1 = max(0, xs.min() - pad), min(w, xs.max() + pad + 1)
            rec_ = (slice(y0, y1), slice(x0, x1))
            c_ = c[rec_]
            grosor, e = 0, c_
            while e.any() and grosor < 4 * grosor_max:
                e = _encoger(e, 1)
                grosor += 2
            r = _trazo(c_, g[rec_] * ~apoyo[rec_] * _crecer(c_, 2), apoyo[rec_], max(grosor, 2))
            if r is not None:
                p, anchos, pegado = r
                largo = float(np.linalg.norm(np.diff(p, axis=0), axis=1).sum())
                ancho = float(np.median(anchos))
            if r is None or largo < min_length * ancho or ancho < 2.5:
                # una mancha o una astilla, no un trazo; si es redonda (un pompón, un botón, una nariz de
                # bola) se informa como bola: su centro y radio, del círculo que mejor sigue su borde libre
                bola = _bola(c_, apoyo[rec_]) if padre is None else None
                if bola is not None:
                    (cx, cy), rr, iou_b = bola
                    bolas.append({'center': [round(float((cx + x0 - v['x0']) * k), 5),
                                             round(float((v['abajo'] - cy - y0) * k), 5)],
                                  'radius': round(float(rr * k), 5), 'iou': round(iou_b, 3)})
                continue
            # IoU de la silueta reconstruida (fuera de lo ya hecho) contra la parte medida
            tg = np.gradient(p, axis=0)
            tg /= np.maximum(np.linalg.norm(tg, axis=1, keepdims=True), 1e-9)
            nrm = np.column_stack([-tg[:, 1], tg[:, 0]])
            borde = np.vstack([p + nrm * anchos[:, None] / 2, (p - nrm * anchos[:, None] / 2)[::-1]])
            hecho = rasterize([borde * [1, -1]], c_.shape, (0.0, 0.0), 1.0)
            # (solo cerca del tubo: las ramas que salen de él se miden aparte)
            afuera = ~apoyo[rec_] & _crecer(hecho, max(2, int(0.5 * ancho)))
            iou = float((hecho & c_ & afuera).sum() / max(((hecho | c_) & afuera).sum(), 1))
            if padre is not None and (iou < 0.6 or ancho < 0.2 * ancho_padre or largo < 0.8 * ancho_padre):
                continue                                    # lo que sobra junto al tubo de la rama madre
            # lo que la rama no cubre (otras ramas que salen de ella) sigue en la cola
            hecho_todo = np.zeros_like(finos)
            hecho_todo[rec_] = hecho
            apoyo |= hecho_todo
            resto = c & ~_crecer(hecho_todo, 2)
            yo = len(salida)
            for sub in regions(trace(resto.astype(np.float64)), min_area=area_min):
                m_ = _rellenar(sub, finos.shape) & resto
                if m_.any():
                    pendientes.append((m_, yo, ancho))
            p = p + [x0, y0]
            pts = np.column_stack([(p[:, 0] - v['x0']) * k, (v['abajo'] - p[:, 1]) * k, anchos * k / 2])
            # más anillos donde el ancho cambia rápido: una punta redonda (una mano, un pie) con pocos
            # anillos sale como un cono
            arco = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pts[:, :2], axis=0), axis=1))])
            u = arco + np.concatenate([[0], np.cumsum(3 * np.abs(np.diff(pts[:, 2])))])
            n = int(np.clip(np.ceil(u[-1] / k / max(1.5, 0.2 * ancho)), 8, 200))
            ui = np.linspace(0, u[-1], n)
            si = np.interp(ui, u, arco)
            # la posición, de la línea con un vértice cada 0.3 anchos: el eje viene de a 1 px, y con anillos
            # a fracciones de px su ruido inclinaba la tangente en la punta (los últimos anillos se torcían)
            sc = np.linspace(0, arco[-1], max(4, int(np.ceil(arco[-1] / k / max(2.0, 0.3 * ancho)))))
            gx, gz = np.interp(sc, arco, pts[:, 0]), np.interp(sc, arco, pts[:, 1])
            sal = np.column_stack([np.interp(si, sc, gx), np.interp(si, sc, gz), np.interp(ui, u, pts[:, 2])])
            salida.append({'points': [[round(float(a), 5), round(float(b), 5)] for a, b in sal[:, :2]],
                           'radii': [round(float(x), 5) for x in sal[:, 2]],
                           'length': round(largo * k, 4), 'attached': pegado, '_padre': padre,
                           'radius': [round(float(sal[:, 2].min()), 4), round(float(sal[:, 2].max()), 4)],
                           'start': [round(float(x), 4) for x in sal[0, :2]],
                           'end': [round(float(x), 4) for x in sal[-1, :2]],
                           # hacia afuera en cada punta: para poner ahí un remate (una flor de regadera, un tapón)
                           'startDirection': _direccion(sal[min(3, len(sal) - 1), :2], sal[0, :2]),
                           'endDirection': _direccion(sal[max(0, len(sal) - 4), :2], sal[-1, :2]),
                           'iou': round(iou, 3)})
    # donde nace una rama, el ancho medido de la madre incluye el de la rama (un bulto en la rama del
    # árbol bajo la pata): ahí la madre toma el radio de sus vecinos
    for s in salida:
        if s['_padre'] is None:
            continue
        madre = salida[s['_padre']]
        mp, mr = np.array(madre['points']), np.array(madre['radii'])
        cerca = np.zeros(len(mp), bool)
        for lado, q in (('start', s['points'][0]), ('end', s['points'][-1])):
            if lado in s['attached']:
                d = 1.5 * (float(np.median(mr)) + float(np.median(s['radii'])))
                cerca |= np.linalg.norm(mp - np.array(q), axis=1) < d
        if cerca.any() and not cerca.all():
            i_ = np.arange(len(mp))
            mr[cerca] = np.interp(i_[cerca], i_[~cerca], mr[~cerca])
            madre['radii'] = [round(float(x), 5) for x in mr]
            madre['radius'] = [round(float(mr.min()), 4), round(float(mr.max()), 4)]
    orden = sorted(range(len(salida)), key=lambda i: -salida[i]['length'])
    nuevo = {viejo: i for i, viejo in enumerate(orden)}
    salida = [salida[i] for i in orden]
    for s in salida:
        padre = s.pop('_padre')
        if padre is not None:
            s['parent'] = nuevo[padre]
    bolas.sort(key=lambda b: -b['radius'])
    info = {'strokes': len(salida), 'thinPercent': float(thin), 'blobs': bolas,
            'elapsedMs': round(1000 * (time.perf_counter() - inicio), 1),
            '_frame': {'k': k, 'x0': v['x0'], 'abajo': v['abajo']}, '_body': v['pol']}
    return salida, info

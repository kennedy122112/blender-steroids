"""
Pruebas del núcleo de contornos (addon/blender_steroids/contours.py). No necesitan Blender, solo NumPy:

    python -m unittest discover -s tests -v

(también corren con el Python de Blender, que ya trae NumPy).
"""
import importlib.util
import os
import unittest

import numpy as np

_RUTA = os.path.join(os.path.dirname(__file__), '..', 'addon', 'blender_steroids', 'contours.py')
_spec = importlib.util.spec_from_file_location('contours', _RUTA)
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)

T = np.linspace(0, 2 * np.pi, 512, endpoint=False)
K = np.fft.fftfreq(512) * 512


def imagen(regiones, n=256, ss=4):
    """Siluetas oscuras sobre fondo claro, con antialias: regiones en coordenadas -0.5..0.5 (y arriba)."""
    lazos = [np.asarray(l, float) for r in regiones for l in [r['outer']] + r.get('holes', [])]
    m = C.rasterize(lazos, (n * ss, n * ss), (-0.5 + 0.5 / (n * ss), 0.5 - 0.5 / (n * ss)), 1.0 / (n * ss))
    cob = m.reshape(n, ss, n, ss).mean(axis=(1, 3))
    rgb = 0.9 - 0.75 * cob
    return np.dstack([rgb, rgb, rgb, np.ones_like(rgb)])


def circulo(r, cx=0.0, cy=0.0, n=400):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([cx + r * np.cos(t), cy + r * np.sin(t)])


class Fourier(unittest.TestCase):
    def test_circulo_solo_k1(self):
        c = C.coefficients(np.column_stack([np.cos(T), np.sin(T)]))
        self.assertAlmostEqual(abs(c[K == 1][0]), 1, places=12)
        self.assertLess(np.abs(c[K != 1]).max(), 1e-12)

    def test_elipse_trasladada(self):
        p = np.column_stack([3 * np.cos(T) + 5, 1.5 * np.sin(T) - 2])
        c = C.coefficients(p)
        self.assertLess(np.abs(c[np.abs(K) > 1]).max(), 1e-12)
        self.assertLess(abs(c[K == 0][0] - (5 - 2j)), 1e-12)
        self.assertLess(np.abs(C.reconstruct(c, 1) - p).max(), 1e-12)

    def test_traslacion_rotacion_escala(self):
        p = np.column_stack([np.cos(T) * (1 + 0.2 * np.sin(5 * T)), np.sin(T)])
        c0 = C.coefficients(p)
        self.assertLess(np.abs((C.coefficients(p + [0.7, -0.4]) - c0)[K != 0]).max(), 1e-12)
        f = 2.0 * np.exp(0.6j)
        z = (p[:, 0] + 1j * p[:, 1]) * f
        self.assertLess(np.abs(C.coefficients(np.column_stack([z.real, z.imag])) - c0 * f).max(), 1e-12)

    def test_recorrido_invertido(self):
        p = np.column_stack([np.cos(T) * (1 + 0.2 * np.sin(5 * T)), np.sin(T)])
        self.assertGreater(np.abs(C.coefficients(p[::-1]) - C.coefficients(p)).max(), 1e-3)
        self.assertLess(np.abs(C.canonical(p[::-1]) - C.canonical(p)).max(), 1e-12)

    def test_orden_invalido(self):
        c = C.coefficients(np.column_stack([np.cos(T), np.sin(T)]))
        for k in (-1, 256):
            with self.assertRaises(ValueError):
                C.reconstruct(c, k)

    def test_entradas_invalidas(self):
        for mala in ([], [[0, 0], [1, 1]], [[0, 0], [1, np.nan], [2, 0]], [[0, 0], [1, np.inf], [2, 0]]):
            with self.assertRaises(ValueError):
                C.coefficients(mala)
        with self.assertRaises(ValueError):
            C.simplify(circulo(1), 0.01, method='spline')

    def test_ruido_se_atenua(self):
        p = np.column_stack([np.cos(T), np.sin(T)])
        ruido = p + np.random.default_rng(1).normal(0, 0.02, p.shape)
        self.assertLess(np.abs(C.reconstruct(C.coefficients(ruido), 6) - p).max(), np.abs(ruido - p).max())

    def test_objetivo_inalcanzable(self):
        cuadrado = C.resample(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float), 512)
        K_, _, e, ok = C.fourier_fit(cuadrado, 1e-4, max_order=8)
        self.assertFalse(ok)
        self.assertGreater(e, 1e-4)


class Lazos(unittest.TestCase):
    def test_remuestreo(self):
        irr = np.array([[0, 0], [4, 0], [4.5, 3], [1, 2.2], [0.3, 4]], float)
        q = C.resample(irr, 300)
        per = np.linalg.norm(np.diff(np.vstack([irr, irr[:1]]), axis=0), axis=1).sum()
        pasos = np.linalg.norm(np.diff(np.vstack([q, q[:1]]), axis=0), axis=1)
        self.assertEqual(len(q), 300)
        self.assertGreater(np.linalg.norm(q[0] - q[-1]), 1e-9)          # sin cierre duplicado
        self.assertAlmostEqual(np.median(pasos), per / 300, places=9)
        self.assertLess(abs(pasos.sum() - per) / per, 0.01)               # las cuerdas acortan las esquinas

    def test_autointerseccion(self):
        t = np.linspace(0, 2 * np.pi, 128, endpoint=False)
        self.assertTrue(C.self_intersects(np.column_stack([np.sin(2 * t), np.sin(t)])))
        self.assertFalse(C.self_intersects(circulo(1, n=128)))

    def test_rdp_cuadrado(self):
        cuad = C.resample(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float), 400)
        self.assertEqual(len(C.rdp(cuad, 1e-6)), 4)

    def test_auto_elige_por_lazo(self):
        _, info = C.simplify(circulo(1), 0.0025 * 2.83)
        self.assertEqual(info['method'], 'fourier')
        estrella = np.array([[np.cos(a) * r, np.sin(a) * r] for a, r in
                             zip(np.linspace(0, 2 * np.pi, 10, endpoint=False), [1, 0.4] * 5)])
        _, info = C.simplify(estrella, 0.005)
        self.assertEqual(info['method'], 'polygon')
        self.assertEqual(info['vertices'], 10)




class Topologia(unittest.TestCase):
    """Hallazgo R1 de la auditoría: contactos que no son cruces estrictos."""

    def test_toque_tangencial(self):
        toca = np.array([[0, 0], [2, 0], [2, 1], [1, 0], [0, 1]], float)        # un vértice apoyado en un lado
        self.assertTrue(C.self_intersects(toca))

    def test_colineal_superpuesto(self):
        col = np.array([[0, 0], [3, 0], [3, 1], [2, 0], [1, 0], [0, 1]], float)
        self.assertTrue(C.self_intersects(col))

    def test_punto_repetido_no_vecino(self):
        ocho = np.array([[0, 0], [1, 1], [2, 0], [1, -1], [0, 0.0001], [0, 0], [-1, 1], [-1, -1]], float)
        self.assertTrue(C.self_intersects(ocho))

    def test_sin_falsos_positivos(self):
        self.assertFalse(C.self_intersects(circulo(1, n=256)))
        self.assertFalse(C.self_intersects(np.array([[0, 0], [1, 0], [1, 1], [0, 1]], float)))
        # una muesca angosta pero abierta no es un cruce
        muesca = np.array([[0, 0], [1, 0], [1, 1], [0.501, 1], [0.501, 0.2], [0.499, 0.2], [0.499, 1], [0, 1]], float)
        self.assertFalse(C.self_intersects(muesca))

    def test_duplicados_consecutivos(self):
        cuad = [[0, 0], [1, 0], [1, 0], [1, 1], [1, 1], [0, 1], [0, 0]]
        salida, info = C.outline([{'outer': cuad}], method='polygon')
        self.assertEqual(info['loops'][0]['vertices'], 4)
        self.assertIn('elapsedMs', info)



def pintar(capas, n=512, fondo=(0.9, 0.88, 0.83)):
    """Imagen RGBA con antialias: capas [(lazos en -0.5..0.5, color rgb)] pintadas en orden."""
    ss = 4
    img = np.ones((n, n, 3)) * fondo
    for lazos, color in capas:
        m = C.rasterize([np.asarray(l, float) for l in lazos], (n * ss, n * ss),
                        (-0.5 + 0.5 / (n * ss), 0.5 - 0.5 / (n * ss)), 1.0 / (n * ss))
        a = m.reshape(n, ss, n, ss).mean(axis=(1, 3))[..., None]
        img = img * (1 - a) + np.array(color) * a
    return np.dstack([img, np.ones((n, n))])


def estrella(r_ext, r_int, cx=0.0, cy=0.0):
    ang = np.pi / 2 + np.arange(10) * np.pi / 5
    rad = np.where(np.arange(10) % 2 == 0, r_ext, r_int)
    return np.column_stack([cx + rad * np.cos(ang), cy + rad * np.sin(ang)])


def rect(x0, y0, x1, y1):
    return np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]], float)


class PorColor(unittest.TestCase):
    """Prueba del farol: la estrella amarilla sobre papel rojo, con tapas doradas cerca."""

    def setUp(self):
        self.img = pintar([([circulo(0.35)], (0.8, 0.2, 0.17)),
                           ([rect(-0.15, 0.36, 0.15, 0.44)], (0.79, 0.6, 0.18)),
                           ([estrella(0.16, 0.07)], (0.97, 0.8, 0.24))])

    def test_solo_la_estrella(self):
        s, info = C.outline(self.img, size=0.32, color='#f7cc3d', tolerance=0.5)
        self.assertEqual(info['regions'], 1)
        self.assertEqual(info['loops'][0]['method'], 'polygon')
        self.assertEqual(info['loops'][0]['vertices'], 10)

    def test_dorado_no_cuenta_como_amarillo(self):
        f = C.color_coverage(self.img, '#f7cc3d')
        n = f.shape[0]
        fila = int((0.5 - 0.40) * n)                         # a la altura de la tapa dorada
        self.assertLess(f[fila].max(), 0.5)

    def test_color_invalido(self):
        with self.assertRaises(ValueError):
            C.outline(self.img, color='amarillo')


class Franjas(unittest.TestCase):
    """Torno con franjas de color: tapa dorada, cuerpo rojo, tapa dorada."""

    def setUp(self):
        self.img = pintar([([rect(-0.12, -0.42, 0.12, -0.32)], (0.79, 0.6, 0.18)),
                           ([rect(-0.25, -0.32, 0.25, 0.30)], (0.8, 0.2, 0.17)),
                           ([rect(-0.10, 0.30, 0.10, 0.40)], (0.79, 0.6, 0.18))])

    def test_tres_franjas(self):
        _, info = C.lathe_profile(self.img, size=0.82)
        b = info['bands']
        self.assertEqual(len(b), 3)
        self.assertEqual([x['color'][:3] for x in b], ['#c9', '#cc', '#c9'])
        self.assertAlmostEqual(b[1]['from'], 0.10 / 0.82, delta=0.01)
        self.assertAlmostEqual(b[1]['to'], 0.72 / 0.82, delta=0.01)
        self.assertAlmostEqual(b[1]['maxRadius'], 0.25, delta=0.005)

    def test_range_mide_solo_su_franja(self):
        b = C.lathe_profile(self.img, size=0.82)[1]['bands']
        perfil, info = C.lathe_profile(self.img, size=0.82, z_range=[b[1]['from'], b[1]['to']])
        self.assertTrue(info['targetMet'])
        self.assertAlmostEqual(perfil[0, 1], b[1]['from'] * 0.82, places=6)
        self.assertAlmostEqual(perfil[-1, 1], b[1]['to'] * 0.82, places=6)
        self.assertLess(np.abs(perfil[1:-1, 0] - 0.25).max(), 0.004)
        with self.assertRaises(ValueError):
            C.lathe_profile(self.img, z_range=[0.6, 0.2])

    def test_base_plana_no_es_asimetria(self):
        # la primera altura rozaba solo una esquina de la base: daba una asimetría falsa enorme
        _, info = C.lathe_profile(self.img, size=0.82)
        self.assertLess(info['asymmetryPercent'], 0.5)


class Bezier(unittest.TestCase):
    def evaluar(self, pts, izq, der, n=64):
        u = np.linspace(0, 1, n)[:, None]
        sal = []
        for i in range(len(pts)):
            p0, p1, p2, p3 = pts[i], der[i], izq[(i + 1) % len(pts)], pts[(i + 1) % len(pts)]
            sal.append((1 - u) ** 3 * p0 + 3 * (1 - u) ** 2 * u * p1 + 3 * (1 - u) * u ** 2 * p2 + u ** 3 * p3)
        return np.vstack(sal)

    def test_circulo_pocos_puntos(self):
        lazo = C.resample(circulo(1.0), 256)
        pts, izq, der, err = C.bezier(lazo, 0.001)
        self.assertLessEqual(len(pts), 8)
        self.assertLessEqual(err, 0.001)
        radios = np.linalg.norm(self.evaluar(pts, izq, der), axis=1)
        self.assertLess(np.abs(radios - 1).max(), 0.0015)

    def test_forma_suave(self):
        t = np.linspace(0, 2 * np.pi, 512, endpoint=False)
        lazo = C.resample(np.column_stack([np.cos(t) * (1 + 0.25 * np.sin(5 * t)), np.sin(t) * (1 + 0.25 * np.sin(5 * t))]), 400)
        pts, izq, der, err = C.bezier(lazo, 0.002)
        self.assertLessEqual(err, 0.002)
        self.assertLess(len(pts), 60)
        self.assertLess(C.hausdorff(lazo, self.evaluar(pts, izq, der)), 0.004)


class DesdeImagen(unittest.TestCase):
    def medir(self, regiones, n=256, **kw):
        img = imagen(regiones, n)
        salida, info = C.outline(img, size=1.0, **kw)
        lazos = [l for r in salida for l in [r['outer']] + r['holes']]
        # la figura original mide lo que mida su caja; se compara a la escala de la salida
        todos = np.vstack([np.asarray(r['outer'], float) for r in regiones])
        k = 1.0 / np.ptp(todos[:, 0])
        centro = (todos.min(0) + todos.max(0)) / 2
        orig = [(np.asarray(l, float) - centro) * k for r in regiones for l in [r['outer']] + r.get('holes', [])]
        forma = (400, 400)
        a = C.rasterize(lazos, forma, (-0.75, 0.75), 1.5 / 400)
        b = C.rasterize(orig, forma, (-0.75, 0.75), 1.5 / 400)
        return info, (a & b).sum() / (a | b).sum()

    def test_dona_con_hueco(self):
        info, iou = self.medir([{'outer': circulo(0.35), 'holes': [circulo(0.12)]}])
        self.assertEqual((info['regions'], info['holes']), (1, 1))
        self.assertEqual([l['method'] for l in info['loops']], ['fourier', 'fourier'])
        self.assertTrue(info['targetMet'])
        self.assertGreater(iou, 0.985)

    def test_dos_regiones_disjuntas(self):
        info, iou = self.medir([{'outer': circulo(0.15, -0.2)}, {'outer': circulo(0.1, 0.25, 0.1)}])
        self.assertEqual((info['regions'], info['holes']), (2, 0))
        self.assertGreater(iou, 0.98)

    def test_concavo_con_esquinas(self):
        ele = np.array([[-0.3, -0.3], [0.3, -0.3], [0.3, -0.1], [-0.1, -0.1], [-0.1, 0.35], [-0.3, 0.35]])
        # a 256 px el antialias redondea las esquinas casi 1 px y salen 7-10 vértices; a 512 px, los 6 exactos
        info, iou = self.medir([{'outer': ele}], n=512)
        self.assertEqual(info['loops'][0]['method'], 'polygon')
        self.assertEqual(info['loops'][0]['vertices'], 6)
        self.assertGreater(iou, 0.985)

    def test_isla_dentro_de_hueco(self):
        info, _ = self.medir([{'outer': circulo(0.4), 'holes': [circulo(0.25)]}, {'outer': circulo(0.1)}])
        self.assertEqual((info['regions'], info['holes']), (2, 1))

    def test_imagen_vacia(self):
        with self.assertRaises(ValueError):
            C.outline(np.ones((64, 64, 4)))

    def test_puntos_invalidos(self):
        for malos in ([[0, 0], [1, 1]], [[0, 0], [1, 1], [2, 2]], [[0, 0], [1, np.nan], [1, 1]]):
            with self.assertRaises(ValueError):
                C.outline([{'outer': malos}])

    def test_puntos_en_metros(self):
        salida, info = C.outline([{'outer': circulo(0.5)}], tolerance=0.1)
        self.assertAlmostEqual(info['size'][0], 1.0, places=2)
        self.assertGreater(C.area(salida[0]['outer']), 0)               # exterior antihorario



def jarron(z):
    """Perfil de un jarrón original: base, panza, cuello angosto y boca abierta (z de 0 a 1)."""
    return 0.16 + 0.12 * np.sin(np.pi * z * 1.1) ** 2 - 0.1 * np.exp(-((z - 0.82) / 0.07) ** 2) + 0.05 * z ** 6


def silueta_jarron(asa=False):
    z = np.linspace(0, 1, 300)
    r = jarron(z)
    lado = np.column_stack([r, z])
    pol = np.vstack([lado, (lado * [-1, 1])[::-1]]) * 0.8 - [0, 0.4]           # cabe en -0.5..0.5
    regs = [{'outer': pol}]
    if asa:                                                          # asa a la derecha: un aro
        regs = [{'outer': pol}, {'outer': circulo(0.14, 0.33, 0.05), 'holes': [circulo(0.08, 0.33, 0.05)]}]
    return regs


class Torno(unittest.TestCase):
    def comparar(self, perfil, alto=1.0):
        z = np.linspace(0.02, 0.98, 200) * alto
        r = np.interp(z, perfil[:, 1], perfil[:, 0])
        return np.abs(r - jarron(z / alto) * alto).max()

    def test_jarron(self):
        perfil, info = C.lathe_profile(imagen(silueta_jarron(), n=512), size=1.0)
        self.assertTrue(info['targetMet'])
        self.assertAlmostEqual(info['height'], 1.0, places=3)
        self.assertLess(self.comparar(perfil), 0.006)              # < 0.6 % del alto
        self.assertLess(info['asymmetryPercent'], 0.5)
        self.assertLess(info['keyPoints'], 60)

    def test_asa_de_un_lado(self):
        img = imagen(silueta_jarron(asa=True), n=512)
        _, ambos = C.lathe_profile(img, size=1.0)
        self.assertGreater(ambos['asymmetryPercent'], 5)           # el aviso de que no es de revolución
        perfil, info = C.lathe_profile(img, size=1.0, side='left')
        self.assertLess(self.comparar(perfil), 0.008)

    def test_lado_invalido(self):
        with self.assertRaises(ValueError):
            C.lathe_profile(imagen(silueta_jarron()), side='arriba')


def arco(R, w, cx=0.0, cy=0.0, n=200):
    """Asa en semicírculo (mitad de arriba) de radio medio R y ancho w."""
    t = np.linspace(0, np.pi, n)
    afuera = np.column_stack([cx + (R + w / 2) * np.cos(t), cy + (R + w / 2) * np.sin(t)])
    adentro = np.column_stack([cx + (R - w / 2) * np.cos(t[::-1]), cy + (R - w / 2) * np.sin(t[::-1])])
    return np.vstack([afuera, adentro])


def barra(a, b, w0, w1):
    """Trazo recto de a a b que se angosta de w0 a w1."""
    a, b = np.array(a, float), np.array(b, float)
    u = (b - a) / np.linalg.norm(b - a)
    n = np.array([-u[1], u[0]])
    return np.array([a + n * w0 / 2, b + n * w1 / 2, b - n * w1 / 2, a - n * w0 / 2])


VERDE = (0.18, 0.56, 0.51)


class Vistas(unittest.TestCase):
    """Prueba de la regadera: un cuerpo desde dos vistas, sin el pico que le sale de un costado."""

    def setUp(self):
        self.frente = pintar([([rect(-0.2, -0.4, 0.2, 0.1)], VERDE), ([barra((0.12, -0.25), (0.42, 0.04), 0.05, 0.03)], VERDE)])
        self.lado = pintar([([rect(-0.12, -0.4, 0.12, 0.1)], VERDE)])

    def test_el_pico_no_ensancha_el_cuerpo(self):
        niveles, info = C.views_body(self.frente, self.lado, 0.5)
        self.assertTrue(info['targetMet'])
        self.assertAlmostEqual(info['size'][0], 0.4, delta=0.006)
        self.assertAlmostEqual(info['size'][1], 0.24, delta=0.006)
        self.assertAlmostEqual(info['size'][2], 0.5, delta=0.006)
        derecha = np.array([n[2] for n in niveles])
        self.assertLess(np.abs(derecha - 0.2).max(), 0.006)       # ni un bulto donde nace el pico
        self.assertLess(info['viewsMismatchPercent'], 1)

    def test_vistas_que_no_coinciden(self):
        # el frente tiene una antena arriba y el costado no: el alto entero no es el mismo objeto
        antena = pintar([([rect(-0.2, -0.4, 0.2, 0.1)], VERDE), ([rect(-0.01, 0.05, 0.01, 0.3)], VERDE)])
        _, info = C.views_body(antena, self.lado, 0.7)
        self.assertGreater(info['viewsMismatchPercent'], 2)

    def test_seccion(self):
        e = C.section_shape(64, 2.0)
        self.assertLess(np.abs(np.hypot(e[:, 0], e[:, 1]) - 1).max(), 1e-9)   # elipse: círculo unitario
        cuadrada = C.section_shape(64, 8.0)
        self.assertGreater(np.abs(cuadrada[8]).min(), 0.9)                    # a 45° casi llega a la esquina


class Trazos(unittest.TestCase):
    """Un asa en arco sobre un cuerpo: su eje, su ancho y que se mete en el cuerpo por las dos puntas."""

    def setUp(self):
        self.img = pintar([([rect(-0.3, -0.45, 0.3, 0.0)], VERDE), ([arco(0.2, 0.04, 0, -0.02)], VERDE)])

    def test_asa(self):
        trazos, info = C.strokes(self.img, height=0.65)
        self.assertEqual(len(trazos), 1)
        t = trazos[0]
        self.assertEqual(sorted(t['attached']), ['end', 'start'])
        self.assertGreater(t['iou'], 0.9)
        self.assertGreater(min(t['radius']), 0.016)
        self.assertLess(max(t['radius']), 0.024)
        self.assertTrue(0.58 < t['length'] < 0.72, t['length'])
        # el eje pasa por el radio medio del arco (fuera del cuerpo)
        p = np.array(t['points'])
        fuera = p[p[:, 1] > 0.47]                                  # z desde abajo de la silueta
        r = np.hypot(fuera[:, 0], fuera[:, 1] - (0.45 - 0.02))
        self.assertLess(np.abs(r - 0.2).max(), 0.006)

    def test_pico_con_direccion(self):
        img = pintar([([rect(-0.2, -0.4, 0.2, 0.1)], VERDE), ([barra((0.12, -0.25), (0.42, 0.04), 0.05, 0.03)], VERDE)])
        trazos, _ = C.strokes(img, height=0.5)
        self.assertEqual(len(trazos), 1)
        t = trazos[0]
        u = np.array([0.30, 0.29]) / np.hypot(0.30, 0.29)
        libre = 'startDirection' if t['attached'] == ['end'] else 'endDirection'
        self.assertGreater(np.dot(t[libre], u), 0.99)
        self.assertGreater(t['radius'][1], t['radius'][0] * 1.3)  # se angosta hacia la punta

    def test_sin_partes_finas(self):
        trazos, _ = C.strokes(pintar([([rect(-0.2, -0.4, 0.2, 0.1)], VERDE)]))
        self.assertEqual(trazos, [])


def degradado(n=512, arriba=(0.93, 0.94, 0.95), abajo=(0.82, 0.84, 0.85)):
    """Fondo con degradado vertical, como un estudio o una ilustración."""
    t = np.linspace(0, 1, n)[:, None, None]
    return np.ones((n, n, 3)) * ((1 - t) * np.array(arriba) + t * np.array(abajo))


def pintar_sobre(fondo, capas):
    n = fondo.shape[0]
    img = fondo.copy()
    for lazos, color in capas:
        img = img * (1 - (a := _cobertura(lazos, n))[..., None]) + np.array(color) * a[..., None]
    return np.dstack([img, np.ones((n, n))])


def _cobertura(lazos, n, ss=4):
    m = C.rasterize([np.asarray(l, float) for l in lazos], (n * ss, n * ss),
                    (-0.5 + 0.5 / (n * ss), 0.5 - 0.5 / (n * ss)), 1.0 / (n * ss))
    return m.reshape(n, ss, n, ss).mean(axis=(1, 3))


class Pajaro(unittest.TestCase):
    """Prueba del pájaro: fondo con degradado, panza clara, patas sobre una rama, partes por color."""

    def test_panza_clara_sobre_degradado(self):
        # la panza crema se parece al fondo y está junto a plumas oscuras: no debe abrir una ranura
        img = pintar_sobre(degradado(), [([circulo(0.3)], (0.2, 0.62, 0.66)),
                                         ([circulo(0.18, 0.1, -0.05)], (0.93, 0.88, 0.77))])
        f = C.coverage(img)
        dentro = _cobertura([circulo(0.3)], 512) > 0.99
        self.assertGreater(f[dentro].min(), 0.5)
        afuera = _cobertura([circulo(0.31)], 512) < 0.01
        self.assertLess(f[afuera].max(), 0.5)

    def test_rama_con_pata(self):
        # una T: la rama da un trazo y la pata otro que nace de ella (parent) y se mete en el cuerpo
        img = pintar([([circulo(0.2, 0, 0.15)], VERDE), ([rect(-0.45, -0.32, 0.45, -0.25)], (0.47, 0.32, 0.2)),
                      ([rect(-0.012, -0.25, 0.012, -0.03)], (0.93, 0.55, 0.16))])
        trazos, _ = C.strokes(img, height=1.0)
        self.assertEqual(len(trazos), 2, [(t['length'], t.get('parent')) for t in trazos])
        rama, pata = trazos
        self.assertNotIn('parent', rama)
        self.assertEqual(pata['parent'], 0)
        self.assertEqual(sorted(pata['attached']), ['end', 'start'])
        self.assertGreater(min(rama['iou'], pata['iou']), 0.9)
        x = np.array(pata['points'])[:, 0]
        self.assertLess(np.abs(x - x.mean()).max(), 0.004)                # derecha, sin doblarse

    def test_color_no_toma_el_fondo(self):
        # crema con tolerancia amplia: el fondo gris claro queda dentro del rango, pero no es la figura
        img = pintar_sobre(degradado(), [([circulo(0.3)], (0.2, 0.62, 0.66)),
                                         ([circulo(0.12, 0.05, -0.05)], (0.93, 0.88, 0.77))])
        regs, info = C.outline(img, color='#eee2c4', color_tol=0.2)
        self.assertEqual(info['regions'], 1)
        self.assertAlmostEqual(info['size'][0], 1.0)

    def test_pick_y_escala(self):
        img = pintar([([circulo(0.2, -0.2, 0)], VERDE), ([circulo(0.1, 0.25, 0)], VERDE)])
        regs, info = C.outline(img, pick=[1], scale=0.01)
        self.assertEqual(info['regions'], 1)
        self.assertAlmostEqual(info['size'][0], 0.2 * 512 * 0.01, delta=0.02)    # el chico, a 1 cm por px
        with self.assertRaises(ValueError):
            C.outline(img, pick=[2])


LILA, NEGRO, BLANCO = (0.59, 0.46, 0.8), (0.12, 0.1, 0.16), (1.0, 1.0, 1.0)


def miembro(a, b, w, color=LILA):
    """Un brazo o una pata: un tramo con la punta redonda (la mano, el pie), en dos capas (en una sola,
    lo que se solapa se restaría)."""
    return [([barra(a, b, w, w)], color), ([circulo(w / 2, b[0], b[1])], color)]


class Personaje(unittest.TestCase):
    """Prueba del personaje: brillos en los ojos, brazos y patas cortos con manos redondas, orejas de canto."""

    def test_brillo_no_muerde_el_cuerpo(self):
        # el brillo de un ojo se parece al fondo (un hueco chico); cerca del borde, al separar una antena,
        # la apertura lo agrandaba y se comía el borde de la cabeza
        img = pintar([([circulo(0.3)], LILA), ([barra((0, 0.29), (0, 0.45), 0.02, 0.02)], LILA),
                      ([circulo(0.05, 0.2, 0.05)], NEGRO), ([circulo(0.012, 0.21, 0.06)], BLANCO)])
        v = C._vista(img, 10)
        dentro = (_cobertura([circulo(0.28)], 512) > 0.99) & ~(_cobertura([circulo(0.025, 0.21, 0.06)], 512) > 0)
        self.assertGreater(v['cuerpo'][dentro].mean(), 0.999)
        self.assertTrue(v['finos'].any())                               # la antena sí es fina

    def test_brazos_y_patas_cortos(self):
        capas = [([circulo(0.22, 0, 0.05)], LILA)]
        for s in (-1, 1):
            capas += miembro((s * 0.15, 0.12), (s * 0.33, 0.0), 0.055)                 # brazos
            capas += miembro((s * 0.09, -0.12), (s * 0.1, -0.32), 0.065)               # patas
        trazos, _ = C.strokes(pintar(capas), height=1.0, thin=12)
        self.assertEqual(len(trazos), 4, [(t['length'], t['iou']) for t in trazos])
        for t in trazos:
            self.assertGreater(t['iou'], 0.85)
            self.assertEqual(len(t['attached']), 1)                      # pegado al cuerpo, la mano libre
            # recto, sin dar la vuelta en la mano redonda
            ida = np.linalg.norm(np.subtract(t['end'], t['start']))
            self.assertGreater(ida, 0.9 * t['length'])

    def test_punta_redonda(self):
        # la mano termina en un semicírculo: el radio cerca de la punta lo sigue (con pocos anillos era un cono)
        capas = [([circulo(0.22)], LILA)] + miembro((0.18, 0.0), (0.4, 0.0), 0.08)
        t = C.strokes(pintar(capas), height=1.0, thin=25)[0][0]
        p, r = np.array(t['points']), np.array(t['radii'])
        punta = p[-1] if t['attached'] == ['start'] else p[0]
        d = np.linalg.norm(p - punta, axis=1)
        R = max(r)
        cerca = (d > 0.2 * R) & (d < 0.8 * R)
        self.assertGreaterEqual(cerca.sum(), 3)
        ideal = np.sqrt(np.maximum(2 * R * d[cerca] - d[cerca] ** 2, 0))
        self.assertLess(np.abs(r[cerca] - ideal).max(), 0.15 * R)

    def test_oreja_de_canto(self):
        # una parte fina y chica (una oreja vista de canto) no es una astilla de esquina: sale del cuerpo
        img = pintar([([circulo(0.25)], LILA), ([barra((0.02, 0.24), (0.04, 0.31), 0.015, 0.012)], LILA)])
        z, _, _, v = C.view_profile(img, 10)
        cima = (z.max() - 0) / v['alto']
        self.assertLess(cima, 0.5 / 0.56 + 0.02)                         # el cuerpo termina en la cabeza
        self.assertEqual(len(C.strokes(img, thin=10)[0]), 1)

    def test_brillo_por_color(self):
        # el brillo se parece al fondo pero lo encierra la figura: es parte de ella, y es chico a propósito
        img = pintar([([circulo(0.3)], LILA), ([circulo(0.06, 0.1, 0.05)], NEGRO), ([circulo(0.012, 0.11, 0.06)], BLANCO)])
        regs, info = C.outline(img, color='#ffffff', color_tol=0.06)
        self.assertEqual(info['regions'], 1)
        self.assertAlmostEqual(info['size'][0], 1.0)
        # un hueco grande sigue siendo fondo (entre unas patas y la rama): un anillo no toma su agujero
        anillo = pintar([([circulo(0.3), circulo(0.15)[::-1]], LILA)])
        with self.assertRaises(ValueError):
            C.outline(anillo, color='#e6e0d4', color_tol=0.05)

    def test_rama_sin_bulto(self):
        # donde nace la pata, el ancho medido de la rama incluye el de la pata: no queda un bulto
        img = pintar([([circulo(0.2, 0, 0.15)], VERDE), ([rect(-0.45, -0.32, 0.45, -0.25)], (0.47, 0.32, 0.2)),
                      ([rect(-0.03, -0.25, 0.03, -0.03)], (0.93, 0.55, 0.16))])
        trazos, _ = C.strokes(img, height=1.0)
        rama = trazos[0]
        self.assertNotIn('parent', rama)
        r = np.array(rama['radii'])
        self.assertLess(r.max(), 1.1 * np.median(r))


def leer_png(ruta):
    """RGBA 0..1 de un PNG de 8 bits RGB o RGBA sin entrelazar, solo con la biblioteca estándar (los tests
    corren también con el Python de Blender, que no trae Pillow)."""
    import struct
    import zlib
    with open(ruta, 'rb') as f_:
        datos = f_.read()
    pos, idat, w = 8, b'', 0
    while pos < len(datos):
        n, tipo = struct.unpack('>I4s', datos[pos:pos + 8])
        cuerpo = datos[pos + 8:pos + 8 + n]
        if tipo == b'IHDR':
            w, h, bits, color = struct.unpack('>IIBB', cuerpo[:10])
            assert bits == 8 and color in (2, 6), (bits, color)
            c = 3 if color == 2 else 4
        elif tipo == b'IDAT':
            idat += cuerpo
        pos += 12 + n
    crudo = np.frombuffer(zlib.decompress(idat), np.uint8).reshape(h, 1 + w * c)
    img = np.zeros((h, w * c), np.int32)
    for y in range(h):
        f, fila = crudo[y, 0], crudo[y, 1:].astype(np.int32)
        arriba = img[y - 1] if y else np.zeros(w * c, np.int32)
        if f == 0:
            img[y] = fila
        elif f == 2:
            img[y] = (fila + arriba) % 256
        else:
            r = np.zeros(w * c, np.int32)
            for x in range(w * c):
                izq = r[x - c] if x >= c else 0
                diag = arriba[x - c] if x >= c else 0
                if f == 1:
                    pred = izq
                elif f == 3:
                    pred = (izq + arriba[x]) // 2
                else:
                    pa, pb, pc = abs(arriba[x] - diag), abs(izq - diag), abs(izq + arriba[x] - 2 * diag)
                    pred = izq if pa <= pb and pa <= pc else (arriba[x] if pb <= pc else diag)
                r[x] = (fila[x] + pred) % 256
            img[y] = r
    img = img.reshape(h, w, c) / 255.0
    return img if c == 4 else np.dstack([img, np.ones((h, w))])


def elipse(a, c, cx=0.0, cy=0.0, n=400):
    t = np.linspace(0, 2 * np.pi, n, endpoint=False)
    return np.column_stack([cx + a * np.cos(t), cy + c * np.sin(t)])


class Vinilo(unittest.TestCase):
    """Prueba de la figura de vinilo: patas cortas bajo un cuerpo redondo y una cola de pompón."""

    def test_patas_bajo_cuerpo_redondo(self):
        # el corte de la unión sigue la curva del cuerpo (con la recta se llevaba una cuña de la panza) y
        # una pata que apenas asoma se mide igual
        capas = [([elipse(0.2, 0.19)], LILA)]
        for s in (-1, 1):
            capas += miembro((s * 0.095, -0.14), (s * 0.105, -0.255), 0.095)
        trazos, _ = C.strokes(pintar(capas), height=1.0, thin=22)
        self.assertEqual(len(trazos), 2, [(t['length'], t['iou']) for t in trazos])
        for t in trazos:
            self.assertGreater(t['iou'], 0.9)
            d = np.subtract(t['end'], t['start'])
            self.assertLess(abs(d[0]), 0.2 * abs(d[1]))                # derecha hacia abajo
        v = C._vista(pintar(capas), 22)
        fila, col = int((0.5 + 0.17) * 512), int(0.5 * 512)              # la panza entre las patas
        self.assertTrue(v['cuerpo'][fila, col])

    def test_pompon(self):
        # una parte redonda pegada al cuerpo no es un trazo: se informa como bola (centro y radio). La vista
        # de costado de examples/menta: pompón de radio 0.075 en (0.18, 0.275) sobre una silueta de 1.12
        img = leer_png(os.path.join(os.path.dirname(__file__), '..', 'examples', 'menta', 'lado.png'))
        trazos, info = C.strokes(img, height=1.12, thin=12)
        self.assertEqual(len(info['blobs']), 1, info['blobs'])
        b = info['blobs'][0]
        self.assertAlmostEqual(b['radius'], 0.075, delta=0.004)
        self.assertAlmostEqual(b['center'][1], 0.275, delta=0.006)
        self.assertGreater(b['iou'], 0.85)
        self.assertFalse(any(abs(t['start'][0] - 0.19) < 0.05 and abs(t['start'][1] - 0.27) < 0.05 for t in trazos))

class Figura(unittest.TestCase):
    """Prueba de la figura de vinilo sobre su base (examples/nico): la base de otro color no es parte de la
    figura, las piernas juntas se separan, una pierna corta va derecha y las botas salen por su color."""

    def setUp(self):
        self.img = leer_png(os.path.join(os.path.dirname(__file__), '..', 'examples', 'nico', 'frente.png'))

    def test_sin_la_base(self):
        v_con = C._vista(self.img, 10)
        v_sin = C._vista(self.img, 10, exclude=['#3a3f4a'], exclude_tol=0.05)
        self.assertAlmostEqual(v_con['alto'], v_sin['alto'])        # el marco es el de la silueta entera
        fila = int(v_sin['abajo'] - 0.03 * v_sin['alto'])           # la base: ni cuerpo ni parte fina
        self.assertFalse((v_sin['cuerpo'][fila] | v_sin['finos'][fila]).any())
        self.assertTrue(v_con['finos'][fila].any())

    def test_piernas_juntas_y_derechas(self):
        # las dos piernas, a 0.06 una de otra bajo el impermeable: cada unión se corta sola (antes la
        # esquina de una se buscaba hasta la otra y se llevaba el impermeable entre las dos), y una pierna
        # tan ancha como larga va de donde se pega hacia abajo, no en diagonal
        trazos, _ = C.strokes(self.img, height=1.0, thin=10, color='#3c5aa0', exclude=['#3a3f4a'], exclude_tol=0.05)
        self.assertEqual(len(trazos), 2, [(t['start'], t['end'], t['iou']) for t in trazos])
        for t in trazos:
            self.assertGreater(t['iou'], 0.8)
            d = np.subtract(t['end'], t['start'])
            self.assertLess(abs(d[0]), 0.15 * abs(d[1]))

    def test_bota_por_color(self):
        # una región de un color, entera y en el marco de la figura: la bota de la derecha
        z, iz, de, v = C.view_profile(self.img, 10, exclude=['#3a3f4a'], exclude_tol=0.05, color='#1e1e22',
                                      color_tol=0.06, pick=[0])
        k = 0.911 / v['alto']                                       # unidades del dibujo
        centro = (iz + de).mean() / 2 * k
        self.assertAlmostEqual(abs(centro), 0.078, delta=0.006)
        self.assertAlmostEqual((de - iz).max() * k, 0.116, delta=0.008)
        self.assertAlmostEqual(z.min() * k, 0.057, delta=0.008)


if __name__ == '__main__':
    unittest.main()

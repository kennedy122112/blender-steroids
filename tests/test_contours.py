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


if __name__ == '__main__':
    unittest.main()

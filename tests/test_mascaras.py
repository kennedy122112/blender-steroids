"""
Pruebas de las siluetas como máscaras (addon/blender_steroids/mascaras.py), sin Blender: separar la
figura del fondo, morfología, huecos, recorte e IoU (también por color).
Ejecutar: python -m unittest discover -s tests
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'blender_steroids'))
import mascaras as M  # noqa: E402


def cuadrado(h=60, w=60, y0=20, y1=40, x0=20, x1=40):
    m = np.zeros((h, w), bool)
    m[y0:y1, x0:x1] = True
    return m


def anillo(h=60, w=60):
    m = cuadrado(h, w, 10, 50, 10, 50)
    m[20:40, 20:40] = False
    return m


class Morfologia(unittest.TestCase):
    def test_dilatar_y_erosionar_un_punto(self):
        m = np.zeros((7, 7), bool)
        m[3, 3] = True
        d = M.dilate(m)
        self.assertEqual(d.sum(), 5)                         # la cruz 3x3
        self.assertEqual(M.dilate(m, 2).sum(), 13)
        self.assertTrue((M.erode(d) == m).all())

    def test_la_apertura_borra_lineas_finas_y_deja_lo_demas(self):
        m = cuadrado()
        m[5, :] = True                                       # una línea de la cuadrícula del visor
        m[30:58, 52:54] = True                               # otra de 2 px (sin cruzarse con la primera)
        a = M.opening(m)
        self.assertFalse(a[5].any())
        self.assertFalse(a[:, 52:54].any())
        self.assertEqual(int(a.sum()), 20 * 20 - 4)            # el cuadrado, con las esquinas redondeadas


class Huecos(unittest.TestCase):
    def test_tapa_el_hueco_cerrado(self):
        lleno = M.fill_holes(anillo())
        self.assertTrue(lleno[10:50, 10:50].all())

    def test_keep_lo_deja(self):
        a = anillo()
        self.assertTrue((M.fill_holes(a, 'keep') == a).all())
        with self.assertRaises(ValueError):
            M.fill_holes(a, 'otro')

    def test_una_isla_dentro_del_hueco_no_vacia_al_contenedor(self):
        a = anillo()
        a[28:32, 28:32] = True
        f = M.filled(a)
        self.assertTrue(f[10:50, 10:50].all())

    def test_no_rellena_una_muesca_abierta(self):
        m = cuadrado(60, 60, 10, 50, 10, 50)
        m[10:30, 26:34] = False                              # muesca de 8 px abierta arriba
        self.assertFalse(M.fill_holes(m)[12:28, 27:33].any())


class Componentes(unittest.TestCase):
    def test_se_queda_con_lo_grande(self):
        m = cuadrado(100, 100, 10, 60, 10, 60)
        m[80:83, 80:83] = True                               # un icono chico
        m[10:40, 70:95] = True                               # una parte suelta grande (> 10 %)
        g = M.largest_component(m)
        self.assertFalse(g[80:83, 80:83].any())
        self.assertTrue(g[10:40, 70:95].all())
        self.assertTrue(g[10:60, 10:60].all())

    def test_vacia(self):
        m = np.zeros((10, 10), bool)
        self.assertFalse(M.largest_component(m).any())


class Caja(unittest.TestCase):
    def test_bbox(self):
        self.assertEqual(M.bbox(cuadrado()), (20, 20, 39, 39))
        self.assertIsNone(M.bbox(np.zeros((5, 5), bool)))

    def test_bordes(self):
        e = M.edges(cuadrado())
        self.assertTrue(e[20, 30] and e[30, 20])
        self.assertFalse(e[30, 30])

    def test_recorte_a_una_altura(self):
        c = M.crop(cuadrado(60, 80, 10, 30, 10, 50), 40)     # 20 de alto x 40 de ancho
        self.assertEqual(c.shape, (40, 80))
        self.assertTrue(c.all())
        self.assertIsNone(M.crop(np.zeros((5, 5), bool), 10))


class IoU(unittest.TestCase):
    def test_iguales_y_mitad(self):
        a = np.ones((10, 10), bool)
        self.assertEqual(M.iou_aligned(a, a), 1.0)
        self.assertAlmostEqual(M.iou_aligned(a, np.ones((10, 20), bool)), 0.5)
        self.assertEqual(M.iou_aligned(np.zeros((4, 4), bool), np.zeros((4, 4), bool)), 0.0)

    def test_por_clase(self):
        a = np.array([[0, 0, 1, 1]], np.int16)
        b = np.array([[0, 1, 1, 1]], np.int16)
        r = M.iou_classes(a, b, [0, 1])
        self.assertAlmostEqual(r[0], 0.5)
        self.assertAlmostEqual(r[1], 2 / 3)


class Figura(unittest.TestCase):
    def test_separa_la_figura_del_fondo(self):
        px = np.ones((80, 80, 4), np.float32)
        px[..., :3] = 0.9                                     # fondo claro
        px[20:60, 25:55, :3] = (0.8, 0.3, 0.2)               # la figura
        px[10, :, :3] = 0.6                                   # una línea de la cuadrícula
        m = M.subject_mask(px)
        self.assertTrue(m[21:59, 25:55].all() and m[20:60, 26:54].all())
        self.assertFalse(m[10].any())
        self.assertEqual(int(m.sum()), 40 * 30 - 4)            # la apertura redondea las 4 esquinas

    def test_con_transparencia_usa_el_alfa(self):
        px = np.zeros((40, 40, 4), np.float32)
        px[10:30, 10:30] = (1, 1, 1, 1)                      # blanca sobre transparente
        self.assertEqual(int(M.subject_mask(px).sum()), 400)

    def test_clasifica_por_color_sin_importar_la_luz(self):
        pal = np.array([[0.8, 0.2, 0.2], [0.2, 0.3, 0.8]], np.float32)
        px = np.zeros((1, 3, 4), np.float32)
        px[0, 0, :3] = (0.4, 0.1, 0.1)                       # rojo en sombra
        px[0, 1, :3] = (0.25, 0.35, 0.9)                     # azul con luz
        mask = np.array([[True, True, False]])
        self.assertEqual(M.classify(px, mask, pal).tolist(), [[0, 1, -1]])


class Dibujo(unittest.TestCase):
    def test_polilinea_cerrada(self):
        img = np.zeros((20, 20, 4), np.float32)
        M.draw_polyline(img, np.array([[2.0, 2.0], [17.0, 2.0], [17.0, 17.0]]), (1, 0, 0))
        self.assertTrue((img[2, 2:18, 0] == 1).all())        # el lado de arriba
        self.assertEqual(img[10, 10, 0], 1)                  # el que cierra, en diagonal
        self.assertEqual(img[15, 3, 0], 0)


if __name__ == '__main__':
    unittest.main()

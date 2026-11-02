"""
Pruebas del emparejamiento de partes finas entre las dos vistas (addon/blender_steroids/vistas.py),
sin Blender: de qué parte de la otra vista toma un trazo su profundidad y su grosor.
Ejecutar: python -m unittest discover -s tests
"""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'blender_steroids'))
import vistas as V  # noqa: E402


def trazo(xs, zs, radio=0.02, pegado=('start',)):
    """Un trazo como lo da contours.strokes: puntos [x, z] en el marco de la vista, radios y puntas pegadas."""
    return {'points': [[float(x), float(z)] for x, z in zip(xs, zs)],
            'radii': [radio] * len(xs), 'attached': list(pegado)}


class Profundidad(unittest.TestCase):
    def test_toma_la_parte_de_las_mismas_alturas(self):
        z = np.linspace(0.1, 0.5, 9)
        pata = trazo(np.full(9, 0.05), z, 0.02)                  # de frente, vertical
        otros = [trazo(np.full(9, -0.1), np.linspace(0.6, 0.9, 9)),          # otra altura
                 trazo(np.linspace(0.0, 0.04, 9), z, 0.01)]                  # la misma pata de costado
        r = V.profundidad(pata, otros)
        self.assertEqual(r['indice'], 1)
        self.assertAlmostEqual(r['ratio'], 0.5)                  # de costado es la mitad de gruesa
        self.assertAlmostEqual(r['centro'][0], 0.0)
        self.assertAlmostEqual(r['centro'][-1], 0.04)            # se inclina hacia adelante

    def test_una_que_vuelve_sobre_si_no_se_lee_por_altura(self):
        z = np.linspace(0.1, 0.5, 9)
        ida_y_vuelta = trazo(np.linspace(0, 0.1, 9), [0.1, 0.2, 0.3, 0.4, 0.5, 0.4, 0.3, 0.2, 0.1])
        self.assertIsNone(V.profundidad(trazo(np.zeros(9), z), [ida_y_vuelta]))

    def test_si_las_puntas_no_calzan_no_es_la_misma_parte(self):
        # un brazo pegado arriba y una cola pegada abajo, en el mismo tramo de alturas
        brazo = trazo(np.zeros(9), np.linspace(0.5, 0.1, 9), pegado=('start',))
        cola = trazo(np.zeros(9), np.linspace(0.1, 0.5, 9), pegado=('start',))
        self.assertIsNone(V.profundidad(brazo, [cola]))

    def test_poco_solape_no_alcanza(self):
        a = trazo(np.zeros(9), np.linspace(0.1, 0.5, 9), pegado=())
        b = trazo(np.zeros(9), np.linspace(0.4, 0.8, 9), pegado=())
        self.assertIsNone(V.profundidad(a, [b]))

    def test_una_parte_horizontal_se_empareja_por_el_largo(self):
        # un brazo estirado hacia adelante: casi no cambia de altura y en las dos vistas termina a una
        # altura un poco distinta; por altura, la mano caería en otro punto del brazo
        n = 11
        frente = trazo(np.linspace(0.10, 0.30, n), np.linspace(0.52, 0.56, n))
        costado = trazo(np.linspace(0.0, 0.20, n), np.linspace(0.51, 0.555, n))
        r = V.profundidad(frente, [costado])
        self.assertEqual(r['indice'], 0)
        np.testing.assert_allclose(r['centro'], np.linspace(0.0, 0.20, n), atol=0.005)


if __name__ == '__main__':
    unittest.main()

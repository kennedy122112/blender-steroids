"""
Pruebas del motor de movimiento (addon/blender_steroids/dynamics.py), sin Blender ni NumPy:

    python -m unittest discover -s tests -v
"""
import importlib.util
import math
import os
import unittest

_RUTA = os.path.join(os.path.dirname(__file__), '..', 'addon', 'blender_steroids', 'dynamics.py')
_spec = importlib.util.spec_from_file_location('dynamics', _RUTA)
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)


def tiempos(seg, fps=24):
    return [i / fps for i in range(int(round(seg * fps)) + 1)]


class Integrador(unittest.TestCase):
    def test_estado_quieto(self):
        ys = D.integrate(lambda t, y: [0.0], [3.5], tiempos(2), 0.01)
        self.assertTrue(all(abs(y[0] - 3.5) < 1e-15 for y in ys))

    def test_exponencial(self):
        ys = D.integrate(lambda t, y: [-0.7 * y[0]], [2.0], tiempos(3), 0.01)
        t = tiempos(3)
        self.assertLess(max(abs(y[0] - 2.0 * math.exp(-0.7 * ti)) for y, ti in zip(ys, t)), 1e-9)

    def test_orden_cuatro(self):
        # al dividir el paso por 2 el error cae ~16 veces
        def err(h):
            ys = D.integrate(lambda t, y: [y[1], -y[0]], [1.0, 0.0], [0.0, 5.0], h)
            return abs(ys[-1][0] - math.cos(5.0))
        r = err(0.1) / err(0.05)
        self.assertGreater(r, 12)
        self.assertLess(r, 20)


class Modelos(unittest.TestCase):
    def test_oscilar(self):
        m = {'kind': 'oscillate', 'frequency': 2, 'amplitude': 25, 'phase': 90}
        v, info = D.simulate(m, tiempos(1, 48))
        self.assertAlmostEqual(v[0], 25, places=9)               # fase 90°: arranca arriba
        self.assertAlmostEqual(v[12], -25, places=9)             # medio ciclo después (1/4 s)
        self.assertEqual(info['mode'], 'kinematic')
        self.assertEqual(info['frames'], 49)

    def test_resorte_vs_exacto(self):
        m = {'kind': 'spring', 'mass': 1.0, 'stiffness': 20.0, 'damping': 0.5, 'initial': 0.15}
        t = tiempos(4, 30)
        v, info = D.simulate(m, t)
        self.assertEqual(info['mode'], 'ode_simulated')
        self.assertLess(max(abs(a - D.spring_exact(m, ti)) for a, ti in zip(v, t)), 1e-7)
        self.assertLess(abs(v[-1]), 0.05)                        # se va asentando

    def test_resorte_por_frecuencia(self):
        m = {'kind': 'spring', 'frequency': 1.5, 'dampingRatio': 0.2, 'initial': 10}
        t = tiempos(3, 60)
        v, _ = D.simulate(m, t)
        self.assertLess(max(abs(a - D.spring_exact(m, ti)) for a, ti in zip(v, t)), 1e-6)
        self.assertAlmostEqual(D.natural_frequency(m), 1.5)

    def test_sin_amortiguar_conserva_energia(self):
        m = {'kind': 'spring', 'mass': 2.0, 'stiffness': 50.0, 'initial': 0.3}
        ys = D.integrate(lambda t, y: [y[1], -25.0 * y[0]], [0.3, 0.0], tiempos(20, 24), 1 / 480)
        e = [0.5 * 2.0 * y[1] ** 2 + 0.5 * 50.0 * y[0] ** 2 for y in ys]
        self.assertLess(abs(e[-1] - e[0]) / e[0], 1e-4)

    def test_pendulo_periodo(self):
        # ángulo chico: T = 2π√(L/g); ángulo grande (60°): ~7 % más largo
        for ang, factor in ((2, 1.0), (60, 1.0732)):
            m = {'kind': 'pendulum', 'length': 1.0, 'initial': ang}
            t = [i / 1000 for i in range(4001)]
            v, _ = D.simulate(m, t)
            cruces = [t[i] for i in range(1, len(v)) if v[i - 1] > 0 >= v[i]]
            T = 2 * math.pi * math.sqrt(1 / 9.81) * factor
            self.assertAlmostEqual(cruces[1] - cruces[0], T, delta=0.004)

    def test_follow_se_inclina_y_vuelve(self):
        t = tiempos(4, 60)
        a = [3.0 if ti < 0.5 else 0.0 for ti in t]               # el guía arranca y luego va parejo
        v, info = D.simulate({'kind': 'follow', 'frequency': 2, 'dampingRatio': 0.3, 'gain': 5}, t, a)
        self.assertLess(min(v), -0.5)                            # se inclina hacia atrás
        self.assertLess(abs(v[-1]), 0.05)                        # y se asienta

    def test_aliasing(self):
        self.assertIsNotNone(D.aliasing(15, 24)[0])              # 1.6 fotogramas por ciclo: error
        self.assertIsNotNone(D.aliasing(8, 24)[1])               # 3: aviso
        self.assertEqual(D.aliasing(2, 24), (None, None))

    def test_entradas_invalidas(self):
        malos = [{'kind': 'volar'}, {'kind': 'oscillate', 'amplitude': 1},
                 {'kind': 'spring', 'mass': 0, 'stiffness': 1}, {'kind': 'spring', 'stiffness': -1},
                 {'kind': 'pendulum', 'length': float('nan')}, {'kind': 'follow', 'frequency': 2},
                 {'kind': 'oscillate', 'frequency': 1, 'amplitude': 90, 'maxAbs': 45}]
        for m in malos:
            with self.assertRaises(ValueError):
                D.simulate(m, tiempos(1))
        with self.assertRaises(ValueError):
            D.simulate({'kind': 'oscillate', 'frequency': 1, 'amplitude': 1}, [0.0] * (D.MAX_FRAMES + 1))



class Robustez(unittest.TestCase):
    """Hallazgos de la auditoría BS-REVIEW-005 (R5, R6)."""

    def test_tiempos_invalidos(self):
        m = {'kind': 'spring', 'frequency': 1, 'initial': 1}
        for malos in ([0, 0.1, 0.05], [0, 0.1, 0.1], [0, float('nan'), 0.2], [0, float('inf')], []):
            with self.assertRaises(ValueError):
                D.simulate(m, malos)

    def test_resorte_rigido_estable(self):
        # 300 Hz con el paso por defecto (1/480 s) es inestable para RK4: el paso se ajusta solo
        m = {'kind': 'spring', 'frequency': 300, 'dampingRatio': 0.05, 'initial': 1}
        t = tiempos(0.5, 24)
        v, info = D.simulate(m, t)
        self.assertLess(max(abs(x) for x in v), 1.0 + 1e-9)
        self.assertLess(max(abs(a - D.spring_exact(m, ti)) for a, ti in zip(v, t)), 1e-6)
        self.assertGreater(info['substeps'], 0)

    def test_tope_de_subpasos(self):
        with self.assertRaises(ValueError):
            D.simulate({'kind': 'spring', 'frequency': 1, 'initial': 1, 'step': 1e-7}, tiempos(60, 24))

    def test_follow_igual_y_lineal(self):
        import time
        t = tiempos(100, 24)                                     # 2401 fotogramas
        a = [math.sin(3 * x) + 0.3 * math.sin(11 * x) for x in t]
        m = {'kind': 'follow', 'frequency': 3, 'dampingRatio': 0.3, 'gain': 2}
        t0 = time.perf_counter()
        v, info = D.simulate(m, t, a)
        dt = time.perf_counter() - t0
        self.assertLess(dt, 2.0)                                 # antes: 8 s (búsqueda lineal)
        # referencia: la misma ecuación con la aceleración interpolada por búsqueda lineal
        w, z = 2 * math.pi * 3, 0.3

        def acel(tt):
            for i in range(1, len(t)):
                if tt <= t[i]:
                    u = (tt - t[i - 1]) / (t[i] - t[i - 1])
                    return a[i - 1] * (1 - u) + a[i] * u
            return a[-1]
        ref = D.integrate(lambda tt, y: [y[1], -w * w * 2 * acel(tt) - 2 * z * w * y[1] - w * w * y[0]],
                          [0.0, 0.0], t[:241], info['step'])
        self.assertLess(max(abs(x - r[0]) for x, r in zip(v[:241], ref)), 1e-9)
        self.assertIn('elapsedMs', info)


if __name__ == '__main__':
    unittest.main()

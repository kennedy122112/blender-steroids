"""
Pruebas de lo que se lee de un spec (addon/blender_steroids/formato.py), sin Blender: colores,
vectores, rutas, el aviso de claves mal escritas y la hoja de vistas.
Ejecutar: python -m unittest discover -s tests
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'addon', 'blender_steroids'))
import formato as F  # noqa: E402


class Colores(unittest.TestCase):
    def test_hex_a_lineal_y_de_vuelta(self):
        for h in ('#000000', '#ffffff', '#3c5aa0', '#e8b04a', '#3a3f4a'):
            self.assertEqual(F.hexcolor(F.color(h)), h)

    def test_lineal(self):
        r, g, b, a = F.color('#808080')
        self.assertAlmostEqual(r, 0.2158605, places=5)
        self.assertEqual((r, g), (g, b))
        self.assertEqual(a, 1.0)

    def test_formas_cortas_y_alfa(self):
        self.assertEqual(F.color('#f00'), F.color('#ff0000'))
        self.assertAlmostEqual(F.color('#ff000080')[3], 128 / 255)
        self.assertEqual(F.color([1, 0, 0], alpha=0.5), (1.0, 0.0, 0.0, 0.5))


class Vectores(unittest.TestCase):
    def test_vec3(self):
        self.assertEqual(F.vec3(None), (0.0, 0.0, 0.0))
        self.assertEqual(F.vec3(2), (2.0, 2.0, 2.0))
        self.assertEqual(F.vec3([1]), (1.0, 0.0, 0.0))
        self.assertEqual(F.vec3([1, 2], default=(9, 9, 9)), (1.0, 2.0, 9.0))

    def test_snake(self):
        self.assertEqual(F.snake('excludeTolerance'), 'exclude_tolerance')
        self.assertEqual(F.snake('size'), 'size')


class Rutas(unittest.TestCase):
    def test_relativa_a_la_carpeta_del_spec(self):
        with tempfile.TemporaryDirectory() as d:
            open(os.path.join(d, 'frente.png'), 'wb').close()
            self.assertEqual(F.ruta('frente.png', d), os.path.join(d, 'frente.png'))
            with self.assertRaises(FileNotFoundError):
                F.ruta('lado.png', d)


class Claves(unittest.TestCase):
    def avisos(self, d):
        w = []
        F.claves_raras(d, '«Caja»', w)
        return w

    def test_las_que_se_usan_no_avisan(self):
        self.assertEqual(self.avisos({'name': 'Caja', 'type': 'cube', 'size': 1, 'material': 'X',
                                      'sheet': {}, 'excludeTolerance': 0.1}), [])

    def test_un_tipeo_sugiere_la_correcta(self):
        w = self.avisos({'sise': 1, 'excludeTolerence': 0.1})
        self.assertEqual(len(w), 2)
        self.assertIn('¿size?', w[0])
        self.assertIn('¿excludeTolerance?', w[1])
        self.assertIn('«Caja»', w[0])

    def test_sin_parecida_no_inventa(self):
        w = self.avisos({'zzzqqq': 1})
        self.assertEqual(len(w), 1)
        self.assertNotIn('¿', w[0])

    def test_las_privadas_no_cuentan(self):
        self.assertEqual(self.avisos({'_nota': 'para mí'}), [])

    def test_salen_de_los_dos_modulos(self):
        conocidas = F.claves_conocidas()
        self.assertIn('lookAt', conocidas)          # se lee en ops.py
        self.assertIn('inView', conocidas)          # se lee en formato.py (y está en GEOM_KEYS)

    def test_los_ejemplos_no_avisan(self):
        # todo lo que traen los ejemplos se usa: un aviso aquí es una clave que el detector no ve
        carpeta = os.path.join(os.path.dirname(__file__), '..', 'examples')
        for nombre in sorted(os.listdir(carpeta)):
            if not nombre.endswith('.json'):
                continue
            with open(os.path.join(carpeta, nombre), encoding='utf-8') as f:
                spec = json.load(f)
            w = []
            F.claves_raras({k: v for k, v in spec.items() if k != 'objects'}, 'spec', w)
            for o in spec.get('objects', []):
                F.claves_raras(o, '«%s»' % o.get('name'), w)
            self.assertEqual(w, [], nombre)


class Hoja(unittest.TestCase):
    HOJA = {'front': 'f.png', 'side': 's.png', 'height': 0.12, 'thin': 12, 'exclude': ['#3a3f4a']}

    def test_views_toma_las_dos_imagenes_y_lo_comun(self):
        o = F.con_hoja({'name': 'Cuerpo', 'type': 'views'}, self.HOJA)
        self.assertEqual((o['front'], o['side'], o['height'], o['thin'], o['exclude']),
                         ('f.png', 's.png', 0.12, 12, ['#3a3f4a']))

    def test_stroke_toma_su_vista_y_la_otra(self):
        o = F.con_hoja({'type': 'stroke'}, self.HOJA)
        self.assertEqual((o['image'], o['side']), ('f.png', 's.png'))
        o = F.con_hoja({'type': 'stroke', 'view': 'side'}, self.HOJA)
        self.assertEqual((o['image'], o['front']), ('s.png', 'f.png'))

    def test_lo_que_dice_la_pieza_manda(self):
        o = F.con_hoja({'type': 'views', 'height': 0.3, 'thin': 15}, self.HOJA)
        self.assertEqual((o['height'], o['thin']), (0.3, 15))

    def test_stroke_de_otra_imagen_no_toma_la_otra_vista(self):
        o = F.con_hoja({'type': 'stroke', 'image': 'otra.png'}, self.HOJA)
        self.assertNotIn('side', o)

    def test_outline_solo_con_inview(self):
        suelto = {'type': 'outline', 'image': 'logo.png'}
        self.assertIs(F.con_hoja(suelto, self.HOJA), suelto)
        o = F.con_hoja({'type': 'outline', 'inView': True, 'color': '#fff'}, self.HOJA)
        self.assertEqual(o['image'], 'f.png')
        self.assertNotIn('side', o)

    def test_no_toca_el_original_ni_otros_tipos(self):
        o = {'type': 'views'}
        F.con_hoja(o, self.HOJA)
        self.assertEqual(o, {'type': 'views'})
        cubo = {'type': 'cube'}
        self.assertIs(F.con_hoja(cubo, self.HOJA), cubo)
        self.assertIs(F.con_hoja(o, None), o)


class Firma(unittest.TestCase):
    def test_solo_la_forma_y_sin_importar_el_orden(self):
        a = F.geom_sig({'size': 1, 'type': 'cube', 'material': 'X'})
        b = F.geom_sig({'type': 'cube', 'size': 1, 'material': 'Y', 'location': [1, 2, 3]})
        self.assertEqual(a, b)
        self.assertNotEqual(a, F.geom_sig({'type': 'cube', 'size': 2}))


if __name__ == '__main__':
    unittest.main()

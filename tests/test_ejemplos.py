"""
Pruebas del formato de los specs de examples/ (tests/estilo_json.py), sin Blender: todos los ejemplos
lo tienen y el formateador solo cambia espacios y saltos de línea.
Ejecutar: python -m unittest discover -s tests
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(__file__))
import estilo_json as E  # noqa: E402

EJEMPLOS = os.path.join(os.path.dirname(__file__), '..', 'examples')


class Ejemplos(unittest.TestCase):
    def test_todos_tienen_el_formato(self):
        for nombre in sorted(os.listdir(EJEMPLOS)):
            if not nombre.endswith('.json'):
                continue
            with open(os.path.join(EJEMPLOS, nombre), encoding='utf-8') as f:
                texto = f.read().replace('\r\n', '\n')
            self.assertEqual(texto, E.formatear(json.loads(texto)),
                             '%s: python tests/estilo_json.py examples/%s lo arregla' % (nombre, nombre))


class Formateador(unittest.TestCase):
    SPEC = {'removeDefaults': True, 'scene': {'resolution': [1280, 720], 'world': {}},
            'collections': [], 'materials': [{'name': 'Ñandú', 'color': '#ffffff'}],
            'objects': [{'name': 'Largo', 'type': 'outline', 'points': [[i / 7, (i * 3 % 5) / 9] for i in range(40)],
                         'attach': {'to': 'Cuerpo', 'side': 'front', 'offset': 0.0008, 'wrap': True,
                                    'project': 'view', 'align': True, 'at': [0.1, 0.2, 0.3]}}]}

    def test_el_json_no_cambia_y_nada_se_pasa_del_ancho(self):
        texto = E.formatear(self.SPEC)
        self.assertEqual(json.loads(texto), self.SPEC)
        self.assertTrue(all(len(l) <= E.ANCHO for l in texto.split('\n')))
        self.assertIn('Ñandú', texto)                       # sin escapar
        self.assertTrue(texto.endswith('}\n'))

    def test_una_pieza_corta_va_en_una_linea(self):
        texto = E.formatear({'objects': [{'name': 'Piso', 'type': 'plane', 'size': 8}]})
        self.assertIn('    { "name": "Piso", "type": "plane", "size": 8 }\n', texto)

    def test_es_estable(self):
        una = E.formatear(self.SPEC)
        self.assertEqual(E.formatear(json.loads(una)), una)


if __name__ == '__main__':
    unittest.main()

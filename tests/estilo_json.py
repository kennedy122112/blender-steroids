"""
El formato de los specs de examples/: el de un spec escrito a mano, para que se lean y se comparen
igual. Dos espacios de sangría; cada clave de arriba en su línea; cada pieza (un objeto de una lista)
en una línea si cabe en ANCHO columnas, y si no, sus claves seguidas en varias líneas; las listas de
números o de pares, seguidas. Solo cambia espacios y saltos de línea: el JSON es el mismo.

    python tests/estilo_json.py examples/*.json           reescribe los archivos con este formato
    python tests/estilo_json.py --check examples/*.json   sale con 1 si alguno no lo tiene

tests/test_ejemplos.py comprueba que todos los ejemplos lo tienen.
"""
import json
import sys

ANCHO = 120
SANGRIA = 2
NL = '\n'


def _plano(v):
    """En una línea: { "a": 1, "b": [1, 2] }."""
    if isinstance(v, dict):
        if not v:
            return '{}'
        return '{ ' + ', '.join('%s: %s' % (json.dumps(k, ensure_ascii=False), _plano(x)) for k, x in v.items()) + ' }'
    if isinstance(v, list):
        return '[' + ', '.join(_plano(x) for x in v) + ']'
    return json.dumps(v, ensure_ascii=False)


def _seguidos(partes, abre, cierra, col, inicio):
    """Las partes una tras otra desde la columna inicio, pasando a la línea siguiente (en la columna
    col) cuando no caben. Una parte de varias líneas empieza una línea; lo que sigue, tras su última."""
    lineas, actual, margen = [], abre, inicio
    for i, p in enumerate(partes):
        p = p + (',' if i < len(partes) - 1 else cierra)
        larga = NL in p
        primera = p.split(NL)[0]
        # ANCHO - 1: deja lugar para la coma que pone el de afuera
        if actual != abre and (larga or margen + len(actual) + 1 + len(primera) > ANCHO - 1):
            lineas.append(actual)
            actual, margen = ' ' * col + p, 0
        else:
            actual += ('' if actual == abre else ' ') + p
        if larga:
            *antes, actual = actual.split(NL)
            lineas.extend(antes)
            margen = 0
    lineas.append(actual)
    return NL.join(lineas)


def _valor(v, col, ancho_libre):
    """v empezando en la columna col (o más a la derecha, tras su clave); ancho_libre: lo que cabe en
    esa primera línea. Lo que no cabe sigue en la columna col + SANGRIA."""
    plano = _plano(v)
    if not isinstance(v, (dict, list)) or len(plano) <= ancho_libre:
        return plano
    sub = col + SANGRIA
    inicio = ANCHO - ancho_libre - 1                     # la columna donde empieza v
    if isinstance(v, list):
        partes = [_plano(x) for x in v]
        if all(isinstance(x, dict) for x in v) or not all(sub + len(p) + 1 <= ANCHO for p in partes):
            # una pieza por línea
            cuerpo = (',' + NL).join(' ' * sub + _valor(x, sub, ANCHO - sub - 1) for x in v)
            return '[' + NL + cuerpo + NL + ' ' * col + ']'
        return _seguidos(partes, '[', ']', sub, inicio)
    partes = []
    for k, x in v.items():
        clave = json.dumps(k, ensure_ascii=False) + ': '
        # la que no cabe sola en una línea se parte, desde su clave
        partes.append(clave + _valor(x, sub, ANCHO - sub - len(clave) - 3))
    return _seguidos(partes, '{ ', ' }', sub, inicio)


def formatear(spec):
    """El texto del spec con el formato de los ejemplos (con salto de línea al final)."""
    lineas = []
    for k, v in spec.items():
        clave = json.dumps(k, ensure_ascii=False) + ': '
        if isinstance(v, dict) and v:
            # las secciones de arriba (scene, sheet...) con una clave por línea, como se escriben a mano
            internas = []
            for kk, x in v.items():
                c = json.dumps(kk, ensure_ascii=False) + ': '
                internas.append('    ' + c + _valor(x, 4, ANCHO - 4 - len(c) - 1))
            texto = '{' + NL + (',' + NL).join(internas) + NL + '  }'
        elif isinstance(v, list) and v and all(isinstance(x, dict) for x in v):
            # materials, objects, animation: una pieza por línea aunque quepan todas juntas
            texto = '[' + NL + (',' + NL).join('    ' + _valor(x, 4, ANCHO - 5) for x in v) + NL + '  ]'
        else:
            texto = _valor(v, SANGRIA, ANCHO - SANGRIA - len(clave) - 1)
        lineas.append('  ' + clave + texto)
    return '{' + NL + (',' + NL).join(lineas) + NL + '}' + NL


def main(args):
    revisar = '--check' in args
    malos = []
    for ruta in [a for a in args if a != '--check']:
        with open(ruta, encoding='utf-8') as f:
            texto = f.read()
        nuevo = formatear(json.loads(texto))
        assert json.loads(nuevo) == json.loads(texto), ruta
        if nuevo != texto.replace('\r\n', NL):
            malos.append(ruta)
            if not revisar:
                with open(ruta, 'w', encoding='utf-8', newline=NL) as f:
                    f.write(nuevo)
    for r in malos:
        print(('sin el formato: ' if revisar else 'reformateado: ') + r)
    return 1 if revisar and malos else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))

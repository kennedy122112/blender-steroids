import os

os.chdir(os.path.dirname(os.path.abspath(__file__)))


def edit(p, reps):
    s = open(p, encoding='utf-8').read()
    for a, b in reps:
        assert a in s, (p, a[:60])
        s = s.replace(a, b, 1)
    open(p, 'w', encoding='utf-8', newline='\n').write(s)


edit('skills/blender-model/SKILL.md', [
    ("""| `decal` | `size`: número o `[ancho, alto]`.""",
     """| `membrane` | Alas de murciélago o dragón, aletas, velas, abanicos: `root` (donde nace), `tip` (punta del hueso principal), `fingers` (puntas del borde, en orden), `scallop` (festón entre puntas, 0.18; 0 = recto), `bend` (curva hacia atrás como vela), `bones` (radio de los huesos; 0 = sin huesos), `thickness`. En coordenadas del mundo con `location` en 0; para el par, `modifiers: [{"type": "mirror", "axis": "X"}]` |
| `decal` | `size`: número o `[ancho, alto]`."""),
    ("""6. **Corrige con medidas, una cosa por vuelta.** Usa `widthByGuide*` y `zByGuide` de `compare`: si la
   referencia mide 0.61 y el render 0.75 en la guía 7, y esa guía es z 0.60–0.71 m, la pieza a cambiar es
   la que está a esa altura (no la que sospeches).""",
     """6. **Corrige con medidas, una cosa por vuelta.** Usa `widthByGuide*`, `zByGuide` y `edgesByGuide` de
   `compare`: si en la guía 4 la referencia mide 0.65 y el render 0.50, esa guía está a z 0.44 m y su
   borde derecho es `MangaD`, la pieza a cambiar es esa (no la que sospeches)."""),
    ("""   detalle, y dile al usuario cuáles quedan y el IoU final.""",
     """   detalle, y dile al usuario cuáles quedan y el IoU final. **Diferencias a propósito**: si haces un
   personaje original inspirado en la referencia, algunas guías no van a coincidir por diseño (otros
   cuernos, otra cola). Anótalas al empezar y no las persigas; mide el progreso en las demás."""),
    ("""Revisa sobre todo las fracciones altas y las piezas que deberían ir **por
  fuera**""",
     """Revisa sobre todo las fracciones altas y las piezas que deberían ir **por
  fuera**"""),
])

edit('skills/blender-render/SKILL.md', [
    ("""- `zByGuide`: la altura del mundo (m) de cada guía, de la 0 (base de la figura) a la 10 (lo más alto).
  Traduce «la guía 7 está ancha» a «lo que hay entre z 0.60 y 0.71 m está ancho».""",
     """- `zByGuide`: la altura del mundo (m) de lo que se ve en cada décimo de la figura (10 valores, de abajo
  arriba), calculada con los vértices reales proyectados por la cámara, así que vale en perspectiva.
- `edgesByGuide`: en cada décimo, qué pieza forma el borde izquierdo y cuál el derecho. Es la respuesta
  directa a «¿qué hace ancha esta guía?»."""),
    ("""usa el que más se parece; `fitView` en la respuesta dice cuál y los tres mejores. Tarda ~35 s. En figuras
casi simétricas la silueta distingue poco el ángulo (los mejores difieren en centésimas): entonces
elige tú el que corresponda a la referencia mirando la imagen.""",
     """usa el que más se parece; `fitView` en la respuesta dice cuál y los tres mejores. Tarda ~35 s. Funciona
bien con figuras asimétricas (una cola o un arma de un lado). En figuras casi simétricas la silueta
distingue poco el ángulo (los mejores difieren en centésimas): entonces elige tú el lado mirando la
imagen (hacia dónde apunta el hocico, qué brazo se ve más)."""),
    ("""Si la referencia tiene varias vistas o barras del programa, recórtala antes a una sola vista.""",
     """Si la referencia tiene varias vistas o barras del programa, recórtala antes a una sola vista y sin
iconos ni gizmos cerca de la figura: compare se queda con la región más grande, pero un icono pegado a
la figura en la misma fila la ensancha (se ve como rayas cian en el panel de siluetas)."""),
])

edit('README.md', [
    ("versi%C3%B3n-1.4.0-", "versi%C3%B3n-1.5.0-"),
    ("- 🧸 **Personajes y formas orgánicas**: cajas redondeadas, cuerpos de bolas fundidas, tubos que siguen curvas, piezas torneadas,",
     "- 🧸 **Personajes y formas orgánicas**: cajas redondeadas, cuerpos de bolas fundidas, tubos que siguen curvas, piezas torneadas, alas y aletas de membrana,"),
])
open('VERSION', 'w', encoding='utf-8', newline='\n').write('1.5.0\n')
edit('addon/blender_steroids/version.py', [("VERSION = '1.4.0'", "VERSION = '1.5.0'")])
edit('addon/blender_steroids/__init__.py', [("'version': (1, 4, 0)", "'version': (1, 5, 0)")])
print('ok')

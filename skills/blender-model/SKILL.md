---
name: blender-model
description: Crea y modifica escenas 3D reales y editables en Blender a partir de lenguaje natural - objetos, muebles, productos, maquetas, escenarios, texto 3D, materiales, luces, cámara y animación simple - y las revisa renderizando. Úsala cuando el usuario diga "modela en Blender", "crea una escena / un objeto / un producto en 3D", "arma una maqueta", "pon luces y cámara", "cambia el material", "anima esto", "que aletee / rebote / se balancee", "hazme un logo 3D", "convierte esta silueta / este logo en 3D", "build X in Blender".
---

# Modelar en Blender

Requiere conexión (`blender-connect`): en vivo o con `-File`. **blender-cli** está definido en `blender-setup`.

## Flujo
1. Entiende qué se pide y descomponlo en piezas simples con **medidas reales en metros** (una mesa
   mide ~0.75 m de alto, una taza ~0.1 m, una persona ~1.75 m, una puerta 0.9 × 2.1 m). Pregunta
   solo lo que cambie el resultado (estilo, colores de marca); lo demás, decídelo tú y dilo.
2. Lee la escena (`blender-cli scene`) para reutilizar materiales y objetos existentes.
3. Escribe un **spec JSON** (UTF-8) y ejecuta `blender-cli build -Spec escena.json` (en vivo) o
   `... -File escena.blend` (sin interfaz; guarda solo si el archivo era nuevo, si no, añade
   `-Save escena.blend`). Guarda el spec junto al `.blend` (`specs/NN-nombre.json`), nunca solo en una
   carpeta temporal: rehacer la escena es volver a correr `build`.
4. **Mira el resultado** antes de darlo por bueno: `blender-cli render -Path vista.png -Preview`
   (rápido, Workbench) y léelo. Para revisar formas, añade vistas `-View front|right|top` y
   `-Objects a,b` para acercarte a una pieza. Corrige piezas flotando, atravesadas o fuera de escala.
5. Cuéntale al usuario qué creó (por colección) y, si trabajaste sin interfaz, dónde quedó el `.blend`.

## Con una imagen de referencia
Cuando el usuario pasa una imagen (o varias), no empieces por los detalles: el primer intento sale
lejos si no lees la referencia antes. Ve en este orden.

1. **Lee la referencia y escribe sus datos** (en tu respuesta o en un comentario del spec) antes de modelar:
   - **Proporciones**, medidas en la imagen: alto total; qué porcentaje del alto ocupa cada bloque
     (cabeza, torso, piernas); ancho de la cabeza contra el del cuerpo. Una figura de vinilo tiene la
     cabeza en ~45-55 % del alto; un personaje realista, en ~13 %.
   - **Silueta**: las 3-6 formas grandes que la definen (cabeza cuadrada redondeada, cuerpo en
     campana, alas abiertas…) y qué primitiva usarás para cada una.
   - **Paleta** en hex, de 4 a 8 colores, con el material de cada uno (vinilo satinado, tela mate, metal).
   - **Puntos clave**: dónde caen los ojos (altura dentro de la cabeza, separación), accesorios, bordes.
   - **Estilo y luz**: figura de vinilo, toon, realista; fondo y dirección de la luz principal.
2. **Boceto de bloques**: solo las formas grandes con su color plano. Compara (paso 4) y ajusta
   proporciones y silueta **hasta que coincidan** antes de agregar cualquier detalle.
3. **Detalles** de lo grande a lo pequeño: accesorios, después la cara (calcomanías con `attach`,
   líneas con `onSurface`), al final materiales finos y luz. Las piezas planas de forma libre que se
   ven de frente (placas, emblemas, llamas, aletas, alas planas, orejas recortadas) no las armes a ojo
   con `mesh`: recorta su silueta de la referencia y constrúyelas con `outline`
   ([references/siluetas-y-torno.md](references/siluetas-y-torno.md)). Si tienes el
   objeto **de frente y de costado** (un plano, dos fotos, una hoja de vistas), el cuerpo sale de las dos
   con `views` y las asas, picos y alambres con `stroke`
   ([references/dos-vistas.md](references/dos-vistas.md)), sin medir nada a ojo.
4. **Compara de verdad**, no de memoria: `blender-cli compare -Reference ref.png -Path comparar.png
   [-View front]` renderiza con el formato de la referencia y pone las dos imágenes lado a lado con
   guías horizontales cada 10 % del alto. Léela y anota diferencias concretas («la cabeza llega a la
   guía 3 en la referencia y a la 4 en el render»). Usa la vista que coincida con la de la referencia.
5. **Lista de control** en cada vuelta: `blender-cli check` (abajo) para piezas flotando, enterradas
   o atravesadas; mira también `-View back` y `right`; proporciones, colores (AgX aclara; si un color se ve lavado, oscurécelo o usa
   `"look": "AgX - Punchy"`), legibilidad de la cara, nada tapado por la cámara.
6. **Cuando las piezas estén y solo falten proporciones, usa `fit`**
   ([references/ajuste-fit.md](references/ajuste-fit.md)) en vez de ajustar a mano.
   Para lo demás, **corrige con medidas, una cosa por vuelta.** Usa `widthByGuide*`, `zByGuide` y `edgesByGuide` de
   `compare`: si en la guía 4 la referencia mide 0.65 y el render 0.50, esa guía está a z 0.44 m y su
   borde derecho es `MangaD`, la pieza a cambiar es esa (no la que sospeches). Anota el `silhouetteIoU` de cada vuelta: si sube, la
   vuelta sirvió; si baja, deshaz ese cambio.
7. Repite 4-6 hasta que el IoU deje de subir (menos de 0.01 por vuelta) o las diferencias sean de
   detalle, y dile al usuario cuáles quedan y el IoU final. **Diferencias a propósito**: si haces un
   personaje original inspirado en la referencia, algunas guías no van a coincidir por diseño (otros
   cuernos, otra cola). Anótalas al empezar y no las persigas; mide el progreso en las demás. Una figura de vinilo bien bloqueada suele
   quedar en 0.85-0.90; por encima, las diferencias son de forma esculpida, no de proporción.

**Límite honesto**: con primitivas y código se logra muy bien lo hecho de piezas (productos,
mobiliario, figuras de vinilo, mascotas simples, maquetas). Una referencia esculpida, con anatomía
compleja o detalle fino, no se iguala; dilo al empezar y propón partir de un modelo base importado
(`.glb`/`.fbx`/`.obj`) que el agente luego viste, pinta, ilumina y renderiza.

**Personajes de terceros**: si la referencia es un personaje con derechos de autor (de anime,
videojuegos, películas, marcas), no lo reproduzcas; propón un personaje original inspirado en el
estilo (proporciones, paleta, tipo de accesorios) y constrúyelo con este mismo flujo.

## Spec JSON
```json
{
  "removeDefaults": true,
  "scene": { "engine": "eevee", "resolution": [1920, 1080], "fps": 24, "frames": [1, 120],
             "samples": 64, "transparent": false, "viewTransform": "AgX",
             "world": { "color": "#20242c", "strength": 0.6, "hdri": "C:/hdri/estudio.exr" } },
  "materials": [
    { "name": "Madera", "color": "#8a5a32", "roughness": 0.55 },
    { "name": "Metal", "color": "#c9ccd1", "metallic": 1, "roughness": 0.3 },
    { "name": "Vidrio", "color": "#ffffff", "transmission": 1, "roughness": 0.05, "ior": 1.45 },
    { "name": "Neon", "color": "#000000", "emission": "#36c5ff", "emissionStrength": 8 },
    { "name": "Logo", "texture": "logo.png" }
  ],
  "collections": ["Mesa", { "name": "Luces", "parent": null }],
  "objects": [
    { "name": "Tablero", "type": "cube", "size": [1.6, 0.9, 0.05], "location": [0, 0, 0.75],
      "material": "Madera", "collection": "Mesa",
      "modifiers": [{ "type": "bevel", "width": 0.01, "segments": 3 }] },
    { "name": "Pata", "type": "cylinder", "radius": 0.03, "depth": 0.73, "origin": "bottom",
      "location": [-0.72, -0.37, 0], "material": "Metal", "smooth": true,
      "modifiers": [{ "type": "mirror", "axis": "XY", "mirrorObject": "Tablero" }] },
    { "name": "Key", "type": "light", "light": "area", "energy": 400, "size": 2,
      "location": [2.5, -2.5, 3.5], "lookAt": "Tablero" },
    { "name": "Camara", "type": "camera", "lens": 50, "frame": ["Tablero", "Pata"], "view": "iso" }
  ],
  "animation": [
    { "object": "Tablero", "property": "rotation", "interpolation": "linear",
      "keys": [{ "frame": 1, "value": [0, 0, 0] }, { "frame": 120, "value": [0, 0, 360] }] }
  ],
  "delete": []
}
```
Todo es opcional salvo `name` en cada objeto. Ejemplo completo: `examples/mesa-con-taza.json`.

### Objetos (`type`)
| type | Parámetros de forma |
|---|---|
| `cube` | `size`: número o `[x, y, z]` en metros (tamaño real, la escala queda en 1) |
| `plane`, `grid` | `size`: número o `[x, y]`; `xSegments`, `ySegments` |
| `uv_sphere` (`sphere`), `ico_sphere` | `radius`; `segments`, `rings` / `subdivisions` |
| `cylinder`, `cone` | `radius`, `radius2` (cono: radio de arriba, 0 = punta), `depth`, `segments` |
| `torus` | `majorRadius`, `minorRadius`, `segments`, `minorSegments` |
| `circle` | `radius`, `segments`, `fill` |
| `monkey` | — |
| `superellipsoid` | `size: [x, y, z]` total, `roundness`: número o `[lados, arriba-abajo]`, 0 = caja, 1 = elipsoide, >1 puntiaguda. Cabezas y cuerpos de vinilo, cojines, piedras, jabones |
| `tube` | `points: [[x,y,z]…]` o `curve: [p0, p1, p2(, p3)]` (Bézier, `steps` tramos); `radii`: `[inicio, fin]` o un radio por punto (o `radius`); `flat` < 1 lo aplana (cintas, bufandas, hojas); `twist`°; `cap`; `segments`. Colas, cuernos, mechones, asas, cables, tentáculos, ribetes. Puntos en coordenadas del mundo con `location` en 0 |
| `lathe` | `profile: [[radio, z]…]` de abajo arriba, girado alrededor de Z (radio 0 cierra en punta); `segments`. Jarrones, botellas, faroles, troncos, peones, lámparas. O `image`: el objeto visto de lado, del que se mide el perfil (ver [references/siluetas-y-torno.md](references/siluetas-y-torno.md)) |
| `views` | Cuerpo desde dos vistas: `front` (imagen de frente, X a la derecha) y `side` (vista derecha, Y a la derecha), `height` (alto de la silueta entera, en metros), `roundness` (2 = sección elíptica; más = más cuadrada) o `top` (imagen de la vista de arriba para la forma de la sección), `thin` (10), `segments`, `rings`, `exclude` (colores que no son de la figura: una base), `paint` (pinta cada cara con el color de las vistas), `color` + `pickFront`/`pickSide` (el volumen de una región de color: una bota). Regaderas, ratones, zapatos, autos de juguete, cuerpos de pájaro. Ver [references/dos-vistas.md](references/dos-vistas.md) |
| `stroke` | Tubos desde las partes finas de una imagen (asas, picos, alambres, antenas, ramas, patas, brazos, orejas): `image`, `view` (front/side), `height`, `pick` [índices], `color`, la otra vista (`side` si view es front, `front` si es side: de ahí salen su profundidad y su grosor de canto) o `flat` (aplana de canto), `near` [[x, z], …] (elige por posición), `blobs: true` (las partes redondas como esferas), `segments`. Ver [references/dos-vistas.md](references/dos-vistas.md) |
| `blobby` | `balls: [[x,y,z,radio]…]` o `[{"at": [x,y,z], "radius": r, "size": [sx,sy,sz]}]`: bolas que se funden en una sola malla suave (cuerpos orgánicos, panzas, patas, nubes); `resolution` (0.02), `threshold` (0.6). Si dos bolas no se tocan, quedan separadas: agrega bolas intermedias |
| `membrane` | Alas de murciélago o dragón, aletas, velas, abanicos: `root` (donde nace), `tip` (punta del hueso principal), `fingers` (puntas del borde, en orden), `scallop` (festón entre puntas, 0.18; 0 = recto), `bend` (curva hacia atrás como vela), `bones` (radio de los huesos; 0 = sin huesos), `thickness`. En coordenadas del mundo con `location` en 0; para el par, `modifiers: [{"type": "mirror", "axis": "X"}]` |
| `outline` | Silueta de una imagen (`image`: figura sobre fondo liso o PNG con transparencia; `threshold` 0-1 si el fondo no se separa solo) o de puntos (`points: [[x, y]…]` en metros y `holes: [[[x, y]…]…]`), extruida `thickness` (0.02; 0 = solo la cara). `width` o `height` en metros; `tolerance` % de la diagonal (0.25); `method` auto/fourier/polygon; `plane` XZ (de pie, de frente a -Y) o XY (en el piso); `output: "curve"` da una curva editable en vez de malla; `color` toma una parte por su color, `pick` elige regiones, `inView` la deja en su lugar de la vista. Ver [references/siluetas-y-torno.md](references/siluetas-y-torno.md) |
| `decal` | `size`: número o `[ancho, alto]`. Pintura plana (ojos, mejillas, manchas, logos, parches) que se pega con `attach` a la superficie y sigue su curvatura |
| `mesh` | `vertices: [[x,y,z]…]`, `faces: [[i,j,k,…]…]`, `edges` (formas a medida que no salen de lo anterior). Las caras se orientan solas hacia afuera. Con vértices en coordenadas del mundo, pon `location: [0,0,0]` |
| `text` | `text`, `size`, `extrude`, `bevelDepth`, `align` (left/center/right), `alignY` |
| `light` | `light`: point/sun/spot/area, `energy` (W; sol: intensidad ~3-5), `color`, `size`, `spotSize`° , `spotBlend` |
| `camera` | `lens` (mm), `ortho` + `orthoScale`, `focus` (objeto o distancia) + `fstop`, `active` (por defecto sí) |
| `empty` | `display` (plain_axes, arrows, cube…), `size` |

Una clave que el código no usa (un error de tipeo como `excludeTolerence`) da un aviso con la más
parecida («¿excludeTolerance?»): no la ignores, corrígela.

Comunes a todos: `location` [m], `rotation` [grados XYZ], `scale`, `dimensions` (fuerza el tamaño final),
`origin: "bottom"` (el origen en la base: así `location` z=0 lo apoya en el piso), `material` o
`materials` + `faceMaterials` (índice por cara), `collection`, `parent` (la `location` que das es la del
mundo), `smooth`, `hidden`, `hideRender`, `display` (wire, solid…), `lookAt` (objeto o `[x,y,z]`;
con `track: true` lo sigue siempre), `cutter: true` (pieza para restar: alámbrica y fuera del render).

### Revisar el armado (`check`)
`blender-cli check [-Objects a,b] [-Tolerance 0.004]` revisa las mallas visibles en el render (con sus
modificadores) y devuelve:
- `floating`: piezas que no tocan nada (garras despegadas, ojos sueltos). Casi siempre es un error.
- `buried`: piezas con al menos 90 % de su superficie dentro de otra; no se ven (una correa metida en
  el abrigo). Se mide por área, así que una garra con la base hundida en la mano no cuenta como enterrada.
  Algunas son a propósito (una llama dentro de un farol de vidrio).
- `intersecting`: pares que se cruzan, con qué fracción de cada uno queda dentro del otro. Muchas son
  uniones a propósito (orejas en la cabeza, manos en las mangas); fíjate en las que deberían ir **por
  fuera** (un bastón que atraviesa el abrigo, una mano que entra en la cara) y en fracciones altas.
Las calcomanías se ignoran en los cruces. Ejecútalo después de cada `build` grande y antes del render final.

### Colocar sobre superficies (`attach`, `onSurface`)
No calcules a ojo dónde queda la superficie de una pieza curva: deja que blender-cli la encuentre.
- **`attach`** apoya un objeto en la superficie de otro (con sus modificadores ya aplicados):
  `"attach": { "to": "Cabeza", "side": "front", "at": [0.1, 0, 0.6], "offset": 0.001, "align": true, "spin": 0 }`.
  Con `wrap: true` además la curva sobre la superficie (un modificador que la sigue pegando); con
  `wrap: "bake"` la curva una vez y la deja así, sin modificadores, para **animarla**: un ala curvada al
  cuerpo que aletea desde un `empty` en el hombro (con `wrap: true` el modificador la volvería a pegar
  al cuerpo en cada cuadro). Toma la pose del cuadro actual.
  Lanza un rayo desde `side` (`front`, `back`, `left`, `right`, `top`, `bottom` o un vector) que pasa por
  `at` (punto aproximado; solo cuentan las dos coordenadas perpendiculares a `side`) y pone el objeto en el
  punto de contacto, separado `offset` y, con `align`, con su eje Z según la normal. Para ojos, botones,
  remaches, emblemas, cuernos que salen de la piel.
- **Piezas que sobresalen** (garras, cuernos, púas, botones, orejas): `"anchor": "base"` apoya la base de
  la pieza (su punto más bajo en Z local; en un `cone`, la base ancha) sobre la superficie, así sale
  entera hacia afuera. `offset` negativo la hunde un poco para que no se vea la junta (-0.003 a -0.005).
- **Calcomanías apiladas**: `decal` + `attach`, con un `offset` mayor en cada capa (ojo 0.001, pupila
  0.002, brillo 0.003) para que no parpadeen. Se proyectan por su propio eje y conservan la forma.
- **`onSurface`** en un `tube` dibuja la línea sobre la superficie: `"onSurface": { "to": "Cabeza", "side":
  "front", "offset": 0.003 }` proyecta cada punto de `points`/`curve` (solo cuentan las coordenadas
  perpendiculares a `side`). Bocas, cejas, líneas de expresión, costuras, ribetes de ropa.

Ejemplo de personaje con todo esto: `examples/pip-farolero.json` (cabeza superelipsoide, cuerpo `blobby`,
cola y bufanda `tube`, farol `lathe`, cara con `decal` + `attach` y boca con `onSurface`).

**Cámara automática**: `"frame": ["A", "B"]` (o `"all"`) la coloca para que esos objetos entren
enteros, desde `"view"`: `iso`, `front`, `back`, `right`, `left`, `top` o un vector `[x, y, z]`;
`margin` (1.1) deja aire alrededor. Úsala en vez de calcular posiciones de cámara a mano.

### Modificadores
`modifiers: [{ "type": ..., ...propiedades }]`, en orden. Las propiedades usan el nombre de Blender
en camelCase (`segments`, `width`, `levels`, `renderLevels`, `thickness`, `count`, `angleLimit`°...).
Atajos: `bevel` (`width`, `segments`), `subsurf`/`subdivision` (`levels`), `solidify` (`thickness`),
`array` (`count`, `offset` relativo `[x,y,z]` o `constantOffset` en metros), `mirror` (`axis`: "X", "XY"…,
`mirrorObject`), `boolean` (`object`, `operation`: difference/union/intersect), `weld`, `triangulate`,
`displace`, `wireframe`, `screw`, `simple_deform`, `shrinkwrap` (`target`, `wrapMethod`, `offset`).
Toda propiedad que apunta a un objeto acepta su nombre (`target`, `offsetObject`…). Si una propiedad no existe, sale en `warnings`.
**Pintura sobre una superficie curva** (ojos, logos, manchas): una esfera aplanada (`scale` con un eje
~0.002) con `shrinkwrap` → `target` la pieza, `wrapMethod: "nearest_surfacepoint"` y un `offset` algo
mayor en cada capa (0.0012, 0.0024…), así quedan pegadas y se apilan sin parpadeos.
Al repetir `build`, los modificadores que ya no estén en el spec se quitan (solo los que puso `build`).

### Materiales
Principled BSDF: `color`, `metallic`, `roughness`, `ior`, `alpha`, `transmission`, `emission` +
`emissionStrength`, `coat`, `sheen`, `subsurface`, `specular`, `texture` (imagen como color base; ruta
absoluta o relativa al spec). Colores en hex como en cualquier selector (`#rrggbb`); blender-cli los
convierte al espacio lineal de Blender. Un `metallic` de 0.8-1 sale casi negro si el mundo es oscuro y no
hay nada que reflejar (el dorado se ve marrón): usa 0.3-0.5 o un HDRI (`asset`). Una `emission` fuerte
aclara y lava el color base; para un objeto que brilla un poco, `emissionStrength` 0.2-0.4.

### Animación
`animation: [{ object, property, keys: [{frame, value}], interpolation }]`. `property`: `location`,
`rotation` (grados), `scale`, o un dato del objeto con `data.` (`data.energy` de una luz, `data.lens` de
una cámara). Al repetir `build` las claves de esa propiedad se reemplazan. Fija `scene.frames`.
Para oscilar, rebotar, colgar o seguir a otro objeto no inventes claves: usa `motion`
([references/movimiento.md](references/movimiento.md)).

### Actualizar lo que existe
Un objeto que ya existe se busca por `name` y solo cambia lo que pongas: `{ "name": "Tablero", "material": "Rojo" }`
le cambia el material sin tocar su forma. La malla se rehace solo si das parámetros de forma
distintos (`size`, `radius`...): **eso descarta las ediciones a mano** que el usuario hizo en esa malla;
avísale antes.

## Guías por técnica
Lee la que toque **antes** de usarla: cada una tiene sus parámetros, sus trampas y los ejemplos medidos.

| Para | Lee |
|---|---|
| Piezas planas desde una imagen o puntos (logos, placas, alas planas, ojos y calcos por color) y objetos de revolución desde una foto (`outline`, `lathe` con `image`) | [references/siluetas-y-torno.md](references/siluetas-y-torno.md) |
| Volumen desde una vista de frente y una de costado: cuerpos, partes finas, personajes y figuras de vinilo (`views`, `stroke`, `sheet`) | [references/dos-vistas.md](references/dos-vistas.md) |
| Ajustar proporciones solas contra la referencia cuando ya están las piezas (`blender-cli fit`) | [references/ajuste-fit.md](references/ajuste-fit.md) |
| Lo que oscila, rebota, cuelga o sigue a otro (`motion`) y ciclos de caminata (`blender-cli walk`) | [references/movimiento.md](references/movimiento.md) |
| Look low-poly / pixel art de 32 bits | [references/retro.md](references/retro.md) |
| Importar modelos, HDRI y texturas de Poly Haven, materiales con mapas | [references/recursos.md](references/recursos.md) |

## Cómo modelar bien con primitivas
- Piensa en piezas: cada parte reconocible (tablero, pata, asa) es un objeto con nombre en el idioma
  del usuario, agrupado en una colección por conjunto.
- Apoya las cosas: con `origin: "bottom"` la z de `location` es la altura del suelo o de la superficie.
  Calcula las alturas sumando (tablero en 0.75 → taza en 0.775).
- `bevel` pequeño (1-2 % del tamaño) en casi todo lo rígido: los bordes perfectos se ven falsos.
- Repetición → `array` o `mirror` en vez de copiar objetos. Huecos → `boolean` con un `cutter`.
- Formas orgánicas → `subsurf` sobre una malla simple; perfiles → `mesh` con vértices y caras.
- Luz de estudio: una `area` principal a 45°, una de relleno más débil al otro lado y el mundo oscuro;
  exteriores: `sun` + mundo azul claro o un HDRI.
- Escenas de más de ~40 objetos: varios `build` por colección.

## Lo que `build` no cubre
Para edición de malla avanzada, nodos de geometría, partículas, rigs, físicas o cualquier otra cosa
de `bpy`, escribe un script y ejecútalo con `blender-cli exec -Script script.py` (en vivo, o con
`-File` y `-Save`). El script tiene `bpy`, `bmesh`, `math`, `Vector` y `ops` (funciones de
blender-steroids, p. ej. `ops.frame_camera(cam, ["A"], "front")`); lo que dejes en la variable
`result` vuelve como JSON y lo que imprimas, en `stdout`. Usa `bpy.data` y `bmesh` en vez de
`bpy.ops` siempre que puedas: los operadores dependen del contexto de la ventana.

No le muestres comandos ni JSON al usuario salvo que lo pida.

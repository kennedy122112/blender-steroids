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
   con `mesh`: recorta su silueta de la referencia y constrúyelas con `outline` (abajo). Si tienes el
   objeto **de frente y de costado** (un plano, dos fotos, una hoja de vistas), el cuerpo sale de las dos
   con `views` y las asas, picos y alambres con `stroke` (abajo), sin medir nada a ojo.
4. **Compara de verdad**, no de memoria: `blender-cli compare -Reference ref.png -Path comparar.png
   [-View front]` renderiza con el formato de la referencia y pone las dos imágenes lado a lado con
   guías horizontales cada 10 % del alto. Léela y anota diferencias concretas («la cabeza llega a la
   guía 3 en la referencia y a la 4 en el render»). Usa la vista que coincida con la de la referencia.
5. **Lista de control** en cada vuelta: `blender-cli check` (abajo) para piezas flotando, enterradas
   o atravesadas; mira también `-View back` y `right`; proporciones, colores (AgX aclara; si un color se ve lavado, oscurécelo o usa
   `"look": "AgX - Punchy"`), legibilidad de la cara, nada tapado por la cámara.
6. **Cuando las piezas estén y solo falten proporciones, usa `fit`** (abajo) en vez de ajustar a mano.
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
| `lathe` | `profile: [[radio, z]…]` de abajo arriba, girado alrededor de Z (radio 0 cierra en punta); `segments`. Jarrones, botellas, faroles, troncos, peones, lámparas. O `image`: el objeto visto de lado, del que se mide el perfil (ver «Torno desde una foto») |
| `views` | Cuerpo desde dos vistas: `front` (imagen de frente, X a la derecha) y `side` (vista derecha, Y a la derecha), `height` (alto de la silueta entera, en metros), `roundness` (2 = sección elíptica; más = más cuadrada) o `top` (imagen de la vista de arriba para la forma de la sección), `thin` (10), `segments`, `rings`, `exclude` (colores que no son de la figura: una base), `paint` (pinta cada cara con el color de las vistas), `color` + `pickFront`/`pickSide` (el volumen de una región de color: una bota). Regaderas, ratones, zapatos, autos de juguete, cuerpos de pájaro. Ver «Volumen desde dos vistas» |
| `stroke` | Tubos desde las partes finas de una imagen (asas, picos, alambres, antenas, ramas, patas, brazos, orejas): `image`, `view` (front/side), `height`, `pick` [índices], `color`, la otra vista (`side` si view es front, `front` si es side: de ahí salen su profundidad y su grosor de canto) o `flat` (aplana de canto), `near` [[x, z], …] (elige por posición), `blobs: true` (las partes redondas como esferas), `segments`. Ver «Volumen desde dos vistas» |
| `blobby` | `balls: [[x,y,z,radio]…]` o `[{"at": [x,y,z], "radius": r, "size": [sx,sy,sz]}]`: bolas que se funden en una sola malla suave (cuerpos orgánicos, panzas, patas, nubes); `resolution` (0.02), `threshold` (0.6). Si dos bolas no se tocan, quedan separadas: agrega bolas intermedias |
| `membrane` | Alas de murciélago o dragón, aletas, velas, abanicos: `root` (donde nace), `tip` (punta del hueso principal), `fingers` (puntas del borde, en orden), `scallop` (festón entre puntas, 0.18; 0 = recto), `bend` (curva hacia atrás como vela), `bones` (radio de los huesos; 0 = sin huesos), `thickness`. En coordenadas del mundo con `location` en 0; para el par, `modifiers: [{"type": "mirror", "axis": "X"}]` |
| `outline` | Silueta de una imagen (`image`: figura sobre fondo liso o PNG con transparencia; `threshold` 0-1 si el fondo no se separa solo) o de puntos (`points: [[x, y]…]` en metros y `holes: [[[x, y]…]…]`), extruida `thickness` (0.02; 0 = solo la cara). `width` o `height` en metros; `tolerance` % de la diagonal (0.25); `method` auto/fourier/polygon; `plane` XZ (de pie, de frente a -Y) o XY (en el piso); `output: "curve"` da una curva editable en vez de malla; `color` toma una parte por su color, `pick` elige regiones, `inView` la deja en su lugar de la vista. Ver «Siluetas» |
| `decal` | `size`: número o `[ancho, alto]`. Pintura plana (ojos, mejillas, manchas, logos, parches) que se pega con `attach` a la superficie y sigue su curvatura |
| `mesh` | `vertices: [[x,y,z]…]`, `faces: [[i,j,k,…]…]`, `edges` (formas a medida que no salen de lo anterior). Las caras se orientan solas hacia afuera. Con vértices en coordenadas del mundo, pon `location: [0,0,0]` |
| `text` | `text`, `size`, `extrude`, `bevelDepth`, `align` (left/center/right), `alignY` |
| `light` | `light`: point/sun/spot/area, `energy` (W; sol: intensidad ~3-5), `color`, `size`, `spotSize`° , `spotBlend` |
| `camera` | `lens` (mm), `ortho` + `orthoScale`, `focus` (objeto o distancia) + `fstop`, `active` (por defecto sí) |
| `empty` | `display` (plain_axes, arrows, cube…), `size` |

Comunes a todos: `location` [m], `rotation` [grados XYZ], `scale`, `dimensions` (fuerza el tamaño final),
`origin: "bottom"` (el origen en la base: así `location` z=0 lo apoya en el piso), `material` o
`materials` + `faceMaterials` (índice por cara), `collection`, `parent` (la `location` que das es la del
mundo), `smooth`, `hidden`, `hideRender`, `display` (wire, solid…), `lookAt` (objeto o `[x,y,z]`;
con `track: true` lo sigue siempre), `cutter: true` (pieza para restar: alámbrica y fuera del render).

### Siluetas desde una imagen o puntos (`outline`)
Para piezas **planas o de grosor uniforme cuya forma está en su contorno**: logos y emblemas 3D,
letreros recortados, engranajes, llamas, rayos, placas, galletas y figuras de cortador, aletas, la
silueta de un personaje para una maqueta o un *standee*. Lee el contorno con precisión de subpíxel,
encuentra los huecos (una dona sale con su agujero) y simplifica cada contorno con el método que mejor
le va. **`method: "auto"`** decide por contorno: si la mayor parte del giro está en esquinas de más de
45°, lo deja como **polígono** con las esquinas reconstruidas (un rayo vuelve a sus 8 vértices); si es
una curva suave, usa una **serie de Fourier** (sin facetas). Fuerza `fourier` o `polygon` solo si
tienes motivo: Fourier ondula junto a las esquinas vivas (efecto Gibbs) y el polígono facetea las curvas.

El resultado de `build` trae `outlines` con lo medido por contorno: `method`, `order` o `vertices`,
`hausdorffPercent` (desviación máxima del borde, en % de la diagonal), `normalizedMaxErrorPercent`
(Fourier) y `targetMet`. Si un contorno no llegó a la tolerancia hay un aviso: dilo, no lo des por bueno.

- **La imagen**: una sola figura, recortada, sobre un fondo liso (o PNG transparente). Una foto con
  luces y brillos sirve (el borde se mide contra el contraste local), pero no una con fondo cargado.
- **Antes de construir, mira qué entiende**: `blender-cli contour -Image silueta.png -Preview vista.png`
  no toca la escena; dice regiones, huecos, método y error de cada contorno y dibuja el resultado sobre
  la imagen (cian = Fourier, magenta = polígono con sus vértices en amarillo). Con `-Lathe [-Side left]`
  muestra el eje y el perfil de torno. Úsalo para elegir `tolerance`, `method` o `threshold`.
- **Malla o curva**: por defecto es una malla. Con `output: "curve"` es una curva 2D de Blender,
  rellena y con grosor (`thickness`), que se edita moviendo puntos de control: los contornos suaves son
  Bézier con pocos puntos (un círculo, 4; la llama del ejemplo, 52 para 89 coeficientes) y los
  angulosos, polilíneas. Calza igual que la malla (IoU 0.988 las dos). Con `plane` XZ el objeto queda
  girado 90° en X para estar de pie; si das `rotation`, súmale ese giro. Cambiar `output` en un objeto
  que ya existe lo reemplaza (malla ↔ curva) conservando nombre, colección, padre e hijos, materiales,
  modificadores que admita el tipo nuevo, animación y propiedades; el resultado lo lista en `replaced`.
- **Trazabilidad**: cada objeto hecho con `outline` o `lathe` + `image` guarda en la propiedad
  `bs_source` con qué se hizo (parámetros, ruta y sha1 de la imagen, versión) y qué salió (método,
  error y coeficientes de Fourier de cada contorno; el perfil del torno). Léela con `scene -Object`
  o `exec` para explicar o rehacer una pieza.
- **Tamaño**: `height` o `width` del conjunto en metros; con `origin: "bottom"` queda apoyada en el piso.
- `tolerance` 0.25 % va bien a 1024 px; con imágenes chicas (< 400 px) usa 0.5 (el antialias redondea
  las esquinas ~1 px).
- Bordes suaves: agrega un modificador `bevel` (`width` 0.005-0.01, `segments` 2).
- **No es para** volúmenes: una sola silueta no da profundidad. Un objeto redondo se hace con `lathe`;
  uno que no es plano ni redondo, con `views` (dos vistas); un personaje, con las primitivas.
  `outline` sirve para sus partes planas.
- Para comparar una pieza con huecos contra su imagen usa `compare -Holes keep`.
- **Una parte de un color** (la estrella amarilla pintada en un farol rojo, un logo sobre una remera):
  `color: "#rrggbb"` toma lo que es de ese color en vez de separar la figura del fondo, con borde
  subpíxel; `colorTolerance` (0.15) si el tono varía. Pide el hex al mirar la imagen o a `contour`.
  Para pegarla a una superficie curva: plane XY + `attach` con `align` y `wrap` (funciona aunque la
  pieza cuelgue de un padre animado). Lo que se aparta del fondo nunca cuenta como ese color, aunque el
  fondo quede dentro de la tolerancia (una panza crema sobre un fondo gris claro).
- **Varias partes del mismo color** (un ala y la cola, los dos ojos): `pick: [i]` elige regiones, de la
  de más área a la de menos (sin `pick`, todas en una pieza: los dos ojos juntos).
- **En su lugar de la vista** (`inView: true`, con `height` = alto de la silueta entera, como `views` y
  `stroke`): la pieza sale a la escala de la vista y queda donde está en el dibujo (su centro, sumado a
  `location`; `view: "side"` si la imagen es la vista derecha). `outlines` trae ese centro en `at`. Con
  `attach` (y sin `at`) se pega en ese lugar del cuerpo: un ala desde el perfil con `side: "front"`, los
  ojos o la panza desde la vista de frente con `side: "right"`. Sin `attach` y con `view: "side"`, queda
  de pie en el plano de esa vista (YZ): la hoja en la punta de una cola dibujada de perfil.
- **Detalles pintados en una vista** (ojos con su brillo, mejillas, una boca): `attach` con
  `project: "view"` los pega como un calco, a lo largo de la vista; así los de distintas piezas coinciden
  como en el dibujo (el brillo cae en su hueco del ojo). Sin eso cada pieza se gira hacia la normal de
  su centro, que es lo mejor para piezas grandes que dan la vuelta al cuerpo (un ala). Un brillo que se
  parece al fondo cuenta igual si la figura lo encierra, y por color se aceptan detalles chicos.
- **Pegadas con `wrap`** se subdividen solas lo necesario para seguir la curva sin que el cuerpo las
  atraviese (según su arista más larga y el tamaño del cuerpo) y toman las normales del cuerpo: se ven
  como pintadas sobre él, sin franjas.

### Torno desde una foto (`lathe` con `image`)
Para objetos **de revolución** (jarrones, botellas, vasos, faroles, peones, columnas, lámparas): en vez
de escribir el `profile` a ojo, pásale la foto de lado y se mide. Usa `height` (o `width`) en metros. El
eje es la vertical que mejor centra la silueta. Con `side: "both"` (por defecto) promedia las dos
mitades; si de un lado hay un asa, un pico o una etiqueta que sobresale, usa `side: "left"` o
`"right"` (la mitad limpia) y agrega el asa aparte con `stroke` desde la misma foto (ver «Volumen
desde dos vistas»).

El resultado de `build` trae en `outlines` el `profile` medido (puedes copiarlo al spec y retocarlo),
`keyPoints`, `maxErrorPercent`, `targetMet` y `asymmetryPercent`. Si la asimetría pasa del 3 % con
`side: "both"` hay un aviso: o hay algo de un solo lado, o la foto no está de lado.

- **La foto**: de lado y a la altura del objeto, lo más lejos y con el zoom más largo posible (un gran
  angular muestra la boca desde arriba y deforma el perfil), sobre un fondo liso. Luces y brillos no
  molestan: el borde se mide contra el contraste local.
- El perfil sale suave entre esquinas (64 puntos, `profileRings`) y con las esquinas exactas (el borde
  de la boca, la base). Probado con un jarrón con asa fotografiado: radio a 0.77 mm del real en 40 cm.
- Es una superficie sin grosor (como `lathe`); para paredes, `modifiers: [{"type": "solidify"}]`.
- **Objetos de varios colores** (un farol con tapas doradas y papel rojo, una botella con tapa y
  etiqueta): `blender-cli contour -Image foto.png -Lathe` devuelve `bands`, las franjas de color a lo
  largo del alto (`from`/`to` en fracción del alto desde abajo, `color` medido, `maxRadius`), y la vista
  previa las marca en verde. Haz un `lathe` por franja con la misma imagen, `height` y `location` y
  `range: [from, to]`: cada pieza sale con la misma escala y el mismo eje, encaja con las vecinas y
  lleva su material con el color de la franja. El error y la asimetría se miden por franja.
  `examples/farol.json` lo hace con 6 franjas, una estrella por color, péndulo y llama.

### Volumen desde dos vistas (`views`) y partes finas (`stroke`)
Para lo que **no es plano ni de revolución** y se puede dibujar o fotografiar de frente y de costado:
una regadera, una tetera, un ratón de computadora, un zapato, un auto de juguete, el cuerpo de un
pájaro o un pez. `views` separa en cada imagen el cuerpo de sus partes finas y, en cada altura, toma
dónde empieza y termina el cuerpo de frente (X) y de costado (Y): la sección es una elipse inscrita en
ese rectángulo (`roundness` 2; 3-4 para cajas redondeadas) o la forma de la vista de arriba (`top`).
Así calza con las dos siluetas: un cuello que no está en el centro (la boca de una regadera) sale
en su lugar, porque el centro de cada altura también se mide.

Las **partes finas** (lo que mide menos de `thin` % del alto de ancho: asas, picos, alambres, antenas,
ramas, patas) no entran en el cuerpo: se hacen con `stroke` desde la imagen donde se ven a lo largo.
`stroke` mide el eje de cada una y su ancho en cada punto, sigue sus curvas, y si toca el cuerpo el
tubo se mete en él, sin huecos.

1. **Mira qué entiende**: `blender-cli contour -Image frente.png -Strokes -Height 0.3 -Preview v.png`
   dibuja el cuerpo en cian y cada trazo con su color, y lista los trazos del más largo al más corto
   (`index`, `length`, `radius`, `attached`, `iou`, y la posición y dirección de cada punta).
2. **Construye** con la misma imagen, el mismo `height` y la misma `location` en las dos piezas, así
   encajan: `{"type": "views", "front": "frente.png", "side": "lado.png", "height": 0.3}` y un
   `{"type": "stroke", "image": "frente.png", "height": 0.3, "pick": [0]}` por parte fina.
3. **Compara con cámara ortográfica**: `compare -Reference frente.png -View front -Reference lado.png
   -View right -Ortho -Objects Cuerpo,Asa,Pico` (las vistas dibujadas no tienen perspectiva; con
   `-Objects` el piso y el resto no cuentan). La regadera del ejemplo da 0.992 de frente y 0.982 de costado.

- **Las imágenes**: una vista cada una, de frente y de costado exactos (sin perspectiva: un plano, un
  dibujo o una foto con zoom largo), con el objeto entero. Las dos deben mostrar el mismo alto total:
  si en una falta una parte de arriba (el asa), `viewsMismatchPercent` lo avisa.
- **De canto y de costado: pásale la otra vista.** Un trazo medido en una vista queda en su plano y
  redondo. Con la otra imagen (`"side": "lado.png"` en un trazo de frente, `"front"` en uno de costado)
  cada trazo busca la parte que ocupa las mismas alturas en la otra vista y toma de ella su posición (una
  oreja que se inclina hacia atrás, una pata que va hacia adelante) y su grosor (una oreja plana); el
  resultado lo marca con `depthFrom`. Si no hay una (un brazo que de costado queda delante del cuerpo),
  queda como estaba: ponlo en su lugar con `location`. Sin la otra imagen, `flat` = ancho de canto /
  ancho, medido con `contour -Strokes` en la otra vista: aplanar a ojo un asa bajó el IoU de 0.98 a 0.92.
- **Partes de otro color o que no son tubos** (la flor de una regadera, un tapón, una boquilla): toma
  solo el tubo con `color` y pon la pieza en la punta con `end`/`start` y su dirección
  (`endDirection`): un `lathe` o un cilindro girado para mirar en esa dirección.
- El resultado trae en `outlines` el `size` del cuerpo, `maxErrorPercent` y `targetMet`, y cada trazo
  con su IoU (aviso si < 0.85). `bs_source` guarda las imágenes con su sha1 y, en `stroke`, los puntos y
  radios de cada trazo. `examples/regadera.json` lo hace con cuerpo, asa, pico y flor.
- **Partes que se ramifican** (patas sobre una rama, una rama con ramitas, una antena en Y): un trazo por
  rama. Primero el más largo; cada rama que sale de él trae `parent` (su índice) y se mete en su tubo.
  Las patas de frente, que se juntan sobre una rama vista de punta, se separan mejor por `color`.
- **Elige por posición con `near`** cuando hay partes de casi el mismo largo (un par de brazos, brazos y
  patas, un pico y una pata): `"near": [x, z]` (o una lista de puntos) toma, para cada punto, el trazo
  que pasa más cerca, en el marco de la vista (como `start`/`end`: la mano, el pie, la punta de la
  oreja). `pick` va por largo, y entre partes casi iguales el orden cambia con cualquier detalle (en Lumo,
  0.0784 contra 0.0778). `color` también sirve si la parte lo tiene.
- **Partes redondas pegadas al cuerpo** (una cola de pompón, un botón, una nariz de bola): no son trazos;
  `contour -Strokes` las lista en `blobs` (centro y radio del círculo que sigue su borde libre, aunque
  tengan una astilla pegada) y las dibuja en blanco. `{"type": "stroke", "blobs": true, ...}` las hace
  esferas en su lugar de la vista (con `pick` si hay varias).
- **Patas cortas bajo un cuerpo redondo**: la unión se corta siguiendo la curva del cuerpo (no la
  recta entre las esquinas, que se llevaba una cuña de la panza). Si las patas casi no asoman y están
  juntas o pegadas al borde del cuerpo, la parte visible no dice hacia dónde van: sepáralas un poco en
  el dibujo o ponlas a mano.
- **Partes casi horizontales** (un brazo estirado hacia adelante): con la otra vista se emparejan por la
  fracción del largo desde donde se pegan al cuerpo, no por la altura (un poco de diferencia de altura
  entre las vistas las acortaba). Para emparejarse, las dos vistas deben mostrar la parte pegada y
  terminando a alturas parecidas.
- **Brazos, patas y orejas cortos y gruesos** (un personaje): salen por su eje principal, con la punta
  redonda (la mano, el pie) y sin dar la vuelta en ella. Que su ancho quede bajo `thin` (12-15 si son
  gruesos). Una parte fina y chica (una oreja vista de canto) también se separa del cuerpo.
- **Fondo con degradado y partes claras**: el fondo se mide por fila (un estudio, una ilustración), y una
  parte clara junto a una oscura (una panza crema) cuenta entera aunque se parezca al fondo.
- **Una figura completa** (`examples/pajaro.json`, un pájaro sobre una rama): cuerpo y cabeza con `views`;
  rama, cola, pico y pata con `stroke` desde el perfil; las dos patas con `stroke` + `color` desde el
  frente; ala, panza y ojos con `outline` + `color` + `inView` + `attach`; alas con `wrap: "bake"` que
  aletean desde un `empty` por hombro (`motion` oscillate) y cola desde otro en su raíz. Calza 0.988 de
  perfil y 0.983 de frente. Si una vista muestra una pieza aparte pegada al borde (alas plegadas vistas
  de frente), el cuerpo la incluye y queda un poco más ancho a esa altura.
- **Un personaje** (`examples/lumo.json`, una criatura bípeda original): cabeza y torso con `views`;
  orejas (por `color`), brazos y patas con `stroke` desde el frente y `side` para su profundidad; cola
  con `stroke` desde el costado y su hoja con `outline` `inView` de costado; cara, brillos y mejillas por
  color con `project: "view"`, y la panza. Los brazos saludan desde un `empty` por hombro y la cola se
  mueve desde su raíz. Calza 0.976 de frente y 0.981 de costado.
- **Una base u otra pieza de otro color pegada a la figura** (la base redonda de una figura de vinilo, unas
  alas plegadas al costado): `exclude: ["#rrggbb"]` (con `excludeTolerance`, 0.1; bájala si un color
  vecino es parecido, como unas botas negras sobre una base gris oscura) la saca de la figura en
  `views`, `stroke` y `outline` con `inView`. El marco no cambia: `height` sigue siendo el alto de la
  silueta entera, así todas las piezas encajan. La base misma: `views` con su `color` (y `pickFront`/
  `pickSide`), no un `lathe` desde una sola imagen: el torno queda centrado en esa vista, y si de costado
  el cuerpo no está en el centro del dibujo (un hocico corre la cabeza hacia adelante) la figura queda
  corrida sobre su base (en un dragoncito, de 0.904 a 0.961 de costado al cambiarla).
- **Varios colores en un cuerpo** (pelo, piel y ropa en la cabeza y el torso de una figura): `paint:
  {"#rrggbb": "Material", ...}` pinta cada cara con el material del color más cercano de la vista que
  la mira (las de adelante, del frente; costados, atrás y arriba, del costado: el pelo cubre la nuca y
  deja la cara). El borde entre colores se subdivide (`paintRefine`, 2) para que no salga en escalera, y
  con `paint` el cuerpo tiene más caras por defecto. Un detalle de otro color (los ojos, unos botones)
  toma el color de alrededor: hazlo aparte con `outline` + `attach`. Lo que en una vista tapa al cuerpo
  (una mano delante del costado) píntalo en el dibujo con un tono de sombra, y no pongas ese tono en
  `paint`: así se salta; si está en la paleta (o es el color de la piel), pinta ese costado.
- **Una pieza de un color con volumen** (una bota, un gorro, la base): `views` con `color` y `pickFront`/
  `pickSide` (la región de ese color en cada vista, de mayor a menor área) sale entera y en su lugar.
- **Piezas planas por color** (unas alas abiertas detrás del cuerpo): elige las regiones con `pick` (las
  más grandes primero); el antialias de otros bordes deja puntitos sueltos de un color parecido.
- **Partes juntas** (dos piernas a pocos mm): cada unión se corta sola, y una parte casi cuadrada (una
  pierna corta entre el cuerpo y una bota) va de donde se pega hacia su centro.
- **Una figura de vinilo sobre su base** (`examples/nico.json`, un personaje original): cabeza y torso con
  `views` pintado (pelo, piel, impermeable), mangas y piernas con `stroke` por color, manos con `blobs`,
  botas con `views` por color, la base con `lathe` y `exclude`, ojos y botones como calco. Calza 0.984 de
  frente y 0.972 de costado.
- **Una figura de vinilo** (`examples/menta.json`, una criatura original de cabeza grande, en pose): una
  oreja de pie y otra caída (con su interior rosado pegado a cada oreja), un brazo que saluda y otro
  estirado hacia adelante, patas cortas y una cola de pompón (`blobs`). Calza 0.980 de frente y 0.958 de
  costado. De una sola foto o un render de 3/4 no se puede medir: dibuja antes las dos vistas.
- **No es para** formas con huecos que atraviesan el cuerpo de lado a lado, ni para personajes con poses
  que no se leen en dos vistas (brazos cruzados delante del cuerpo, piernas dobladas): ahí, primitivas.

### Ajuste automático de proporciones (`fit`)
Cuando el boceto ya tiene las piezas correctas pero las proporciones no terminan de coincidir, no
ajustes número por número: `blender-cli fit -Reference ref.png -Parts partes.json -FitView [-Budget 600]`
mueve y escala las piezas que indiques (cientos de renders rápidos de silueta) hasta que la silueta del
render se parezca lo más posible a la de la referencia, alternando la búsqueda del ángulo de cámara y la
de proporciones. Tarda 15-40 s.
- `partes.json`: `[{"name": "Cuerpo"}, {"name": "AlaI", "mirror": "AlaD"}, {"name": "Sombrero",
  "params": "sx sz z", "maxScale": 1.4, "maxMove": 0.1}]`. Por defecto ajusta `sx sy sz x y z`;
  `mirror` mueve la pareja en espejo. Pon solo las piezas grandes que hacen la silueta, con su origen
  en su centro (primitivas con `location`), no tubos ni membranas en coordenadas del mundo.
- Devuelve `iouStart` → `iouEnd` y `parts` (location y scale de cada pieza). Guarda la salida en un
  archivo y reconstruye con `blender-cli build -Spec escena.json -Patch salida-de-fit.json`: así el spec
  conserva el resultado y las calcomanías y piezas con `attach` se recolocan sobre las nuevas superficies.
- **Verifica siempre** con `compare` aparte (a resolución completa), no te quedes con el número interno.
- **Varias vistas**: repite `-Reference` y `-View` en orden (`-Reference tres-cuartos.png -Reference
  perfil.png -View fit -View right`; `fit` busca esa vista). `fit` maximiza el promedio. Con una sola
  vista oblicua el IoU puede pasar de 0.90 con las piezas grandes un 20 % más anchas o hondas de lo real
  (ancho y profundidad se confunden); con tres cuartos + perfil, en la prueba a ciegas, el error del
  cuerpo bajó de 21 % a 3 % y el de la cabeza de 11 % a 6 %. **Pide al usuario una segunda vista**
  (frente o perfil) cuando las medidas importen; si no la hay, díselo al entregar.
- **Piezas chicas: `-Colors`.** Lo que casi no cambia la silueta (alas pegadas al cuerpo, penachos,
  patas, piezas delante de otra) no se recupera con la silueta sola: en la prueba quedaron con 28-34 %
  de error. Con `-Colors`, `fit` asigna cada píxel de la referencia al material más parecido (sin
  depender de la luz) y puntúa también cuánto coincide cada región de color; `-ColorWeight` (0.3) es
  su peso frente a la silueta. En la prueba a ciegas el error medio de las piezas bajó de 18 % a 11 %
  (penachos 34 % → 5 %, sombrero 10 % → 4 %), a cambio de bajar algo la silueta (tres cuartos 0.91 →
  0.875). Es un compromiso: si importa la silueta exacta, sin `-Colors`; si importan las piezas, con él.
  Funciona mejor cuando los materiales tienen colores bien distintos: dos marrones parecidos (cuerpo y
  ala) se confunden, y los materiales con emisión fuerte pueden no reconocerse. Usa en el spec colores
  parecidos a los de la referencia para que la asignación sea buena.
  `-Detail 320` (más resolución interna) no arregla las piezas chicas.
- No inventa piezas: ajusta las que hay. Si falta una forma de la referencia, agrégala antes.

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

### Estilo retro de 32 bits (low-poly y pixel art)
Para el look de los juegos 3D de consolas de 32 bits:
- **Geometría**: pocas caras y sombreado plano: `"smooth": false`, `segments` 4-8 en cilindros y tubos,
  `ico_sphere` con `subdivisions: 1`, sin `subsurf` ni biseles redondeados.
- **Texturas pixeladas en el spec**: un material con `pixels` dibuja la imagen carácter a carácter y la
  muestra sin suavizar:
  `{"name": "Cara", "emissionStrength": 1.5, "pixels": {"rows": ["........", ".GG..GG.", "..GGGG.."],
  "palette": {".": "#08110b", "G": "#5dff7a"}, "plane": [0.3, 0.19], "axes": "XZ"}}`.
  `plane` es el tamaño (m) del área que cubre la imagen sobre la pieza (centrada en su origen), `axes`
  "XZ" para un frente y "XY" para un piso; `"repeat": true` repite (baldosas). Imágenes chicas (8-32
  píxeles de lado) y paletas cortas. Pon la textura en una pieza fina pegada a la cara (pantalla, panel).
- **Render**: `blender-cli render -Path x.png -Retro` (ver `blender-render`) y `viewTransform: "Standard"`
  para que los colores de la paleta salgan tal cual.

### Animación
`animation: [{ object, property, keys: [{frame, value}], interpolation }]`. `property`: `location`,
`rotation` (grados), `scale`, o un dato del objeto con `data.` (`data.energy` de una luz, `data.lens` de
una cámara). Al repetir `build` las claves de esa propiedad se reemplazan. Fija `scene.frames`.

### Movimiento con ecuaciones (`motion`)
Para todo lo que oscila, rebota, cuelga o se bambolea, **no inventes claves**: en una entrada de
`animation` pon `motion` en vez de `keys`, con `property` (`location`, `rotation` en grados, `scale` o
`data.x`), `axis` (x/y/z) y `frames` (por defecto los de la escena). Se calcula un valor por fotograma y
se hornea como claves lineales en ese único canal, **sumado a su valor de reposo** (el que tenía la
primera vez; repetir `build` no lo corre ni duplica claves). Los otros ejes y animaciones no se tocan.

| kind | Para qué | Parámetros |
|---|---|---|
| `oscillate` | Cinemático: alas, ventiladores, respirar, flotar, una señal que parpadea | `frequency` (Hz), `amplitude`, `phase` (grados), `offset` |
| `noise` | Cinemático: variación suave y sin patrón (una llama, un motor, viento, un temblor) | `frequency` (Hz, sus componentes van de f/2 a 2f), `amplitude` (el máximo exacto), `seed` (otra semilla, otro ruido; la misma, el mismo), `offset` |
| `spring` | Simulado: rebota y se asienta (un golpe, una caída, un *squash*) | `frequency` + `dampingRatio` (0 sin pérdida, 1 crítico), o `mass` + `stiffness` + `damping`; `initial`, `velocity`, `force` |
| `pendulum` | Simulado: péndulo real, también con ángulos grandes | `length` (m), `initial` (grados), `velocity`, `damping`, `gravity` (9.81) |
| `follow` | Simulado: movimiento secundario (antenas, orejas, colas, cables) que sigue a otro objeto con retraso y rebote | `leader` (objeto), `leaderAxis` (eje de su aceleración en el mundo), `frequency`, `dampingRatio` (0.3), `gain` (grados o m que se inclina por cada m/s² del guía) |

- **Varios movimientos en un canal**: `motion` también acepta una lista y los suma (una llama:
  dos `noise` de frecuencias distintas; un balanceo con temblor: `pendulum` + `noise`).
- **Pivote**: la rotación es alrededor del origen del objeto. Para un ala, una antena o un péndulo crea
  un `empty` en la bisagra, emparenta la pieza (`parent`) y anima el empty (así lo hace
  `examples/libelula.json`).
- **Aliasing**: los fps tienen que alcanzar para la frecuencia. Con 2 fotogramas o menos por ciclo,
  build da error (se vería quieto o al revés); con menos de 8, aviso de que se verá entrecortado. Un
  aleteo real de 30 Hz no se puede mostrar a 24 fps: baja la frecuencia o sube `scene.fps`.
- El resultado de build trae `motions` (canal, `mode` kinematic u ode_simulated, fotogramas, máximo) y
  cada objeto guarda en `bs_motion` el modelo y sus parámetros. Dile al usuario si es cinemático
  (una fórmula) o simulado (una ecuación integrada): **no es física de choques ni de aerodinámica**.
- `follow` con `walk`: después de `walk`, crea la bisagra de la antena con `parent: "bs_walk_cabeza"`,
  cuelga la antena de ella y usa `leader: "bs_walk_cabeza"`, `leaderAxis: "z"` (el rebote del paso).
- Se exporta: el GLB lleva un canal de animación por cada motion (verificado).
- El paso de integración se achica solo si el sistema oscila rápido (estable aunque sea muy rígido) y
  hay un tope de cálculo: si una simulación lo pasa, build lo dice en vez de quedarse colgado.
  `motions` trae `elapsedMs`, `step` y `substeps`.

### Actualizar lo que existe
Un objeto que ya existe se busca por `name` y solo cambia lo que pongas: `{ "name": "Tablero", "material": "Rojo" }`
le cambia el material sin tocar su forma. La malla se rehace solo si das parámetros de forma
distintos (`size`, `radius`...): **eso descarta las ediciones a mano** que el usuario hizo en esa malla;
avísale antes.

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

## Partir de modelos y recursos ya hechos
No todo hay que modelarlo: para objetos realistas (muebles, plantas, utensilios) o cuando la referencia
es esculpida, parte de un modelo y vístelo, ilumínalo y renderízalo con blender-steroids.
- **Importar un modelo** del usuario o descargado: `blender-cli import -Path modelo.glb [-Name Sillon]
  [-Height 0.85] [-Location x,y,z] [-Rotation 0,0,25]` (glb, gltf, fbx, obj, stl, ply, usd). Agrupa sus
  piezas bajo un vacío con ese nombre (en su colección), con el origen en el centro de la base: `-Height`
  lo escala a esa altura real y `-Location` lo apoya ahí. Después se mueve, se le cambian materiales o
  se le ponen cosas encima con `build`/`attach` como a cualquier pieza.
- **Recursos libres de Poly Haven** (CC0: se pueden usar en cualquier proyecto, también comercial, sin
  pedir permiso). Requiere internet; lo descargado queda en una caché local y no se vuelve a bajar.
  - Buscar: `blender-cli asset search -Type hdri|texture|model -Query "wood floor" [-Limit 10]`
    (ordena por descargas; muestra `id`, nombre, categorías y etiquetas).
  - HDRI (luz y fondo realistas): `blender-cli asset get -Type hdri -Id brown_photostudio_02 -Apply`.
  - Textura: `blender-cli asset get -Type texture -Id laminate_floor_02 -Apply -Material Piso` crea el
    material con sus mapas (color, normal, rugosidad, ao); asígnalo con `build`
    (`{"name": "Piso", "material": "Piso"}`). Sin `-Apply` devuelve `material`, listo para pegar en el spec.
  - Modelo: `blender-cli asset get -Type model -Id modern_arm_chair_01 -Apply` lo descarga e importa.
  - `-Res 1k|2k|4k` (por defecto 1k: liviano; usa 2k o 4k para el render final si la cámara está cerca).
- **Materiales con mapas propios** en el spec: `{"name": "Ladrillo", "maps": {"color": "ladrillo_col.jpg",
  "normal": "ladrillo_nor.jpg", "roughness": "ladrillo_rough.jpg"}, "textureScale": 2}`. Se proyectan en
  caja desde el objeto: no hace falta desplegar UV en las piezas de `build`. `textureScale` más alto
  repite más la textura (piezas más grandes).

## Caminar (personajes de piezas, sin huesos)
`blender-cli walk -Spec caminata.json [-Save x.blend]` arma un ciclo de caminata para un personaje hecho
de piezas: pivotes en las caderas que balancean cada pierna, el pie que avanza se levanta, el cuerpo
sube, baja y se mece, la cabeza asiente y, si se piden, los brazos se balancean al revés que las piernas.
```json
{ "cycle": 24, "cycles": 2, "angle": 22, "lift": 0.035, "follow": "Camara",
  "legs": [ { "pivot": [-0.1, 0, 0.31], "parts": ["PieI", "PiernaI"], "foot": "PieI" },
            { "pivot": [ 0.1, 0, 0.31], "parts": ["PieD", "PiernaD"], "foot": "PieD" } ],
  "body": { "pivot": [0, 0, 0.33], "parts": ["Torso", "BrazoI", "BrazoD"] },
  "head": { "pivot": [0, 0, 0.79], "parts": ["Cabeza", "Cara"] },
  "arms": [ { "pivot": [-0.25, 0, 0.68], "parts": ["BrazoI"] } ] }
```
- El personaje debe mirar a **-Y** en reposo; `direction` [x, y] cambia hacia dónde camina.
- `pivot` de cada pierna = la cadera (donde gira); `foot` = la pieza que apoya: se mantiene plana.
- El rebote del cuerpo se **mide** en cada fotograma para que el pie de apoyo toque el piso: la
  respuesta trae `footMinZ`, que debe ser 0. Si el personaje sostiene algo con las manos, no pongas
  `arms`: los brazos van en `body`.
- `follow` hace que la cámara lo acompañe (el piso se desliza debajo): pon un piso con textura para que
  se note el avance. El ciclo se repite sin cortes; para un video, `render -Animation` (con `-Retro` si
  es estilo 32 bits) y une los fotogramas con ffmpeg.

## Lo que `build` no cubre
Para edición de malla avanzada, nodos de geometría, partículas, rigs, físicas o cualquier otra cosa
de `bpy`, escribe un script y ejecútalo con `blender-cli exec -Script script.py` (en vivo, o con
`-File` y `-Save`). El script tiene `bpy`, `bmesh`, `math`, `Vector` y `ops` (funciones de
blender-steroids, p. ej. `ops.frame_camera(cam, ["A"], "front")`); lo que dejes en la variable
`result` vuelve como JSON y lo que imprimas, en `stdout`. Usa `bpy.data` y `bmesh` en vez de
`bpy.ops` siempre que puedas: los operadores dependen del contexto de la ventana.

No le muestres comandos ni JSON al usuario salvo que lo pida.

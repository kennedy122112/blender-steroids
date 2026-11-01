<!-- Parte de la skill blender-model: léela cuando SKILL.md te mande aquí. -->

# Volumen desde dos vistas (`views`) y partes finas (`stroke`)
Para lo que **no es plano ni de revolución** y se puede dibujar o fotografiar de frente y de costado:
una regadera, una tetera, un ratón de computadora, un zapato, un auto de juguete, el cuerpo de un
pájaro o un pez. `views` separa en cada imagen el cuerpo de sus partes finas y, en cada altura, toma
dónde empieza y termina el cuerpo de frente (X) y de costado (Y): la sección es una elipse inscrita en
ese rectángulo (`roundness` 2; 3-4 para cajas redondeadas) o la forma de la vista de arriba (`top`).
Así calza con las dos siluetas: un cuello que no está en el centro (la boca de una regadera) sale
en su lugar, porque el centro de cada altura también se mide.

**La hoja de vistas (`sheet`)**: todas las piezas que salen de las mismas dos imágenes tienen que
medirse con el mismo marco (las imágenes, `height`, `thin`, `threshold`, `exclude`): si una difiere, queda
desalineada sin aviso. Decláralo una vez arriba del spec y cada pieza lo hereda (lo que la pieza diga
manda): `views` toma las dos imágenes; `stroke` y `outline` con `inView`, la de su `view`; y `stroke`,
además, la otra vista para su profundidad (una pata que se ve de frente toma su posición de costado sin
`location` a mano). Las dos imágenes se analizan una sola vez por build.

```json
"sheet": {"front": "nico/frente.png", "side": "nico/lado.png", "height": 0.12, "exclude": ["#3a3f4a"]},
"objects": [{"name": "Cuerpo", "type": "views", "paint": {...}},
            {"name": "Piernas", "type": "stroke", "color": "#3c5aa0"}, ...]
```

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

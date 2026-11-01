<!-- Parte de la skill blender-model: léela cuando SKILL.md te mande aquí. -->

# Siluetas desde una imagen o puntos (`outline`)
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
  uno que no es plano ni redondo, con `views` ([dos-vistas.md](dos-vistas.md)); un personaje, con las primitivas.
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

# Torno desde una foto (`lathe` con `image`)
Para objetos **de revolución** (jarrones, botellas, vasos, faroles, peones, columnas, lámparas): en vez
de escribir el `profile` a ojo, pásale la foto de lado y se mide. Usa `height` (o `width`) en metros. El
eje es la vertical que mejor centra la silueta. Con `side: "both"` (por defecto) promedia las dos
mitades; si de un lado hay un asa, un pico o una etiqueta que sobresale, usa `side: "left"` o
`"right"` (la mitad limpia) y agrega el asa aparte con `stroke` desde la misma foto (ver
[dos-vistas.md](dos-vistas.md)).

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

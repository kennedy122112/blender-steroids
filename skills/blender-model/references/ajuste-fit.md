<!-- Parte de la skill blender-model: léela cuando SKILL.md te mande aquí. -->

# Ajuste automático de proporciones (`fit`)
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

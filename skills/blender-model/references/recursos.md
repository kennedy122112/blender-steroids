<!-- Parte de la skill blender-model: léela cuando SKILL.md te mande aquí. -->

# Partir de modelos y recursos ya hechos
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

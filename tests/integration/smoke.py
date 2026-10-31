"""
Prueba de integración con Blender de verdad (sin interfaz): construye los ejemplos, lee las curvas de
animación, exporta GLB y lo abre aparte, y revisa idempotencia, reemplazo malla/curva y que un error no
estropee el archivo. Solo biblioteca estándar; necesita Blender (BLENDER_STEROIDS_BLENDER o el de
siempre).

    python tests/integration/smoke.py [carpeta_de_trabajo]

Sale con código 1 si algo falla e imprime un resumen en JSON.
"""
import json
import math
import os
import struct
import subprocess
import sys
import tempfile

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
CLI = [sys.executable, os.path.join(REPO, 'bin', 'blender_cli.py')]
TMP = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else tempfile.mkdtemp(prefix='bs-smoke-')
os.makedirs(TMP, exist_ok=True)
resultados, fallas = {}, []


def cli(*args):
    p = subprocess.run(CLI + list(args), capture_output=True, text=True, encoding='utf-8', errors='replace')
    try:
        return json.loads(p.stdout)
    except ValueError:
        return {'ok': False, 'error': 'salida no JSON', 'stdout': p.stdout[-800:], 'stderr': p.stderr[-800:]}


def check(nombre, cond, detalle=None):
    resultados[nombre] = 'ok' if cond else 'FALLA'
    if not cond:
        fallas.append({nombre: detalle})


def ruta(n):
    return os.path.join(TMP, n)


def script(nombre, codigo):
    p = ruta(nombre)
    with open(p, 'w', encoding='utf-8') as f:
        f.write(codigo)
    return p


def glb_json(path):
    with open(path, 'rb') as f:
        b = f.read()
    n = struct.unpack('<I', b[12:16])[0]
    return json.loads(b[20:20 + n])


LEER = '''
import json, math
def curva(o, path, idx):
    ad = o.animation_data
    try:
        from bpy_extras.anim_utils import action_get_channelbag_for_slot
        fcs = action_get_channelbag_for_slot(ad.action, ad.action_slot).fcurves
    except Exception:
        fcs = ad.action.fcurves
    return [fc for fc in fcs if fc.data_path == path and fc.array_index == idx][0]
s = bpy.context.scene
fps = s.render.fps / s.render.fps_base
'''

# 1. los ejemplos construyen sin errores
for ej in ('mesa-con-taza', 'pip-farolero', 'siluetas', 'libelula', 'pendulo-y-resorte'):
    r = cli('build', '--file', ruta(ej + '.blend'), '--spec', os.path.join(REPO, 'examples', ej + '.json'))
    check('build ' + ej, r.get('ok'), r.get('error'))

# 2. libélula: curvas horneadas = fórmula, GLB con su animación y abierto por separado
r = cli('exec', '--file', ruta('libelula.blend'), '--script', script('alas.py', LEER + '''
err = 0.0
for n, A, off, fase in (('BisagraDA', 32, -5, 0), ('BisagraIA', 32, 5, 180), ('BisagraDT', 28, -5, 90)):
    fc = curva(bpy.data.objects[n], 'rotation_euler', 1)
    err = max(err, max(abs(math.degrees(fc.evaluate(f)) - (off + A * math.sin(2 * math.pi * 6 * (f - 1) / fps
              + math.radians(fase)))) for f in range(1, 121)))
result = {'errorGrados': err, 'claves': len(curva(bpy.data.objects['BisagraDA'], 'rotation_euler', 1).keyframe_points)}
'''))
res = r.get('result') or {}
check('alas = fórmula (< 1e-5°)', r.get('ok') and res.get('errorGrados', 1) < 1e-5, r.get('error') or res)
check('alas con 120 claves', res.get('claves') == 120, res)
r = cli('export', '--file', ruta('libelula.blend'), '--path', ruta('libelula.glb'))
check('export GLB', r.get('ok'), r.get('error'))
if r.get('ok'):
    j = glb_json(ruta('libelula.glb'))
    canales = sum(len(a['channels']) for a in j.get('animations', []))
    muestras = {j['accessors'][smp['input']]['count'] for a in j.get('animations', []) for smp in a['samplers']}
    check('GLB con 6 canales animados', canales == 6, canales)
    check('GLB con 120 muestras por canal', muestras == {120}, sorted(muestras))
    r = cli('import', '--file', ruta('reimport.blend'), '--path', ruta('libelula.glb'))
    check('GLB se vuelve a importar', r.get('ok'), r.get('error'))

# 3. péndulo: período medido en las curvas contra la teoría (serie de la integral elíptica)
r = cli('exec', '--file', ruta('pendulo-y-resorte.blend'), '--script', script('pendulo.py', LEER + '''
fc = curva(bpy.data.objects['Eje'], 'rotation_euler', 1)
a = [fc.evaluate(f) for f in range(1, 151)]
c = [f - a[f - 1] / (a[f] - a[f - 1]) for f in range(1, 150) if a[f - 1] > 0 >= a[f]]
result = {'periodo': (c[1] - c[0]) / fps}
'''))
L, g, a0 = 0.7, 9.81, math.radians(30)
k = math.sin(a0 / 2)
teorico = 2 * math.pi * math.sqrt(L / g) * (1 + k ** 2 / 4 + 9 * k ** 4 / 64)
periodo = (r.get('result') or {}).get('periodo')
check('período del péndulo (±1 %)', periodo and abs(periodo - teorico) / teorico < 0.01, [periodo, teorico])

# 4. idempotencia y objetos ajenos intactos
cli('exec', '--file', ruta('libelula.blend'), '--save', ruta('libelula.blend'), '--script', script('ajeno.py', '''
o = bpy.data.objects.new('Ajeno', None); bpy.context.scene.collection.objects.link(o); o.location = (5, 6, 7)
result = True
'''))
r1 = cli('build', '--file', ruta('libelula.blend'), '--spec', os.path.join(REPO, 'examples', 'libelula.json'),
         '--save', ruta('libelula.blend'))
check('repetir build no crea nada', r1.get('ok') and not r1.get('created'), r1.get('created'))
r = cli('exec', '--file', ruta('libelula.blend'), '--script', script('cuenta.py', LEER + '''
o = bpy.data.objects
result = {'objetos': len(o), 'ajeno': list(o['Ajeno'].location),
          'claves': len(curva(o['BisagraDA'], 'rotation_euler', 1).keyframe_points),
          'base': json.loads(o['Libelula']['bs_motion_base'])['location[z]']}
'''))
res = r.get('result') or {}
check('objeto ajeno intacto', res.get('ajeno') == [5.0, 6.0, 7.0], res)
check('sin claves duplicadas ni reposo corrido', res.get('claves') == 120 and abs(res.get('base', 0) - 0.6) < 1e-6, res)   # float32 de Blender

# 5. reemplazo malla <-> curva conservando lo que lleva el objeto
ala = os.path.join(REPO, 'examples', 'libelula', 'ala.png')


def spec_ala(salida):
    o = {'name': 'Pieza', 'type': 'outline', 'image': ala, 'width': 0.5, 'thickness': 0.01, 'material': 'Rojo',
         'modifiers': [{'type': 'solidify', 'thickness': 0.002}]}
    if salida:
        o['output'] = salida
    return {'materials': [{'name': 'Rojo', 'color': '#d6453d'}],
            'objects': [o, {'name': 'Hijo', 'type': 'cube', 'size': 0.05, 'location': [0.3, 0, 0.2], 'parent': 'Pieza'}],
            'animation': [{'object': 'Pieza', 'property': 'location', 'axis': 'z',
                           'motion': {'kind': 'oscillate', 'frequency': 1, 'amplitude': 0.1}}]}


VER = '''
import json
o = bpy.data.objects['Pieza']
result = {'tipo': o.type, 'hijos': [c.name for c in o.children], 'mat': [m.name for m in o.data.materials],
          'mods': [m.type for m in o.modifiers], 'motion': 'bs_motion' in o, 'source': 'bs_source' in o,
          'anim': bool(o.animation_data and o.animation_data.action),
          'hijoZ': round(bpy.data.objects['Hijo'].matrix_world.translation.z, 4),
          'nombres': sorted(x.name for x in bpy.data.objects)}
'''
for paso, salida, tipo in (('malla', None, 'MESH'), ('curva', 'curve', 'CURVE'), ('malla de nuevo', None, 'MESH')):
    with open(ruta('pieza.json'), 'w', encoding='utf-8') as f:
        json.dump(spec_ala(salida), f)
    r = cli('build', '--file', ruta('pieza.blend'), '--spec', ruta('pieza.json'), '--save', ruta('pieza.blend'))
    check('reemplazo: build %s' % paso, r.get('ok'), r.get('error'))
    v = (cli('exec', '--file', ruta('pieza.blend'), '--script', script('ver.py', VER)).get('result') or {})
    bien = (v.get('tipo') == tipo and v.get('hijos') == ['Hijo'] and v.get('mat') == ['Rojo'] and v.get('motion')
            and v.get('source') and v.get('anim') and v.get('nombres') == ['Hijo', 'Pieza'] and 'SOLIDIFY' in v.get('mods', []))
    check('reemplazo: %s conserva hijo, material, modificador, animación y fuente' % paso, bien, v)

# 6. farol: franjas de color, estrella por color pegada al cuerpo aunque cuelgue de la bisagra,
#    péndulo, borla con follow y luz con dos ruidos sumados
r = cli('build', '--file', ruta('farol.blend'), '--spec', os.path.join(REPO, 'examples', 'farol.json'))
check('build farol sin avisos', r.get('ok') and not r.get('warnings'), r.get('error') or r.get('warnings'))
o = r.get('outlines') or {}
check('farol: cada franja cumple la tolerancia', all(o.get(n, {}).get('targetMet') for n in
                                                      ('Borla', 'TapaInf', 'AroInf', 'Cuerpo', 'TapaSup', 'Alambre')), o)
est = (o.get('Estrella') or {}).get('loops') or [{}]
check('farol: estrella de 10 vértices', len(est) == 1 and est[0].get('vertices') == 10, est)
mot = {m['object']: m for m in r.get('motions', [])}
check('farol: la luz suma dos ruidos', (mot.get('Luz') or {}).get('kind') == 'noise+noise', mot.get('Luz'))
r = cli('exec', '--file', ruta('farol.blend'), '--script', script('estrella.py', '''
s = bpy.context.scene
s.frame_set(1)
b = bpy.data.objects['Bisagra']
b.animation_data_clear(); b.rotation_euler = (0, 0, 0)
bpy.context.view_layer.update()
e = bpy.data.objects['Estrella'].matrix_world.translation
result = {'estrella': [round(e.x, 4), round(e.y, 4), round(e.z, 4)]}
'''))
e = (r.get('result') or {}).get('estrella') or [9, 9, 9]
check('farol: estrella al frente del cuerpo (attach con padre)', abs(e[0]) < 0.01 and -0.26 < e[1] < -0.2
      and abs(e[2] - 1.042) < 0.01, e)

# 7. una entrada inválida no estropea el archivo
antes = os.path.getmtime(ruta('pieza.blend'))
with open(ruta('malo.json'), 'w', encoding='utf-8') as f:
    json.dump({'objects': [{'name': 'Otra', 'type': 'cube'}],
               'animation': [{'object': 'Pieza', 'property': 'location', 'axis': 'z',
                              'motion': {'kind': 'oscillate', 'frequency': 30, 'amplitude': 1}}]}, f)
r = cli('build', '--file', ruta('pieza.blend'), '--spec', ruta('malo.json'), '--save', ruta('pieza.blend'))
check('entrada inválida da error', not r.get('ok') and 'aliasing' in (r.get('error') or ''), r.get('error'))
check('el archivo no se tocó', os.path.getmtime(ruta('pieza.blend')) == antes)

print(json.dumps({'ok': not fallas, 'carpeta': TMP, 'pruebas': resultados, 'fallas': fallas}, ensure_ascii=False, indent=1))
sys.exit(1 if fallas else 0)

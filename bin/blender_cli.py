"""
blender_cli.py - puente local entre el agente y Blender. Sin MCP, sin nube, solo biblioteca estándar.

Dos formas de trabajar:
  en vivo       con Blender abierto y el puente activo (add-on o `launch`): los cambios se ven al momento
  sin interfaz  con --file <archivo.blend>: Blender corre en segundo plano sobre ese archivo

Uso (toda salida es JSON por stdout):
  status                                    ¿Blender instalado? ¿abierto? ¿puente activo?
  doctor                                    revisa todo (Python, Blender, add-on, puerto, versión, copia,
                                            unidades de red) y dice cómo arreglar cada problema
  setup                                     instala y activa el add-on en el Blender de esta PC
  launch [--file x.blend]                   abre Blender con el puente activo y espera a que responda
  info | scene [--object nombre]            qué hay en la escena
  build --spec escena.json [--save x.blend] crea o actualiza objetos, materiales, luces, cámara, animación
  exec --script código.py [--save x.blend]  ejecuta Python con bpy (deja la respuesta en `result`)
  save [--path x.blend] | open --path x.blend
  render --path img.png [--preview] [--view iso|front|top|right|left|back] [--engine eevee|cycles|workbench]
         [--samples N] [--resolution 1920x1080] [--percentage 50] [--camera nombre] [--frame N]
         [--animation [--frames 1-120]] [--transparent]
  export --path modelo.glb|fbx|obj|stl|ply|usd [--objects a,b]
  compare --reference ref.png --path comparar.png [--view front|...] [--objects a,b] [--preview]
          [--fit-view] [--no-align] [--no-overlay] [--no-guides]
                                            referencia | render alineado a su figura | siluetas
                                            superpuestas, con guías cada 10 % y medidas (IoU, anchos)
  check [--objects a,b] [--tolerance 0.004] piezas que flotan, enterradas o que se atraviesan
  fit --reference ref.png [--reference perfil.png ...] --parts partes.json
      [--view right ... | --fit-view] [--budget 400] [--colors [--color-weight 0.3]] [--save x.blend]
                                            (cada --view va con su --reference, en orden; las que falten
                                            se buscan con --fit-view)
                                            ajusta escala y posición de las piezas hasta que la silueta
                                            se parezca a la de la referencia (lo más posible)
  build ... --patch ajuste.json             aplica location/scale por nombre (la salida `parts` de fit)

Con --file la orden se aplica a ese .blend sin interfaz (si no existe, se crea vacío y --save
lo guarda ahí). render y export, en vivo, trabajan sobre una copia: no congelan tu Blender.
Las opciones también se aceptan al estilo PowerShell: -Path, -Spec, -File...
"""
import argparse
import glob
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ADDON_DIR = os.path.join(ROOT, 'addon')
PORT = int(os.environ.get('BLENDER_STEROIDS_PORT', '9777'))
APPDATA = os.environ.get('APPDATA', os.path.expanduser('~'))
HOME_INSTALL = os.path.join(os.path.expanduser('~'), '.blender-steroids')


def _read_version():
    try:
        with open(os.path.join(ADDON_DIR, 'blender_steroids', 'version.py'), encoding='utf-8') as f:
            return re.search(r"VERSION = '([^']+)'", f.read()).group(1)
    except (OSError, AttributeError):
        return None


VERSION = _read_version()
WARNINGS = []          # avisos que acompañan a cualquier respuesta (copia distinta, add-on desactualizado)
LAST_CONNECT_ERROR = None

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def out(obj, code=0):
    if WARNINGS and isinstance(obj, dict):
        obj.setdefault('warnings', [])
        obj['warnings'] = list(dict.fromkeys(obj['warnings'] + WARNINGS))
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    sys.stdout.flush()
    sys.exit(code)


def _same(a, b):
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:
        return False


def copy_warning():
    """Avisa si este blender-cli no es el instalado en ~/.blender-steroids (p. ej. una copia que un
    agente descargó en su carpeta temporal): sus cambios no llegan a las skills ni al add-on."""
    if os.path.isdir(HOME_INSTALL) and not _same(ROOT, HOME_INSTALL):
        return ('Estás usando una copia de blender-steroids en %s; la instalada es %s (%s). '
                'Usa la instalada para que coincida con las skills y el add-on.'
                % (ROOT, HOME_INSTALL, os.path.realpath(HOME_INSTALL)))
    return None


def fail(msg, **extra):
    out(dict({'ok': False, 'error': msg}, **extra), 1)


# ------------------------------------------------------------------------- dónde está Blender

def find_blender():
    env = os.environ.get('BLENDER_STEROIDS_BLENDER')
    if env and os.path.exists(env):
        return env
    cands = []
    for base in (os.environ.get('ProgramFiles', r'C:\Program Files'), os.environ.get('ProgramFiles(x86)', '')):
        if base:
            cands += glob.glob(os.path.join(base, 'Blender Foundation', '*', 'blender.exe'))
            cands += glob.glob(os.path.join(base, 'Steam', 'steamapps', 'common', 'Blender', 'blender.exe'))
    cands += glob.glob(os.path.join(os.environ.get('LOCALAPPDATA', ''), 'Programs', 'Blender*', '*', 'blender.exe'))
    # macOS: Blender.app (también renombrada, p. ej. «Blender 4.2.app») en /Applications o ~/Applications
    for apps in ('/Applications', os.path.expanduser('~/Applications'),
                 os.path.expanduser('~/Library/Application Support/Steam/steamapps/common/Blender')):
        cands += glob.glob(os.path.join(apps, 'Blender*.app', 'Contents', 'MacOS', 'Blender'))
    cands += glob.glob(os.path.expanduser('~/.steam/steam/steamapps/common/Blender/blender'))
    # Linux: paquete, snap, flatpak o el .tar.xz descomprimido en la carpeta personal
    cands += glob.glob('/usr/bin/blender') + glob.glob('/usr/local/bin/blender') + glob.glob('/snap/bin/blender')
    cands += glob.glob(os.path.expanduser('~/blender*/blender')) + glob.glob('/opt/blender*/blender')
    if not cands and shutil.which('blender'):
        cands.append(shutil.which('blender'))
    if not cands:
        return None
    # la versión más alta gana
    return max(cands, key=lambda p: [int(x) for x in re.findall(r'\d+', version_of(p) or '0')])


_versions = {}


def version_of(exe):
    """Versión corta (5.2) por la carpeta de datos de Blender; si no aparece, preguntándole a Blender."""
    if exe in _versions:
        return _versions[exe]
    real = os.path.realpath(exe)
    dirs = [os.path.dirname(exe), os.path.dirname(real),
            os.path.join(os.path.dirname(os.path.dirname(real)), 'Resources'),   # macOS: Contents/Resources/5.2
            '/usr/share/blender']                                                 # paquetes de Linux
    vs = []
    for d in dirs:
        if os.path.isdir(d):
            vs += [n for n in os.listdir(d) if re.fullmatch(r'\d+\.\d+', n) and os.path.isdir(os.path.join(d, n))]
    v = max(vs, key=lambda v: [int(x) for x in v.split('.')]) if vs else None
    if v is None:
        try:
            r = subprocess.run([exe, '--version'], capture_output=True, text=True, timeout=60)
            m = re.search(r'Blender (\d+\.\d+)', r.stdout)
            v = m.group(1) if m else None
        except (OSError, subprocess.SubprocessError):
            pass
    _versions[exe] = v
    return v


def user_addons_dir(version):
    if sys.platform == 'win32':
        return os.path.join(APPDATA, 'Blender Foundation', 'Blender', version, 'scripts', 'addons')
    if sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/Blender/%s/scripts/addons' % version)
    return os.path.expanduser('~/.config/blender/%s/scripts/addons' % version)


def blender_running():
    if sys.platform != 'win32':
        # en macOS el proceso se llama «Blender»; en Linux, «blender»
        try:
            return subprocess.run(['pgrep', '-ix', 'blender'], capture_output=True).returncode == 0
        except OSError:
            return False
    r = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq blender.exe', '/NH'], capture_output=True, text=True)
    return 'blender.exe' in r.stdout.lower()


# ------------------------------------------------------------------------- hablar con Blender

def live(cmd, args=None, timeout=600):
    """Envía un pedido al Blender abierto. Devuelve None si el puente no responde."""
    global LAST_CONNECT_ERROR
    try:
        s = socket.create_connection(('127.0.0.1', PORT), timeout=3)
    except PermissionError:
        LAST_CONNECT_ERROR = 'sandbox'   # el agente no tiene permiso para abrir conexiones locales
        return None
    except OSError as e:
        LAST_CONNECT_ERROR = 'refused' if isinstance(e, ConnectionRefusedError) else str(e)
        return None
    LAST_CONNECT_ERROR = None
    try:
        with s:
            s.settimeout(timeout)
            s.sendall(json.dumps({'cmd': cmd, 'args': args or {}}, ensure_ascii=False).encode('utf-8') + b'\n')
            data = b''
            while not data.endswith(b'\n'):
                chunk = s.recv(1 << 16)
                if not chunk:
                    break
                data += chunk
    except socket.timeout:
        return {'ok': False, 'error': 'Blender no respondió en %d s.' % timeout,
                'hint': 'Puede estar renderizando o esperando una respuesta en un diálogo. Espera o ciérralo.'}
    except OSError as e:
        return {'ok': False, 'error': 'Se cortó la conexión con Blender: %s' % e}
    if not data:
        return {'ok': False, 'error': 'Blender cerró la conexión sin responder',
                'hint': 'El puerto %d lo puede estar usando otro programa. Ejecuta `doctor`.' % PORT}
    try:
        resp = json.loads(data.decode('utf-8'))
    except ValueError:
        return {'ok': False, 'error': 'Respuesta no válida en el puerto %d: no parece blender-steroids.' % PORT,
                'hint': 'Otro programa usa ese puerto. Define BLENDER_STEROIDS_PORT con otro número.'}
    check_bridge(resp.pop('_bridge', None) if isinstance(resp, dict) else None)
    return resp


def check_bridge(bridge):
    """Compara el add-on que tiene cargado el Blender abierto con este blender-cli."""
    if bridge is None:
        WARNINGS.append('El Blender abierto tiene un add-on de blender-steroids anterior a 1.1.0. '
                        'Cierra y vuelve a abrir Blender para cargar el actual (%s).' % VERSION)
        return
    if VERSION and bridge.get('version') != VERSION:
        WARNINGS.append('El Blender abierto tiene cargado el add-on %s y este blender-cli es %s. Cierra y '
                        'vuelve a abrir Blender (o reinstala con `setup`).' % (bridge.get('version'), VERSION))
    path = bridge.get('path')
    if path and not _same(path, os.path.join(ADDON_DIR, 'blender_steroids')):
        WARNINGS.append('El add-on cargado en Blender viene de %s, no de esta copia (%s).' % (path, ROOT))


def not_connected():
    """Error común cuando no hay puente: distingue sandbox de Blender cerrado."""
    if LAST_CONNECT_ERROR == 'sandbox':
        fail('El agente no tiene permiso para conectarse al puerto local %d (sandbox).' % PORT,
             hint='Vuelve a ejecutar el comando con acceso completo / fuera del sandbox.')
    fail('No hay un Blender abierto con el puente activo.',
         hint='Ejecuta `launch` para abrir Blender listo, activa el add-on (`setup`) en tu Blender, '
              'o usa --file <archivo.blend> para trabajar sin interfaz. `doctor` revisa todo.',
         blenderRunning=blender_running())


def headless(cmd, args=None, file=None, save=None, timeout=None):
    exe = find_blender()
    if not exe:
        fail('No encuentro Blender en esta PC. Instálalo desde blender.org (o define BLENDER_STEROIDS_BLENDER).')
    new = bool(file) and not os.path.exists(file)
    if new and cmd not in ('build', 'exec'):
        fail('No existe el archivo %s' % os.path.abspath(file))
    tmp = tempfile.mkdtemp(prefix='bs-')
    req_p, out_p = os.path.join(tmp, 'pedido.json'), os.path.join(tmp, 'respuesta.json')
    if new and not save and cmd in ('build', 'exec'):
        save = file
    req = {'cmd': cmd, 'args': args or {}, 'new': new or not file, 'save': save}
    with open(req_p, 'w', encoding='utf-8') as f:
        json.dump(req, f, ensure_ascii=False)
    argv = [exe, '-b']
    if file and not new:
        argv.append(os.path.abspath(file))
    argv += ['--factory-startup', '--python-exit-code', '1', '--python', os.path.join(ADDON_DIR, 'headless.py'),
             '--', req_p, out_p]
    p = subprocess.run(argv, capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=timeout)
    if not os.path.exists(out_p):
        fail('Blender terminó sin respuesta (código %d)' % p.returncode, log=(p.stdout + p.stderr)[-3000:])
    with open(out_p, encoding='utf-8') as f:
        resp = json.load(f)
    resp['mode'] = 'headless'
    return resp


def run(cmd, args, a, live_only=False):
    """Decide el modo: --file -> sin interfaz; si no, el Blender abierto."""
    if getattr(a, 'file', None):
        return headless(cmd, args, file=a.file, save=getattr(a, 'save', None))
    resp = live(cmd, args)
    if resp is None:
        not_connected()
    resp['mode'] = 'live'
    if resp.get('ok') and getattr(a, 'save', None) and cmd in ('build', 'exec', 'fit'):
        sv = live('save', {'path': a.save})
        resp['saved'] = sv.get('saved') if sv and sv.get('ok') else sv
    return resp


def on_copy(cmd, args, a):
    """render/export: en vivo se guarda una copia del archivo abierto y se procesa sin interfaz."""
    if a.file:
        return headless(cmd, args, file=a.file)
    tmp = os.path.join(tempfile.mkdtemp(prefix='bs-'), 'copia.blend')
    sv = live('save', {'path': tmp, 'copy': True})
    if sv is None:
        not_connected()
    if not sv.get('ok'):
        out(sv, 1)
    resp = headless(cmd, args, file=tmp)
    resp['source'] = 'copia del Blender abierto'
    return resp


# ------------------------------------------------------------------------- comandos

def cmd_status(a):
    exe = find_blender()
    ver = version_of(exe) if exe else None
    st = {'ok': True, 'cli': VERSION, 'blender': exe, 'version': ver, 'running': blender_running(), 'port': PORT}
    if ver:
        link = os.path.join(user_addons_dir(ver), 'blender_steroids')
        st['addonInstalled'] = os.path.exists(os.path.join(link, '__init__.py'))
    info = live('info', timeout=10)
    st['bridge'] = bool(info and info.get('ok'))
    if st['bridge']:
        info.pop('ok', None)
        st['scene'] = info
    if not exe:
        st['ok'] = False
        st['error'] = 'Blender no está instalado (o no está en la carpeta de siempre).'
    return st


def _link(src, dst):
    if os.path.lexists(dst):
        if os.path.realpath(dst) == os.path.realpath(src):
            return 'ya estaba'
        if os.path.isdir(dst) and not os.path.islink(dst) and not _is_junction(dst):
            fail('Ya existe una carpeta real en %s: muévela o bórrala antes.' % dst)
        os.rmdir(dst) if _is_junction(dst) else os.unlink(dst)
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if sys.platform == 'win32':
        r = subprocess.run(['cmd', '/c', 'mklink', '/J', dst, src], capture_output=True, text=True)
        if r.returncode:
            fail('No se pudo enlazar el add-on: ' + (r.stdout + r.stderr).strip())
    else:
        os.symlink(src, dst)
    return 'enlazado'


def _is_junction(p):
    try:
        return bool(os.readlink(p))
    except (OSError, ValueError):
        return False


def cmd_setup(a):
    exe = find_blender()
    if not exe:
        fail('No encuentro Blender. Instálalo desde blender.org y vuelve a ejecutar setup.')
    ver = version_of(exe)
    dst = os.path.join(user_addons_dir(ver), 'blender_steroids')
    how = _link(os.path.join(ADDON_DIR, 'blender_steroids'), dst)
    expr = ("import bpy, addon_utils; addon_utils.enable('blender_steroids', default_set=True, persistent=True); "
            "bpy.ops.wm.save_userpref(); "
            "import sys; print('BS_ENABLED', addon_utils.check('blender_steroids'))")
    p = subprocess.run([exe, '-b', '--python-expr', expr], capture_output=True, text=True, encoding='utf-8',
                       errors='replace', timeout=180)
    enabled = 'BS_ENABLED (True, True)' in p.stdout
    res = {'ok': enabled, 'blender': exe, 'version': ver, 'addon': dst, 'link': how, 'enabled': enabled}
    if not enabled:
        res['log'] = (p.stdout + p.stderr)[-2000:]
    elif blender_running() and not live('ping', timeout=5):
        res['note'] = ('Blender ya estaba abierto: ciérralo y ábrelo de nuevo, o en ese Blender activa '
                       '«blender-steroids» en Edición > Preferencias > Complementos.')
    return res


def cmd_launch(a):
    if live('ping', timeout=5):
        return dict({'ok': True, 'already': True}, **live('info'))
    exe = find_blender()
    if not exe:
        fail('No encuentro Blender en esta PC.')
    argv = [exe]
    if a.file:
        argv.append(os.path.abspath(a.file))
    argv += ['--python', os.path.join(ADDON_DIR, 'startup.py')]
    # que Blender siga abierto aunque termine el proceso del agente
    if sys.platform == 'win32':
        detach = {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP}
    else:
        detach = {'start_new_session': True}
    subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL,
                     close_fds=True, **detach)
    t0 = time.time()
    while time.time() - t0 < a.wait:
        info = live('info', timeout=5)
        if info and info.get('ok'):
            info['launched'] = exe
            return info
        time.sleep(1)
    fail('Blender se abrió pero el puente no respondió en %d s.' % a.wait,
         hint='Puede haber otro Blender usando el puerto %d, o Blender muestra un aviso esperando respuesta.' % PORT)


def cmd_spec_build(a):
    try:
        with open(a.spec, encoding='utf-8-sig') as f:
            spec = json.load(f)
    except FileNotFoundError:
        fail('No existe el spec %s' % os.path.abspath(a.spec))
    except ValueError as e:
        fail('El spec %s no es JSON válido: %s' % (a.spec, e))
    spec['_baseDir'] = os.path.dirname(os.path.abspath(a.spec))
    if getattr(a, 'patch', None):
        # resultado de fit: location/scale por nombre de pieza, sobre el spec
        try:
            with open(a.patch, encoding='utf-8-sig') as f:
                patch = json.load(f)
        except (OSError, ValueError) as e:
            fail('No se pudo leer el patch %s: %s' % (a.patch, e))
        patch = patch.get('parts', patch)
        for o in spec.get('objects', []):
            if o.get('name') in patch:
                o.update({k: v for k, v in patch[o['name']].items() if k in ('location', 'scale')})
    return run('build', spec, a)


def cmd_exec(a):
    try:
        with open(a.script, encoding='utf-8-sig') as f:
            code = f.read()
    except FileNotFoundError:
        fail('No existe el script %s' % os.path.abspath(a.script))
    return run('exec', {'code': code, 'filename': os.path.abspath(a.script)}, a)


def cmd_render(a):
    args = {'path': os.path.abspath(a.path), 'preview': a.preview, 'view': a.view, 'engine': a.engine,
            'samples': a.samples, 'percentage': a.percentage, 'camera': a.camera, 'frame': a.frame,
            'animation': a.animation}
    if a.view and ',' in a.view:   # dirección propia: "0.9,-0.6,0.2"
        args['view'] = [float(x) for x in a.view.strip('[]').split(',')]
    if a.resolution:
        args['resolution'] = [int(x) for x in re.split('[x,]', a.resolution)]
    if a.frames:
        args['frames'] = [int(x) for x in a.frames.split('-')]
    if a.objects:
        args['objects'] = [x.strip() for x in a.objects.split(',')]
    if a.transparent:
        args['transparent'] = True
    return on_copy('render', {k: v for k, v in args.items() if v not in (None, False)}, a)


def _vista(v):
    return [float(x) for x in v.strip('[]').split(',')] if v and ',' in v else v


def cmd_compare(a):
    refs, vistas = a.reference, a.view or []
    if len(refs) > 1:
        # varias referencias (p. ej. tres cuartos + perfil): una comparación por vista y el promedio
        base, ext = os.path.splitext(os.path.abspath(a.path))
        res = {'ok': True, 'views': []}
        for i, r in enumerate(refs):
            sub = argparse.Namespace(**vars(a))
            sub.reference, sub.view = [r], [vistas[i]] if i < len(vistas) else []
            sub.path = '%s_%d%s' % (base, i + 1, ext)
            sub.fit_view = a.fit_view and i >= len(vistas)
            one = cmd_compare(sub)
            if not one.get('ok'):
                return one
            res['views'].append({'reference': os.path.abspath(r), 'image': one['image'],
                                 'silhouetteIoU': one['alignment'].get('silhouetteIoU'),
                                 'view': one.get('fitView', {}).get('view') or sub.view[:1], 'alignment': one['alignment']})
        ious = [v['silhouetteIoU'] for v in res['views'] if v['silhouetteIoU'] is not None]
        res['meanIoU'] = round(sum(ious) / len(ious), 3) if ious else None
        return res
    ref = os.path.abspath(refs[0])
    if not os.path.exists(ref):
        fail('No existe la referencia %s' % ref)
    view = vistas[0] if vistas else None
    args = {'reference': ref, 'path': os.path.abspath(a.path), 'preview': a.preview, 'view': _vista(view),
            'engine': a.engine, 'samples': a.samples, 'camera': a.camera, 'frame': a.frame}
    if a.objects:
        args['objects'] = [x.strip() for x in a.objects.split(',')]
    args = {k: v for k, v in args.items() if v not in (None, False)}
    if a.no_guides:
        args['guides'] = False
    if a.no_align:
        args['align'] = False
    if a.no_overlay:
        args['overlay'] = False
    if a.fit_view:
        args['fitView'] = True
    return on_copy('compare', args, a)


def cmd_fit(a):
    try:
        with open(a.parts, encoding='utf-8-sig') as f:
            parts = json.load(f)
    except (OSError, ValueError) as e:
        fail('No se pudo leer %s: %s' % (a.parts, e))
    vistas = a.view or []
    refs = []
    for i, r in enumerate(a.reference):
        if not os.path.exists(r):
            fail('No existe la referencia %s' % os.path.abspath(r))
        v = _vista(vistas[i]) if i < len(vistas) else ('fit' if a.fit_view else None)
        refs.append({'path': os.path.abspath(r), 'view': v})
    args = {'references': refs, 'parts': parts, 'budget': a.budget, 'detail': a.detail,
            'resolution': max(320, a.detail * 2), 'colors': a.colors,
            'colorWeight': a.colorweight}
    if a.fit_view:
        args['fitView'] = True
    return run('fit', args, a)


def cmd_check(a):
    args = {'tolerance': a.tolerance}
    if a.objects:
        args['objects'] = [x.strip() for x in a.objects.split(',')]
    return run('check', args, a)


def cmd_export(a):
    args = {'path': os.path.abspath(a.path)}
    if a.objects:
        args['objects'] = [x.strip() for x in a.objects.split(',')]
    return on_copy('export', args, a)


def _network_drives():
    """Unidades de red de Windows que no responden (PowerShell avisa «InitializeDefaultDrives» por ellas)."""
    if sys.platform != 'win32':
        return []
    import ctypes
    import string
    import threading
    k32 = ctypes.windll.kernel32
    mask = k32.GetLogicalDrives()
    caidas = []
    for i, letra in enumerate(string.ascii_uppercase):
        if not mask & (1 << i):
            continue
        raiz = letra + ':\\'
        if k32.GetDriveTypeW(raiz) != 4:        # 4 = DRIVE_REMOTE
            continue
        res = {}

        def probar():
            libre = ctypes.c_ulonglong(0)
            res['ok'] = bool(k32.GetDiskFreeSpaceExW(raiz, None, None, ctypes.byref(libre)))
        t = threading.Thread(target=probar, daemon=True)
        t.start()
        t.join(3)                                # una unidad caída puede tardar en fallar
        if not res.get('ok'):
            caidas.append(letra + ':')
    return caidas


def _probe_port():
    """'bridge' si responde blender-steroids, 'other' si otro programa usa el puerto, 'free' si nadie,
    'sandbox' si el agente no puede abrir conexiones locales."""
    resp = live('ping', timeout=5)
    if resp is None:
        return 'sandbox' if LAST_CONNECT_ERROR == 'sandbox' else 'free'
    return 'bridge' if resp.get('pong') else 'other'


def cmd_doctor(a):
    checks = []

    def check(name, ok, detail, fix=None, level='error'):
        c = {'check': name, 'ok': bool(ok), 'detail': detail}
        if not ok:
            c['level'] = level
            if fix:
                c['fix'] = fix
        checks.append(c)
        return ok

    check('cli', VERSION is not None, 'blender-cli %s en %s' % (VERSION, ROOT),
          'Falta addon/blender_steroids/version.py: reinstala blender-steroids.')
    w = copy_warning()
    check('copia', w is None, w or 'Es la copia instalada (%s)' % HOME_INSTALL if os.path.isdir(HOME_INSTALL)
          else 'No hay instalación en %s' % HOME_INSTALL,
          'Llama al puente instalado: %s' % os.path.join(HOME_INSTALL, 'bin', 'blender-cli.cmd' if
                                                         sys.platform == 'win32' else 'blender-cli'),
          level='warning')
    check('python', sys.version_info >= (3, 8), '%s (%s)' % (sys.version.split()[0], sys.executable),
          'Instala Python 3.8 o superior, o deja que el lanzador use el que trae Blender.')

    exe = find_blender()
    ver = version_of(exe) if exe else None
    nums = [int(x) for x in re.findall(r'\d+', ver or '0')[:2]] + [0]
    if check('blender', exe, '%s (%s)' % (exe, ver) if exe else 'No encontrado',
             'Instala Blender desde blender.org o define BLENDER_STEROIDS_BLENDER con la ruta del ejecutable.'):
        check('blender-version', nums[:2] >= [4, 2], 'Blender %s' % ver,
              'blender-steroids necesita Blender 4.2 o superior.')

    if ver:
        link = os.path.join(user_addons_dir(ver), 'blender_steroids')
        instalado = os.path.exists(os.path.join(link, '__init__.py'))
        if check('addon', instalado, link if instalado else 'No está en %s' % link,
                 'Ejecuta `setup` para instalarlo y activarlo.', level='warning'):
            check('addon-copia', _same(link, os.path.join(ADDON_DIR, 'blender_steroids')),
                  'El add-on apunta a %s' % os.path.realpath(link),
                  'Ejecuta `setup` desde la copia que quieres usar para reenlazarlo.', level='warning')

    abierto = blender_running()
    estado = _probe_port()
    if estado == 'sandbox':
        check('puerto', False, 'Sin permiso para conectarse a 127.0.0.1:%d' % PORT,
              'El agente corre en un sandbox: vuelve a ejecutar con acceso completo.')
    elif estado == 'other':
        check('puerto', False, 'Otro programa responde en el puerto %d' % PORT,
              'Define BLENDER_STEROIDS_PORT con otro número (igual para Blender y blender-cli) y reabre Blender.')
    elif estado == 'free':
        check('puente', False, 'Blender %s, puente sin respuesta en el puerto %d'
              % ('abierto' if abierto else 'cerrado', PORT),
              ('Ese Blender no tiene el add-on activo: reinícialo o actívalo en Preferencias > Complementos.'
               if abierto else 'Ejecuta `launch`, o usa --file para trabajar sin interfaz.'), level='warning')
    else:
        info = live('info', timeout=10) or {}
        check('puente', True, 'Blender %s responde en el puerto %d (archivo: %s)'
              % (info.get('blender'), PORT, info.get('file') or 'sin guardar'))
        if WARNINGS:
            check('puente-version', False, ' '.join(WARNINGS),
                  'Cierra y vuelve a abrir Blender para que cargue el add-on actual.', level='warning')
            WARNINGS.clear()

    caidas = _network_drives()
    check('unidades-red', not caidas,
          'Unidades de red sin respuesta: %s' % ', '.join(caidas) if caidas else 'Sin unidades de red caídas',
          'PowerShell muestra «InitializeDefaultDrives» por ellas: es solo un aviso, el comando funciona. '
          'Para quitarlo, reconecta la red/VPN o borra la unidad (net use X: /delete). En Windows usa '
          'blender-cli.cmd, que no pasa por PowerShell.', level='warning')

    try:
        with tempfile.NamedTemporaryFile(prefix='bs-', delete=True):
            pass
        check('temporal', True, tempfile.gettempdir())
    except OSError as e:
        check('temporal', False, str(e), 'La carpeta temporal no admite escritura: render y export la necesitan.')

    errores = [c for c in checks if not c['ok'] and c.get('level') == 'error']
    avisos = [c for c in checks if not c['ok'] and c.get('level') == 'warning']
    return {'ok': not errores, 'cli': VERSION, 'errors': len(errores), 'warnings_count': len(avisos),
            'checks': checks, 'fixes': [c['fix'] for c in errores + avisos if c.get('fix')]}


class JsonArgumentParser(argparse.ArgumentParser):
    """Errores de argumentos como JSON, no como texto de uso."""

    def error(self, message):
        fail('Argumentos no válidos: %s' % message, usage=self.format_usage().strip())


def main(argv):
    # admite el estilo de ea-cli: -Path, -Spec, -File...
    argv = ['--' + x[1:].lower() if re.fullmatch(r'-[A-Za-z][A-Za-z]+', x) else x for x in argv]
    ap = JsonArgumentParser(prog='blender-cli', description='Puente local con Blender')
    sub = ap.add_subparsers(dest='cmd', parser_class=JsonArgumentParser)

    def p(name, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument('--file', help='trabajar sin interfaz sobre este .blend')
        return sp

    p('status')
    p('doctor')
    p('setup')
    sp = p('launch')
    sp.add_argument('--wait', type=int, default=90)
    p('info')
    sp = p('scene')
    sp.add_argument('--object')
    sp = p('build')
    sp.add_argument('--spec', required=True)
    sp.add_argument('--save')
    sp.add_argument('--patch')
    sp = p('exec')
    sp.add_argument('--script', required=True)
    sp.add_argument('--save')
    sp = p('save')
    sp.add_argument('--path')
    sp = p('open')
    sp.add_argument('--path', required=True)
    sp = p('render')
    sp.add_argument('--path', required=True)
    sp.add_argument('--preview', action='store_true')
    sp.add_argument('--view')
    sp.add_argument('--engine')
    sp.add_argument('--samples', type=int)
    sp.add_argument('--resolution')
    sp.add_argument('--percentage', type=int)
    sp.add_argument('--camera')
    sp.add_argument('--frame', type=int)
    sp.add_argument('--animation', action='store_true')
    sp.add_argument('--frames')
    sp.add_argument('--objects')
    sp.add_argument('--transparent', action='store_true')
    sp = p('export')
    sp.add_argument('--path', required=True)
    sp.add_argument('--objects')
    sp = p('compare')
    sp.add_argument('--reference', required=True, action='append')
    sp.add_argument('--path', required=True)
    sp.add_argument('--view', action='append')
    sp.add_argument('--objects')
    sp.add_argument('--camera')
    sp.add_argument('--engine')
    sp.add_argument('--samples', type=int)
    sp.add_argument('--frame', type=int)
    sp.add_argument('--preview', action='store_true')
    sp.add_argument('--no-guides', '--noguides', dest='no_guides', action='store_true')
    sp.add_argument('--no-align', '--noalign', dest='no_align', action='store_true')
    sp.add_argument('--no-overlay', '--nooverlay', dest='no_overlay', action='store_true')
    sp.add_argument('--fit-view', '--fitview', dest='fit_view', action='store_true')
    sp = p('fit')
    sp.add_argument('--reference', required=True, action='append')
    sp.add_argument('--parts', required=True)
    sp.add_argument('--fit-view', '--fitview', dest='fit_view', action='store_true')
    sp.add_argument('--view', action='append')
    sp.add_argument('--budget', type=int, default=400)
    sp.add_argument('--detail', type=int, default=160)
    sp.add_argument('--colors', action='store_true')
    sp.add_argument('--colorweight', '--color-weight', dest='colorweight', type=float, default=0.3)
    sp.add_argument('--save')
    sp = p('check')
    sp.add_argument('--objects')
    sp.add_argument('--tolerance', type=float, default=0.004)
    a = ap.parse_args(argv)
    w = copy_warning()
    if w and a.cmd != 'doctor':
        WARNINGS.append(w)

    if a.cmd in (None, 'status'):
        res = cmd_status(a)
    elif a.cmd == 'doctor':
        res = cmd_doctor(a)
    elif a.cmd == 'setup':
        res = cmd_setup(a)
    elif a.cmd == 'launch':
        res = cmd_launch(a)
    elif a.cmd == 'info':
        res = run('info', {}, a)
    elif a.cmd == 'scene':
        res = run('scene', {'object': a.object} if a.object else {}, a)
    elif a.cmd == 'build':
        res = cmd_spec_build(a)
    elif a.cmd == 'exec':
        res = cmd_exec(a)
    elif a.cmd == 'save':
        res = run('save', {'path': os.path.abspath(a.path)} if a.path else {}, a)
    elif a.cmd == 'open':
        if a.file:
            fail('open es para el Blender abierto; con --file ya trabajas sobre ese archivo.')
        res = run('open', {'path': os.path.abspath(a.path)}, a)
    elif a.cmd == 'render':
        res = cmd_render(a)
    elif a.cmd == 'compare':
        res = cmd_compare(a)
    elif a.cmd == 'check':
        res = cmd_check(a)
    elif a.cmd == 'fit':
        res = cmd_fit(a)
    else:
        res = cmd_export(a)
    out(res, 0 if res.get('ok') else 1)


if __name__ == '__main__':
    try:
        main(sys.argv[1:])
    except SystemExit:
        raise
    except KeyboardInterrupt:
        out({'ok': False, 'error': 'Interrumpido.'}, 130)
    except BaseException as e:   # toda salida es JSON, también lo inesperado
        import traceback
        out({'ok': False, 'error': '%s: %s' % (type(e).__name__, e),
             'hint': 'Error inesperado de blender-cli. Ejecuta `doctor`; si persiste, abre un issue con este trace.',
             'trace': traceback.format_exc()[-3000:]}, 1)

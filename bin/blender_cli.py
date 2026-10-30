"""
blender_cli.py - puente local entre el agente y Blender. Sin MCP, sin nube, solo biblioteca estándar.

Dos formas de trabajar:
  en vivo       con Blender abierto y el puente activo (add-on o `launch`): los cambios se ven al momento
  sin interfaz  con --file <archivo.blend>: Blender corre en segundo plano sobre ese archivo

Uso (toda salida es JSON por stdout):
  status                                    ¿Blender instalado? ¿abierto? ¿puente activo?
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

try:
    sys.stdout.reconfigure(encoding='utf-8')
except Exception:
    pass


def out(obj, code=0):
    print(json.dumps(obj, ensure_ascii=False, indent=1, default=str))
    sys.exit(code)


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
    try:
        s = socket.create_connection(('127.0.0.1', PORT), timeout=3)
    except OSError:
        return None
    with s:
        s.settimeout(timeout)
        s.sendall(json.dumps({'cmd': cmd, 'args': args or {}}, ensure_ascii=False).encode('utf-8') + b'\n')
        data = b''
        while not data.endswith(b'\n'):
            chunk = s.recv(1 << 16)
            if not chunk:
                break
            data += chunk
    if not data:
        return {'ok': False, 'error': 'Blender cerró la conexión sin responder'}
    return json.loads(data.decode('utf-8'))


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
        fail('No hay un Blender abierto con el puente activo.',
             hint='Ejecuta `launch` para abrir Blender listo, activa el add-on (`setup`) en tu Blender, '
                  'o usa --file <archivo.blend> para trabajar sin interfaz.',
             blenderRunning=blender_running())
    resp['mode'] = 'live'
    if resp.get('ok') and getattr(a, 'save', None) and cmd in ('build', 'exec'):
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
        fail('No hay un Blender abierto con el puente activo.',
             hint='Usa --file <archivo.blend>, `launch` o activa el add-on con `setup`.')
    if not sv.get('ok'):
        out(sv, 1)
    resp = headless(cmd, args, file=tmp)
    resp['source'] = 'copia del Blender abierto'
    return resp


# ------------------------------------------------------------------------- comandos

def cmd_status(a):
    exe = find_blender()
    ver = version_of(exe) if exe else None
    st = {'ok': True, 'blender': exe, 'version': ver, 'running': blender_running(), 'port': PORT}
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
    with open(a.spec, encoding='utf-8-sig') as f:
        spec = json.load(f)
    spec['_baseDir'] = os.path.dirname(os.path.abspath(a.spec))
    return run('build', spec, a)


def cmd_exec(a):
    with open(a.script, encoding='utf-8-sig') as f:
        code = f.read()
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


def cmd_export(a):
    args = {'path': os.path.abspath(a.path)}
    if a.objects:
        args['objects'] = [x.strip() for x in a.objects.split(',')]
    return on_copy('export', args, a)


def main(argv):
    # admite el estilo de ea-cli: -Path, -Spec, -File...
    argv = ['--' + x[1:].lower() if re.fullmatch(r'-[A-Za-z][A-Za-z]+', x) else x for x in argv]
    ap = argparse.ArgumentParser(prog='blender-cli', description='Puente local con Blender')
    sub = ap.add_subparsers(dest='cmd')

    def p(name, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument('--file', help='trabajar sin interfaz sobre este .blend')
        return sp

    p('status')
    p('setup')
    sp = p('launch')
    sp.add_argument('--wait', type=int, default=90)
    p('info')
    sp = p('scene')
    sp.add_argument('--object')
    sp = p('build')
    sp.add_argument('--spec', required=True)
    sp.add_argument('--save')
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
    a = ap.parse_args(argv)

    if a.cmd in (None, 'status'):
        res = cmd_status(a)
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
    else:
        res = cmd_export(a)
    out(res, 0 if res.get('ok') else 1)


if __name__ == '__main__':
    main(sys.argv[1:])

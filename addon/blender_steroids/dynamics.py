"""
Movimiento con ecuaciones, sin bpy: devuelve un valor por fotograma que build hornea como claves.

  oscillate  cinemático: offset + amplitude·sin(2π·f·t + fase)            (alas, ventiladores, respirar)
  spring     ODE: m·x'' + c·x' + k·x = F, desde x0, v0                     (rebota y se asienta)
  pendulum   ODE: θ'' = -(g/L)·sin θ - b·θ'                                (péndulo real, ángulos grandes)
  follow     ODE: x'' + 2ζω·x' + ω²·x = -ω²·gain·a(t), a = aceleración de otro (antenas, orejas, colas);
             gain = cuánto se inclina (grados o m) por cada m/s² sostenido del guía

Las ODE se integran con RK4 de paso fijo (subpasos dentro de cada fotograma). Cada resultado dice si
es 'kinematic' o 'ode_simulated', con métricas y avisos (aliasing cuando los fps no alcanzan para la
frecuencia). Unidades: s, m, kg; los ángulos en grados, como en el resto del spec.
"""
import bisect
import math
import time

KINDS = ('oscillate', 'spring', 'pendulum', 'follow')
MAX_FRAMES = 20000
MAX_SUBSTEPS = 2000000          # tope de pasos RK4 por movimiento (unos segundos de cálculo)
PASOS_POR_CICLO = 40            # el paso se achica solo para dar al menos esto por ciclo natural


def rk4(f, y, t, dt):
    """Un paso de Runge-Kutta 4 para y' = f(t, y) (y es una lista)."""
    k1 = f(t, y)
    k2 = f(t + dt / 2, [a + dt / 2 * b for a, b in zip(y, k1)])
    k3 = f(t + dt / 2, [a + dt / 2 * b for a, b in zip(y, k2)])
    k4 = f(t + dt, [a + dt * b for a, b in zip(y, k3)])
    return [a + dt / 6 * (b + 2 * c + 2 * d + e) for a, b, c, d, e in zip(y, k1, k2, k3, k4)]


def integrate(f, y0, times, max_step):
    """Estados en cada instante de `times` (crecientes, desde times[0]) con subpasos <= max_step."""
    y, t = list(y0), times[0]
    out = [list(y)]
    for t1 in times[1:]:
        n = max(1, int(math.ceil((t1 - t) / max_step - 1e-9)))
        h = (t1 - t) / n
        for _ in range(n):
            y = rk4(f, y, t, h)
            t += h
        t = t1
        out.append(list(y))
    return out


def _num(m, key, default=None, positive=False, nonneg=False):
    v = m.get(key, default)
    if v is None:
        raise ValueError('motion %s necesita %s' % (m.get('kind'), key))
    v = float(v)
    if not math.isfinite(v):
        raise ValueError('%s debe ser un número finito' % key)
    if positive and v <= 0:
        raise ValueError('%s debe ser mayor que 0' % key)
    if nonneg and v < 0:
        raise ValueError('%s no puede ser negativo' % key)
    return v


def _spring_params(m):
    """Masa, rigidez y amortiguamiento: directos (mass, stiffness, damping) o por frecuencia natural
    (frequency Hz) y razón de amortiguamiento (dampingRatio: 0 sin pérdida, 1 crítico)."""
    masa = _num(m, 'mass', 1.0, positive=True)
    if 'frequency' in m:
        w = 2 * math.pi * _num(m, 'frequency', positive=True)
        k = masa * w * w
        c = 2 * _num(m, 'dampingRatio', 0.1, nonneg=True) * math.sqrt(k * masa)
    else:
        k = _num(m, 'stiffness', positive=True)
        c = _num(m, 'damping', 0.0, nonneg=True)
    return masa, k, c


def natural_frequency(m):
    """Frecuencia característica (Hz) del movimiento, para avisar de aliasing."""
    kind = m.get('kind')
    if kind == 'oscillate':
        return abs(_num(m, 'frequency', positive=True))
    if kind in ('spring', 'follow'):
        if kind == 'follow':
            return _num(m, 'frequency', positive=True)
        masa, k, _ = _spring_params(m)
        return math.sqrt(k / masa) / (2 * math.pi)
    if kind == 'pendulum':
        return math.sqrt(_num(m, 'gravity', 9.81, positive=True) / _num(m, 'length', positive=True)) / (2 * math.pi)
    return 0.0


def simulate(m, times, leader_accel=None):
    """Valores del movimiento `m` en cada instante de `times` (s, desde 0). Para follow, leader_accel
    es la aceleración del objeto guía en esos mismos instantes (m/s²). Devuelve (valores, info)."""
    inicio = time.perf_counter()
    kind = m.get('kind')
    if kind not in KINDS:
        raise ValueError('motion kind debe ser uno de: %s' % ', '.join(KINDS))
    if not times:
        raise ValueError('No hay instantes que calcular')
    if len(times) > MAX_FRAMES:
        raise ValueError('Demasiados fotogramas (%d, máximo %d)' % (len(times), MAX_FRAMES))
    if not all(math.isfinite(t) for t in times):
        raise ValueError('Los instantes deben ser números finitos')
    if any(b <= a for a, b in zip(times, times[1:])):
        raise ValueError('Los instantes deben ser estrictamente crecientes')
    # paso de integración: el pedido (o 1/480 s), achicado si el sistema oscila rápido: RK4 se vuelve
    # inestable con paso·ω > 2.8 y pierde precisión mucho antes
    paso = _num(m, 'step', 1 / 480, positive=True)
    if kind != 'oscillate':
        paso = min(paso, 1 / (PASOS_POR_CICLO * natural_frequency(m)))
        subpasos = int(math.ceil((times[-1] - times[0]) / paso))
        if subpasos > MAX_SUBSTEPS:
            raise ValueError('La simulación necesita %d pasos (máximo %d): acorta la duración, sube step o '
                             'baja la frecuencia' % (subpasos, MAX_SUBSTEPS))
    if kind == 'oscillate':
        f = _num(m, 'frequency', positive=True)
        A = _num(m, 'amplitude')
        fase = math.radians(_num(m, 'phase', 0.0))
        off = _num(m, 'offset', 0.0)
        vals = [off + A * math.sin(2 * math.pi * f * t + fase) for t in times]
        modo = 'kinematic'
    elif kind == 'spring':
        masa, k, c = _spring_params(m)
        F = _num(m, 'force', 0.0)
        ys = integrate(lambda t, y: [y[1], (F - c * y[1] - k * y[0]) / masa],
                       [_num(m, 'initial', 0.0), _num(m, 'velocity', 0.0)], times, paso)
        vals = [y[0] for y in ys]
        modo = 'ode_simulated'
    elif kind == 'pendulum':
        g = _num(m, 'gravity', 9.81, positive=True)
        L = _num(m, 'length', positive=True)
        b = _num(m, 'damping', 0.0, nonneg=True)
        ys = integrate(lambda t, y: [y[1], -(g / L) * math.sin(y[0]) - b * y[1]],
                       [math.radians(_num(m, 'initial', 20.0)), math.radians(_num(m, 'velocity', 0.0))], times, paso)
        vals = [math.degrees(y[0]) for y in ys]
        modo = 'ode_simulated'
    else:
        if leader_accel is None or len(leader_accel) != len(times):
            raise ValueError('follow necesita la aceleración del objeto guía (leader)')
        w = 2 * math.pi * _num(m, 'frequency', positive=True)
        z = _num(m, 'dampingRatio', 0.3, nonneg=True)
        gain = _num(m, 'gain', 1.0)

        def acel(t):
            # aceleración del guía interpolada entre fotogramas (búsqueda binaria del tramo)
            if t <= times[0]:
                return leader_accel[0]
            i = bisect.bisect_left(times, t)
            if i >= len(times):
                return leader_accel[-1]
            u = (t - times[i - 1]) / (times[i] - times[i - 1])
            return leader_accel[i - 1] * (1 - u) + leader_accel[i] * u
        ys = integrate(lambda t, y: [y[1], -w * w * gain * acel(t) - 2 * z * w * y[1] - w * w * y[0]],
                       [0.0, 0.0], times, paso)
        vals = [y[0] for y in ys]
        modo = 'ode_simulated'
    malos = sum(1 for v in vals if not math.isfinite(v))
    if malos:
        raise ValueError('La simulación dio %d valores no finitos: revisa los parámetros' % malos)
    lim = m.get('maxAbs')
    info = {'kind': kind, 'mode': modo, 'frames': len(vals),
            'maxAbs': round(max(abs(v) for v in vals), 6) if vals else 0.0, 'warnings': [],
            'elapsedMs': round(1000 * (time.perf_counter() - inicio), 1)}
    if modo == 'ode_simulated':
        info['step'] = paso
        info['substeps'] = int(math.ceil((times[-1] - times[0]) / paso))
    if lim is not None and info['maxAbs'] > float(lim):
        raise ValueError('El movimiento llega a %.4g y el límite (maxAbs) es %s' % (info['maxAbs'], lim))
    return vals, info


def aliasing(freq, fps):
    """Aviso si los fps no alcanzan para una frecuencia: <= 2 muestras por ciclo se ve al revés o
    quieto (Nyquist); menos de 8 se ve entrecortado. Devuelve (error, aviso)."""
    if freq <= 0:
        return None, None
    por_ciclo = fps / freq
    if por_ciclo <= 2:
        return ('A %.3g Hz con %g fps hay %.2g fotogramas por ciclo: el movimiento se vería quieto o al '
                'revés (aliasing). Sube los fps a más de %g o baja la frecuencia.' % (freq, fps, por_ciclo, 8 * freq)), None
    if por_ciclo < 8:
        return None, ('A %.3g Hz con %g fps quedan %.2g fotogramas por ciclo: se verá entrecortado. Para un '
                      'movimiento fluido usa %g fps o más, o baja la frecuencia (en un render, el desenfoque '
                      'de movimiento lo disimula).' % (freq, fps, por_ciclo, 8 * freq))
    return None, None


def spring_exact(m, t):
    """Solución exacta del resorte subamortiguado sin fuerza (para validar el integrador)."""
    masa, k, c = _spring_params(m)
    x0, v0 = float(m.get('initial', 0.0)), float(m.get('velocity', 0.0))
    w0 = math.sqrt(k / masa)
    z = c / (2 * math.sqrt(k * masa))
    if z >= 1:
        raise ValueError('solo subamortiguado')
    wd = w0 * math.sqrt(1 - z * z)
    return math.exp(-z * w0 * t) * (x0 * math.cos(wd * t) + (v0 + z * w0 * x0) / wd * math.sin(wd * t))

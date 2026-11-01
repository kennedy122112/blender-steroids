"""Emparejar las partes finas de una vista con las de la otra: de qué parte de la vista de costado toma
su profundidad y su grosor un trazo medido de frente (y al revés). Sin Blender: se prueba con
tests/test_vistas.py."""
import numpy as np


def profundidad(t, otros):
    """La parte de la otra vista que ocupa las mismas alturas que el trazo t (casi el mismo tramo de z, y
    que sube o baja sin volver): en cada punto de t su centro en la otra vista, y cuánto más fino o
    grueso es ahí (la mediana de sus radios sobre la de t). None si ninguna calza."""
    z = np.array(t['points'])[:, 1]

    def puntas(tr):
        """Altura de la punta pegada al cuerpo y de la libre (o la más baja y la más alta)."""
        zz = np.array(tr['points'])[:, 1]
        if tr['attached'] == ['start']:
            return zz[0], zz[-1]
        if tr['attached'] == ['end']:
            return zz[-1], zz[0]
        return zz.min(), zz.max()

    def largo(tr):
        return float(np.linalg.norm(np.diff(np.array(tr['points']), axis=0), axis=1).sum())
    mejor, solape_max = None, 0.6
    for j, u in enumerate(otros):
        q = np.array(u['points'])
        zq = q[:, 1]
        dz = np.diff(zq)
        if len(dz) < 2 or max((dz > 0).mean(), (dz < 0).mean()) < 0.9:
            continue                                        # vuelve sobre sí misma: no se lee por altura
        # la misma parte se pega al cuerpo y termina a las mismas alturas en las dos vistas (una cola y
        # un brazo pueden solaparse en altura y no ser la misma cosa)
        if max(abs(a_ - b_) for a_, b_ in zip(puntas(t), puntas(u))) > 0.3 * max(largo(t), largo(u)):
            continue
        solape = min(z.max(), zq.max()) - max(z.min(), zq.min())
        solape /= max(z.max() - z.min(), zq.max() - zq.min(), 1e-9)
        if solape > solape_max:
            mejor, solape_max = j, solape
    if mejor is None:
        return None
    u = otros[mejor]
    q = np.array(u['points'])
    orden = np.argsort(q[:, 1])
    rq, rt = np.array(u['radii']), np.array(t['radii'])
    dentro = (z >= q[:, 1].min()) & (z <= q[:, 1].max())
    ratio = float(np.median(rq)) / max(float(np.median(rt[dentro] if dentro.any() else rt)), 1e-9)
    centro = np.interp(z, q[orden, 1], q[orden, 0])

    def fraccion(tr):
        """Fracción del largo de cada punto, desde la punta pegada al cuerpo."""
        pp = np.array(tr['points'])
        s_ = np.concatenate([[0], np.cumsum(np.linalg.norm(np.diff(pp, axis=0), axis=1))])
        s_ = s_ / max(s_[-1], 1e-12)
        return 1 - s_ if tr['attached'] == ['end'] else s_
    # una parte casi horizontal (un brazo estirado hacia adelante) casi no cambia de altura: por altura,
    # un poco de diferencia entre las vistas lleva a otro punto del brazo. Se empareja por la fracción del
    # largo desde donde se pega al cuerpo
    pt = np.array(t['points'])
    largo_t = float(np.linalg.norm(np.diff(pt, axis=0), axis=1).sum())
    if np.ptp(z) < 0.5 * largo_t and len(t['attached']) == 1 and len(u['attached']) == 1:
        su = fraccion(u)
        o_ = np.argsort(su)
        centro = np.interp(fraccion(t), su[o_], q[o_, 0])
    return {'indice': mejor, 'ratio': ratio, 'centro': centro.tolist()}

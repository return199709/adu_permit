"""A-2: floor plan of the new work with its openings and overall dimensions."""
from drawkit.core import *
from . import load, strip

a, r, res, cfg = load(); n = a['new']; w, d = n['w'], n['d']
v = View(9.0, 7.0)
f = Floor(v, [(0, 0), (w, 0), (w, d), (0, d)], ext='WALL-NEW')
for o in n.get('openings', []):
    s, e = o['offset'], o['offset'] + o['width']
    p, q = {'north': ((s, 0), (e, 0)), 'south': ((s, d), (e, d)), 'west': ((0, s), (0, e)), 'east': ((w, s), (w, e))}[o['wall']]
    if o['type'] == 'window': f.window(p, q)
    else: f.door(p, q, (w / 2, d / 2), ext=True, slider=o['type'] == 'slider')
    m = ((p[0] + q[0]) / 2, (p[1] + q[1]) / 2); out = {'north': (0, -1.4), 'south': (0, 1.4), 'west': (-1.6, 0), 'east': (1.6, 0)}[o['wall']]
    text('DIM-NEW', v.p(m[0] + out[0], m[1] + out[1]), ftin(o['width']), 0.07, 'c', 90 if o['wall'] in ('west', 'east') else 0)
f.render()
for rm in n.get('rooms', [{'name': n['name'], 'x': w / 2, 'y': d / 2}]): room(v, rm['x'], rm['y'], rm['name'].upper())
text('NOTE', v.p(w / 2, d / 2 + 1.6), f"{ftin(w)} × {ftin(d)} = {w * d:,.0f} SF", 0.085)
dim(v, (0, 0), (w, 0), -4.0, ftin(w), layer='DIM-NEW'); dim(v, (0, 0), (0, d), -4.0, ftin(d), layer='DIM-NEW')
text('ROOM', v.p(w / 2, d + 7), 'FLOOR PLAN — ' + n['name'].upper(), 0.2, bold=True); text('NOTE', v.p(w / 2, d + 8.6), "SCALE: 1/4\" = 1'-0\"   ·   NORTH IS UP", 0.1)
strip(a, 'FLOOR PLAN', 'A-2', ['Outside dimensions and openings as', 'reported by the owner. Interior', 'layout is not drawn unless supplied.'])

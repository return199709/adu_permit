"""A-1: site plan (lot, streets, setbacks, buildings, yards) and roof plan."""
from drawkit import core, sheet, roof
from drawkit.core import *
from . import load, strip

a, r, res, cfg = load(); lot = a['lot']; n = a['new']; W, D = lot['width_ft'], lot['depth_ft']
sc = 0.1 if max(W, D) <= 150 else 0.05; core.set_scale(sc)
rad = lot.get('corner_radius_ft') or 0
LOT = [(0, 0), (W, 0)] + (arc_pts((W - rad, D - rad), rad, 0, 90, 16) if rad else [(W, D)]) + [(0, D)]
v = View(3.0, 6.0)
line('PL', *[v.p(*q) for q in LOT], closed=True)
streets = lot.get('streets', {}); off = 14
for side, name in streets.items():
    if side in ('north', 'south'): text('ROOM', v.p(W / 2, -off if side == 'north' else D + off), name.upper(), 0.15, bold=True)
    else: text('ROOM', v.p(-off if side == 'west' else W + off, D / 2), name.upper(), 0.15, 'c', 90, bold=True)
# setback lines from the reviewed rules
sb = {s: 0 for s in ('north', 'east', 'south', 'west')}
for x in [x for x in r['rules'] if x['kind'] == 'setback' and (x['reviewed'] or cfg.get('allow_draft'))]:
    for s, role in res['roles'].items():
        if role == x['params']['side']: sb[s] = max(sb[s], x['params']['feet'])
if any(sb.values()):
    line('SETBK', v.p(sb['west'], sb['north']), v.p(W - sb['east'], sb['north']), v.p(W - sb['east'], D - sb['south']), v.p(sb['west'], D - sb['south']), closed=True)
    text('NOTE', v.p(W / 2, sb['north'] + 1.6), 'SETBACK LINE', 0.05)
wings = [(w['x'], w['x'] + w['w'], w['y'], w['y'] + w['d'], w.get('plate_ft', 9)) for w in a['existing']['wings']] + [(n['x'], n['x'] + n['w'], n['y'], n['y'] + n['d'], n.get('plate_ft', 9))]
faces, outline = roof.hip_roof(wings)
rect = lambda w: [(w[0], w[2]), (w[1], w[2]), (w[1], w[3]), (w[0], w[3])]
roof.draw_roof(v, faces, outline)
fill('TINT', [v.p(*q) for q in rect(wings[-1])])
for w in wings: line('FOOT', *[v.p(*q) for q in rect(w)], closed=True)
for w in a['existing']['wings']: text('NOTE', v.p(w['x'] + w['w'] / 2, w['y'] + w['d'] / 2), w['name'].upper(), 0.065)
text('FLAG', v.p(n['x'] + n['w'] / 2, n['y'] + n['d'] / 2), f"{n['name'].upper()}  {n['w'] * n['d']:,.0f} SF", 0.065, bold=True)
cx, cy = n['x'] + n['w'] / 2, n['y'] + n['d'] / 2
for a_, b_ in [((cx, 0), (cx, n['y'])), ((cx, n['y'] + n['d']), (cx, D)), ((0, cy), (n['x'], cy)), ((n['x'] + n['w'], cy), (W, cy))]:
    dim(v, a_, b_, 0.01, ftin(abs(a_[0] - b_[0]) + abs(a_[1] - b_[1])))
text('NOTE', v.p(W / 2, -2.4), f"PROPERTY LINE  {W:g}'", 0.08, bold=True); text('NOTE', v.p(-2.6, D / 2), f"PROPERTY LINE  {D:g}'", 0.08, 'c', 90, bold=True)
poc = (a.get('utilities') or {}).get('sewer_poc')
if poc:
    q = (poc['x'], poc['y']); line('SEWER', *[v.p(*z) for z in arc_pts(q, 1.0, 0, 360, 20)]); line('SEWER', v.p(q[0] - 1, q[1]), v.p(q[0] + 1, q[1])); line('SEWER', v.p(q[0], q[1] - 1), v.p(q[0], q[1] + 1))
    line('SEWER', v.p(*q), v.p(cx, cy)); text('SEWER', v.p(q[0] + 2, q[1] - 1.5), 'SEWER POINT OF CONNECTION', 0.055, 'l')
text('ROOM', v.p(W / 2, D + 26), 'SITE PLAN', 0.2, bold=True); text('NOTE', v.p(W / 2, D + 26 + 0.3 / sc), f"SCALE: 1\" = {1 / sc:g}'", 0.1)
sheet.north_arrow(3.0 + (W + 8) * sc, 6.0 + (D - 6) * sc)
# roof plan
x0 = min(w[0] for w in wings); x1 = max(w[1] for w in wings); y0 = min(w[2] for w in wings); y1 = max(w[3] for w in wings)
rs = 0.1875 if (x1 - x0) <= 80 and (y1 - y0) <= 90 else 0.125
rv = View(20.5 - x0 * rs + 2 * rs, 6.5 - y0 * rs, sc=rs)
roof.draw_roof(rv, faces, outline)
for w in wings: line('FOOT', *[rv.p(*q) for q in rect(w)], closed=True)
text('ROOM', rv.p((x0 + x1) / 2, y1 + 8), 'ROOF PLAN', 0.2, bold=True)
text('NOTE', rv.p((x0 + x1) / 2, y1 + 8 + 0.3 / rs), f"SCALE: {'3/16' if rs > 0.15 else '1/8'}\" = 1'-0\"   ·   4:12 HIPS ASSUMED   ·   DASHED = WALLS BELOW", 0.1)
strip(a, 'SITE AND ROOF PLAN', 'A-1', ['Distances are from the new work to', 'the property lines as reported by the', 'owner. Roof planes are computed.'])

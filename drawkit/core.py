"""Drawing primitives, layers, views, dimensions, tables and a floor-plan wall model.

A sheet module draws by calling line(), fill() and text(); every call appends a primitive to PR.
drawkit.render then writes PR to a PDF and a DXF.  Model units are feet (x right, y down);
sheet units are inches from the top-left corner.
"""
import math
from shapely.geometry import Polygon, LineString, Point
from shapely.ops import unary_union

SC = 0.25                       # sheet inches per model foot (1/4" = 1'-0")
SHEET_W, SHEET_H = 42.0, 30.0   # sheet size in inches
DXF_PREFIX = 'A-'               # prefix of every DXF layer name
PR = []                         # primitives: (kind, layer, data)

def set_scale(inches_per_foot):
    """Set the default scale for View objects created without their own scale."""
    global SC
    SC = inches_per_foot

# ---------------------------------------------------------------- layers
# name: (rgb 0-1, line width in points, dash pattern or None, AutoCAD colour index).  ORDER is the drawing order.
LAYERS = {
    'TINT':     ((0.93, 0.93, 0.90), 0.3, None, 254),
    # site
    'CURB':     ((0.45, 0.45, 0.45), 0.4, None, 8),
    'SETBK':    ((0.35, 0.35, 0.35), 0.45, (2, 3), 9),
    'FOOT':     ((0.30, 0.30, 0.30), 0.45, (5, 3), 9),
    'ROOF-LT':  ((0.25, 0.25, 0.25), 0.4, None, 8),
    'ROOF':     ((0.05, 0.05, 0.05), 0.9, None, 7),
    'ROW-CL':   ((0.35, 0.35, 0.35), 0.5, (10, 3, 2, 3), 8),
    'ESMT':     ((0.75, 0.25, 0.10), 0.7, (4, 3), 30),
    'PL':       ((0, 0, 0), 1.6, (14, 3, 3, 3), 7),
    # section details
    'S-FILL':   ((0.86, 0.86, 0.84), 0.3, None, 254),
    'S-LT':     ((0.40, 0.40, 0.40), 0.3, None, 8),
    'S-MED':    ((0.10, 0.10, 0.10), 0.55, None, 7),
    'S-HID':    ((0.15, 0.15, 0.15), 0.6, (4, 2.5), 9),
    'S-PLY':    ((0, 0, 0), 2.2, (1.2, 1.2), 3),
    'S-CUT':    ((0.05, 0.05, 0.05), 1.0, None, 7),
    'S-BAR':    ((0, 0, 0), 1.7, None, 1),
    # plans
    'WALL-INT': ((0.42, 0.42, 0.42), 0.4, None, 8),
    'WALL-EXT': ((0.08, 0.08, 0.08), 0.6, None, 7),
    'WALL-NEW': ((0.00, 0.36, 0.38), 0.6, None, 132),
    'NEW-LT':   ((0.00, 0.36, 0.38), 0.4, None, 132),
    'STAIR':    ((0.35, 0.35, 0.35), 0.35, None, 9),
    # elevations
    'ELEV-XL':  ((0.66, 0.66, 0.66), 0.25, None, 9),
    'ELEV-LT':  ((0.35, 0.35, 0.35), 0.35, None, 8),
    'DASH':     ((0.35, 0.35, 0.35), 0.5, (4, 3), 9),
    'REF':      ((0.75, 0.25, 0.10), 0.7, (6, 3), 30),
    'OPENING':  ((0.15, 0.15, 0.15), 0.45, None, 7),
    'ELEV':     ((0.05, 0.05, 0.05), 0.75, None, 7),
    'UNDOC':    ((0.75, 0.25, 0.10), 0.8, None, 30),
    'GROUND':   ((0, 0, 0), 1.8, None, 7),
    'SEWER':    ((0.0, 0.2, 0.85), 0.9, None, 5),
    # annotation
    'DIM':      ((0.10, 0.30, 0.55), 0.4, None, 5),
    'DIM-NEW':  ((0.00, 0.42, 0.40), 0.4, None, 132),
    'THIN':     ((0, 0, 0), 0.5, None, 7),
    'BORDER':   ((0, 0, 0), 1.6, None, 7),
    'NOTE':     ((0.15, 0.15, 0.15), 0.4, None, 7),
    'ROOM':     ((0.05, 0.05, 0.05), 0.4, None, 7),
    'FLAG':     ((0.75, 0.25, 0.10), 0.5, None, 30),
}
ORDER = list(LAYERS)
WHITE_FILLED = {'OPENING'}      # closed outlines on these layers are filled white (window and door symbols mask the wall)

def add_layer(name, rgb, width, dash=None, aci=7, before=None):
    """Define a layer.  It is drawn just before the layer named in `before` (default: before the dimensions)."""
    LAYERS[name] = (tuple(rgb), width, dash, aci)
    if name in ORDER: ORDER.remove(name)
    ORDER.insert(ORDER.index(before or 'DIM'), name)

# ---------------------------------------------------------------- primitives
def line(layer, *pts, closed=False): PR.append(('pl', layer, (list(pts), closed, False)))
def fill(layer, pts):                PR.append(('pl', layer, (list(pts), True, True)))
def text(layer, p, s, h=0.11, align='c', rot=0, bold=False):
    """Text of cap height h inches, centred vertically on p.  align: 'l', 'c' or 'r'."""
    PR.append(('tx', layer, (p, s, h, align, rot, bold)))

class View:
    """Places model coordinates (feet) on the sheet: origin at (ox, oy) inches, optional own scale."""
    def __init__(s, ox, oy, sc=None): s.ox, s.oy, s.sc = ox, oy, sc
    def p(s, x, y=None):
        if y is None: x, y = x
        k = s.sc or SC
        return (s.ox + x * k, s.oy + y * k)
    def pts(s, seq): return [s.p(q) for q in seq]

def ftin(v, plusminus=False):
    """Decimal feet -> feet and inches to the nearest half inch, e.g. 12.54 -> 12'-6½"."""
    half = round(v * 24)
    ft, rem = divmod(half, 24)
    inch, h = divmod(rem, 2)
    s = f"{ft}'-{inch}" + ("½" if h else "") + '"'
    return s + ("±" if plusminus else "")

# ---------------------------------------------------------------- geometry helpers
def arc_pts(c, r, a0, a1, n=14):
    return [(c[0] + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)),
             c[1] + r * math.sin(math.radians(a0 + (a1 - a0) * i / n))) for i in range(n + 1)]

def bez(p0, c1, c2, p3, n=10):
    """Sample a cubic Bezier curve."""
    return [tuple(round((1-t)**3*p0[i] + 3*(1-t)**2*t*c1[i] + 3*(1-t)*t*t*c2[i] + t**3*p3[i], 3) for i in (0, 1))
            for t in [k / n for k in range(n + 1)]]

TE, TI = 0.5, 0.36     # exterior / interior wall thickness (ft)

def seg(a, b, t):      # wall rectangle about a centre-line
    return LineString([a, b]).buffer(t / 2, cap_style='flat')

def polys(g):
    if g.is_empty: return []
    return [g] if g.geom_type == 'Polygon' else [q for q in g.geoms if q.geom_type == 'Polygon']

def draw_region(v, layer, g):
    """Fill a shapely region (holes respected) on a layer."""
    for pg in polys(g):
        PR.append(('cp', layer, [v.pts(list(pg.exterior.coords))] + [v.pts(list(r.coords)) for r in pg.interiors]))

# ---------------------------------------------------------------- floor-plan wall model
class Floor:
    """Walls of one storey.  Give the outside outline; add interior walls, doors and windows; render().

    The exterior wall is the outline offset inward by TE.  Doors and windows cut the walls and draw their symbols.
    """
    def __init__(s, v, outline, ext='WALL-EXT', int_='WALL-INT'):
        s.v = v; s.lay_ext, s.lay_int = ext, int_
        s.out = Polygon(outline); s.inner = s.out.buffer(-TE, join_style='mitre', mitre_limit=4)
        s.ext = s.out.difference(s.inner); s.int = []; s.cuts = []; s.sym = []
    def wall(s, a, b, t=TI): s.int.append(seg(a, b, t))
    def extwall(s, a, b, t=TE): s.ext = s.ext.union(seg(a, b, t))
    def _n(s, a, b, toward=None):
        ux, uy = b[0] - a[0], b[1] - a[1]; L = math.hypot(ux, uy); ux, uy = ux / L, uy / L
        n = (-uy, ux); m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        if toward is None:   # point to building interior
            if not s.out.contains(Point(m[0] + n[0] * 0.25, m[1] + n[1] * 0.25)): n = (uy, -ux)
        else:
            if (toward[0] - m[0]) * n[0] + (toward[1] - m[1]) * n[1] < 0: n = (uy, -ux)
        return n
    def window(s, a, b):
        """a, b on the exterior face."""
        n = s._n(a, b); t = TE
        q = [a, b, (b[0] + n[0] * t, b[1] + n[1] * t), (a[0] + n[0] * t, a[1] + n[1] * t)]
        s.cuts.append(Polygon(q).buffer(0.02))
        mid = [(a[0] + n[0] * t / 2, a[1] + n[1] * t / 2), (b[0] + n[0] * t / 2, b[1] + n[1] * t / 2)]
        s.sym.append(('win', q, mid))
    def door(s, h, k, toward, ext=False, double=False, slider=False, overhead=False):
        """h = hinge, k = strike, both on the wall centre-line (interior) or the exterior face (ext=True).
        The leaf swings toward the point `toward`."""
        if ext:
            n0 = s._n(h, k); t = TE
            q = Polygon([h, k, (k[0] + n0[0] * t, k[1] + n0[1] * t), (h[0] + n0[0] * t, h[1] + n0[1] * t)])
            s.cuts.append(q.buffer(0.02))
            h = (h[0] + n0[0] * t / 2, h[1] + n0[1] * t / 2); k = (k[0] + n0[0] * t / 2, k[1] + n0[1] * t / 2)
        else:
            s.cuts.append(LineString([h, k]).buffer(TI / 2 + 0.08, cap_style='flat'))
        n = s._n(h, k, toward); w = math.dist(h, k)
        if slider or overhead:
            s.sym.append(('sl' if slider else 'oh', h, k, n)); return
        leaves = [(h, k, w)] if not double else [(h, ((h[0] + k[0]) / 2, (h[1] + k[1]) / 2), w / 2),
                                                 (k, ((h[0] + k[0]) / 2, (h[1] + k[1]) / 2), w / 2)]
        for hh, kk, ww in leaves:
            tip = (hh[0] + n[0] * ww, hh[1] + n[1] * ww)
            a0 = math.degrees(math.atan2(kk[1] - hh[1], kk[0] - hh[0])); a1 = math.degrees(math.atan2(n[1], n[0]))
            d = (a1 - a0 + 180) % 360 - 180
            s.sym.append(('door', hh, tip, arc_pts(hh, ww, a0, a0 + d, 10)))
    def render(s):
        v = s.v; cuts = unary_union(s.cuts) if s.cuts else Polygon()
        ext = s.ext.difference(cuts)
        inn = unary_union(s.int).intersection(s.inner).difference(cuts).difference(s.ext) if s.int else Polygon()
        draw_region(v, s.lay_int, inn); draw_region(v, s.lay_ext, ext)
        for sy in s.sym:
            if sy[0] == 'win':
                line('OPENING', *v.pts(sy[1]), closed=True); line('OPENING', *v.pts(sy[2]))
            elif sy[0] == 'door':
                line('OPENING', v.p(sy[1]), v.p(sy[2])); line('STAIR', *v.pts(sy[3]))
            elif sy[0] == 'sl':
                h, k, n = sy[1:]; m = ((h[0] + k[0]) / 2, (h[1] + k[1]) / 2); o = 0.09
                line('OPENING', v.p(h[0] + n[0] * o, h[1] + n[1] * o), v.p(m[0] + n[0] * o + (k[0]-h[0])*0.04, m[1] + n[1] * o + (k[1]-h[1])*0.04))
                line('OPENING', v.p(m[0] - n[0] * o - (k[0]-h[0])*0.04, m[1] - n[1] * o - (k[1]-h[1])*0.04), v.p(k[0] - n[0] * o, k[1] - n[1] * o))
            elif sy[0] == 'oh':
                line('DASH', v.p(sy[1]), v.p(sy[2]))

# ---------------------------------------------------------------- dimensions, labels, tables
TH = 0.105   # dimension text height (in)
def dim(v, a, b, off, txt, label_only=False, layer='DIM'):
    """Dimension between model points a and b on a horizontal or vertical segment.
    off = signed distance (ft) from the segment to the dimension line."""
    horiz = abs(a[1] - b[1]) < 1e-6
    sgn = 1 if off > 0 else -1; g = 0.45; e = 0.45; tk = 0.32
    if horiz:
        y = a[1] + off; pa, pb = (a[0], y), (b[0], y)
        if not label_only:
            for q in (a, b): line(layer, v.p(q[0], q[1] + sgn * g), v.p(q[0], y + sgn * e))
        tp = ((a[0] + b[0]) / 2, y + sgn * 0.62 if not label_only else y); rot = 0
    else:
        x = a[0] + off; pa, pb = (x, a[1]), (x, b[1])
        if not label_only:
            for q in (a, b): line(layer, v.p(q[0] + sgn * g, q[1]), v.p(x + sgn * e, q[1]))
        tp = (x + sgn * 0.62 if not label_only else x, (a[1] + b[1]) / 2); rot = 90
    if not label_only:
        line(layer, v.p(pa), v.p(pb))
        for q in (pa, pb): line(layer, v.p(q[0] - tk, q[1] + tk), v.p(q[0] + tk, q[1] - tk))
    text(layer, v.p(tp), txt, TH, 'c', rot)

def room(v, x, y, name, sub=None, h=0.13, rot=0):
    """Room name with optional small lines of text under it."""
    text('ROOM', v.p(x, y), name, h, 'c', rot, bold=True)
    if sub:
        for i, sline in enumerate(sub if isinstance(sub, (list, tuple)) else [sub]):
            dx, dy = (0, 0.75 + 0.6 * i) if rot == 0 else (0.75 + 0.6 * i, 0)
            text('NOTE', v.p(x + dx, y + dy), sline, 0.075, 'c', rot)

def table(x, y, widths, rows, title, rh=0.27, hs=0.085, head=True):
    """Table at sheet position (x, y) inches.  A cell given as a 1-tuple is drawn in the FLAG colour.
    Returns the y of the bottom edge."""
    W = sum(widths); text('ROOM', (x, y - 0.12), title, 0.12, 'l', bold=True)
    for r, row in enumerate(rows):
        yy = y + r * rh; cx = x
        if head and r == 0: fill('TINT', [(x, yy), (x + W, yy), (x + W, yy + rh), (x, yy + rh)])
        for c, cell in enumerate(row):
            flag = isinstance(cell, tuple); s = cell[0] if flag else cell
            al = 'l' if c == 0 else 'r'
            text('FLAG' if flag else 'NOTE', (cx + 0.07 if al == 'l' else cx + widths[c] - 0.07, yy + rh / 2), s, hs, al, bold=(head and r == 0))
            cx += widths[c]
        line('THIN', (x, yy + rh), (x + W, yy + rh))
    line('THIN', (x, y), (x + W, y), (x + W, y + len(rows) * rh), (x, y + len(rows) * rh), closed=True)
    cx = x
    for w in widths[:-1]:
        cx += w; line('THIN', (cx, y), (cx, y + len(rows) * rh))
    return y + len(rows) * rh

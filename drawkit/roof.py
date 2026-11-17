"""Hip-roof plan from the rectangles of a building's wings.

Each wing gets a hip roof of the given pitch with its eave overhanging the walls; where roofs of different
wings overlap, the higher surface wins.  The result is the set of visible roof planes (hips, ridges and
valleys fall out as their edges) and the outline of the eaves.  Intersections are computed on a grid, so
they are accurate to about the grid size."""
import numpy as np
from shapely.geometry import box
from shapely.ops import unary_union
from .core import line

def hip_roof(wings, pitch=4 / 12, eave=2.0, grid=0.125):
    """wings: [(x0, x1, y0, y1, plate_height_ft), ...] in model feet.  Returns (faces, outline):
    faces is a list of shapely polygons, one per roof plane; outline is the eave outline."""
    x0 = min(w[0] for w in wings) - eave - 2; x1 = max(w[1] for w in wings) + eave + 2
    y0 = min(w[2] for w in wings) - eave - 2; y1 = max(w[3] for w in wings) + eave + 2
    xs = np.arange(x0, x1, grid) + grid / 2; ys = np.arange(y0, y1, grid) + grid / 2; X, Y = np.meshgrid(xs, ys)
    Z = np.full(X.shape, -1e9); LAB = np.full(X.shape, -1, int)
    for code, (a, b, c, d, plate) in enumerate(wings):
        dist = np.stack([X - (a - eave), (b + eave) - X, Y - (c - eave), (d + eave) - Y]); m = dist.min(0); f = dist.argmin(0)
        z = np.where(m >= 0, plate + pitch * m, -1e9); up = z > Z + 1e-9
        Z = np.where(up, z, Z); LAB = np.where(up, code * 4 + f, LAB)
    faces = []
    for lab in np.unique(LAB):
        if lab < 0: continue
        cells = []
        for j in range(LAB.shape[0]):
            row = LAB[j] == lab
            if not row.any(): continue
            idx = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
            for a, b in zip(idx[::2], idx[1::2]): cells.append(box(xs[a] - grid / 2, ys[j] - grid / 2, xs[b - 1] + grid / 2, ys[j] + grid / 2))
        g = unary_union(cells).simplify(grid * 2)
        faces += [p for p in (g.geoms if g.geom_type == 'MultiPolygon' else [g]) if p.area > 1.5]
    outline = unary_union(faces).buffer(0.2).buffer(-0.2).simplify(grid * 2)
    return faces, outline

def draw_roof(v, faces, outline, T=lambda q: q, edge='ROOF', inner='ROOF-LT'):
    """Draw roof planes and the eave outline in view v.  T maps model points (e.g. building -> lot coordinates)."""
    for pg in faces: line(inner, *[v.p(*T(q)) for q in pg.exterior.coords])
    for pg in (outline.geoms if outline.geom_type == 'MultiPolygon' else [outline]):
        line(edge, *[v.p(*T(q)) for q in pg.exterior.coords])

"""Prototype: turn one cleaned plan sheet into centerline vectors (DXF + SVG).

Install:  pip install pymupdf opencv-python-headless numpy scipy scikit-image ezdxf
Run:      python vectorize_plan.py cleaned_blueprint.pdf 1 page1
          -> page1.dxf, page1.svg (scan underlay + vectors), page1_overlay.png

Tuned on sheet 1 only. Lines are traced as found: they are not snapped to
horizontal/vertical or joined at corners, and lettering, symbols and hatching
are left as plain polylines (layer DETAIL), not read as text or objects.
"""
import base64
import sys
from collections import defaultdict

import cv2
import ezdxf
import numpy as np
import pymupdf  # PyMuPDF
from ezdxf.lldxf import const
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.spatial import cKDTree
from skimage.morphology import skeletonize

DRAWING_SCALE = 48  # 1/4" = 1'-0": one inch on paper is 48 inches of building

# layer -> (DXF colour index, SVG colour, what it holds)
LAYERS = {
  "HEAVY_LINES": (1, "#e00000", "thick straight lines: walls, borders"),
  "LINES": (5, "#0000e0", "thin straight lines: dimensions, edges"),
  "LINES_DASHED": (3, "#00a000", "dashed or broken straight lines"),
  "ARCS": (4, "#00b8d4", "arcs and circles: door swings, symbols"),
  "HEAVY_DETAIL": (6, "#d000d0", "thick curves and shapes"),
  "DETAIL": (30, "#ff8c00", "lettering, symbols, free curves (not interpreted)"),
}

OFFSETS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))


def load_ink(pdf_path, page_no):
  """Returns (ink, dpi): the page's scan as a boolean mask (True = ink) at its
  native resolution, and that resolution in pixels per inch of paper."""
  page = pymupdf.open(pdf_path)[page_no - 1]
  images = page.get_images(full=True)
  if len(images) != 1:
    sys.exit(f"Page {page_no} is not a single scanned image ({len(images)} images found).")
  xref, _, width, height = images[0][:4]
  rect = page.get_image_rects(xref)[0]
  pix = page.get_pixmap(
      matrix=pymupdf.Matrix(width / rect.width, height / rect.height),
      colorspace=pymupdf.csGRAY,
      alpha=False,
  )
  ink = np.frombuffer(pix.samples, np.uint8).reshape(pix.h, pix.w) < 128
  return ink, width / rect.width * 72


def trace_skeleton(skel, spur_len=10):
  """Turns a 1-px-wide skeleton into strokes.

  Skeleton pixels with exactly two neighbours are chained into branches; end
  points and junctions (and the clusters they form) are the graph nodes.
  Short spurs hanging off a junction are rough-edge noise and are dropped, and
  a node left with only two branches is dissolved so the stroke runs through it.

  Returns a list of (points, closed): points is an (n, 2) float array of
  (x, y) pixel coordinates, closed marks a loop with no junction.
  """
  pad = np.pad(skel, 1)
  ys, xs = np.nonzero(pad)
  idx = np.full(pad.shape, -1, np.int32)
  idx[ys, xs] = np.arange(len(ys), dtype=np.int32)
  nb = np.stack([idx[ys + dy, xs + dx] for dy, dx in OFFSETS], axis=1)
  is_node = (nb >= 0).sum(axis=1) != 2  # end points and junction pixels

  node_img = np.zeros(pad.shape, np.uint8)
  node_img[ys[is_node], xs[is_node]] = 1
  _, node_lab = cv2.connectedComponents(node_img, connectivity=8)
  chain_img = np.zeros(pad.shape, np.uint8)
  chain_img[ys[~is_node], xs[~is_node]] = 1
  _, chain_lab = cv2.connectedComponents(chain_img, connectivity=8)
  node_of = node_lab[ys, xs]
  chain_of = chain_lab[ys, xs]

  n_nodes = int(node_of.max()) + 1
  count = np.bincount(node_of, minlength=n_nodes).clip(1)
  node_xy = np.stack(
      [np.bincount(node_of, weights=xs, minlength=n_nodes) / count,
       np.bincount(node_of, weights=ys, minlength=n_nodes) / count],
      axis=1,
  ) - 1
  pix_xy = np.stack([xs - 1, ys - 1], axis=1).astype(np.float64)

  # Walk every chain of two-neighbour pixels from one end to the other.
  nbl = nb.tolist()
  node_of_l = node_of.tolist()
  members = np.flatnonzero(chain_of > 0)
  members = members[np.argsort(chain_of[members], kind="stable")]
  groups = np.split(members, np.flatnonzero(np.diff(chain_of[members])) + 1)
  edges = {}  # id -> [node_a, node_b, points]; node 0 means a closed loop
  for eid, group in enumerate(groups):
    group = group.tolist()
    gset = set(group)
    start = group[0]
    for i in group:
      if sum(1 for j in nbl[i] if j in gset) <= 1:
        start = i
        break
    path, seen, cur = [start], {start}, start
    while True:
      nxt = [j for j in nbl[cur] if j in gset and j not in seen]
      if not nxt:
        break
      cur = nxt[0]
      path.append(cur)
      seen.add(cur)

    def end_node(i, skip=0):
      for j in nbl[i]:
        if j >= 0 and node_of_l[j] > 0 and node_of_l[j] != skip:
          return node_of_l[j]
      return 0

    a = end_node(path[0])
    b = end_node(path[-1], skip=a if len(path) == 1 else 0) or a
    pts = pix_xy[path]
    if a:
      pts = np.vstack([node_xy[a], pts, node_xy[b]])
    edges[eid] = [a, b, pts]

  node_deg = defaultdict(int)
  inc = defaultdict(set)
  for eid, (a, b, _) in edges.items():
    if a:
      node_deg[a] += 1
      node_deg[b] += 1
      inc[a].add(eid)
      inc[b].add(eid)

  def length(p):
    return float(np.hypot(*np.diff(p, axis=0).T).sum())

  changed = True
  while changed:  # prune spurs: short branch from a junction to a free end
    changed = False
    for eid in [e for e, (a, b, _) in edges.items() if a and a != b]:
      a, b, p = edges[eid]
      ends = (node_deg[a] == 1, node_deg[b] == 1)
      other = b if ends[0] else a
      if ends[0] != ends[1] and node_deg[other] >= 3 and length(p) < spur_len:
        del edges[eid]
        for n in (a, b):
          node_deg[n] -= 1
          inc[n].discard(eid)
        changed = True

  next_id = len(groups)
  changed = True
  while changed:  # dissolve nodes that joined exactly two branches
    changed = False
    for node in [n for n, d in node_deg.items() if d == 2 and len(inc[n]) == 2]:
      if node_deg[node] != 2 or len(inc[node]) != 2:
        continue
      e1, e2 = sorted(inc[node])
      a1, b1, p1 = edges[e1]
      a2, b2, p2 = edges[e2]
      if b1 != node:
        a1, b1, p1 = b1, a1, p1[::-1]
      if a2 != node:
        a2, b2, p2 = b2, a2, p2[::-1]
      del edges[e1], edges[e2]
      inc[a1].discard(e1)
      inc[b2].discard(e2)
      inc[node].clear()
      node_deg[node] = 0
      edges[next_id] = [a1, b2, np.vstack([p1, p2[1:]])]
      inc[a1].add(next_id)
      inc[b2].add(next_id)
      next_id += 1
      changed = True

  return [(p, a == 0) for a, b, p in edges.values() if len(p) >= 2]


def split_heavy(ink):
  """Splits the ink into heavy strokes (walls, borders) and everything else.

  Walls are drawn as stippled bands. Skeletonizing the stipple gives a ladder
  of tiny loops, so the holes in heavy regions are filled first.
  """
  m = ink.astype(np.uint8)
  closed = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
  core = cv2.morphologyEx(
      closed, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (9, 9))
  )
  heavy = cv2.dilate(core, np.ones((3, 3), np.uint8)) & closed
  heavy = cv2.morphologyEx(heavy, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8))
  margin = cv2.dilate(heavy, np.ones((5, 5), np.uint8)) > 0
  light = cv2.morphologyEx(
      (ink & ~margin).astype(np.uint8), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8)
  )
  return heavy, light


def find_strokes(ink):
  """Traces centerlines. Returns a list of (points, closed, width_px, heavy)."""
  heavy_mask, light_mask = split_heavy(ink)
  strokes = []
  for mask, heavy, spur_len in ((heavy_mask, True, 25), (light_mask, False, 10)):
    skel = skeletonize(mask.astype(bool))
    dist = cv2.distanceTransform(mask, cv2.DIST_L2, 3)
    for pts, closed in trace_skeleton(skel, spur_len):
      xy = np.round(pts).astype(int)
      xy[:, 0] = xy[:, 0].clip(0, mask.shape[1] - 1)
      xy[:, 1] = xy[:, 1].clip(0, mask.shape[0] - 1)
      width = 2 * float(np.median(dist[xy[:, 1], xy[:, 0]])) - 1
      strokes.append((pts, closed, max(width, 1.0), heavy))
  return strokes


def path_length(pts):
  return float(np.hypot(*np.diff(pts, axis=0).T).sum())


def simplify(pts, eps, closed=False):
  out = cv2.approxPolyDP(pts.astype(np.float32).reshape(-1, 1, 2), eps, closed)
  return out.reshape(-1, 2).astype(np.float64)


def fit_circle(pts):
  """Least-squares circle through points: (cx, cy, r, rms_error)."""
  x, y = pts[:, 0], pts[:, 1]
  c = np.linalg.lstsq(np.c_[2 * x, 2 * y, np.ones(len(x))], x**2 + y**2, rcond=None)[0]
  r = float(np.sqrt(max(c[2] + c[0] ** 2 + c[1] ** 2, 0.0)))
  return c[0], c[1], r, float(np.sqrt(np.mean((np.hypot(x - c[0], y - c[1]) - r) ** 2)))


def is_smooth_curve(coarse):
  """True when a simplified polyline bends gently, mostly the same way.

  A hand-drawn curve wobbles, so a few vertices may bend the other way; what
  counts is that the bends are gentle and add up to a real turn. A slightly
  wavy straight line bends both ways and nets out to almost nothing.
  """
  if len(coarse) < 4:
    return False
  d = np.diff(coarse, axis=0)
  turn = np.diff(np.arctan2(d[:, 1], d[:, 0]))
  turn = (turn + np.pi) % (2 * np.pi) - np.pi
  mostly_one_way = max(np.mean(turn > 0), np.mean(turn < 0)) >= 0.75
  return bool(mostly_one_way and np.abs(turn).max() <= np.radians(45)
              and abs(turn.sum()) >= np.radians(15))


def chord_deviation(pts):
  """Largest distance of the points from the straight chord through the ends."""
  d = pts[-1] - pts[0]
  n = float(np.hypot(*d))
  if n < 1e-6:
    return float(np.hypot(*(pts - pts[0]).T).max())
  return float(np.abs((pts[:, 0] - pts[0, 0]) * d[1] - (pts[:, 1] - pts[0, 1]) * d[0]).max() / n)


def as_arc(pts, closed, min_r=18, max_r=5000, max_rms=2.0, min_len=60):
  """Returns [cx, cy, r, theta0, dtheta] if the stroke is a circle or arc.

  Curves in lettering are small, so an open arc must be at least `min_len`
  px long; that keeps door swings and symbols and drops the letters.
  """
  cx, cy, r, rms = fit_circle(pts)
  if not (min_r <= r <= max_r and rms <= max_rms):
    return None
  theta = np.unwrap(np.arctan2(pts[:, 1] - cy, pts[:, 0] - cx))
  sweep = theta[-1] - theta[0]
  if closed:
    sweep = 2 * np.pi * (1 if sweep >= 0 else -1)
  elif r * abs(sweep) < min_len or np.any(np.diff(theta) * np.sign(sweep) < -0.1):
    return None
  return [cx, cy, r, theta[0], sweep]


def bridge_dashes(strokes, explained, tol=3.0, gap=60.0, min_frag=4.0,
                  min_count=3, min_span=60.0, min_cover=0.25, band=14.0,
                  max_clutter=1.0):
  """Joins faint fragments that lie on the same horizontal or vertical axis.

  Dash-dot centre lines come out of the scan as many tiny fragments with
  unreliable angles, so they are grouped by position (same x, or same y)
  instead of by direction. Returns (lines, coverage, used): new line rows,
  their inked fraction, and a mask of the strokes they absorbed.
  """
  new_lines, new_cover = [], []
  used = np.zeros(len(strokes), bool)
  centre = np.array([s[0].mean(axis=0) for s in strokes])
  for lat in (0, 1):  # 0: vertical lines (compare x), 1: horizontal (compare y)
    al = 1 - lat
    ids, pos, lo, hi, wid = [], [], [], [], []
    for sid, (pts, closed, width, heavy) in enumerate(strokes):
      if explained[sid] or heavy:
        continue
      extent = np.ptp(pts, axis=0)
      if extent[al] >= min_frag and extent[lat] <= 0.4 * extent[al]:
        ids.append(sid)
        pos.append(np.median(pts[:, lat]))
        lo.append(pts[:, al].min())
        hi.append(pts[:, al].max())
        wid.append(width)
    ids, pos, lo, hi, wid = (np.array(a) for a in (ids, pos, lo, hi, wid))
    order = np.argsort(pos)
    cluster = []
    for k in range(len(order) + 1):
      if k == len(order) or (cluster and pos[order[k]] - pos[order[cluster]].mean() > tol):
        if len(cluster) >= min_count:
          c = order[cluster]
          c = c[np.argsort(lo[c])]
          chains, cur = [], [c[0]]
          for j in c[1:]:
            if lo[j] - hi[cur].max() > gap:
              chains.append(cur)
              cur = []
            cur.append(j)
          chains.append(cur)
          for ch in chains:
            ch = np.array(ch)
            span = hi[ch].max() - lo[ch].min()
            covered, end = 0.0, -np.inf
            for j in ch[np.argsort(lo[ch])]:
              covered += max(0.0, hi[j] - max(lo[j], end))
              end = max(end, hi[j])
            if len(ch) >= min_count and span >= min_span and covered / span >= min_cover:
              p = float(np.average(pos[ch], weights=hi[ch] - lo[ch] + 1))
              a, b = float(lo[ch].min()), float(hi[ch].max())
              # lettering is full of other strokes next to the line, a real
              # dashed line is not
              busy = ((np.abs(centre[:, lat] - p) <= band)
                      & (centre[:, al] >= a - 10) & (centre[:, al] <= b + 10))
              busy[ids[ch]] = False
              clutter = busy.sum() / len(ch)
              if clutter > max_clutter:
                continue
              row = [p, a, p, b] if lat == 0 else [a, p, b, p]
              new_lines.append([*row, float(wid[ch].mean()), 0.0])
              new_cover.append(covered / span)
              used[ids[ch]] = True
        cluster = []
      if k < len(order):
        cluster.append(k)
  return (np.array(new_lines, dtype=np.float64).reshape(-1, 6),
          np.array(new_cover, dtype=np.float64), used)


def build_primitives(strokes, min_piece=12, min_line=60, gap=40.0,
                     line_eps=2.5, poly_eps=1.2):
  """Splits strokes into straight lines, arcs and everything else.

  Straight pieces (even short dashes) are joined across gaps; a joined group
  that adds up to at least `min_line` px is a line. Strokes that fit a circle
  (door swings, round symbols) become arcs. What is left (lettering, symbols,
  free curves) stays as simplified polylines.

  Returns (lines, coverage, arcs, polys). lines rows are [x1, y1, x2, y2,
  width, heavy]; coverage is the inked fraction of each line (dashed or
  broken lines are lower); arcs rows are [cx, cy, r, theta0, dtheta, width,
  heavy] (angles in image coordinates, y down); polys are (points, closed,
  width, heavy).
  """
  pieces, owner, arcs = [], [], []
  explained = np.zeros(len(strokes), bool)
  for sid, (pts, closed, width, heavy) in enumerate(strokes):
    coarse = simplify(pts, line_eps, closed)
    curved = is_smooth_curve(coarse)
    if path_length(pts) >= 30 and (closed or curved or chord_deviation(pts) >= 3.0):
      arc = as_arc(pts, closed)
      if arc is not None:
        arcs.append([*arc, width, heavy])
        explained[sid] = True
        continue
    if curved:
      continue  # a free curve, not a chain of lines
    ring = np.vstack([coarse, coarse[:1]]) if closed else coarse
    straight = [(a, b) for a, b in zip(ring[:-1], ring[1:])
                if np.hypot(*(b - a)) >= min_piece]
    if straight and sum(np.hypot(*(b - a)) for a, b in straight) >= 0.6 * path_length(pts):
      pieces += [[*a, *b, width, heavy] for a, b in straight]
      owner += [sid] * len(straight)
  pieces = np.array(pieces, dtype=np.float64).reshape(-1, 6)
  owner = np.array(owner, dtype=int)

  merged, coverage, group_of = merge_collinear(pieces, gap)
  span = np.hypot(merged[:, 2] - merged[:, 0], merged[:, 3] - merged[:, 1])
  size = np.bincount(group_of, minlength=len(merged))
  good = (span >= min_line) & ((size == 1) | (coverage >= 0.4))

  # a stroke is explained by lines when most of its pieces ended up in one
  total = np.array([path_length(s[0]) for s in strokes])
  piece_len = np.hypot(pieces[:, 2] - pieces[:, 0], pieces[:, 3] - pieces[:, 1])
  kept_len = np.bincount(owner, weights=piece_len * good[group_of], minlength=len(strokes))
  explained |= kept_len >= 0.6 * total

  extra, extra_coverage, used = bridge_dashes(strokes, explained)
  explained |= used
  polys = [(simplify(pts, poly_eps, closed), closed, width, heavy)
           for sid, (pts, closed, width, heavy) in enumerate(strokes)
           if not explained[sid] and total[sid] >= 4]
  return (np.vstack([merged[good], extra]),
          np.concatenate([coverage[good], extra_coverage]),
          np.array(arcs, dtype=np.float64).reshape(-1, 7), polys)


def arc_points(arc, step_deg=4.0):
  """Samples an arc row [cx, cy, r, theta0, dtheta, ...] as an (n, 2) polyline."""
  cx, cy, r, theta0, dtheta = arc[:5]
  n = max(2, int(np.ceil(abs(dtheta) / np.radians(step_deg))) + 1)
  theta = theta0 + dtheta * np.linspace(0, 1, n)
  return np.stack([cx + r * np.cos(theta), cy + r * np.sin(theta)], axis=1)


def merge_collinear(lines, gap=40.0, offset_tol=3.0, angle_tol_deg=3.0):
  """Joins straight pieces that continue each other across a gap.

  Returns (merged, coverage, group_of): merged has the same columns as
  `lines`, coverage is the fraction of each merged line that was actually
  inked, group_of maps every input piece to its merged line.
  """
  n = len(lines)
  if n == 0:
    return lines, np.zeros(0), np.zeros(0, dtype=int)
  p, q = lines[:, :2], lines[:, 2:4]
  length = np.hypot(*(q - p).T)
  u = (q - p) / length[:, None]
  ends = np.vstack([p, q])
  owner = np.concatenate([np.arange(n), np.arange(n)])
  pairs = cKDTree(ends).query_pairs(gap, output_type="ndarray")
  ia, ib = owner[pairs[:, 0]], owner[pairs[:, 1]]
  pa, pb = ends[pairs[:, 0]], ends[pairs[:, 1]]
  v = pb - pa
  cross_a = np.abs(v[:, 0] * u[ia, 1] - v[:, 1] * u[ia, 0])
  cross_b = np.abs(v[:, 0] * u[ib, 1] - v[:, 1] * u[ib, 0])
  parallel = np.abs((u[ia] * u[ib]).sum(axis=1)) >= np.cos(np.radians(angle_tol_deg))
  same_kind = lines[ia, 5] == lines[ib, 5]
  ok = (ia != ib) & parallel & same_kind & (cross_a <= offset_tol) & (cross_b <= offset_tol)
  graph = coo_matrix((np.ones(ok.sum()), (ia[ok], ib[ok])), shape=(n, n))
  n_groups, group_of = connected_components(graph, directed=False)

  merged, coverage = [], []
  for g in range(n_groups):
    ids = np.flatnonzero(group_of == g)
    w = length[ids]
    direction = (u[ids] * np.sign((u[ids] * u[ids[0]]).sum(axis=1))[:, None] * w[:, None]).sum(axis=0)
    direction /= np.hypot(*direction)
    pts = np.vstack([p[ids], q[ids]])
    centre = (pts * np.concatenate([w, w])[:, None]).sum(axis=0) / (2 * w.sum())
    t = (pts - centre) @ direction
    a, b = centre + t.min() * direction, centre + t.max() * direction
    span = t.max() - t.min()
    width = float((lines[ids, 4] * w).sum() / w.sum())
    merged.append([*a, *b, width, lines[ids[0], 5]])
    coverage.append(min(1.0, w.sum() / span))
  return np.array(merged), np.array(coverage), group_of


def line_layer(heavy, coverage):
  return "HEAVY_LINES" if heavy else ("LINES_DASHED" if coverage < 0.8 else "LINES")


def explained_share(ink, lines, arcs, polys):
  """Share of the ink within a stroke's own half-width + 3 px of lines/arcs,
  of detail polylines only, and of nothing."""
  mask = np.zeros(ink.shape, np.uint8)
  for x1, y1, x2, y2, width, _ in lines:
    cv2.line(mask, (round(x1), round(y1)), (round(x2), round(y2)), 1, int(max(7, width + 6)))
  for arc in arcs:
    cv2.polylines(mask, [np.round(arc_points(arc)).astype(np.int32)], False, 1, int(max(7, arc[5] + 6)))
  on_lines = int((ink & (mask > 0)).sum())
  for pts, closed, width, _ in polys:
    cv2.polylines(mask, [np.round(pts).astype(np.int32)], closed, 1, int(max(7, width + 6)))
  on_all = int((ink & (mask > 0)).sum())
  n = int(ink.sum())
  return on_lines / n, (on_all - on_lines) / n, (n - on_all) / n


def write_dxf(path, height, in_per_px, lines, coverage, arcs, polys):
  """DXF in real-world inches (y up), one layer per kind of primitive."""
  doc = ezdxf.new("R2010", setup=True)
  doc.units = ezdxf.units.IN
  doc.header["$LTSCALE"] = 24  # dash pattern sized for a building, not a part
  for name, (colour, _, _) in LAYERS.items():
    doc.layers.add(name, color=colour)
  doc.layers.get("LINES_DASHED").dxf.linetype = "DASHED"
  msp = doc.modelspace()

  def pt(x, y):
    return (x * in_per_px, (height - y) * in_per_px)

  def weight(width_px, dpi=200):  # nearest standard plot weight, 1/100 mm
    return min(const.VALID_DXF_LINEWEIGHTS, key=lambda v: abs(v - width_px * 2540 / dpi))

  for (x1, y1, x2, y2, width, heavy), cov in zip(lines, coverage):
    msp.add_line(pt(x1, y1), pt(x2, y2), dxfattribs={
        "layer": line_layer(heavy, cov), "lineweight": weight(width)})
  for cx, cy, r, theta0, sweep, width, heavy in arcs:
    attribs = {"layer": "ARCS", "lineweight": weight(width)}
    centre = pt(cx, cy)
    if abs(sweep) >= 2 * np.pi - 0.01:
      msp.add_circle(centre, r * in_per_px, dxfattribs=attribs)
      continue
    # image angles run clockwise (y down); DXF arcs run counter-clockwise
    first, last = -theta0, -(theta0 + sweep)
    start, end = (first, last) if sweep < 0 else (last, first)
    msp.add_arc(centre, r * in_per_px, np.degrees(start) % 360, np.degrees(end) % 360,
                dxfattribs=attribs)
  for pts, closed, width, heavy in polys:
    msp.add_lwpolyline([pt(x, y) for x, y in pts], close=closed, dxfattribs={
        "layer": "HEAVY_DETAIL" if heavy else "DETAIL", "lineweight": weight(width)})
  doc.saveas(path)


def write_svg(path, ink, lines, coverage, arcs, polys):
  """SVG in scan pixels: the cleaned scan as a faded underlay plus a group per layer."""
  height, width = ink.shape
  png = cv2.imencode(".png", np.where(ink, 0, 255).astype(np.uint8))[1].tobytes()
  groups = {name: [] for name in LAYERS}

  def points(pts):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

  for (x1, y1, x2, y2, _, heavy), cov in zip(lines, coverage):
    groups[line_layer(heavy, cov)].append(
        f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>')
  for arc in arcs:
    groups["ARCS"].append(f'<polyline points="{points(arc_points(arc))}"/>')
  for pts, closed, _, heavy in polys:
    tag = "polygon" if closed else "polyline"
    groups["HEAVY_DETAIL" if heavy else "DETAIL"].append(f'<{tag} points="{points(pts)}"/>')

  out = [
      f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
      f'viewBox="0 0 {width} {height}">',
      "<style>.v *{vector-effect:non-scaling-stroke;fill:none;stroke-linecap:round}</style>",
      f'<g id="scan" opacity="0.35"><image width="{width}" height="{height}" '
      f'xlink:href="data:image/png;base64,{base64.b64encode(png).decode()}"/></g>',
  ]
  for name, items in groups.items():
    stroke = "2.5" if name == "HEAVY_LINES" else "1.2"
    out.append(f'<g id="{name}" class="v" stroke="{LAYERS[name][1]}" stroke-width="{stroke}">')
    out += items
    out.append("</g>")
  out.append("</svg>")
  with open(path, "w") as f:
    f.write("\n".join(out))


def draw_layers(vis, lines, coverage, arcs, polys, scale=1.0, origin=(0, 0), heavy_px=3):
  """Draws every primitive in its layer colour (BGR) onto `vis`."""
  def bgr(layer):
    h = LAYERS[layer][1]
    return (int(h[5:7], 16), int(h[3:5], 16), int(h[1:3], 16))

  def pix(pts):
    return np.round((np.asarray(pts) - origin) * scale).astype(np.int32)

  for pts, closed, _, heavy in polys:
    cv2.polylines(vis, [pix(pts)], closed, bgr("HEAVY_DETAIL" if heavy else "DETAIL"), 1, cv2.LINE_AA)
  for arc in arcs:
    cv2.polylines(vis, [pix(arc_points(arc))], False, bgr("ARCS"), 2, cv2.LINE_AA)
  for (x1, y1, x2, y2, _, heavy), cov in zip(lines, coverage):
    a, b = pix([[x1, y1], [x2, y2]])
    layer = line_layer(heavy, cov)
    cv2.line(vis, tuple(a), tuple(b), bgr(layer), heavy_px if heavy else 2, cv2.LINE_AA)
  return vis


def write_overlay(path, ink, lines, coverage, arcs, polys, scale=0.5):
  """Whole-page preview: faded scan with the vectors on top and a legend."""
  gray = cv2.resize(np.where(ink, 0, 255).astype(np.uint8), None, fx=scale, fy=scale,
                    interpolation=cv2.INTER_AREA)
  vis = cv2.cvtColor((255 - (255 - gray) * 0.45).astype(np.uint8), cv2.COLOR_GRAY2BGR)
  draw_layers(vis, lines, coverage, arcs, polys, scale)
  y = vis.shape[0] - 24 * len(LAYERS) - 30
  for name, (_, hexcol, text) in LAYERS.items():
    col = (int(hexcol[5:7], 16), int(hexcol[3:5], 16), int(hexcol[1:3], 16))
    cv2.line(vis, (40, y - 6), (90, y - 6), col, 4)
    cv2.putText(vis, f"{name}: {text}", (104, y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (40, 40, 40), 1, cv2.LINE_AA)
    y += 24
  cv2.imwrite(path, vis)


def main(pdf_path, page_no, prefix):
  ink, dpi = load_ink(pdf_path, page_no)
  in_per_px = DRAWING_SCALE / dpi
  print(f"Page {page_no}: {ink.shape[1]}x{ink.shape[0]} px at {dpi:.0f} DPI "
        f"(1 px = {in_per_px:.3f} in at 1/4\" = 1'-0\")")
  strokes = find_strokes(ink)
  lines, coverage, arcs, polys = build_primitives(strokes)
  heavy = lines[:, 5] > 0
  dashed = ~heavy & (coverage < 0.8)
  print(f"{len(strokes):,} strokes -> {int(heavy.sum())} heavy lines, "
        f"{int((~heavy & ~dashed).sum())} thin lines, {int(dashed.sum())} dashed/broken lines, "
        f"{len(arcs)} arcs, {len(polys):,} detail polylines")
  on_lines, on_detail, rest = explained_share(ink, lines, arcs, polys)
  print(f"Ink explained by lines and arcs: {100 * on_lines:.1f}%, only by detail polylines: "
        f"{100 * on_detail:.1f}%, by nothing: {100 * rest:.1f}%")
  write_dxf(f"{prefix}.dxf", ink.shape[0], in_per_px, lines, coverage, arcs, polys)
  write_svg(f"{prefix}.svg", ink, lines, coverage, arcs, polys)
  write_overlay(f"{prefix}_overlay.png", ink, lines, coverage, arcs, polys)
  print(f"Saved {prefix}.dxf, {prefix}.svg, {prefix}_overlay.png")


if __name__ == "__main__":
  if len(sys.argv) != 4:
    sys.exit(__doc__)
  main(sys.argv[1], int(sys.argv[2]), sys.argv[3])

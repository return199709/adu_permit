"""Prototype: turn one cleaned plan sheet into centerline vectors (DXF + SVG).

Install:  pip install pymupdf opencv-python-headless numpy scipy scikit-image ezdxf
Run:      python vectorize_plan.py cleaned_blueprint.pdf 1 page1
          -> page1.dxf, page1.svg (scan underlay + vectors), page1_overlay.png,
             page1_text.json (where every line of text is), page1_text_removed.png

The lettering is found first and erased from the scan; the drawing that is left
is traced into straight lines (snapped square when within 2.5 degrees of
horizontal/vertical), arcs, and short lines attached to them. Anything else is
treated as noise and dropped. The text is located and traced, not read, and
lines are not joined at corners. Tuned on sheet 1.
"""
import base64
import json
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
  "LINES_SHORT": (150, "#5a78ff", "short straight lines attached to the drawing: symbols, ticks"),
  "ARCS": (4, "#00b8d4", "arcs and circles: door swings, symbols"),
  "TEXT": (6, "#c000c0", "lettering found as text (traced, not read)"),
  "TEXT_BOX": (200, "#8a40ff", "a box around each line of text"),
  "UNSURE": (8, "#a0a0a0", "curvy leftovers kept for review (hidden)"),
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
  instead of by direction. Returns (lines, coverage, span): new line rows,
  their inked fraction, and for every stroke the length of the new line that
  absorbed it (0 when none did).
  """
  new_lines, new_cover = [], []
  span_of = np.zeros(len(strokes))
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
              span_of[ids[ch]] = np.maximum(span_of[ids[ch]], span)
        cluster = []
      if k < len(order):
        cluster.append(k)
  return (np.array(new_lines, dtype=np.float64).reshape(-1, 6),
          np.array(new_cover, dtype=np.float64), span_of)


def build_primitives(strokes, min_piece=12, min_line=60, gap=40.0, line_eps=2.5):
  """Splits strokes into straight lines, arcs and everything else.

  Straight pieces (even short dashes) are joined across gaps; a joined group
  that adds up to at least `min_line` px is a line. Strokes that fit a circle
  (door swings, round symbols) become arcs. What is left is `leftover`.

  Returns a dict:
    lines     rows [x1, y1, x2, y2, width, heavy]
    coverage  inked fraction of each line (dashed or broken lines are lower)
    arcs      rows [cx, cy, r, theta0, dtheta, width, heavy] (image angles, y down)
    span      per stroke: length of the line or arc it became part of (0 if none)
    leftover  ids of the strokes that are neither line nor arc
  """
  pieces, owner, arcs = [], [], []
  explained = np.zeros(len(strokes), bool)
  span_of = np.zeros(len(strokes))
  for sid, (pts, closed, width, heavy) in enumerate(strokes):
    total = path_length(pts)
    if not closed:
      chord = float(np.hypot(*(pts[-1] - pts[0])))
      bow = chord_deviation(pts)
      if bow <= max(2.5, min(8.0, 0.03 * chord)):  # straight, give or take hand wobble
        if chord >= min_piece:
          pieces.append([*pts[0], *pts[-1], width, heavy])
          owner.append(sid)
        continue
    if total >= 30 and (closed or (bow >= 6.0 and bow >= 0.04 * chord)):  # a circle, or visibly bowed
      arc = as_arc(pts, closed)
      if arc is not None:
        arcs.append([*arc, width, heavy])
        explained[sid] = True
        span_of[sid] = arc[2] * abs(arc[4])
        continue
    coarse = simplify(pts, line_eps, closed)
    if is_smooth_curve(coarse):
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
  np.maximum.at(span_of, owner, np.where(good[group_of], span[group_of], 0.0))

  extra, extra_coverage, extra_span = bridge_dashes(strokes, explained)
  explained |= extra_span > 0
  span_of = np.maximum(span_of, extra_span)
  return {
      "lines": np.vstack([merged[good], extra]),
      "coverage": np.concatenate([coverage[good], extra_coverage]),
      "arcs": np.array(arcs, dtype=np.float64).reshape(-1, 7),
      "span": span_of,
      "leftover": np.flatnonzero(~explained & (total >= 4)),
  }


def is_symbol_frame(pts, closed):
  """A closed shape with a few long straight edges: diamond, triangle, box."""
  if not closed:
    return False
  corners = simplify(pts, 2.5, True)
  edges = np.hypot(*(corners - np.roll(corners, 1, axis=0)).T)
  return bool(3 <= len(corners) <= 8 and edges.min() >= 15 and np.ptp(pts, axis=0).max() >= 20)


def split_lines(group, strokes, axis, max_spread=22.0):
  """Splits a blob that holds several text lines into one group per line.

  Strokes are clustered by where their centres lie across the text direction
  (`axis` 1: rows, for horizontal text; 0: columns, for rotated text), using
  the smallest number of lines for which every line is only about one letter
  tall. A few stray strokes (a dashed line crossing the text) get a cluster
  of their own instead of stretching the real lines.
  """
  centre = np.array([strokes[i][0][:, axis].mean() for i in group])
  for k in range(1, 7):
    edges = np.quantile(centre, (np.arange(k) + 0.5) / k)
    for _ in range(20):  # 1-D k-means
      label = np.abs(centre[:, None] - edges[None, :]).argmin(axis=1)
      new = np.array([centre[label == j].mean() if np.any(label == j) else edges[j] for j in range(k)])
      if np.allclose(new, edges):
        break
      edges = new
    spreads = [np.ptp(np.percentile(centre[label == j], [5, 95])) for j in range(k) if np.any(label == j)]
    if max(spreads) <= max_spread:
      break
  return [group[label == j] for j in range(k) if np.any(label == j)]


def find_text(strokes, span, arcs, shape, reach=17, max_extent=80.0, max_length=160.0):
  """Finds lettering: lines of short strokes of lettering size.

  Strokes that belong to a long line (span >= 100 px), heavy bands, callout
  markers and anything inside a circle or marker are left alone. The rest are
  drawn on a canvas and closed by `reach` px along the text direction
  (horizontally for normal text, vertically for rotated text), which fuses the
  letters of a line into one blob. Blobs that hold several lines are split.
  A line is text when it holds enough letter-sized strokes that are densely
  packed; long parallel strokes (hatching) and runs of dashes are not text.

  Returns (is_text, boxes, lines): a bool per stroke, and for every line of
  text its oriented box (4 x 2 array of corners) and the ids of its strokes.
  """
  n = len(strokes)
  if n == 0:
    return np.zeros(0, bool), [], []
  extent = np.array([np.ptp(s[0], axis=0).max() for s in strokes])
  length = np.array([path_length(s[0]) for s in strokes])
  ok = np.array([not s[3] and not is_symbol_frame(s[0], s[1]) for s in strokes])
  ok &= (span < 100) & (extent <= max_extent) & (length <= max_length)
  symbol = np.zeros(shape, np.uint8)  # filled circles and frames: what is inside is not lettering
  for cx, cy, r, _, sweep, _, _ in arcs:
    if abs(sweep) >= 5.5 and r <= 80:
      cv2.circle(symbol, (round(cx), round(cy)), round(r), 1, -1)
  for pts, closed, _, _ in strokes:
    if is_symbol_frame(pts, closed):
      cv2.fillPoly(symbol, [np.round(simplify(pts, 2.5, True)).astype(np.int32)], 1)

  # Callout markers (diamond, triangle, box) are small enclosed shapes with a few
  # straight sides. A leader line attached to a corner splits their outline into
  # several strokes, so find them as holes in the traced linework instead.
  linework = np.zeros(shape, np.uint8)  # drawn thick enough to close the gaps at corners
  for s in strokes:
    cv2.polylines(linework, [np.round(s[0]).astype(np.int32)], False, 1, 7)
  sides = np.zeros(shape, np.uint8)
  contours, hierarchy = cv2.findContours(linework, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
  for k, contour in enumerate(contours if hierarchy is not None else []):
    if hierarchy[0][k][3] >= 0 and 350 <= cv2.contourArea(contour) <= 8000:  # a hole
      corners = cv2.approxPolyDP(contour, 2.0, True)
      if 3 <= len(corners) <= 6 and cv2.isContourConvex(corners):
        cv2.fillPoly(symbol, [corners], 1)
        cv2.polylines(sides, [corners], True, 1, 9)
  on_sides = np.array([sides[np.round(s[0][:, 1]).astype(int).clip(0, shape[0] - 1),
                             np.round(s[0][:, 0]).astype(int).clip(0, shape[1] - 1)].mean() >= 0.7 for s in strokes])
  ok &= ~on_sides
  all_mid = np.round([s[0][len(s[0]) // 2] for s in strokes]).astype(int)
  ok &= symbol[all_mid[:, 1], all_mid[:, 0]] == 0
  ids = np.flatnonzero(ok)
  canvas = np.zeros(shape, np.uint8)
  for i in ids:
    cv2.polylines(canvas, [np.round(strokes[i][0]).astype(np.int32)], False, 1, 3)
  mid = all_mid[ids]

  def lettering(group, horizontal):
    """The oriented box if the strokes in `group` form a line of text, else None."""
    big = group[extent[group] >= 5]
    if len(big) < 3:
      return None  # too few letter-sized strokes
    pts = np.vstack([strokes[i][0] for i in group])
    centres = np.array([strokes[i][0].mean(axis=0) for i in group])
    size = float(np.median(extent[big]))
    # robust size of the line: spread of the stroke centres plus one letter
    along_axis, across_axis = (0, 1) if horizontal else (1, 0)
    along = np.ptp(np.percentile(centres[:, along_axis], [5, 95])) + size
    across = np.ptp(np.percentile(centres[:, across_axis], [5, 95])) + size
    if not (8 <= across <= 95 and along >= 1.2 * across):
      return None  # not the shape of a line of text
    ink_length = length[group].sum()
    if size > 55 or ink_length < 0.02 * along * across:
      return None  # strokes too big for lettering, or too sparse
    faint = np.median([strokes[i][2] for i in group]) < 1.3
    if ink_length < 35 or (faint and ink_length < 55):
      return None  # a few faint specks, not lettering
    ln = length[big]
    chord = np.array([strokes[i][0][-1] - strokes[i][0][0] for i in big])
    angle = np.arctan2(chord[:, 1], chord[:, 0])
    straight = np.hypot(*chord.T) >= 0.9 * ln
    run = 0.0 if horizontal else np.pi / 2  # direction of the text line
    parallel = np.abs(np.sin(angle - run)) <= np.sin(np.radians(15))
    if np.mean(straight & parallel) >= 0.6:
      return None  # a run of dashes
    if len(big) >= 6 and np.median(ln) >= 25:  # many long parallel strokes: hatching
      if abs(np.sum(ln / ln.sum() * np.exp(2j * angle))) > 0.8:
        return None
    # Lettering shows most of these together; dashes, hatching and symbol
    # fragments only a few of them.
    directions = np.histogram(np.mod(angle, np.pi), bins=6, range=(0, np.pi))[0] / len(big)
    traits = [
        np.std(extent[big]) / np.mean(extent[big]) <= 0.6,  # letters of similar size
        np.mean(straight & parallel) <= 0.3,  # not a row of dashes
        (directions >= 0.1).sum() >= min(3, len(big) - 1),  # strokes in several directions
        np.mean(~straight) >= 0.25,  # curved strokes
        len(group) / along * 100 >= 6,  # enough strokes for its length
        length[group].sum() / (along * across) >= 0.04,  # dense enough
    ]
    if sum(traits) < 5:
      return None
    return cv2.boxPoints(cv2.minAreaRect(pts.astype(np.float32)))

  is_text = np.zeros(n, bool)
  boxes, members = [], []
  for horizontal in (True, False):  # normal text, then rotated text
    kw, kh = (2 * reach + 1, 1) if horizontal else (1, 2 * reach + 1)
    closed = cv2.morphologyEx(canvas, cv2.MORPH_CLOSE, np.ones((kh, kw), np.uint8))
    _, blob = cv2.connectedComponents(closed, connectivity=8)
    blob_of = blob[mid[:, 1], mid[:, 0]]
    order = np.argsort(blob_of, kind="stable")
    for group in np.split(ids[order], np.flatnonzero(np.diff(blob_of[order])) + 1):
      group = group[~is_text[group]]
      if len(group) == 0:
        continue
      for line in split_lines(group, strokes, 1 if horizontal else 0):
        box = lettering(line, horizontal)
        if box is not None:
          is_text[line] = True
          boxes.append(box)
          members.append(line)

  # punctuation and stray marks beside a line of text belong to it
  if boxes:
    near = np.zeros(shape, np.uint8)
    cv2.fillPoly(near, [np.round(b).astype(np.int32) for b in boxes], 1)
    near = cv2.dilate(near, np.ones((9, 9), np.uint8))
    small = np.flatnonzero(~is_text & ok & (extent <= 12))
    centre = np.round([strokes[i][0][len(strokes[i][0]) // 2] for i in small]).astype(int)
    if len(small):
      is_text[small[near[centre[:, 1], centre[:, 0]] > 0]] = True
  return is_text, boxes, members


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


def remove_text(ink, strokes, is_text):
  """The scan with the lettering erased: what is left is the drawing."""
  mask = np.zeros(ink.shape, np.uint8)
  for i in np.flatnonzero(is_text):
    pts, closed, width, _ = strokes[i]
    cv2.polylines(mask, [np.round(pts).astype(np.int32)], closed, 1, int(width) + 4)
  return ink & ~(mask > 0)


def tidy_leftover(strokes, prims, min_keep=40, near=4.0, min_piece=12):
  """Keeps what is straight, drops what is noise.

  Strokes that are neither lines nor arcs become short straight lines when they
  are mostly straight and part of the drawing: long enough, touching a line or
  an arc, or a closed frame. Isolated short bits are noise and are dropped.
  Curvy leftovers are kept apart, in `unsure`, only when they are long.

  Returns (short, unsure, dropped): short-line rows [x1, y1, x2, y2, width,
  heavy], ids of the unsure strokes, and the number of strokes dropped.
  """
  parts = []
  for x1, y1, x2, y2, _, _ in prims["lines"]:
    k = max(2, int(np.hypot(x2 - x1, y2 - y1) / 4))
    parts.append(np.stack([np.linspace(x1, x2, k), np.linspace(y1, y2, k)], axis=1))
  parts += [arc_points(arc, 3.0) for arc in prims["arcs"]]
  parts += [s[0][::3] for s in strokes if s[3]]
  tree = cKDTree(np.vstack(parts) if parts else np.full((1, 2), -1e9))
  short, unsure, dropped = [], [], 0
  for sid in prims["leftover"]:
    pts, closed, width, heavy = strokes[sid]
    total = path_length(pts)
    coarse = simplify(pts, 2.0, closed)
    ring = np.vstack([coarse, coarse[:1]]) if closed else coarse
    pieces = [(a, b) for a, b in zip(ring[:-1], ring[1:]) if np.hypot(*(b - a)) >= min_piece]
    if pieces and sum(np.hypot(*(b - a)) for a, b in pieces) >= 0.6 * total:
      attached = min(tree.query([p for ab in pieces for p in ab])[0]) <= near
      if total >= min_keep or attached or is_symbol_frame(pts, closed):
        short += [[*a, *b, width, heavy] for a, b in pieces]
      else:
        dropped += 1
    elif total >= 60:
      unsure.append(sid)
    else:
      dropped += 1
  return np.array(short, dtype=np.float64).reshape(-1, 6), unsure, dropped


def inside_boxes(boxes, shape, grow=0):
  """A mask of the oriented boxes, grown by `grow` px."""
  mask = np.zeros(shape, np.uint8)
  if boxes:
    cv2.fillPoly(mask, [np.round(b).astype(np.int32) for b in boxes], 1)
  if grow:
    mask = cv2.dilate(mask, np.ones((2 * grow + 1, 2 * grow + 1), np.uint8))
  return mask > 0


def new_boxes(boxes, found, shape, overlap=0.6):
  """The boxes in `found` that are not mostly covered by the ones in `boxes`."""
  covered = inside_boxes(boxes, shape)
  kept = []
  for box in found:
    x, y, w, h = cv2.boundingRect(np.round(box).astype(np.int32))
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, shape[1]), min(y + h, shape[0])
    local = np.zeros((h, w), np.uint8)
    cv2.fillPoly(local, [np.round(box - [x, y]).astype(np.int32)], 1)
    area = int(local.sum())
    inside = int((covered[y0:y1, x0:x1] & (local[y0 - y:y1 - y, x0 - x:x1 - x] > 0)).sum()) if x1 > x0 and y1 > y0 else 0
    if area == 0 or inside < overlap * area:
      kept.append(box)
  return kept


def snap_square(lines, tol_deg=1.0):
  """Makes lines that are within `tol_deg` of horizontal or vertical exactly so."""
  lines = lines.copy()
  if len(lines) == 0:
    return lines
  dx, dy = lines[:, 2] - lines[:, 0], lines[:, 3] - lines[:, 1]
  angle = np.degrees(np.arctan2(np.abs(dy), np.abs(dx)))  # 0 = horizontal, 90 = vertical
  flat, upright = angle <= tol_deg, angle >= 90 - tol_deg
  lines[flat, 1] = lines[flat, 3] = (lines[flat, 1] + lines[flat, 3]) / 2
  lines[upright, 0] = lines[upright, 2] = (lines[upright, 0] + lines[upright, 2]) / 2
  return lines


def vectorize(ink, snap_deg=2.5):
  """Text first, then the drawing.

  Finds the lettering, erases it from the scan, traces what is left (looking
  once more for lettering that the first pass could not see) and keeps only
  straight lines, arcs and short lines attached to them. Returns a dict with
  the lines, arcs, text and a few counts.
  """
  strokes = find_strokes(ink)
  first = build_primitives(strokes)
  is_text, boxes, _ = find_text(strokes, first["span"], first["arcs"], ink.shape)
  text = [strokes[i] for i in np.flatnonzero(is_text)]
  drawing = remove_text(ink, strokes, is_text)

  # round two, on the drawing without lettering: lines that were not real no
  # longer shield the letters they were built from
  clean = find_strokes(drawing)
  second = build_primitives(clean)
  is_text2, boxes2, _ = find_text(clean, second["span"], second["arcs"], ink.shape)
  text += [clean[i] for i in np.flatnonzero(is_text2)]
  boxes += new_boxes(boxes, boxes2, ink.shape)
  drawing = remove_text(drawing, clean, is_text2)
  clean = [s for s, t in zip(clean, is_text2) if not t]

  prims = build_primitives(clean)
  short, unsure, dropped = tidy_leftover(clean, prims)

  # small bits of the drawing do not lie inside a line of text; long lines can
  # (an underline), and with the lettering erased they are real
  in_text = inside_boxes(boxes, ink.shape, grow=3)

  def mid_in_text(rows):
    x = np.clip(np.round((rows[:, 0] + rows[:, 2]) / 2).astype(int), 0, ink.shape[1] - 1)
    y = np.clip(np.round((rows[:, 1] + rows[:, 3]) / 2).astype(int), 0, ink.shape[0] - 1)
    return in_text[y, x]

  lines, coverage = prims["lines"], prims["coverage"]
  short = short[~mid_in_text(short)] if len(short) else short

  def arc_in_text(arc):  # is the middle of the arc inside a line of text?
    t = arc[3] + arc[4] / 2
    x = int(np.clip(round(arc[0] + arc[2] * np.cos(t)), 0, ink.shape[1] - 1))
    y = int(np.clip(round(arc[1] + arc[2] * np.sin(t)), 0, ink.shape[0] - 1))
    return in_text[y, x]

  arcs = np.array([a for a in prims["arcs"] if not arc_in_text(a)], dtype=np.float64).reshape(-1, 7)
  return {
      "lines": snap_square(lines, snap_deg),
      "coverage": coverage,
      "short": snap_square(short, snap_deg),
      "arcs": arcs,
      "text": [(simplify(s[0], 1.2, s[1]), s[1], s[2]) for s in text],
      "boxes": boxes,
      "unsure": [(simplify(clean[i][0], 1.2, clean[i][1]), clean[i][1], clean[i][2], clean[i][3])
                 for i in unsure],
      "dropped": dropped,
      "drawing": drawing,
  }


def ink_shares(ink, result):
  """Share of the ink within a stroke's half-width + 3 px of the drawing
  (lines, arcs), of the text, and of nothing."""
  drawing = np.zeros(ink.shape, np.uint8)
  for x1, y1, x2, y2, width, _ in np.vstack([result["lines"], result["short"]]):
    cv2.line(drawing, (round(x1), round(y1)), (round(x2), round(y2)), 1, int(max(7, width + 6)))
  for arc in result["arcs"]:
    cv2.polylines(drawing, [np.round(arc_points(arc)).astype(np.int32)], False, 1, int(max(7, arc[5] + 6)))
  text = np.zeros(ink.shape, np.uint8)
  for pts, closed, width in result["text"]:
    cv2.polylines(text, [np.round(pts).astype(np.int32)], closed, 1, int(max(7, width + 6)))
  n = int(ink.sum())
  on_drawing = int((ink & (drawing > 0)).sum())
  on_text = int((ink & (drawing == 0) & (text > 0)).sum())
  return on_drawing / n, on_text / n, (n - on_drawing - on_text) / n


def write_dxf(path, height, in_per_px, result):
  """DXF in real-world inches (y up), one layer per kind of primitive."""
  doc = ezdxf.new("R2010", setup=True)
  doc.units = ezdxf.units.IN
  doc.header["$LTSCALE"] = 24  # dash pattern sized for a building, not a part
  for name, (colour, _, _) in LAYERS.items():
    doc.layers.add(name, color=colour)
  doc.layers.get("LINES_DASHED").dxf.linetype = "DASHED"
  doc.layers.get("UNSURE").off()
  msp = doc.modelspace()

  def pt(x, y):
    return (x * in_per_px, (height - y) * in_per_px)

  def weight(width_px, dpi=200):  # nearest standard plot weight, 1/100 mm
    return min(const.VALID_DXF_LINEWEIGHTS, key=lambda v: abs(v - width_px * 2540 / dpi))

  for (x1, y1, x2, y2, width, heavy), cov in zip(result["lines"], result["coverage"]):
    msp.add_line(pt(x1, y1), pt(x2, y2), dxfattribs={
        "layer": line_layer(heavy, cov), "lineweight": weight(width)})
  for x1, y1, x2, y2, width, heavy in result["short"]:
    msp.add_line(pt(x1, y1), pt(x2, y2), dxfattribs={
        "layer": "LINES_SHORT", "lineweight": weight(width)})
  for cx, cy, r, theta0, sweep, width, heavy in result["arcs"]:
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
  for pts, closed, width in result["text"]:
    msp.add_lwpolyline([pt(x, y) for x, y in pts], close=closed, dxfattribs={
        "layer": "TEXT", "lineweight": weight(width)})
  for box in result["boxes"]:
    msp.add_lwpolyline([pt(x, y) for x, y in box], close=True, dxfattribs={"layer": "TEXT_BOX"})
  for pts, closed, width, heavy in result["unsure"]:
    msp.add_lwpolyline([pt(x, y) for x, y in pts], close=closed, dxfattribs={"layer": "UNSURE"})
  doc.saveas(path)


def write_svg(path, ink, result):
  """SVG in scan pixels: the scan as a faded underlay plus a group per layer."""
  height, width = ink.shape
  png = cv2.imencode(".png", np.where(ink, 0, 255).astype(np.uint8))[1].tobytes()
  groups = {name: [] for name in LAYERS}

  def points(pts):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)

  def line(x1, y1, x2, y2):
    return f'<line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}"/>'

  for (x1, y1, x2, y2, _, heavy), cov in zip(result["lines"], result["coverage"]):
    groups[line_layer(heavy, cov)].append(line(x1, y1, x2, y2))
  for x1, y1, x2, y2, _, _ in result["short"]:
    groups["LINES_SHORT"].append(line(x1, y1, x2, y2))
  for arc in result["arcs"]:
    groups["ARCS"].append(f'<polyline points="{points(arc_points(arc))}"/>')
  for pts, closed, _ in result["text"]:
    groups["TEXT"].append(f'<{"polygon" if closed else "polyline"} points="{points(pts)}"/>')
  for box in result["boxes"]:
    groups["TEXT_BOX"].append(f'<polygon points="{points(box)}"/>')
  for pts, closed, _, _ in result["unsure"]:
    groups["UNSURE"].append(f'<{"polygon" if closed else "polyline"} points="{points(pts)}"/>')

  out = [
      f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink" '
      f'viewBox="0 0 {width} {height}">',
      "<style>.v *{vector-effect:non-scaling-stroke;fill:none;stroke-linecap:round}</style>",
      f'<g id="scan" opacity="0.35"><image width="{width}" height="{height}" '
      f'xlink:href="data:image/png;base64,{base64.b64encode(png).decode()}"/></g>',
  ]
  for name, items in groups.items():
    stroke = "2.5" if name == "HEAVY_LINES" else "1.2"
    hidden = ' display="none"' if name == "UNSURE" else ""
    out.append(f'<g id="{name}" class="v" stroke="{LAYERS[name][1]}" stroke-width="{stroke}"{hidden}>')
    out += items
    out.append("</g>")
  out.append("</svg>")
  with open(path, "w") as f:
    f.write("\n".join(out))


def write_text_index(path, height, in_per_px, boxes):
  """A list of every line of text found: where it is, how big, which way it runs.

  Positions are in real-world inches (y up), the same frame as the DXF; angle
  is the direction of the line of text, counter-clockwise from the x axis.
  """
  entries = []
  for k, box in enumerate(boxes):
    sides = np.roll(box, -1, axis=0) - box
    lengths = np.hypot(*sides.T)
    edge = sides[int(np.argmax(lengths[:2]))]
    angle = float(np.degrees(np.arctan2(-edge[1], edge[0])) % 180)  # image y points down
    corners = [[round(float(x * in_per_px), 2), round(float((height - y) * in_per_px), 2)] for x, y in box]
    entries.append({
        "id": k,
        "centre_in": [round(float(box[:, 0].mean() * in_per_px), 2),
                      round(float((height - box[:, 1].mean()) * in_per_px), 2)],
        "length_in": round(float(lengths[:2].max() * in_per_px), 2),
        "height_in": round(float(lengths[:2].min() * in_per_px), 2),
        "angle_deg": round(angle, 1),
        "corners_in": corners,
    })
  with open(path, "w") as f:
    json.dump({"units": "inches at drawing scale, y up", "text_lines": entries}, f, indent=1)


def draw_layers(vis, result, scale=1.0, origin=(0, 0), heavy_px=3):
  """Draws every primitive in its layer colour (BGR) onto `vis`."""
  def bgr(layer):
    h = LAYERS[layer][1]
    return (int(h[5:7], 16), int(h[3:5], 16), int(h[1:3], 16))

  def pix(pts):
    return np.round((np.asarray(pts) - origin) * scale).astype(np.int32)

  for pts, closed, _ in result["text"]:
    cv2.polylines(vis, [pix(pts)], closed, bgr("TEXT"), 1, cv2.LINE_AA)
  for box in result["boxes"]:
    cv2.polylines(vis, [pix(box)], True, bgr("TEXT_BOX"), 1, cv2.LINE_AA)
  for arc in result["arcs"]:
    cv2.polylines(vis, [pix(arc_points(arc))], False, bgr("ARCS"), 2, cv2.LINE_AA)
  for x1, y1, x2, y2, _, _ in result["short"]:
    a, b = pix([[x1, y1], [x2, y2]])
    cv2.line(vis, tuple(a), tuple(b), bgr("LINES_SHORT"), 1, cv2.LINE_AA)
  for (x1, y1, x2, y2, _, heavy), cov in zip(result["lines"], result["coverage"]):
    a, b = pix([[x1, y1], [x2, y2]])
    cv2.line(vis, tuple(a), tuple(b), bgr(line_layer(heavy, cov)), heavy_px if heavy else 2, cv2.LINE_AA)
  return vis


def write_overlay(path, ink, result, scale=0.5):
  """Whole-page preview: faded scan with the vectors on top and a legend."""
  gray = cv2.resize(np.where(ink, 0, 255).astype(np.uint8), None, fx=scale, fy=scale,
                    interpolation=cv2.INTER_AREA)
  vis = cv2.cvtColor((255 - (255 - gray) * 0.45).astype(np.uint8), cv2.COLOR_GRAY2BGR)
  draw_layers(vis, result, scale)
  shown = [name for name in LAYERS if name != "UNSURE"]
  y = vis.shape[0] - 24 * len(shown) - 30
  for name in shown:
    _, hexcol, text = LAYERS[name]
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
  result = vectorize(ink)
  lines, coverage = result["lines"], result["coverage"]
  heavy = lines[:, 5] > 0
  dashed = ~heavy & (coverage < 0.8)
  print(f"Text: {len(result['boxes'])} lines of lettering ({len(result['text']):,} strokes) taken out of the drawing")
  print(f"Drawing: {int(heavy.sum())} heavy lines, {int((~heavy & ~dashed).sum())} thin lines, "
        f"{int(dashed.sum())} dashed/broken lines, {len(result['short'])} short lines, {len(result['arcs'])} arcs")
  print(f"Dropped as noise: {result['dropped']:,} bits; kept aside as unsure: {len(result['unsure'])}")
  on_drawing, on_text, rest = ink_shares(ink, result)
  print(f"Ink: {100 * on_drawing:.1f}% in the drawing, {100 * on_text:.1f}% in text, {100 * rest:.1f}% left over")
  write_dxf(f"{prefix}.dxf", ink.shape[0], in_per_px, result)
  write_svg(f"{prefix}.svg", ink, result)
  write_overlay(f"{prefix}_overlay.png", ink, result)
  write_text_index(f"{prefix}_text.json", ink.shape[0], in_per_px, result["boxes"])
  cv2.imwrite(f"{prefix}_text_removed.png", np.where(result["drawing"], 0, 255).astype(np.uint8))
  print(f"Saved {prefix}.dxf, {prefix}.svg, {prefix}_overlay.png, {prefix}_text.json, {prefix}_text_removed.png")


if __name__ == "__main__":
  if len(sys.argv) != 4:
    sys.exit(__doc__)
  main(sys.argv[1], int(sys.argv[2]), sys.argv[3])

"""Put transcribed lettering into a vectorized plan sheet.

Install:  pip install pymupdf opencv-python-headless numpy scipy scikit-image ezdxf
Run:      python apply_text.py cleaned_blueprint.pdf 1 page1 page1_transcription.json
          -> page1.dxf, page1.svg, page1_overlay.png, page1_text.json   (as vectorize_plan.py)
             page1_text_read.json / .csv   every line of text with what it says
             page1_dimension_check_01.png ...   each dimension string beside a crop of the plan

vectorize_plan.py finds every line of lettering but cannot read it. The transcription
file says what each one reads and what it is. It was read by eye from the scan, so it
can be wrong; the dimension sheets exist so that a person can check them.

  {"page": 1, "boxes_digest": "...", "entries": [
     {"id": 8, "kind": "DIM", "text": "14'-9\\"", "conf": "med", "note": "..."}, ...]}

`id` is the line's number in page1_text.json, `conf` is high, med or low (low text goes
on its own layer, TEXT_CHECK). `kind` decides what happens to it:
  DIM NOTE LABEL CALL TITLE LEGEND   typed into the DXF as text (a " / " in the text starts a new row)
  SYM                                a marker symbol: its strokes are kept, traced, on SYMBOLS
  NOTTEXT                            not lettering after all (tick, hatching, symbol): the ink goes back into the drawing
  anything else (UNREAD, STAMP, ...) left as traced strokes on TEXT, not retyped
"""
import csv
import hashlib
import json
import sys
import textwrap

import cv2
import numpy as np

import vectorize_plan as vp

TYPED = {"DIM": "TEXT_DIM", "NOTE": "TEXT_NOTE", "LABEL": "TEXT_NOTE", "CALL": "TEXT_NOTE",
         "TITLE": "TEXT_NOTE", "LEGEND": "TEXT_NOTE"}


def boxes_digest(boxes):
  """A fingerprint of where the lines of text are, so a transcription is not applied to the wrong run."""
  rows = [[round(float(b[:, 0].mean())), round(float(b[:, 1].mean())),
           round(float(np.hypot(*(b[1] - b[0]))))] for b in boxes]
  return hashlib.md5(json.dumps(rows).encode()).hexdigest()


def box_frame(box):
  """(centre, length, height, d, up, angle) of an oriented box, in scan pixels (y down).

  d runs along the text the way it reads: left to right, bottom to top for text
  that is nearly vertical. up points from the baseline to the tops of the letters.
  angle is the direction of d in degrees, counter-clockwise with y up.
  """
  sides = np.roll(box, -1, axis=0) - box
  lengths = np.hypot(*sides.T)
  edge = sides[int(np.argmax(lengths[:2]))]
  angle = float(np.degrees(np.arctan2(-edge[1], edge[0])) % 180)
  if angle > 100:
    angle -= 180
  phi = np.radians(angle)
  d = np.array([np.cos(phi), -np.sin(phi)])
  up = np.array([-np.sin(phi), -np.cos(phi)])
  return box.mean(axis=0), float(lengths[:2].max()), float(lengths[:2].min()), d, up, angle


def labels_for(entry, box):
  """Typed text for one line of lettering: one label per row."""
  centre, length, height, d, up, _ = box_frame(box)
  rows = [r.strip() for r in entry["text"].split(" / ") if r.strip()]
  layer = TYPED[entry["kind"]]
  if entry["conf"] == "low" or "?" in entry["text"]:
    layer = "TEXT_CHECK"
  out = []
  for k, row in enumerate(rows):
    bottom = height / 2 - (k + 1) * height / len(rows)  # of this row, measured up from the centre
    start = centre - d * length / 2 + up * bottom
    out.append({"text": row, "layer": layer, "base": [start.tolist(), (start + d * length).tolist()],
                "height": 0.9 * height / len(rows)})
  return out


def overlap(a, b):
  """Share of the smaller of two oriented boxes that lies inside the other."""
  a, b = a.astype(np.float32), b.astype(np.float32)
  inter, _ = cv2.intersectConvexConvex(a, b)
  return float(inter / max(1e-9, min(cv2.contourArea(a), cv2.contourArea(b))))


def drop_duplicates(entries, boxes):
  """Boxes nested inside each other that carry the same words: keep the fuller one."""
  typed = [i for i, e in entries.items() if e["kind"] in TYPED and e["text"].strip()]
  norm = {i: "".join(entries[i]["text"].lower().split()) for i in typed}
  gone = {}
  centre = {i: boxes[i].mean(axis=0) for i in typed}
  for a in typed:
    for b in typed:
      if a >= b or a in gone or b in gone or np.hypot(*(centre[a] - centre[b])) > 400:
        continue
      same = norm[a] == norm[b]
      if (same or norm[a] in norm[b] or norm[b] in norm[a]) and overlap(boxes[a], boxes[b]) >= (0.3 if same else 0.6):
        keep, lose = (a, b) if (len(norm[a]), cv2.contourArea(boxes[a].astype(np.float32))) >= (
            len(norm[b]), cv2.contourArea(boxes[b].astype(np.float32))) else (b, a)
        gone[lose] = keep
  return gone


def stroke_owners(boxes, strokes, shape):
  """For each stroke, the id of the smallest box that holds most of it (-1 if none)."""
  canvas = np.full(shape, -1, np.int32)
  for i in np.argsort([-cv2.contourArea(b.astype(np.float32)) for b in boxes]):  # biggest first
    cv2.fillPoly(canvas, [np.round(boxes[i]).astype(np.int32)], int(i))
  owners = []
  for stroke in strokes:
    pts = stroke[0]
    pick = pts[np.linspace(0, len(pts) - 1, min(len(pts), 5)).astype(int)]
    ids = canvas[np.clip(np.round(pick[:, 1]).astype(int), 0, shape[0] - 1),
                 np.clip(np.round(pick[:, 0]).astype(int), 0, shape[1] - 1)]
    ids = ids[ids >= 0]
    owners.append(int(np.bincount(ids).argmax()) if len(ids) else -1)
  return owners


def crop_around(gray, box, pad_x, pad_y, zoom, limit=700):
  """The scan around one line of text, turned so the text reads left to right."""
  centre, length, height, d, up, angle = box_frame(box)
  zoom = min(zoom, limit / (length + 2 * pad_x))
  width, tall = int((length + 2 * pad_x) * zoom) + 1, int((height + 2 * pad_y) * zoom) + 1
  m = cv2.getRotationMatrix2D((float(centre[0]), float(centre[1])), -angle, zoom)
  m[0, 2] += width / 2 - centre[0]
  m[1, 2] += tall / 2 - centre[1]
  crop = cv2.warpAffine(gray, m, (width, tall), flags=cv2.INTER_LINEAR, borderValue=255)
  out = cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR)
  cv2.rectangle(out, (int(pad_x * zoom), int(pad_y * zoom)),
                (int((pad_x + length) * zoom), int((pad_y + height) * zoom)), (200, 0, 200), 1)
  return out


def write_check_sheets(prefix, ink, boxes, entries, ids, name, page_height=1800):
  """Sheets with a crop of the plan around each line and what it was read as."""
  gray = np.where(ink, 0, 255).astype(np.uint8)
  order = sorted(ids, key=lambda i: (round(float(boxes[i][:, 1].mean()) / 160), float(boxes[i][:, 0].mean())))
  cards = []
  for i in order:
    e = entries[i]
    crop = crop_around(gray, boxes[i], 120, 40, 2.0, limit=660)
    said = textwrap.wrap(f"read as: {e['conf']}" + (f" | {e['note']}" if e.get("note") else ""), 80)[:3]
    head = np.full((40 + 18 * len(said), max(crop.shape[1], 330), 3), 255, np.uint8)
    cv2.putText(head, f"#{i}   {e['text']}", (6, 30), cv2.FONT_HERSHEY_DUPLEX, 0.95, (0, 0, 170), 1, cv2.LINE_AA)
    for k, row in enumerate(said):
      cv2.putText(head, row, (6, 52 + 18 * k), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 60, 60), 1, cv2.LINE_AA)
    card = np.full((head.shape[0] + crop.shape[0] + 8, head.shape[1], 3), 255, np.uint8)
    card[:head.shape[0]] = head
    card[head.shape[0]:head.shape[0] + crop.shape[0], :crop.shape[1]] = crop
    cv2.rectangle(card, (0, 0), (card.shape[1] - 1, card.shape[0] - 1), (170, 170, 170), 1)
    cards.append(card)
  pages, column, sheet = [], 0, np.full((page_height, 1400, 3), 255, np.uint8)
  heights = [0, 0]
  for card in cards:
    if heights[column] + card.shape[0] > page_height:
      if column == 0:
        column = 1
      else:
        pages.append(sheet)
        sheet, heights, column = np.full((page_height, 1400, 3), 255, np.uint8), [0, 0], 0
    x0, y0 = column * 700, heights[column]
    sheet[y0:y0 + card.shape[0], x0 + 2:x0 + 2 + min(card.shape[1], 696)] = card[:, :696]
    heights[column] += card.shape[0] + 6
  if cards:
    pages.append(sheet)
  paths = []
  for k, page in enumerate(pages, 1):
    used = max(1, max(int(np.flatnonzero((page < 255).any(axis=(1, 2))).max()) + 8, 1))
    paths.append(f"{prefix}_{name}_{k:02d}.png")
    cv2.imwrite(paths[-1], page[:used])
  return paths


def write_reading(prefix, height, in_per_px, boxes, entries, dropped):
  """Every line of text with what it says, as JSON and as a CSV to open in a spreadsheet."""
  rows = []
  for i, box in enumerate(boxes):
    e = entries.get(i, {"kind": "", "text": "", "conf": ""})
    centre, length, h, _, _, angle = box_frame(box)
    rows.append({
        "id": i, "kind": e["kind"], "text": e["text"], "confidence": e["conf"],
        "typed_in_dxf": e["kind"] in TYPED and bool(e["text"].strip()) and i not in dropped,
        "needs_check": e["kind"] == "DIM" or e["conf"] == "low" or "?" in e["text"],
        "note": "; ".join(x for x in (e.get("note", ""), f"duplicate of #{dropped[i]}" if i in dropped else "") if x),
        "x_in": round(float(centre[0] * in_per_px), 1), "y_in": round(float((height - centre[1]) * in_per_px), 1),
        "angle_deg": round(angle, 1), "length_in": round(length * in_per_px, 1), "height_in": round(h * in_per_px, 1)})
  with open(f"{prefix}_text_read.json", "w") as f:
    json.dump(rows, f, indent=1)
  with open(f"{prefix}_text_read.csv", "w", newline="", encoding="utf-8-sig") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]))
    writer.writeheader()
    writer.writerows(rows)


def main(pdf_path, page_no, prefix, transcription_path):
  ink, dpi = vp.load_ink(pdf_path, page_no)
  in_per_px = vp.DRAWING_SCALE / dpi
  height = ink.shape[0]
  text, boxes, drawing = vp.find_lettering(ink)
  with open(transcription_path) as f:
    data = json.load(f)
  if data.get("boxes_digest") != boxes_digest(boxes):
    sys.exit("The transcription was made for a different run: the lines of text are not where it expects. "
             "Run vectorize_plan.py again with the same settings, or redo the transcription.")
  entries = {e["id"]: e for e in data["entries"]}
  missing = [i for i in range(len(boxes)) if i not in entries]
  if missing:
    print(f"{len(missing)} lines of text have no transcription and stay as traced strokes")
  vp.write_text_index(f"{prefix}_text.json", height, in_per_px, boxes)
  kind = lambda o: entries[o]["kind"] if o in entries else ""

  # sort the strokes of the lettering by what turned out to be there; what was
  # not lettering gets its ink back before the drawing is traced
  owners = stroke_owners(boxes, text, ink.shape)
  not_lettering = np.zeros(ink.shape, np.uint8)
  for stroke, o in zip(text, owners):
    if kind(o) == "NOTTEXT":
      cv2.polylines(not_lettering, [np.round(stroke[0]).astype(np.int32)], stroke[1], 1, int(stroke[2]) + 4)
  drawing = drawing | (ink & (not_lettering > 0))
  result = vp.trace_drawing(drawing, [b for i, b in enumerate(boxes) if kind(i) != "NOTTEXT"])

  # nothing may vanish: a stroke that was called "not lettering" but did not become a line or an
  # arc stays visible as a traced stroke (it may be lettering the finder cut up)
  covered = np.zeros(ink.shape, np.uint8)
  for x1, y1, x2, y2, *_ in np.vstack([result["lines"], result["short"]]):
    cv2.line(covered, (round(x1), round(y1)), (round(x2), round(y2)), 1, 7)
  for arc in result["arcs"]:
    cv2.polylines(covered, [np.round(vp.arc_points(arc)).astype(np.int32)], False, 1, 7)

  def in_drawing(stroke):
    pts = np.round(stroke[0]).astype(int)
    return covered[pts[:, 1].clip(0, ink.shape[0] - 1), pts[:, 0].clip(0, ink.shape[1] - 1)].mean() >= 0.6

  kept_apart = [k for k, o in enumerate(owners) if kind(o) == "NOTTEXT" and not in_drawing(text[k])]
  keep = [k for k, o in enumerate(owners) if kind(o) not in ("NOTTEXT", "SYM")] + kept_apart
  simple = lambda s: (vp.simplify(s[0], 1.2, s[1]), s[1], s[2])
  result.update({
      "text": [simple(text[k]) for k in keep],
      "text_layer": ["TEXT_TRACED" if kind(owners[k]) in TYPED and entries[owners[k]]["text"].strip() else "TEXT"
                     for k in keep],
      "symbols": [simple(s) for s, o in zip(text, owners) if kind(o) == "SYM"],
      "boxes": [b for i, b in enumerate(boxes) if kind(i) not in ("NOTTEXT", "SYM")],
      "drawing": drawing})
  dropped = drop_duplicates(entries, boxes)
  labels = [lab for i, e in entries.items() if i < len(boxes) and e["kind"] in TYPED and e["text"].strip()
            and i not in dropped for lab in labels_for(e, boxes[i])]

  vp.write_dxf(f"{prefix}.dxf", height, in_per_px, result, labels)
  vp.write_svg(f"{prefix}.svg", ink, result, labels)
  vp.write_overlay(f"{prefix}_overlay.png", ink, result)
  write_reading(prefix, height, in_per_px, boxes, entries, dropped)
  dims = [i for i, e in entries.items() if e["kind"] == "DIM" and i not in dropped]
  sheets = write_check_sheets(prefix, ink, boxes, entries, dims, "dimension_check")
  low = [i for i, e in entries.items() if e["kind"] in TYPED and e["kind"] != "DIM" and i not in dropped
         and (e["conf"] == "low" or "?" in e["text"])]
  sheets += write_check_sheets(prefix, ink, boxes, entries, low, "text_check")
  joins = result["joins"]
  back = sum(kind(o) == "NOTTEXT" for o in owners)
  print(f"Typed {len(labels)} lines of text; of {back} strokes that were not lettering, {back - len(kept_apart)} are "
        f"now part of the drawing and {len(kept_apart)} stay as traced strokes; "
        f"{len(result['symbols'])} marker strokes kept on SYMBOLS")
  print(f"Joined: {joins['corners']} corners and {joins['tees']} T-junctions")
  print(f"Saved {prefix}.dxf, {prefix}.svg, {prefix}_overlay.png, {prefix}_text.json, "
        f"{prefix}_text_read.json/.csv and {', '.join(sheets)}")


if __name__ == "__main__":
  if len(sys.argv) != 5:
    sys.exit(__doc__)
  main(sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4])

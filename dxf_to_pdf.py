"""Print a plan DXF to a PDF at paper size (the drawing is 1/4" = 1'-0", so 1/48).

Install:  pip install ezdxf matplotlib
Run:      python dxf_to_pdf.py page1.dxf page1.pdf

Draws every layer that is switched on in the DXF (so not the hidden ones) as
vectors, so the PDF can be zoomed without limit, and puts a key under the drawing.
"""
import sys

import ezdxf
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from ezdxf import bbox  # noqa: E402
from ezdxf.addons.drawing import Frontend, RenderContext  # noqa: E402
from ezdxf.addons.drawing.config import BackgroundPolicy, Configuration  # noqa: E402
from ezdxf.addons.drawing.matplotlib import MatplotlibBackend  # noqa: E402
from ezdxf.colors import aci2rgb  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

DRAWING_SCALE = 48  # one inch on paper is 48 inches of building
KEY_ROWS = 3
KEY = {  # what each layer of vectorize_plan.py / apply_text.py holds
    "HEAVY_LINES": "walls and borders",
    "LINES": "thin lines",
    "LINES_DASHED": "dashed or broken lines",
    "LINES_SHORT": "short lines",
    "ARCS": "door swings, circles",
    "SYMBOLS": "marker symbols, traced",
    "TEXT": "lettering not retyped (stamps, unreadable), traced",
    "TEXT_DIM": "dimensions typed from the lettering: check",
    "TEXT_NOTE": "notes, room names, tags, title block",
    "TEXT_CHECK": "hard-to-read text: check",
}


def main(dxf_path, pdf_path):
  doc = ezdxf.readfile(dxf_path)
  msp = doc.modelspace()
  box = bbox.extents(msp, fast=True)
  x0, y0, x1, y1 = box.extmin.x, box.extmin.y, box.extmax.x, box.extmax.y
  width, height = (x1 - x0) / DRAWING_SCALE, (y1 - y0) / DRAWING_SCALE  # paper inches
  key_h = 0.5 * KEY_ROWS + 0.4
  fig = plt.figure()
  ax = fig.add_axes([0, 0, 1, 1])
  config = Configuration(background_policy=BackgroundPolicy.WHITE, lineweight_scaling=0.6)
  Frontend(RenderContext(doc), MatplotlibBackend(ax), config=config).draw_layout(msp, finalize=True)
  fig.set_size_inches(width + 0.5, height + 0.5 + key_h)  # the drawing resets it, so set it afterwards
  ax.set_aspect("equal", adjustable="box")
  ax.set_xlim(x0, x1)
  ax.set_ylim(y0, y1)
  ax.set_position([0.25 / fig.get_figwidth(), (0.25 + key_h) / fig.get_figheight(),
                   width / fig.get_figwidth(), height / fig.get_figheight()])

  # a key: one swatch per layer that is on and has something in it
  used = {e.dxf.layer for e in msp}
  layers = [(l.dxf.name, l.dxf.color) for l in doc.layers if not l.is_off() and l.dxf.name in used]
  per_row = -(-len(layers) // KEY_ROWS)
  for k, (name, colour) in enumerate(layers):
    row, col = divmod(k, per_row)
    fx, fy = (0.25 + col * (width / per_row)) / fig.get_figwidth(), (0.25 + 0.5 * (KEY_ROWS - row - 0.5)) / fig.get_figheight()
    rgb = "#000000" if colour == 7 else "#%02x%02x%02x" % aci2rgb(colour)
    fig.add_artist(Line2D([fx, fx + 0.3 / fig.get_figwidth()], [fy, fy], color=rgb, linewidth=3, transform=fig.transFigure))
    fig.text(fx + 0.4 / fig.get_figwidth(), fy, f"{name}: {KEY[name]}" if name in KEY else name, va="center", fontsize=9)
  fig.savefig(pdf_path, facecolor="white")
  print(f"Saved {pdf_path}: {width + 0.5:.1f} x {height + 0.5 + key_h:.1f} in, 1/4\" = 1'-0\"")


if __name__ == "__main__":
  if len(sys.argv) != 3:
    sys.exit(__doc__)
  main(sys.argv[1], sys.argv[2])

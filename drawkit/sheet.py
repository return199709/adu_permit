"""Sheet furniture: border, title strip, north arrow, legend."""
from . import core
from .core import line, fill, text, arc_pts

def frame(strip=4.8):
    """Sheet border with a title strip of the given width on the right.  Returns the x of the strip's left edge."""
    W, H = core.SHEET_W, core.SHEET_H; x = W - strip
    line('BORDER', (0.5, 0.5), (W - 0.5, 0.5), (W - 0.5, H - 0.5), (0.5, H - 0.5), closed=True)
    line('BORDER', (x, 0.5), (x, H - 0.5))
    return x

def title_strip(x, project, address, title, subtitle=(), blocks=(), scale='', date='', sheet='', rev=''):
    """Fill the title strip.  blocks: [(heading, [lines]), ...] such as sources and notes."""
    W, H = core.SHEET_W, core.SHEET_H
    tb = lambda y, s, h=0.1, bold=False, lay='NOTE': text(lay, (x + 0.2, y), s, h, 'l', bold=bold)
    tb(1.0, project, 0.24, True, 'ROOM')
    for i, s in enumerate(address): tb(1.38 + i * 0.22, s, 0.115)
    y = 1.38 + len(address) * 0.22 + 0.1; line('THIN', (x, y), (W - 0.5, y))
    tb(y + 0.3, title, 0.15, True, 'ROOM')
    for i, s in enumerate(subtitle): tb(y + 0.56 + i * 0.17, s, 0.085)
    y += 0.56 + len(subtitle) * 0.17 + 0.1
    for heading, lines_ in blocks:
        line('THIN', (x, y), (W - 0.5, y)); tb(y + 0.25, heading, 0.1, True, 'ROOM')
        for i, s in enumerate(lines_): tb(y + 0.5 + i * 0.165, s, 0.075)
        y += 0.5 + len(lines_) * 0.165 + 0.15
    yb = H - 3.0; line('THIN', (x, yb), (W - 0.5, yb))
    if rev: tb(yb - 0.25, rev, 0.07)
    tb(yb + 0.3, 'SCALE', 0.07); tb(yb + 0.52, scale, 0.1, True, 'ROOM')
    tb(yb + 0.85, 'DRAWN', 0.07); tb(yb + 1.07, date, 0.1, True, 'ROOM')
    tb(yb + 1.4, 'SHEET', 0.07); text('ROOM', (x + 0.2, yb + 2.0), sheet, 0.4, 'l', bold=True)

def north_arrow(x, y, r=0.42, layer='WALL-EXT'):
    line('THIN', *arc_pts((x, y), r, 0, 360, 40))
    fill(layer, [(x, y - r * 1.48), (x - r * 0.4, y + r * 0.6), (x, y + r * 0.24), (x + r * 0.4, y + r * 0.6)])
    text('ROOM', (x, y - r * 1.9), 'N', r / 3, bold=True)

def legend(x, y, items, title='LEGEND', col=10.6, per_col=4):
    """items: [(layer, 'bar' or 'line', description), ...]"""
    text('ROOM', (x, y - 0.12), title, 0.12, 'l', bold=True)
    for i, (lay, kind, desc) in enumerate(items):
        xx = x + (i // per_col) * col; yy = y + 0.18 + (i % per_col) * 0.3
        if kind == 'bar': fill(lay, [(xx, yy - 0.055), (xx + 1.2, yy - 0.055), (xx + 1.2, yy + 0.055), (xx, yy + 0.055)])
        else: line(lay, (xx, yy), (xx + 1.2, yy))
        text('NOTE', (xx + 1.4, yy), desc, 0.085, 'l')

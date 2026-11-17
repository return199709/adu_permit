"""Render a sheet DXF to PDF with drawkit's layer styles, so a sheet can be maintained as an edited DXF.

    python -m drawkit.dxf2pdf in.dxf out.pdf K "pdf title"

K = model inches per sheet inch = 12 / (sheet inches per foot): 48 for 1/4" plans, 64 for 3/16" elevations,
8 for 1 1/2" details.  Layer names are <prefix>-<drawkit layer>; the prefix is ignored.  Entities read:
LWPOLYLINE, HATCH (polyline paths) and TEXT.  A text style whose name ends in B or BOLD renders bold."""
import sys
from . import core, render

def convert(src, out, K, title, author=''):
    import ezdxf
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from ezdxf.enums import TextEntityAlignment as TA
    render.register_fonts()
    ents = list(ezdxf.readfile(src).modelspace())
    lay_of = lambda e: e.dxf.layer.split('-', 1)[1]
    used = {lay_of(e) for e in ents}; assert used <= set(core.ORDER), f'undefined layers: {used - set(core.ORDER)}'
    key = lambda pts: tuple((round(x, 2), round(y, 2)) for x, y in pts)
    hatched = set()
    for e in ents:
        if e.dxftype() == 'HATCH':
            for path in e.paths: hatched.add((e.dxf.layer, key([(v[0], v[1]) for v in path.vertices])))
    c = canvas.Canvas(out, pagesize=(core.SHEET_W * 72, core.SHEET_H * 72)); c.setTitle(title); c.setAuthor(author)
    P = lambda x, y: (x / K * 72, y / K * 72)
    for lay in core.ORDER:
        if lay not in used: continue
        rgb, lw, dash, _ = core.LAYERS[lay]
        c.setStrokeColorRGB(*rgb); c.setFillColorRGB(*rgb); c.setLineWidth(lw); c.setLineCap(0)
        if dash: c.setDash(list(dash))
        else: c.setDash()
        for e in ents:
            if lay_of(e) != lay: continue
            t = e.dxftype()
            if t == 'LWPOLYLINE':
                pts = [(q[0], q[1]) for q in e.get_points()]
                if (e.dxf.layer, key(pts)) in hatched: continue      # outline of a fill on the same layer: the hatch draws it
                p = c.beginPath(); p.moveTo(*P(*pts[0]))
                for q in pts[1:]: p.lineTo(*P(*q))
                if e.closed: p.close()
                if lay in core.WHITE_FILLED and e.closed:
                    c.setFillColorRGB(1, 1, 1); c.drawPath(p, stroke=1, fill=1); c.setFillColorRGB(*rgb)
                else: c.drawPath(p, stroke=1, fill=0)
            elif t == 'HATCH':
                p = c.beginPath()
                for path in e.paths:
                    vs = [(v[0], v[1]) for v in path.vertices]; p.moveTo(*P(*vs[0]))
                    for q in vs[1:]: p.lineTo(*P(*q))
                    p.close()
                c.drawPath(p, stroke=0, fill=1, fillMode=0)
            elif t == 'TEXT':
                al, p1, p2 = e.get_placement(); size = e.dxf.height / K * 100
                f = 'B' if e.dxf.style.upper().endswith(('B', 'BOLD')) else 'R'
                x, y = P(p1[0], p1[1]); s = e.dxf.text; w = pdfmetrics.stringWidth(s, f, size)
                dx = {TA.MIDDLE_CENTER: -w / 2, TA.MIDDLE_LEFT: 0, TA.MIDDLE_RIGHT: -w}[al]
                c.saveState(); c.translate(x, y); c.rotate(e.dxf.rotation); c.setFont(f, size); c.drawString(dx, -size * 0.36, s); c.restoreState()
    c.showPage(); c.save()

if __name__ == '__main__': convert(sys.argv[1], sys.argv[2], float(sys.argv[3]), sys.argv[4])

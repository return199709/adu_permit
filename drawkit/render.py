"""Write the primitives collected in drawkit.core to <out>.pdf and <out>.dxf."""
import os
from . import core

FONT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'fonts')

def register_fonts():
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    pdfmetrics.registerFont(TTFont('R', os.path.join(FONT_DIR, 'LiberationSans-Regular.ttf')))
    pdfmetrics.registerFont(TTFont('B', os.path.join(FONT_DIR, 'LiberationSans-Bold.ttf')))

def write(out, title, author=''):
    from reportlab.pdfgen import canvas
    from reportlab.pdfbase import pdfmetrics
    from fontTools.ttLib import TTFont as FT
    import ezdxf
    from ezdxf.enums import TextEntityAlignment as TA
    PR, LAYERS, W, H = core.PR, core.LAYERS, core.SHEET_W, core.SHEET_H
    register_fonts()
    cm = FT(os.path.join(FONT_DIR, 'LiberationSans-Regular.ttf')).getBestCmap()
    miss = {ch for k, l, d in PR if k == 'tx' for ch in d[1] if ord(ch) not in cm}
    if miss: print('missing glyphs:', miss)
    used = {l for _, l, _ in PR}
    assert used <= set(core.ORDER), f'undefined layers: {used - set(core.ORDER)}'

    # ------------------------------------------------------------ PDF
    I = 72.0
    c = canvas.Canvas(out + '.pdf', pagesize=(W * I, H * I)); c.setTitle(title); c.setAuthor(author)
    def P(p): return (p[0] * I, (H - p[1]) * I)
    for lay in core.ORDER:
        if lay not in used: continue
        rgb, lw, dash, _ = LAYERS[lay]
        c.setStrokeColorRGB(*rgb); c.setFillColorRGB(*rgb); c.setLineWidth(lw); c.setLineCap(0)
        if dash: c.setDash(list(dash))
        else: c.setDash()
        for k, l, d in PR:
            if l != lay: continue
            if k == 'pl':
                pts, closed, fl = d; p = c.beginPath(); p.moveTo(*P(pts[0]))
                for q in pts[1:]: p.lineTo(*P(q))
                if closed: p.close()
                if lay in core.WHITE_FILLED and closed and not fl:
                    c.setFillColorRGB(1, 1, 1); c.drawPath(p, stroke=1, fill=1); c.setFillColorRGB(*rgb)
                else: c.drawPath(p, stroke=0 if fl else 1, fill=1 if fl else 0)
            elif k == 'cp':
                p = c.beginPath()
                for ring in d:
                    p.moveTo(*P(ring[0]))
                    for q in ring[1:]: p.lineTo(*P(q))
                    p.close()
                c.drawPath(p, stroke=0, fill=1, fillMode=0)
            elif k == 'tx':
                (pt, s, h, al, rot, bold) = d; f = 'B' if bold else 'R'; size = h * I / 0.72
                x, y = P(pt); c.saveState(); c.translate(x, y); c.rotate(rot); c.setFont(f, size)
                w = pdfmetrics.stringWidth(s, f, size); dx = {'c': -w / 2, 'l': 0, 'r': -w}[al]
                c.drawString(dx, -size * 0.36, s); c.restoreState()
    c.showPage(); c.save()

    # ------------------------------------------------------------ DXF (model space in real-world inches)
    K = 12.0 / core.SC; pre = core.DXF_PREFIX
    doc = ezdxf.new('R2010', setup=True); doc.units = ezdxf.units.IN; doc.header['$INSUNITS'] = 1
    doc.styles.add('TEXT', font='arial.ttf'); doc.styles.add('TEXT-BOLD', font='arialbd.ttf')
    for name in core.ORDER:
        if name in used:
            rgb, lw, dash, aci = LAYERS[name]; doc.layers.add(pre + name, color=aci, linetype='DASHED' if dash else 'Continuous')
    doc.header['$LTSCALE'] = 12
    msp = doc.modelspace()
    def Q(p): return (round(p[0] * K, 3), round((H - p[1]) * K, 3))
    for k, l, d in PR:
        L = pre + l
        if k == 'pl':
            pts, closed, fl = d
            msp.add_lwpolyline([Q(p) for p in pts], close=closed, dxfattribs={'layer': L})
            if fl:
                h = msp.add_hatch(dxfattribs={'layer': L}); h.paths.add_polyline_path([Q(p) for p in pts], is_closed=True)
        elif k == 'cp':
            h = msp.add_hatch(dxfattribs={'layer': L})
            for i, ring in enumerate(d):
                msp.add_lwpolyline([Q(p) for p in ring], close=True, dxfattribs={'layer': L})
                h.paths.add_polyline_path([Q(p) for p in ring], is_closed=True, flags=ezdxf.const.BOUNDARY_PATH_EXTERNAL if i == 0 else ezdxf.const.BOUNDARY_PATH_OUTERMOST)
        elif k == 'tx':
            (pt, s, hh, al, rot, bold) = d
            t = msp.add_text(s, height=hh * K, rotation=rot, dxfattribs={'layer': L, 'style': 'TEXT-BOLD' if bold else 'TEXT'})
            t.set_placement(Q(pt), align={'c': TA.MIDDLE_CENTER, 'l': TA.MIDDLE_LEFT, 'r': TA.MIDDLE_RIGHT}[al])
    doc.saveas(out + '.dxf')
    errs = len(ezdxf.readfile(out + '.dxf').audit().errors)
    return f'{len(PR)} primitives, DXF audit errors {errs}'

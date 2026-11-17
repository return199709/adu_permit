"""Sheet A-2: site plan and roof plan for the made-up house.  The building comes from floor_plan.py."""
import floor_plan                       # importing it draws A-1; the primitives are cleared below
from drawkit import core, sheet, roof
core.PR.clear(); core.set_scale(0.1)    # site plan at 1" = 10'
from drawkit.core import *
from floor_plan import HOUSE, ADDITION, WINGS

# ---- lot: 100 x 100 ft, corner of two streets, 15 ft radius at the south-east corner (x east, y south)
LOT = [(0, 0), (100, 0)] + arc_pts((85, 85), 15, 0, 90, 16) + [(0, 100)]
BX, BY = 14.0, 20.0                     # where the building's (0, 0) sits on the lot
B = lambda q: (BX + q[0], BY + q[1])
faces, outline = roof.hip_roof(WINGS, pitch=4 / 12, eave=2.0)

v = View(3.5, 7.0)
line('PL', *[v.p(*q) for q in LOT], closed=True)
line('ROW-CL', v.p(130, -15), v.p(130, 140)); line('ROW-CL', v.p(-10, 130), v.p(145, 130))
line('ESMT', *[v.p(*q) for q in [(95, 0)] + arc_pts((85, 85), 10, 0, 90, 16) + [(0, 95)]])
line('SETBK', v.p(5, 5), v.p(80, 5), v.p(80, 90), v.p(5, 90), closed=True)
roof.draw_roof(v, faces, outline, B)
line('FOOT', *[v.p(*B(q)) for q in HOUSE], closed=True); fill('TINT', [v.p(*B(q)) for q in ADDITION]); line('FOOT', *[v.p(*B(q)) for q in ADDITION], closed=True)
text('ROOM', v.p(118, 50), 'FIRST STREET', 0.15, 'c', 90, bold=True); text('ROOM', v.p(50, 118), 'OAK LANE', 0.15, bold=True)
text('NOTE', v.p(50, -2.2), "PROPERTY LINE  100.00'", 0.08, bold=True); text('NOTE', v.p(-2.4, 50), "PROPERTY LINE  100.00'", 0.08, 'c', 90, bold=True)
text('FLAG', v.p(40, 93.4), "5' UTILITY EASEMENT", 0.055); text('NOTE', v.p(42, 6.6), 'SETBACK LINE', 0.05)
text('NOTE', v.p(BX + 24, BY + 13), 'EXISTING RESIDENCE', 0.085, bold=True); text('FLAG', v.p(BX + 14, BY + 32), 'ADDITION', 0.06, bold=True)
dim(v, (100, -8), (130, -8), -3, "30'"); text('DIM', v.p(115, -15), "60' RIGHT-OF-WAY", 0.07)
for a, b in [((BX + 10, 0), (BX + 10, BY)), ((0, BY + 10), (BX, BY + 10)), ((BX + 66, BY + 15), (100, BY + 15)), ((BX + 14, BY + 38), (BX + 14, 100))]:
    dim(v, a, b, 0.01, ftin(abs(a[0] - b[0]) + abs(a[1] - b[1])))
text('ROOM', (3.5 + 5.0, 7.0 + 14.6), 'SITE PLAN', 0.2, bold=True); text('NOTE', (3.5 + 5.0, 7.0 + 14.9), "SCALE: 1\" = 10'", 0.1)
sheet.north_arrow(3.5 + 13.6, 7.0 + 12.5)

r = View(19.5, 8.0, sc=0.1875)          # roof plan at 3/16" = 1'-0"
roof.draw_roof(r, faces, outline)
line('FOOT', *[r.p(*q) for q in HOUSE], closed=True); line('FOOT', *[r.p(*q) for q in ADDITION], closed=True)
dim(r, (0, -2), (66, -2), -3.0, ftin(66) + '  (WALLS)'); dim(r, (-2, 20), (0, 20), 2.2, "2'-0\" EAVE")
text('NOTE', r.p(22, 10), '4:12 HIP ROOF', 0.075, bold=True)
text('ROOM', r.p(33, 47), 'ROOF PLAN', 0.2, bold=True); text('NOTE', r.p(33, 48.6), "SCALE: 3/16\" = 1'-0\"   ·   DASHED = LINE OF WALLS BELOW", 0.1)

x = sheet.frame()
sheet.title_strip(x, 'SAMPLE RESIDENCE', ['100 EXAMPLE STREET', 'ANYTOWN'], 'SITE AND ROOF PLAN', ['Made-up data for the drawkit example'],
                  [('NOTES', ['1. Every number on this sheet is invented.', '2. Roof planes are computed from the wing', '   rectangles by drawkit.roof.'])],
                  scale='AS NOTED', date='2026', sheet='A-2')

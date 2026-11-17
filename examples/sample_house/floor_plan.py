"""Sheet A-1: floor plan of a made-up one-story house with a rear addition.  Feet, x east, y south."""
from drawkit.core import *
from drawkit import sheet

# ---- the building as numbers (site_plan.py imports these)
HOUSE = [(0, 0), (44, 0), (44, 4), (66, 4), (66, 26), (0, 26)]        # existing house with attached garage
ADDITION = [(6, 26), (22, 26), (22, 38), (6, 38)]                     # new rear addition
WINGS = [(0, 44, 0, 26, 9.0), (44, 66, 4, 26, 9.0), (6, 22, 26, 38, 9.0)]   # x0, x1, y0, y1, plate height (roof plan)

v = View(7.5, 6.0)
f = Floor(v, HOUSE)
f.extwall((44.25, 4), (44.25, 26))                                    # house / garage wall
for a, b in [((20, 0), (20, 14)), ((0, 14), (30, 14)), ((14, 14), (14, 26)), ((30, 12), (30, 26)), ((30, 12), (44, 12)), ((22, 20), (30, 20))]:
    f.wall(a, b)
f.door((24, 0), (27, 0), (25, 3), ext=True)                           # front door
f.door((66, 7), (66, 23), (60, 15), ext=True, overhead=True)          # garage door
f.door((10, 26), (16, 26), (13, 24), ext=True, slider=True)           # slider to the addition
f.door((44.25, 18), (44.25, 21), (48, 19))
f.door((20, 9), (20, 12), (17, 10)); f.door((9, 14), (12, 14), (10, 17)); f.door((17, 14), (19.5, 14), (18, 17))
f.door((30, 15), (30, 18), (33, 16)); f.door((24.5, 20), (27, 20), (26, 22))
for a, b in [((4, 0), (10, 0)), ((32, 0), (38, 0)), ((0, 4), (0, 9)), ((0, 17), (0, 22)), ((34, 26), (40, 26))]: f.window(a, b)
f.render()

g = Floor(v, ADDITION, ext='WALL-NEW')                                # the addition, in the "new work" colour
g.cuts.append(Polygon([(6.5, 25.9), (21.5, 25.9), (21.5, 26.6), (6.5, 26.6)]))   # it shares the house wall: no north wall of its own
g.window((10, 38), (18, 38)); g.window((6, 30), (6, 35))
g.render()

room(v, 10, 7, 'LIVING ROOM'); room(v, 26, 6.5, 'KITCHEN'); room(v, 37, 6, 'DINING'); room(v, 7, 20, 'BEDROOM')
room(v, 18, 20, 'BATH', h=0.1); room(v, 37, 19, 'BEDROOM'); room(v, 26, 17, 'HALL', h=0.09); room(v, 26, 23.3, 'CLOSET', h=0.08)
room(v, 55, 15, 'GARAGE', ['NOT IN LIVING AREA', "22'-0\" × 22'-0\" = 484 SF"])
room(v, 14, 32, 'ADDITION', ["16'-0\" × 12'-0\" = 192 SF"])

dim(v, (0, 0), (44, 0), -3.0, ftin(44)); dim(v, (44, 4), (66, 4), -7.0, ftin(22)); dim(v, (0, 0), (66, 0), -6.0, ftin(66) + '  OVERALL')
dim(v, (0, 0), (0, 26), -3.0, ftin(26)); dim(v, (66, 4), (66, 26), 3.0, ftin(22))
dim(v, (6, 38), (22, 38), 3.0, ftin(16), layer='DIM-NEW'); dim(v, (22, 26), (22, 38), 3.0, ftin(12), layer='DIM-NEW')
dim(v, (0, 26), (6, 26), 2.4, ftin(6))
text('ROOM', v.p(33, 46), 'FLOOR PLAN', 0.2, bold=True); text('NOTE', v.p(33, 47.6), "SCALE: 1/4\" = 1'-0\"", 0.1)

y = table(27.0, 6.5, [5.4, 1.9], [
    ['AREA', 'SQ FT'],
    ['Existing house (44 × 26)', '1,144'],
    ['Garage (22 × 22), not living area', '484'],
    [('New addition (16 × 12)',), ('192',)],
    ['Living area with the addition', '1,336'],
], 'AREAS')
sheet.legend(27.0, y + 1.0, [('WALL-EXT', 'bar', 'Existing exterior wall'), ('WALL-INT', 'bar', 'Existing interior partition'),
                             ('WALL-NEW', 'bar', 'New wall'), ('DIM', 'line', 'Existing dimension'), ('DIM-NEW', 'line', 'New-work dimension')], per_col=5)
sheet.north_arrow(34.5, 14.5)
x = sheet.frame()
sheet.title_strip(x, 'SAMPLE RESIDENCE', ['100 EXAMPLE STREET', 'ANYTOWN'], 'FLOOR PLAN', ['Made-up data for the drawkit example'],
                  [('NOTES', ['1. Every number on this sheet is invented.', '2. Black walls: existing. Teal: new work.', '3. Dimensions are to outside faces.'])],
                  scale="1/4\" = 1'-0\"", date='2026', sheet='A-1')

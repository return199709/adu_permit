"""T-1: scope, property information, code check, areas, yards and the city's plan checklist."""
import textwrap
from drawkit.core import *
from . import load, strip

a, r, res, cfg = load(); p = a['project']; j = r['jurisdiction']
F = lambda s: (s,)
text('ROOM', (1.2, 1.5), p['name'].upper(), 0.3, 'l', bold=True)
text('NOTE', (1.2, 2.0), ', '.join(p.get('address', [])), 0.14, 'l')
text('ROOM', (1.2, 2.9), 'SCOPE OF WORK', 0.12, 'l', bold=True)
for i, s in enumerate(textwrap.wrap(p.get('scope', ''), 120)): text('NOTE', (1.2, 3.2 + i * 0.22), s, 0.1, 'l')
y = table(1.2, 4.6, [3.2, 5.2], [['PROPERTY', ''], ['Jurisdiction', f"{j['name']}, {j['state']}"], ['Zone', p.get('zone') or j.get('zone', '')],
                                 ['Lot area', f"{res['lot_area']:,.0f} SF"], ['Project type', p.get('type', '').replace('_', ' ')]], 'PROPERTY INFORMATION')
flag = lambda row, bad: [F(c) for c in row] if bad else list(row)
rows = [['RULE', 'LIMIT', 'PROPOSED', 'RESULT']] + [flag([n, lim, prop, st + (f' — {note}' if note else '')], st != 'OK') for n, lim, prop, st, note in res['rows']]
y = table(1.2, y + 0.8, [4.6, 2.6, 2.8, 6.2], rows, 'CODE CHECK')
if res['skipped']: text('FLAG', (1.2, y + 0.2), f"{res['skipped']} rule(s) in the rule file have not been reviewed by a person and were not applied.", 0.085, 'l')
if any('[DRAFT RULE]' in n for n, *_ in res['rows']): text('FLAG', (1.2, y + 0.2), 'Rows marked [DRAFT RULE] were extracted automatically and have not been reviewed by a person.', 0.085, 'l')
cat = {'living': 'living area', 'garage': 'garage', 'covered_patio': 'covered patio', 'accessory': 'accessory structure'}
y2 = table(18.5, 4.6, [5.0, 2.6, 1.6, 1.6], [['AREA', 'COUNTED AS', 'SQ FT', 'NEW']] + [flag([n, cat.get(c, c), f'{s:,.1f}', 'yes' if new else ''], new) for n, s, c, new, _ in res['areas']], 'AREAS')
y2 = table(18.5, y2 + 0.8, [3.0, 3.0, 4.8], [['LOT LINE', 'ROLE', 'NEW WORK TO PROPERTY LINE']] + [[s.capitalize(), res['roles'][s].replace('_', ' '), ftin(res['yards'][s])] for s in ('north', 'east', 'south', 'west')], 'YARDS')
SHOWN = {'title sheet': 'T-1', 'site plan': 'A-1', 'roof plan': 'A-1', 'floor plan': 'A-2'}
sub = [['THE CITY EXPECTS', 'WHERE']] + [flag([f"{s['sheet'].capitalize()}: {s['text']}"[:118], SHOWN.get(s['sheet'], 'NOT IN THIS SET')], s['sheet'] not in SHOWN) for s in r.get('submittal', [])]
if len(sub) > 1: y = table(1.2, max(y, y2) + 1.0, [14.2, 2.4], sub, 'PLAN CHECKLIST', hs=0.075)
for i, n in enumerate(res['notes'][:8]): text('NOTE', (18.5, y2 + 0.9 + i * 0.22), '• ' + n['text'][:150], 0.08, 'l')
strip(a, 'COVER SHEET', 'T-1', ['Code check from the rule file for', f"{j['name']}. Limits are only as good", 'as that file: see who reviewed it.'])

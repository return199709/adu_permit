"""Check an owner's answers against a rule file.

Geometry in the answers is in feet from the lot's north-west corner: x east, y south."""
import json, math
from . import schema

SIDES = ('north', 'east', 'south', 'west'); OPP = {'north': 'south', 'south': 'north', 'east': 'west', 'west': 'east'}

def lot_area(lot):
    if lot.get('area_sf'): return float(lot['area_sf'])
    r = lot.get('corner_radius_ft', 0) or 0
    return lot['width_ft'] * lot['depth_ft'] - (r * r - math.pi * r * r / 4)

def sf(w): return w['w'] * w['d']

def areas(a):
    """Rows of (name, square feet, category, is_new, has footprint)."""
    rows = [(w['name'], sf(w), w.get('counts_as', 'living'), False, True) for w in a['existing']['wings']]
    rows += [(o['name'], o['sf'], o['counts_as'], False, o.get('footprint', True)) for o in a['existing'].get('other_areas', [])]
    if a['existing'].get('second_floor_sf'): rows.append(('Second floor', a['existing']['second_floor_sf'], 'living', False, False))
    n = a['new']; rows.append((n['name'], sf(n), n.get('counts_as', 'living'), True, True))
    return rows

def yards(a):
    """Distance from the new work to each property line, and which line is the front, rear and so on."""
    lot, n = a['lot'], a['new']
    d = {'west': n['x'], 'north': n['y'], 'east': lot['width_ft'] - n['x'] - n['w'], 'south': lot['depth_ft'] - n['y'] - n['d']}
    front = lot['front']; street = lot.get('street_side'); role = {front: 'front', OPP[front]: 'rear'}
    for s in SIDES:
        if s not in role: role[s] = 'street_side' if s == street else 'interior_side'
    return d, role

def run(answers, rules, allow_draft=False):
    """Returns {'rows': [...], 'missing': [...], 'skipped': n}.  Each row: rule, limit, proposed, status, note."""
    a = answers if isinstance(answers, dict) else json.load(open(answers))
    r = rules if isinstance(rules, dict) else schema.load(rules)
    use = schema.usable(r, allow_draft); ptype = a['project'].get('type', 'adu')
    use = [x for x in use if not x.get('applies_to') or ptype in x['applies_to']]
    L = lot_area(a['lot']); rows_a = areas(a); d, role = yards(a); out = []; missing = []
    exc = {x['params']['applies_to']: x for x in use if x['kind'] == 'exception'}
    def judge(value, limit, what, lower_is_ok=True):
        ok = value <= limit + 1e-9 if lower_is_ok else value >= limit - 1e-9
        if ok: return 'OK', ''
        e = exc.get(what)
        if e:
            lim2 = limit * (1 + e['params']['percent'] / 100) if lower_is_ok else limit * (1 - e['params']['percent'] / 100)
            if (value <= lim2 + 1e-9) if lower_is_ok else (value >= lim2 - 1e-9):
                return 'NEEDS EXCEPTION', f"within {e['params'].get('name', 'the exception')} ({e['params']['percent']:g}%: {lim2:,.1f})"
            return 'OVER', f"exceeds even {e['params'].get('name', 'the exception')} ({lim2:,.1f})"
        return 'OVER', ''
    for x in use:
        k, p = x['kind'], x['params']; tag = '' if x['reviewed'] else ' [DRAFT RULE]'
        if k == 'max_floor_area':
            counts = p.get('counts', ['living', 'garage', 'covered_patio'])
            total = sum(s for _, s, c, _, _ in rows_a if c in counts); limit = p.get('base_sf', 0) + p.get('lot_fraction', 0) * L
            if p.get('cap_sf'): limit = min(limit, p['cap_sf'])
            st, note = judge(total, limit, 'floor_area'); out.append((x['id'] + tag, f'{limit:,.1f} SF', f'{total:,.1f} SF', st, note))
        elif k == 'max_lot_coverage':
            counts = p.get('counts', ['living', 'garage', 'covered_patio', 'accessory'])
            cov = sum(s for _, s, c, _, fp in rows_a if fp and c in counts); limit = p['fraction'] * L
            st, note = judge(cov, limit, 'lot_coverage'); out.append((x['id'] + tag, f"{limit:,.1f} SF ({p['fraction']:.0%})", f'{cov:,.1f} SF ({cov / L:.1%})', st, note))
        elif k == 'setback':
            for side in SIDES:
                if role[side] == p['side']:
                    st, note = judge(d[side], p['feet'], 'setback', lower_is_ok=False)
                    if p.get('measured_from'): note = (note + '; ' if note else '') + 'measured from ' + p['measured_from']
                    out.append((f"{x['id']} ({side}){tag}", f"{p['feet']:g} ft min", f'{d[side]:.1f} ft', st, note))
        elif k == 'max_unit_size':
            st, note = judge(sf(a['new']), p['sf'], 'unit_size'); out.append((x['id'] + tag, f"{p['sf']:,.0f} SF", f"{sf(a['new']):,.0f} SF", st, note))
        elif k == 'max_height':
            h = a['new'].get('height_ft')
            if h is None: missing.append('new.height_ft (height of the new work)')
            else: st, note = judge(h, p['feet'], 'height'); out.append((x['id'] + tag, f"{p['feet']:g} ft", f'{h:g} ft', st, note))
        elif k == 'max_second_story_fraction':
            fa = next((y for y in use if y['kind'] == 'max_floor_area'), None); s2 = a['existing'].get('second_floor_sf', 0)
            if fa:
                lim = fa['params'].get('base_sf', 0) + fa['params'].get('lot_fraction', 0) * L
                if fa['params'].get('cap_sf'): lim = min(lim, fa['params']['cap_sf'])
                st, note = judge(s2, p['fraction'] * lim, 'second_story'); out.append((x['id'] + tag, f"{p['fraction'] * lim:,.1f} SF", f'{s2:,.1f} SF', st, note))
    skipped = len([x for x in r['rules'] if not x['reviewed']]) if not allow_draft else 0
    return {'rows': out, 'missing': missing, 'skipped': skipped, 'lot_area': L, 'areas': rows_a, 'yards': d, 'roles': role,
            'notes': [x for x in use if x['kind'] == 'note']}

def report(res):
    w = max([len(r[0]) for r in res['rows']] + [10])
    for name, lim, prop, st, note in res['rows']: print(f'{name:<{w}}  limit {lim:<22} proposed {prop:<24} {st}' + (f'  ({note})' if note else ''))
    for m in res['missing']: print('MISSING ANSWER:', m)
    if res['skipped']: print(f"{res['skipped']} rule(s) were not applied because nobody has reviewed them (use --allow-draft to see them)")
    return not any(r[3] == 'OVER' for r in res['rows'])

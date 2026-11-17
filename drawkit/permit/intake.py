"""What to ask the owner for: measurements, photos and documents, derived from the rule file and the project type."""
import json
from . import schema

BASE_MEASURE = [
    ('lot.width_ft, lot.depth_ft', 'Lot width and depth along the property lines', 'From the plat, tract map or deed, not from fences.'),
    ('lot.front, lot.street_side, lot.streets', 'Which lot line is the street front, and whether another line is also on a street', 'Setbacks depend on it.'),
    ('existing.wings[]', 'Each rectangular part of the existing house: width, depth, and its distance from the north and west property lines', 'Measure outside wall to outside wall.'),
    ('new: x, y, w, d', 'The new work: outside width and depth, and its distance from the north and west property lines', 'Measure from the property line, not the curb or fence.'),
    ('new.plate_ft, new.height_ft', 'Wall height to the top plate and overall height to the ridge of the new work', ''),
    ('new.openings[]', 'Every door and window of the new work: which wall, distance from the left corner, width', ''),
]
BASE_PHOTOS = [
    'Each face of the existing house, straight on (north, south, east, west)',
    'The place where the new work goes, from two directions',
    'Both street frontages showing curb, sidewalk and the front of the house',
    'Roof eave and wall finish where the new work meets or faces the house (to match materials)',
    'Electric panel, gas meter, water meter and sewer cleanout, each with something for scale',
]
BASE_DOCS = ['Plat, tract map or deed with the lot dimensions', 'Any previously approved plans for the house', 'Assessor record (parcel number, lot size, building size)']
BY_KIND = {
    'max_floor_area': ([('lot.area_sf', 'Net lot area in square feet', 'The floor-area limit is computed from it.'),
                        ('existing.other_areas[], existing.second_floor_sf', 'Area of every space the code counts: {counts}, and the second floor', 'Covered patios and attached garages are often counted.')], [], []),
    'max_lot_coverage': ([('existing.other_areas[]', 'Footprint of every roofed structure on the lot, including sheds, carports and covered patios', '')],
                         ['Every accessory structure on the lot (shed, carport, pergola, pool equipment)'], []),
    'setback': ([('new: x, y', 'Distance from the new work to the {side} property line', '{measured_from}')], [], []),
    'exception': ([], [], ['Preliminary title report and a written justification, if an exception will be requested']),
}

def build(rules, project_type='adu', allow_draft=True):
    r = rules if isinstance(rules, dict) else schema.load(rules)
    use = [x for x in schema.usable(r, allow_draft) if not x.get('applies_to') or project_type in x['applies_to']]
    measure = [dict(field=f, ask=a, note=n, because='always needed') for f, a, n in BASE_MEASURE]
    photos = [dict(ask=p, because='always needed') for p in BASE_PHOTOS]; docs = [dict(ask=d, because='always needed') for d in BASE_DOCS]
    seen = {m['ask'] for m in measure}
    for x in use:
        ms, ps, ds = BY_KIND.get(x['kind'], ([], [], []))
        p = dict(x['params']); p.setdefault('measured_from', ''); p['counts'] = ', '.join(c.replace('_', ' ') for c in p.get('counts', ['living area', 'garage', 'covered patio']))
        p['side'] = str(p.get('side', '')).replace('_', ' ')
        for f, a, n in ms:
            a, n = a.format(**p), n.format(**p)
            if a not in seen: seen.add(a); measure.append(dict(field=f, ask=a, note=('Measured from ' + n if x['kind'] == 'setback' and n else n), because=x['id']))
        for q in ps:
            if q not in seen: seen.add(q); photos.append(dict(ask=q, because=x['id']))
        for q in ds:
            if q not in seen: seen.add(q); docs.append(dict(ask=q, because=x['id']))
    for s in r.get('submittal', []):
        t = s['text'].lower()
        if 'sewer' in t and 'Where the sewer lateral or cleanout is, measured from two walls' not in seen:
            seen.add('Where the sewer lateral or cleanout is, measured from two walls'); measure.append(dict(field='utilities.sewer_poc', ask='Where the sewer lateral or cleanout is, measured from two walls', note='', because=s['id']))
        if 'drain' in t and 'slope' not in ''.join(seen):
            photos.append(dict(ask='The ground around the new work after rain or with a level, showing which way it slopes', because=s['id'])); seen.add('slope')
        if 'schedule' in t and 'window' in t:
            measure.append(dict(field='new.openings[]: height, material', ask='Height, material and finish of every new window and door', note='', because=s['id']))
    return {'jurisdiction': r['jurisdiction'], 'project_type': project_type, 'measurements': measure, 'photos': photos, 'documents': docs,
            'plans_must_show': [dict(sheet=s['sheet'], text=s['text'], reviewed=s['reviewed']) for s in r.get('submittal', [])],
            'open_questions': r.get('open_questions', []), 'draft_rules': [x['id'] for x in use if not x['reviewed']]}

def markdown(q):
    j = q['jurisdiction']; out = [f"# What we need to draw your {q['project_type'].replace('_', ' ')} — {j['name']}, {j['state']}", '']
    if q['draft_rules']: out += [f"> {len(q['draft_rules'])} of the city rules behind this list have not been checked by a person yet.", '']
    out += ['## Measurements', '']
    out += [f"{i}. **{m['ask']}.** {m['note']}".rstrip() for i, m in enumerate(q['measurements'], 1)]
    out += ['', '## Photos', ''] + [f"{i}. {p['ask']}." for i, p in enumerate(q['photos'], 1)]
    out += ['', '## Documents', ''] + [f"{i}. {d['ask']}." for i, d in enumerate(q['documents'], 1)]
    if q['plans_must_show']: out += ['', '## What the city expects on the plans', ''] + [f"- **{s['sheet'].capitalize()}:** {s['text']}" for s in q['plans_must_show']]
    if q['open_questions']: out += ['', '## Questions for the city', ''] + [f'- {x}' for x in q['open_questions']]
    return '\n'.join(out) + '\n'

TEMPLATE = {
    'project': {'name': '', 'address': ['', ''], 'scope': '', 'type': 'adu', 'zone': ''},
    'lot': {'width_ft': None, 'depth_ft': None, 'area_sf': None, 'corner_radius_ft': 0, 'front': 'east', 'street_side': None, 'streets': {}},
    'existing': {'wings': [{'name': 'House', 'x': None, 'y': None, 'w': None, 'd': None, 'plate_ft': 9, 'counts_as': 'living'}], 'other_areas': [], 'second_floor_sf': 0},
    'new': {'name': 'ADU', 'x': None, 'y': None, 'w': None, 'd': None, 'plate_ft': 9, 'height_ft': None, 'counts_as': 'living', 'openings': []},
    'utilities': {'sewer_poc': None},
}

def write(rules, project_type, outdir):
    import os
    os.makedirs(outdir, exist_ok=True); q = build(rules, project_type)
    open(os.path.join(outdir, 'intake.md'), 'w').write(markdown(q)); json.dump(q, open(os.path.join(outdir, 'intake.json'), 'w'), indent=2, ensure_ascii=False)
    t = json.loads(json.dumps(TEMPLATE)); t['project']['type'] = project_type
    json.dump(t, open(os.path.join(outdir, 'answers.template.json'), 'w'), indent=2)
    print(f"{len(q['measurements'])} measurements, {len(q['photos'])} photos, {len(q['documents'])} documents -> {outdir}/intake.md")

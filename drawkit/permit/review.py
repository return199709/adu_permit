"""Human review of a draft rule file: list what is unreviewed, approve items, or delete wrong ones."""
import datetime, json
from . import schema

def show(path):
    r = schema.load(path); n = 0
    for group in ('rules', 'submittal'):
        for x in r[group]:
            mark = 'ok ' if x['reviewed'] else '?? '; n += not x['reviewed']
            s = x.get('source', {})
            print(f"{mark}{group[:4]}  {x['id']}: {x['text']}")
            if not x['reviewed']:
                print(f"         quote: \"{s.get('quote', '')}\"" + ('' if x.get('quote_found', True) else '   <-- NOT FOUND IN SOURCE TEXT'))
                print(f"         where: {s.get('section', '')} {s.get('url', s.get('title', ''))}")
    for q in r['open_questions']: print('open ', q)
    print(f'{n} item(s) still need review')

def approve(path, ids, by):
    r = json.load(open(path)); today = datetime.date.today().isoformat(); done = []
    for group in ('rules', 'submittal'):
        for x in r[group]:
            if 'all' in ids or x['id'] in ids:
                x['reviewed'] = True; x['reviewed_by'] = by; x['reviewed_on'] = today; done.append(x['id'])
    if all(x.get('reviewed') for g in ('rules', 'submittal') for x in r[g]): r['status'] = 'reviewed'
    json.dump(r, open(path, 'w'), indent=2, ensure_ascii=False); print('approved:', ', '.join(done) or 'nothing matched')

def drop(path, ids):
    r = json.load(open(path))
    for group in ('rules', 'submittal'): r[group] = [x for x in r[group] if x['id'] not in ids]
    json.dump(r, open(path, 'w'), indent=2, ensure_ascii=False); print('removed:', ', '.join(ids))

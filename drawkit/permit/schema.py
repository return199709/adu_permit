"""Rule files: what a rule looks like, and loading them.

A rule file is JSON:
  jurisdiction  {"name", "state", "zone"}
  rules         [{"id", "kind", "params", "text", "applies_to", "source": {"title", "url", "section", "quote"},
                  "reviewed": bool, "reviewed_by", "reviewed_on"}]
  submittal     [{"id", "sheet", "text", "source", "reviewed"}]   what the plans must show
  open_questions [str]                                            things the text did not settle

Only the kinds below are checked by machine; anything else is kind "note" and is printed for the drafter."""
import json

KINDS = {
    'max_floor_area':     'params: base_sf, lot_fraction, cap_sf (optional), counts: list of living|garage|covered_patio|accessory',
    'max_lot_coverage':   'params: fraction, counts (optional)',
    'setback':            'params: side (front|rear|interior_side|street_side), feet, measured_from (optional text)',
    'max_height':         'params: feet',
    'max_unit_size':      'params: sf   (largest new unit or ADU)',
    'max_second_story_fraction': 'params: fraction of the maximum floor area',
    'exception':          'params: applies_to (floor_area|lot_coverage|setback), percent, name',
    'note':               'params: {}   (not machine-checked)',
}
SOURCE = {'type': 'object', 'properties': {'title': {'type': 'string'}, 'url': {'type': 'string'}, 'section': {'type': 'string'},
          'quote': {'type': 'string', 'description': 'Short verbatim quote (25 words or fewer) that states the rule'}}, 'required': ['url', 'quote']}
TOOL = {
    'name': 'record_rules',
    'description': 'Record the development standards and plan-submittal requirements found in the supplied code text.',
    'input_schema': {'type': 'object', 'required': ['rules', 'submittal', 'open_questions'], 'properties': {
        'rules': {'type': 'array', 'items': {'type': 'object', 'required': ['id', 'kind', 'params', 'text', 'source'], 'properties': {
            'id': {'type': 'string', 'description': 'short snake_case name'},
            'kind': {'type': 'string', 'enum': list(KINDS)},
            'params': {'type': 'object', 'description': '; '.join(f'{k}: {v}' for k, v in KINDS.items())},
            'text': {'type': 'string', 'description': 'the rule in one plain sentence'},
            'applies_to': {'type': 'array', 'items': {'type': 'string', 'enum': ['adu', 'addition', 'new_house']}},
            'source': SOURCE}}},
        'submittal': {'type': 'array', 'items': {'type': 'object', 'required': ['id', 'sheet', 'text', 'source'], 'properties': {
            'id': {'type': 'string'}, 'sheet': {'type': 'string', 'description': 'title sheet, site plan, floor plan, elevations, roof plan, schedule, form, other'},
            'text': {'type': 'string'}, 'source': SOURCE}}},
        'open_questions': {'type': 'array', 'items': {'type': 'string'}, 'description': 'what the text leaves unclear or refers elsewhere for'}}},
}

def load(path):
    r = json.load(open(path))
    for k in ('rules', 'submittal'):
        for item in r.get(k, []):
            item.setdefault('reviewed', False); item.setdefault('params', {})
            if k == 'rules' and item['kind'] not in KINDS: raise ValueError(f"{item['id']}: unknown kind {item['kind']}")
    r.setdefault('open_questions', [])
    return r

def usable(rules, allow_draft=False):
    """Rules that may be relied on: reviewed ones, or all of them when drafts are explicitly allowed."""
    return [x for x in rules['rules'] if x['reviewed'] or allow_draft]

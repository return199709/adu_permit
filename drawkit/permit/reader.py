"""Read a city's code and extract its rules with Claude.

    export ANTHROPIC_API_KEY=...
    python permit.py read drawkit/permit/jurisdictions/claremont_ca.json --out rules/claremont_ca.draft.json
    python permit.py read ... --dry-run      # fetch the sources and show what would be sent; no API call

The jurisdiction file lists the pages to read (URLs, or local .txt/.html/.pdf files).  The output is a DRAFT:
every rule carries a quote and a link, and nothing is used for checking until a person approves it (permit.py review).
The model is told to record only what the text states and to list what it leaves open."""
import html.parser, json, os, re, urllib.request, datetime
from . import schema

API = 'https://api.anthropic.com/v1/messages'
MODEL = os.environ.get('DRAWKIT_MODEL', 'claude-sonnet-5-5')
MAX_CHARS = 60000          # per source, to keep the request within the context window

class _Text(html.parser.HTMLParser):
    def __init__(s): super().__init__(); s.out = []; s.skip = 0
    def handle_starttag(s, tag, a):
        if tag in ('script', 'style', 'nav', 'footer'): s.skip += 1
        if tag in ('p', 'br', 'li', 'tr', 'h1', 'h2', 'h3', 'h4', 'div'): s.out.append('\n')
    def handle_endtag(s, tag):
        if tag in ('script', 'style', 'nav', 'footer') and s.skip: s.skip -= 1
    def handle_data(s, d):
        if not s.skip: s.out.append(d)

def to_text(raw, kind):
    if kind == 'pdf':
        import io
        from pypdf import PdfReader
        return '\n'.join(p.extract_text() or '' for p in PdfReader(io.BytesIO(raw)).pages)
    s = raw.decode('utf-8', 'replace')
    if kind == 'html': p = _Text(); p.feed(s); s = ''.join(p.out)
    return re.sub(r'\n\s*\n+', '\n\n', re.sub(r'[ \t]+', ' ', s)).strip()

def fetch(src):
    """src: URL or local path.  Returns plain text."""
    if re.match(r'https?://', src):
        req = urllib.request.Request(src, headers={'User-Agent': 'drawkit-permit-reader'})
        with urllib.request.urlopen(req, timeout=60) as r: raw = r.read(); ctype = r.headers.get('content-type', '')
        kind = 'pdf' if 'pdf' in ctype or src.lower().endswith('.pdf') else 'html'
    else:
        raw = open(src, 'rb').read(); kind = 'pdf' if src.lower().endswith('.pdf') else 'html' if src.lower().endswith(('.html', '.htm')) else 'txt'
    return to_text(raw, kind)

SYSTEM = """You read municipal zoning and building-permit text for a residential drafter.
Record ONLY what the supplied text states. Do not use outside knowledge and do not guess a number.
For every rule give a short verbatim quote and the URL it came from. If a value depends on a zone or a table you
were not given, record it as an open question instead of a rule. Prefer the machine-checkable kinds; use "note"
for anything else the drafter must know. Record what the plans must show as submittal items."""

def build_request(j, texts):
    parts = [f"Jurisdiction: {j['name']}, {j['state']}. Zone of interest: {j.get('zone', 'not specified')}. "
             f"Project types of interest: {', '.join(j.get('project_types', ['adu', 'addition']))}.\n"]
    for src, t in texts: parts.append(f'<source url="{src}">\n{t[:MAX_CHARS]}\n</source>')
    return {'model': MODEL, 'max_tokens': 8000, 'system': SYSTEM, 'tools': [schema.TOOL],
            'tool_choice': {'type': 'tool', 'name': 'record_rules'}, 'messages': [{'role': 'user', 'content': '\n\n'.join(parts)}]}

def call(body, key):
    req = urllib.request.Request(API, data=json.dumps(body).encode(), method='POST',
                                 headers={'x-api-key': key, 'anthropic-version': '2023-06-01', 'content-type': 'application/json'})
    with urllib.request.urlopen(req, timeout=600) as r: resp = json.load(r)
    for block in resp.get('content', []):
        if block.get('type') == 'tool_use' and block.get('name') == 'record_rules': return block['input']
    raise RuntimeError('the model did not return rules: ' + json.dumps(resp)[:400])

def to_rule_file(j, extracted, sources):
    """Turn the model's output into a draft rule file; drop anything without a quote found in the sources."""
    hay = re.sub(r'\s+', ' ', ' '.join(t for _, t in sources)).lower()
    def keep(item):
        q = re.sub(r'\s+', ' ', item.get('source', {}).get('quote', '')).lower().strip(' ."“”')
        item['quote_found'] = bool(q) and q in hay; item['reviewed'] = False
        return item
    out = {'jurisdiction': {k: j.get(k, '') for k in ('name', 'state', 'zone')}, 'status': 'draft',
           'extracted': {'by': MODEL, 'on': datetime.date.today().isoformat(), 'sources': [s for s, _ in sources]},
           'rules': [keep(r) for r in extracted.get('rules', []) if r.get('kind') in schema.KINDS],
           'submittal': [keep(r) for r in extracted.get('submittal', [])], 'open_questions': extracted.get('open_questions', [])}
    return out

def read(jurisdiction_file, out=None, dry_run=False, client=call):
    j = json.load(open(jurisdiction_file)); texts = []
    for src in j['sources']:
        try: t = fetch(src); texts.append((src, t)); print(f'read {len(t):>7,} chars  {src}')
        except Exception as e: print(f'FAILED {src}: {e}')
    if not texts: raise SystemExit('no source could be read')
    body = build_request(j, texts)
    if dry_run:
        print(f"dry run: would send {sum(len(t[:MAX_CHARS]) for _, t in texts):,} chars to {MODEL}; nothing sent"); return None
    key = os.environ.get('ANTHROPIC_API_KEY')
    if not key: raise SystemExit('set ANTHROPIC_API_KEY (or use --dry-run)')
    rf = to_rule_file(j, client(body, key), texts)
    bad = [r['id'] for r in rf['rules'] + rf['submittal'] if not r['quote_found']]
    if out: json.dump(rf, open(out, 'w'), indent=2, ensure_ascii=False)
    print(f"{len(rf['rules'])} rules, {len(rf['submittal'])} submittal items, {len(rf['open_questions'])} open questions -> {out}")
    if bad: print('quote NOT found word-for-word in the sources (check these first):', ', '.join(bad))
    print('This is a draft. Approve each rule against its source with:  python permit.py review', out)
    return rf

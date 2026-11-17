"""Sheets drawn from answers.json and rules.json in the current folder (written by permit.py draw)."""
import json
from .. import schema, check

def load():
    a = json.load(open('answers.json')); r = schema.load('rules.json'); cfg = json.load(open('permit.json'))
    return a, r, check.run(a, r, cfg.get('allow_draft', False)), cfg

def strip(a, title, sheet_no, notes):
    from drawkit import sheet
    x = sheet.frame(); p = a['project']
    sheet.title_strip(x, p['name'].upper(), [s.upper() for s in p.get('address', [])], title, [],
                      [('NOTES', notes + ['', 'Drawn from measurements supplied by', 'the owner. Not a survey and not a', 'stamped drawing. Verify on site.'])],
                      scale='AS NOTED', date=p.get('date', ''), sheet=sheet_no)

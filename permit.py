#!/usr/bin/env python3
"""From a city's code to a first permit drawing set.

  python permit.py read    JURISDICTION.json --out RULES.json [--dry-run]   read the city's code with Claude -> draft rules
  python permit.py review  RULES.json [--approve all|ID ...] [--by NAME] [--drop ID ...]   a person checks each rule
  python permit.py intake  RULES.json --type adu --out FOLDER              what to ask the owner for
  python permit.py check   ANSWERS.json RULES.json [--allow-draft]         test the answers against the rules
  python permit.py draw    ANSWERS.json RULES.json --out FOLDER [--allow-draft]   then:  python run.py FOLDER

Rules extracted by the model are drafts. check and draw ignore a rule until a person has approved it,
unless --allow-draft is given (the sheets then mark those rows)."""
import argparse, sys
from drawkit.permit import reader, review, intake, check, generate

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter); sub = ap.add_subparsers(dest='cmd', required=True)
    p = sub.add_parser('read'); p.add_argument('jurisdiction'); p.add_argument('--out', required=True); p.add_argument('--dry-run', action='store_true')
    p = sub.add_parser('review'); p.add_argument('rules'); p.add_argument('--approve', nargs='*'); p.add_argument('--by', default=''); p.add_argument('--drop', nargs='*')
    p = sub.add_parser('intake'); p.add_argument('rules'); p.add_argument('--type', default='adu'); p.add_argument('--out', required=True)
    p = sub.add_parser('check'); p.add_argument('answers'); p.add_argument('rules'); p.add_argument('--allow-draft', action='store_true')
    p = sub.add_parser('draw'); p.add_argument('answers'); p.add_argument('rules'); p.add_argument('--out', required=True); p.add_argument('--allow-draft', action='store_true')
    a = ap.parse_args()
    if a.cmd == 'read': reader.read(a.jurisdiction, a.out, a.dry_run)
    elif a.cmd == 'review':
        if a.drop: review.drop(a.rules, a.drop)
        if a.approve:
            if not a.by: sys.exit('--by NAME is required: the file records who approved each rule')
            review.approve(a.rules, a.approve, a.by)
        review.show(a.rules)
    elif a.cmd == 'intake': intake.write(a.rules, a.type, a.out)
    elif a.cmd == 'check': sys.exit(0 if check.report(check.run(a.answers, a.rules, a.allow_draft)) else 1)
    elif a.cmd == 'draw': generate.draw(a.answers, a.rules, a.out, a.allow_draft)

if __name__ == '__main__': main()

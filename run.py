#!/usr/bin/env python3
"""Build every sheet of a project, merge them into one set, and check the result.

    python run.py                              # the bundled example, into examples/sample_house/output
    python run.py path/to/project              # your own project folder
    python run.py path/to/project --only A-1   # one sheet
    python run.py path/to/project --out build  # another output folder (relative to the project)

A project folder holds project.py, which lists the sheets:

    SHEETS = [(sheet id, output stem, kind, source, PDF title, K), ...]

kind 'generated': source is a Python module in the project folder; importing it draws the sheet with drawkit.
kind 'dxf':       source is a DXF file in the project folder, rendered with drawkit's layer styles;
                  K = model inches per sheet inch (48 for 1/4" = 1'-0", 64 for 3/16", 8 for 1 1/2").
Optional in project.py: TITLE_PREFIX, AUTHOR, SET_NAME, FORM = (blank.pdf, values.json, output name).
An optional layers.py in the project folder can define extra layers with drawkit.core.add_layer.
"""
import argparse, importlib, os, shutil, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('project', nargs='?', default='examples/sample_house'); ap.add_argument('--out', default='output'); ap.add_argument('--only')
    a = ap.parse_args()
    proj = Path(a.project).resolve(); out = (proj / a.out).resolve(); out.mkdir(parents=True, exist_ok=True)
    sys.path[:0] = [str(ROOT), str(proj)]
    cfg = importlib.import_module('project')
    prefix = getattr(cfg, 'TITLE_PREFIX', ''); author = getattr(cfg, 'AUTHOR', '')
    sheets = [s for s in cfg.SHEETS if not a.only or s[0] == a.only]
    if not sheets: raise SystemExit(f'unknown sheet {a.only}; choose from {[s[0] for s in cfg.SHEETS]}')
    env = dict(os.environ, PYTHONPATH=str(ROOT) + os.pathsep + os.environ.get('PYTHONPATH', ''))
    from drawkit import core, dxf2pdf
    if (proj / 'layers.py').exists(): importlib.import_module('layers')
    for sid, stem, kind, src, title, k in sheets:
        if kind == 'generated':
            r = subprocess.run([sys.executable, '-W', 'ignore', '-m', 'drawkit.build', src, str(out / stem), prefix + title, author], cwd=proj, env=env, capture_output=True, text=True)
            if r.returncode: raise SystemExit(f'{sid}: build failed\n{r.stderr}')
            info = r.stdout.strip().splitlines()[-1]
        else:
            shutil.copy(proj / src, out / (stem + '.dxf'))
            dxf2pdf.convert(str(proj / src), str(out / (stem + '.pdf')), float(k), prefix + title, author); info = 'rendered from ' + src
        print(f'{sid:5} {stem}.pdf  ({info})')
    full = not a.only
    from pypdf import PdfReader, PdfWriter
    if full:
        name = getattr(cfg, 'SET_NAME', 'Drawing_Set.pdf'); w = PdfWriter()
        for _, stem, *_ in cfg.SHEETS: w.append(str(out / (stem + '.pdf')))
        w.write(str(out / name)); print(f'set   {name}  ({len(cfg.SHEETS)} sheets)')
        if getattr(cfg, 'FORM', None):
            from drawkit import forms
            blank, values, fname = cfg.FORM; forms.fill(str(proj / blank), str(proj / values), str(out / fname)); print(f'form  {fname}')
    # ---- checks
    import ezdxf
    bad = []
    for sid, stem, *_ in sheets:
        pdf = PdfReader(str(out / (stem + '.pdf'))); b = pdf.pages[0].mediabox
        if len(pdf.pages) != 1 or round(float(b.width)) != round(core.SHEET_W * 72) or round(float(b.height)) != round(core.SHEET_H * 72): bad.append(f'{sid}: PDF is not one {core.SHEET_W:g} x {core.SHEET_H:g} in. page')
        errs = len(ezdxf.readfile(str(out / (stem + '.dxf'))).audit().errors)
        if errs: bad.append(f'{sid}: DXF audit found {errs} errors')
    if full and len(PdfReader(str(out / name)).pages) != len(cfg.SHEETS): bad.append('combined set has the wrong page count')
    if bad: raise SystemExit('CHECK FAILED\n  ' + '\n  '.join(bad))
    print(f'checks passed: every sheet is one {core.SHEET_W:g} x {core.SHEET_H:g} in. page and every DXF audits clean')

if __name__ == '__main__': main()

# adu_permit

`drawkit` is a small Python engine for drawing residential permit sheets — floor plans, site and roof plans,
elevations, details — as PDF and DXF from numbers in code. One command builds every sheet of a project, merges
them into a set, and checks the result.

It contains no real project. The bundled example is a made-up house.

![Sample floor plan](docs/sample-1.png)
![Sample site and roof plan](docs/sample-2.png)

## Run

```bash
pip install -r requirements.txt
python run.py                              # builds examples/sample_house into its output/ folder
python run.py path/to/project              # your own project
python run.py path/to/project --only A-1   # one sheet
```

Python 3.10 or newer. No system packages are needed; the fonts are bundled. Every push builds the sample on
GitHub Actions and attaches the PDFs and DXFs as the `sample-drawing-set` artifact.

## What the engine does

| Module | Purpose |
|---|---|
| `drawkit/core.py` | Primitives (`line`, `fill`, `text`), layers with line weights, `View` (feet to sheet inches at a scale), dimensions in feet and inches, room labels, tables, and `Floor`: a wall model that takes an outline, interior walls, doors and windows and draws the plan |
| `drawkit/roof.py` | Hip-roof plan from the rectangles of a building's wings: hips, ridges and valleys are computed |
| `drawkit/sheet.py` | Border, title strip, north arrow, legend |
| `drawkit/render.py` | Writes a sheet to PDF and DXF (one DXF layer per drawkit layer, real-world inches) |
| `drawkit/dxf2pdf.py` | Renders a sheet DXF to PDF with the same line weights, so a sheet can be maintained in CAD |
| `drawkit/forms.py` | Fills a fillable PDF form from a JSON file |
| `drawkit/permit/` | Rule files, the code reader, intake, compliance check and generated sheets (see below) |
| `run.py` | The pipeline: build each sheet, merge the set, fill the form, check page size and DXF validity |

## A project

A project is a folder with a `project.py` that lists its sheets:

```python
SHEETS = [
    # id,   output stem,       kind,        source,                PDF title,     K
    ('A-1', 'A-1_floor_plan',  'generated', 'floor_plan',          'Floor Plan',  None),
    ('A-3', 'A-3_notes',       'dxf',       'sheets/A-3_notes.dxf', 'Notes',      48),
]
```

- **`generated`**: `source` is a Python module in the project folder. Importing it draws the sheet.
  Keep the building as data (outline polygons, wing rectangles) so other sheets can import it;
  in the example, `site_plan.py` takes the outline from `floor_plan.py`.
- **`dxf`**: `source` is a DXF you edit by hand. `K` is model inches per sheet inch: 48 for 1/4" = 1'-0",
  64 for 3/16", 8 for 1 1/2". Layer names are `<prefix>-<drawkit layer>`.

Optional in `project.py`: `TITLE_PREFIX`, `AUTHOR`, `SET_NAME`, and
`FORM = (blank.pdf, values.json, output name)`. A `layers.py` in the project folder can add layers with
`drawkit.core.add_layer`.

A minimal generated sheet:

```python
from drawkit.core import *
from drawkit import sheet

v = View(8, 6)                                   # sheet position of the model origin, in inches
f = Floor(v, [(0, 0), (30, 0), (30, 20), (0, 20)])   # outside outline, in feet
f.wall((12, 0), (12, 20))
f.door((12, 8), (12, 11), toward=(9, 9))
f.window((4, 0), (9, 0))
f.render()
dim(v, (0, 0), (30, 0), -3, ftin(30))
room(v, 6, 10, 'BEDROOM')
sheet.title_strip(sheet.frame(), 'PROJECT', ['ADDRESS'], 'FLOOR PLAN', scale='1/4" = 1\'-0"', sheet='A-1')
```

## Conventions

- Model units are feet, x to the right and y down the sheet. Sheet units are inches from the top-left corner.
- The default sheet is 42 × 30 in. and the default scale is 1/4" = 1'-0" (`core.set_scale` changes it).
- Layers carry meaning and line weight: `WALL-EXT`, `WALL-INT`, `WALL-NEW` on plans; `ELEV`, `ELEV-LT`, `ELEV-XL`
  on elevations; `PL`, `SETBK`, `ESMT`, `ROOF` on site plans; `DIM`, `NOTE`, `FLAG` for annotation.

## From a city's code to a first drawing set

`permit.py` sits on top of the drawing engine. It turns a city's rules into the list of things to ask an owner
for, checks the answers, and draws a first set.

```bash
export ANTHROPIC_API_KEY=...                                   # only the read step needs it
python permit.py read   drawkit/permit/jurisdictions/austin_tx.json --out rules/austin_tx.json
python permit.py review rules/austin_tx.json                   # see every rule with its quote and link
python permit.py review rules/austin_tx.json --approve max_lot_coverage --by "Your Name"
python permit.py intake rules/austin_tx.json --type adu --out intake/     # measurements, photos, documents to collect
python permit.py check  answers.json rules/austin_tx.json
python permit.py draw   answers.json rules/austin_tx.json --out build/ && python run.py build/
```

| Step | What happens |
|---|---|
| `read` | Fetches the pages listed for the city and has Claude extract development standards and plan requirements into a rule file. Every rule carries a quote and a link; rules whose quote is not found word for word in the page are flagged. `--dry-run` fetches without calling the model. |
| `review` | A person approves or drops each rule. The file records who approved it and when. |
| `intake` | Writes `intake.md` (what to measure, photograph and bring) and an `answers.template.json` to fill in. |
| `check` | Floor area, lot coverage, setbacks, unit size and height against the approved rules, including any exception the code allows. |
| `draw` | Writes a project with a cover sheet (scope, code check, areas, the city's plan checklist), a site and roof plan, and a floor plan of the new work. |

`check` and `draw` ignore a rule nobody has approved, unless you pass `--allow-draft`; the sheets then mark those rows.
Try it without an API key on made-up data:

```bash
python permit.py draw examples/sample_permit/answers.json examples/sample_permit/rules.json --out build/ && python run.py build/
```

`drawkit/permit/rules/claremont_ca.json` is a first draft rule file for Claremont, California. None of it has been
reviewed yet. `drawkit/permit/jurisdictions/` lists the pages to read for Claremont and for Austin, Texas.

What this first version does not do: it does not draw elevations or interior layouts, it models buildings as
rectangles on a rectangular lot, it does not read photos (they are for the drafter), and the `read` step has
only been tested with a stand-in for the model, not against the live API.

## Limits

The output is not a survey or a stamped drawing. A code check is only as good as the rule file behind it, and a
rule file is only as good as the person who reviewed it. Building-code and structural requirements are not checked.

Fonts: Liberation Sans, SIL Open Font License 1.1 (see `fonts/`).

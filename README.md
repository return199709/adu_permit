# adu_permit

Tools for turning a scanned, hand-drawn permit plan into a computer drawing.

    pip install pymupdf opencv-python-headless numpy scipy scikit-image ezdxf

1. `clean_blueprint.py` removes the scanner speckle.

       python clean_blueprint.py plan.pdf cleaned_blueprint.pdf

2. `vectorize_plan.py` finds every line of lettering, takes it out, and traces what is
   left into straight lines (joined at corners), arcs and short lines. One sheet at a time.

       python vectorize_plan.py cleaned_blueprint.pdf 1 page1

   Writes `page1.dxf` (layers: walls, thin lines, dashed lines, arcs, text boxes),
   `page1.svg` (the same over the scan), `page1_overlay.png` and `page1_text.json`
   (where each line of lettering is).

3. `apply_text.py` types the lettering into the drawing. The lettering is found by
   step 2 but not read, so a transcription file says what each line reads
   (see the docstring for the format).

       python apply_text.py cleaned_blueprint.pdf 1 page1 page1_transcription.json

   Writes the DXF and SVG again with real text on `TEXT_DIM`, `TEXT_NOTE` and
   `TEXT_CHECK`, puts things that were not lettering (ticks, symbols) back into the
   drawing, and writes `page1_text_read.csv` plus `page1_dimension_check_*.png`: each
   dimension string next to a crop of the plan, to be checked by a person.

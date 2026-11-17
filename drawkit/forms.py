"""Fill a one-page fillable PDF form.

    python -m drawkit.forms blank.pdf values.json out.pdf

values.json: {"text": {field name: value}, "buttons": {checkbox or radio-group name: state such as "/Yes"}}.
The output stays fillable."""
import json, sys

def fill(blank, values, out):
    from pypdf import PdfWriter
    from pypdf.generic import NameObject
    v = json.load(open(values)); w = PdfWriter(clone_from=blank); pg = w.pages[0]
    w.update_page_form_field_values(pg, v.get('text', {}), auto_regenerate=False)
    w.set_need_appearances_writer(True)
    for a in pg['/Annots']:
        a = a.get_object(); par = a.get('/Parent')
        name = a.get('/T') or (par.get_object().get('/T') if par else None)
        state = v.get('buttons', {}).get(name)
        if state and state in a['/AP']['/N']:
            a[NameObject('/AS')] = NameObject(state)
            (par.get_object() if par and '/T' not in a else a)[NameObject('/V')] = NameObject(state)
    w.write(out)

def fields(blank):
    """List the form's field names, types and positions (use this to write values.json)."""
    from pypdf import PdfReader
    for a in PdfReader(blank).pages[0].get('/Annots', []):
        a = a.get_object(); par = a.get('/Parent')
        name = a.get('/T') or (par.get_object().get('/T') if par else None)
        states = [k for k in a['/AP']['/N'].keys()] if '/AP' in a and a.get('/FT', par and par.get_object().get('/FT')) == '/Btn' else ''
        print(name, a.get('/FT') or (par.get_object().get('/FT') if par else ''), [round(float(x)) for x in a['/Rect']], states)

if __name__ == '__main__':
    fields(sys.argv[1]) if len(sys.argv) == 2 else fill(*sys.argv[1:4])

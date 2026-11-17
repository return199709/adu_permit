"""A made-up house, to show how a project is laid out.  Build it with:  python run.py examples/sample_house"""
TITLE_PREFIX = 'Sample Residence - '
AUTHOR = 'drawkit example'
SET_NAME = 'Sample_Residence_Set.pdf'
SHEETS = [
    # id,   output stem,                kind,        source,                           PDF title,            K
    ('A-1', 'A-1_floor_plan',           'generated', 'floor_plan',                     'Floor Plan',          None),
    ('A-2', 'A-2_site_and_roof_plan',   'generated', 'site_plan',                      'Site and Roof Plan',  None),
    ('A-3', 'A-3_general_notes',        'dxf',       'sheets/A-3_general_notes.dxf',   'General Notes',       48),
]

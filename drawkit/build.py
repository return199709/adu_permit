"""Build one generated sheet:  python -m drawkit.build <module> <out stem> <pdf title> [author]

The module is imported from the current directory; importing it draws the sheet."""
import importlib, os, sys
from . import render

def main():
    module, out, title = sys.argv[1:4]; author = sys.argv[4] if len(sys.argv) > 4 else ''
    sys.path.insert(0, os.getcwd())
    importlib.import_module(module)
    print(render.write(out, title, author))

if __name__ == '__main__': main()

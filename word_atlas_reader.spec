# PyInstaller spec for the Word Atlas Reader: one folder (or one file)
# that carries Python and Qt inside, so a reader installs nothing.
#
#     pip install pyinstaller
#     pyinstaller word_atlas_reader.spec
#
# The result is dist/WordAtlasReader (a folder with the program and its
# libraries; zip it to hand it on).  For a single file instead, see the
# note at the end.  Build on the platform you are building for: the
# Windows build on Windows, the Ubuntu build on Ubuntu.

block_cipher = None

a = Analysis(
    ["word_atlas_reader.py"],
    pathex=["."],
    binaries=[],
    datas=[],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=["tkinter", "PyQt6.QtWebEngineCore", "PyQt6.QtWebEngineWidgets", "PyQt6.QtMultimedia",
              "PyQt6.Qt3DCore", "PyQt6.QtQml", "PyQt6.QtQuick"],
    cipher=block_cipher,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WordAtlasReader",
    console=False,          # no terminal window behind the program
    icon=None,
)
coll = COLLECT(exe, a.binaries, a.zipfiles, a.datas, name="WordAtlasReader")

# One file instead of one folder: replace the EXE and COLLECT above with
#   exe = EXE(pyz, a.scripts, a.binaries, a.zipfiles, a.datas, name="WordAtlasReader", console=False)
# and drop COLLECT.  A one-file build starts more slowly, since it
# unpacks itself to a temporary folder on each start.

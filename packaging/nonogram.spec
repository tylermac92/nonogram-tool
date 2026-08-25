# PyInstaller spec for the standalone `nonogram` binary.
#
# Builds one onefile executable from the unified dispatcher
# (nonogram_tool.nonogram_cli) rather than one binary per interface -
# see that module's docstring for why. Since nonogram_cli dispatches
# to nonogram_overlap/nonogram_repl/nonogram_tui/nonogram_web via a
# runtime importlib.import_module() call (so a plain `pip install`
# without extras still works), PyInstaller's static import analysis
# can't discover those four modules on its own - they're listed under
# hiddenimports instead. collect_all('textual')/('rich') pull in each
# package's non-.py data files (textual ships tree-sitter query files
# for its optional syntax-highlighting widget; unused here, but cheap
# to include rather than assume they're never needed).
#
# Build with (from the repo root, after `pip install -e ".[all]"
# pyinstaller`):
#     pyinstaller packaging/nonogram.spec --distpath dist --workpath build/pyinstaller

from PyInstaller.utils.hooks import collect_all

datas = [("../src/nonogram_tool/nonogram_web.html", "nonogram_tool")]
binaries = []
hiddenimports = [
    "nonogram_tool.nonogram_overlap",
    "nonogram_tool.nonogram_linesolve",
    "nonogram_tool.nonogram_puzzle",
    "nonogram_tool.nonogram_library",
    "nonogram_tool.nonogram_webpbn",
    "nonogram_tool.nonogram_repl",
    "nonogram_tool.nonogram_tui",
    "nonogram_tool.nonogram_web",
]

for pkg in ("textual", "rich", "prompt_toolkit"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(pkg)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

a = Analysis(
    ["../src/nonogram_tool/nonogram_cli.py"],
    pathex=["../src"],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="nonogram",
    console=True,
    onefile=True,
)

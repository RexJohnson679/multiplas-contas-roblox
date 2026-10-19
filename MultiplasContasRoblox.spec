# -*- mode: python ; coding: utf-8 -*-
"""Build único e sem console: equivalente a --onefile --noconsole."""

from PyInstaller.utils.hooks import collect_data_files, copy_metadata

resources = collect_data_files("customtkinter")
resources += [("LICENSE", "licenses/multiplas-contas-roblox")]
# Inclui as licenças das dependências e a exceção do bootloader do PyInstaller.
for package in ("customtkinter", "psutil", "darkdetect", "packaging", "pyinstaller"):
    resources += copy_metadata(package)
a = Analysis(
    ["desktop_app.py"],
    pathex=[], binaries=[],
    datas=resources,
    hiddenimports=[], hookspath=[], hooksconfig={}, runtime_hooks=[], excludes=[],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="MultiplasContasRoblox", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
)

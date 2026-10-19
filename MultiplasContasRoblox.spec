# -*- mode: python ; coding: utf-8 -*-
"""Build Windows. MULTIROBLOX_ONEFILE=1 seleciona o pacote de arquivo único."""

import os
from PyInstaller.utils.hooks import collect_data_files, copy_metadata

onefile = os.environ.get("MULTIROBLOX_ONEFILE") == "1"
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
options = dict(
    name="MultiplasContasRoblox", debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False, disable_windowed_traceback=False,
)
if onefile:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], **options)
else:
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **options)
    coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name=options["name"])

# -*- mode: python ; coding: utf-8 -*-
#
# Build:  pyinstaller --clean --noconfirm HamsterDXSimulator.spec
#
# Escolhas para reduzir falso positivo de antivírus:
#   * modo "onedir" (pasta com o .exe + DLLs) em vez de "onefile": o onefile se
#     auto-extrai para %TEMP% e executa de lá, que é exatamente o comportamento
#     que as heurísticas de malware procuram.
#   * upx=False: executáveis comprimidos com UPX são muito sinalizados.
#   * console=False + recurso de versão (version_info.txt) + ícone: um .exe com
#     metadados completos parece menos "anônimo" para os scanners.

import os

block_cipher = None
ROOT = os.path.abspath(SPECPATH)

a = Analysis(
    [os.path.join(ROOT, "main.py")],
    pathex=[ROOT],
    binaries=[],
    datas=[
        (os.path.join(ROOT, "fixtures"), "fixtures"),
        (os.path.join(ROOT, "assets"), "assets"),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # Módulos da stdlib que o simulador não usa (deixa a pasta menor)
    excludes=[
        "unittest", "pydoc", "doctest", "pdb", "lib2to3", "test",
        "sqlite3", "xmlrpc", "multiprocessing", "asyncio", "distutils",
        "setuptools", "pip", "numpy", "PIL",
    ],
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,           # => onedir
    name="HamsterDXSimulator",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,                   # sem janela preta de terminal
    disable_windowed_traceback=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
    version=os.path.join(ROOT, "build_tools", "version_info.txt"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="HamsterDXSimulator",
)

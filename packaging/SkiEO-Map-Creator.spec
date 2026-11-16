# -*- mode: python ; coding: utf-8 -*-
# build: packaging\build.bat   (one-file exe in dist\)
from pathlib import Path
from PyInstaller.utils.hooks import collect_all

ROOT = Path(SPECPATH).parent

# rasterio and the STAC client load modules and data files PyInstaller does not see by itself (e.g. rasterio.serde,
# the GDAL / PROJ data): take everything of them
EXTRA_DATAS, EXTRA_BINARIES, EXTRA_HIDDEN = [], [], []
for _pkg in ('rasterio', 'pystac', 'pystac_client'):
    _d, _b, _h = collect_all(_pkg)
    EXTRA_DATAS += _d; EXTRA_BINARIES += _b; EXTRA_HIDDEN += _h

a = Analysis(
    [str(ROOT / 'run.py')],
    pathex=[str(ROOT)],
    binaries=[(str(ROOT / 'tools' / 'retoc.exe'), 'tools')] + EXTRA_BINARIES,
    datas=[(str(ROOT / 'web'), 'web'), (str(ROOT / 'data'), 'data'), (str(ROOT / 'tools' / 'retoc-LICENSE'), 'tools'),
           (str(ROOT / 'packaging' / 'THIRD-PARTY.txt'), '.')] + EXTRA_DATAS,
    hiddenimports=['webview.platforms.edgechromium', 'webview.platforms.winforms', 'clr_loader', 'pythonnet',
                   *EXTRA_HIDDEN,
                   'rasterio.sample', 'rasterio.vrt', 'rasterio._features', 'rasterio.control', 'rasterio.warp',
                   'truststore', 'pystac_client'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(ROOT / 'packaging' / 'rthook_gdal.py')],
    excludes=['tkinter', 'unittest', 'pydoc', 'test', 'scipy', 'pyproj', 'matplotlib', 'IPython', 'PyQt5', 'PyQt6',
              'PySide2', 'PySide6', 'gi', 'cefpython3'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='SkiEO-Map-Creator',
    icon=str(ROOT / 'packaging' / 'icon.ico'),
    version=str(ROOT / 'packaging' / 'version_info.txt'),
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

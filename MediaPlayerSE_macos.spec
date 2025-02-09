# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[],
    hiddenimports=['videowidget'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['_bootlocale'],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='MediaPlayerSE',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=['app.icns'],
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='MediaPlayerSE',
)
app = BUNDLE(
    coll,
    name='MediaPlayerSE.app',
    icon='app.icns',
    bundle_identifier=None,
    info_plist={
        'CFBundleShortVersionString': '0.1.0',
        'Associations': '3gp avi m2ts m2v mov mp4 mpg mpeg mts mxf ts vob wav mp3 aif aiff',
        'CFBundleDocumentTypes': [
            {
                'CFBundleTypeExtensions': ['3gp', 'avi', 'm2ts', 'm2v', 'mov', 'mp4', 'mpg', 'mpeg', 'mts', 'mxf', 'ts', 'vob', 'wav', 'mp3', 'aif', 'aiff'],
                'CFBundleTypeRole': 'Viewer'
            }
        ],
        'NSAppTransportSecurity': {
            'NSAllowsArbitraryLoads': True
        },
    },
)


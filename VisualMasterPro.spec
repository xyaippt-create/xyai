# -*- mode: python ; coding: utf-8 -*-


a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[('engine', 'engine'), ('gui', 'gui'), ('batch', 'batch'), ('runtime', 'runtime'), ('help', 'help'), ('pipelines', 'pipelines'), ('modes', 'modes'), ('rules', 'rules'), ('ai_noise_rules', 'ai_noise_rules'), ('material_rules', 'material_rules'), ('visual_style_rules', 'visual_style_rules'), ('public/branding/hdde', 'public/branding/hdde')],
    hiddenimports=['gui.app', 'gui.help_system', 'gui.powershell_fallback', 'batch.batch_processor', 'runtime.crash_handler', 'runtime.user_settings'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name='VisualMasterPro',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    icon='public/branding/hdde/hdde.ico',
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='VisualMasterPro',
)

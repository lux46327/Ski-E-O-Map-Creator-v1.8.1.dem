"""Self-check of the mod library (skieo_creator/modlib.py) in a throwaway game folder: no game.
usage: python tests/test_modlib.py"""
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from skieo_creator import modlib, paths  # noqa: E402

game = Path(tempfile.mkdtemp(prefix='skieo_modlib_'))
work = Path(tempfile.mkdtemp(prefix='skieo_modlib_data_'))
real_resource = paths.resource
try:
    b = modlib._bin(game)
    b.mkdir(parents=True)
    mods_dir = b / 'ue4ss' / 'Mods'

    # ---- Lua mods: the app installs UE4SS (with its shared libraries, Blueprint loader not switched on) and the mod
    cheats = modlib.MODS['cheats']
    modlib._set_lua(game, cheats['folder'], True)
    assert (b / 'dwmapi.dll').is_file() and (b / 'ue4ss' / modlib.MARKER).is_file()
    assert (mods_dir / 'shared' / 'UEHelpers' / 'UEHelpers.lua').is_file(), 'Lua mods may require("UEHelpers")'
    assert modlib._lua_on(b, cheats['folder']) and not modlib._line_on(b, 'BPModLoaderMod')
    # another modder's mod in the same UE4SS: switching the app's last mod off keeps UE4SS for it
    other = mods_dir / 'SomeoneElsesMod'
    (other / 'Scripts').mkdir(parents=True)
    (other / 'Scripts' / 'main.lua').write_text('print("hi")\n', encoding='utf-8')
    modlib._set_line(b, 'SomeoneElsesMod', True)
    modlib._set_lua(game, cheats['folder'], False)
    assert (b / 'dwmapi.dll').is_file() and (other / 'Scripts' / 'main.lua').is_file()
    assert not (mods_dir / cheats['folder']).exists()
    assert modlib._enabled_lines(b) == ['SomeoneElsesMod : 1'], modlib._enabled_lines(b)
    shutil.rmtree(other)                                    # once it is gone, the app removes what it installed
    modlib._set_lua(game, cheats['folder'], True)
    modlib._set_lua(game, cheats['folder'], False)
    assert not (b / 'dwmapi.dll').exists() and not (b / 'ue4ss').exists()

    # ---- mods.txt: UE4SS's Keybinds line stays last, other lines are kept
    mods_dir.mkdir(parents=True)
    modlib._mods_txt(b).write_text('; comment\nTheirMod : 1\nKeybinds : 1\n', encoding='utf-8')
    modlib._set_line(b, 'OofsSpeed', True)
    assert modlib._enabled_lines(b) == ['; comment', 'TheirMod : 1', 'OofsSpeed : 1', 'Keybinds : 1'], modlib._enabled_lines(b)
    modlib._set_line(b, 'OofsSpeed', False)
    assert modlib._enabled_lines(b) == ['; comment', 'TheirMod : 1', 'Keybinds : 1']
    shutil.rmtree(b / 'ue4ss')

    # ---- other modders' pak mods, packaged like the app's: several paks, a Blueprint mod in LogicMods
    def pak_zip(name, paks):
        z = work / name
        with zipfile.ZipFile(z, 'w') as zf:
            for p in paks:
                for e in modlib.PAK_EXTS:
                    zf.writestr('Their Mod/' + p + e, p + e)
        return z
    zips = {'Their_Pack.zip': pak_zip('Their_Pack.zip', ['TheirPack_P', 'TheirPackExtra_P']),
            'Their_BP.zip': pak_zip('Their_BP.zip', ['TheirBlueprintMod'])}
    paths.resource = lambda *a: zips[a[2]] if a[:2] == ('data', 'lifts') and a[2] in zips else real_resource(*a)
    modlib.MODS['their_pack'] = dict(kind='pak', name='Their Pack', author='Someone', paks=['TheirPack_P', 'TheirPackExtra_P'],
                                     zip='Their_Pack.zip', tables=['/Game/Mods/Their/DT_TheirRows'],
                                     snowcaps=[('/Game/Mods/Their/BP_Hut', 'BP_Hut_C', '/Game/Mods/Their/DA_Cap_Hut')], about='')
    modlib.MODS['their_bp'] = dict(kind='pak', name='Their Blueprint Mod', author='Someone', paks=['TheirBlueprintMod'],
                                   dest='logic', zip='Their_BP.zip', about='')
    modlib._set_pak(game, modlib.MODS['their_pack'], True)
    mods = modlib._mods_dir(game)
    assert all((mods / ('%s%s' % (p, e))).is_file() for p in ('TheirPack_P', 'TheirPackExtra_P') for e in modlib.PAK_EXTS)
    assert modlib._pak_on(game, modlib.MODS['their_pack'])
    st = {m['id']: m for m in modlib.status(game)['mods']}
    assert st['their_pack']['author'] == 'Someone' and st['their_pack']['menu'] and st['their_pack']['on']
    parents, caps, ships = modlib._shared([modlib.MODS['r2six'], modlib.MODS['their_pack']])
    assert parents == ['/Game/Data/DT_BuildingStock_0', '/Game/Data/DT_LiftMod_R2Six01', '/Game/Mods/Their/DT_TheirRows']
    assert caps == [['/Game/Mods/Their/BP_Hut', 'BP_Hut_C', '/Game/Mods/Their/DA_Cap_Hut']] and ships == []
    assert modlib._shared([modlib.MODS['cheats']]) == ([], [], [])
    # a mod made to replace the whole building table: its renamed copy (in its zip) goes before the game's
    with zipfile.ZipFile(zips['Their_Pack.zip'], 'a') as zf:
        zf.writestr('tables/DT_BuildingMod_001.uasset', b'ua')
        zf.writestr('tables/DT_BuildingMod_001.uexp', b'ue')
    full = dict(modlib.MODS['their_pack'], full_tables=['DT_BuildingMod_001'], tables=[])
    parents, _, ships = modlib._shared([full, modlib.MODS['r2six']])
    assert parents == ['/Game/Data/DT_BuildingMod_001', '/Game/Data/DT_BuildingStock_0', '/Game/Data/DT_LiftMod_R2Six01']
    assert ships[0][:2] == ['DT_BuildingMod_001', 'Their_Pack.zip'] and len(ships[0][2]) == 2
    modlib._ensure_bp_loader(game)                          # what set_mod does for a Blueprint mod
    modlib._set_pak(game, modlib.MODS['their_bp'], True)
    logic = modlib._paks_dir(game) / 'LogicMods'
    assert (logic / 'TheirBlueprintMod.pak').is_file() and not (mods / 'TheirBlueprintMod.pak').exists()
    assert modlib._line_on(b, 'BPModLoaderMod') and modlib._line_on(b, 'BPML_GenericFunctions')
    assert (mods_dir / 'BPModLoaderMod' / 'Scripts' / 'main.lua').is_file()
    assert modlib._others(game) == [], modlib._others(game)     # UE4SS's own libraries and the app's mods only
    (logic / 'SomeoneElses.pak').write_bytes(b'')           # a Blueprint mod the app didn't install keeps UE4SS
    modlib._set_pak(game, modlib.MODS['their_bp'], False)
    modlib._maybe_remove_ue4ss(game)
    assert (b / 'dwmapi.dll').is_file() and modlib._others(game) == ['SomeoneElses.pak']
    (logic / 'SomeoneElses.pak').unlink()
    modlib._maybe_remove_ue4ss(game)
    assert not (b / 'dwmapi.dll').exists() and not (b / 'ue4ss').exists()

    st = {m['id']: m for m in modlib.status(game)['mods']}
    modlib.MODS['their_full'] = dict(modlib.MODS['their_pack'], tables=[], full_tables=['DT_BuildingMod_001'])
    assert {m['id']: m for m in modlib.status(game)['mods']}['their_full']['menu'], 'a whole-table mod is in the menu'

    # ---- the UE4SS of an older app version: libraries it lacks added, never replacing a file; its settings (all
    # hooks off) replaced if untouched; edited ones get those hooks back on, unless the player set hooks themselves
    modlib._ensure_ue4ss(game)
    ini = b / 'ue4ss' / 'UE4SS-settings.ini'
    shipped = (Path(__file__).resolve().parent.parent / 'data' / 'ue4ss' / 'ue4ss' / 'UE4SS-settings.ini').read_text(encoding='utf-8')
    assert 'HookBeginPlay = 1' in shipped and 'HookProcessInternal = 1' in shipped, 'stock hooks on (mods use them)'
    shutil.rmtree(mods_dir / 'shared')
    modlib._ensure_bp_loader(game)
    order = mods_dir / 'BPModLoaderMod' / 'load_order.txt'
    order.write_text('TheirBlueprintMod\n', encoding='utf-8')
    old_off = 'HookProcessInternal = 0\nHookBeginPlay = 0\nHookEngineTick = 1\nConsoleEnabled = 1\n'
    ini.write_text(old_off, encoding='utf-8')
    modlib._sync_ue4ss(game)
    assert (mods_dir / 'shared' / 'UEHelpers' / 'UEHelpers.lua').is_file()
    assert order.read_text(encoding='utf-8') == 'TheirBlueprintMod\n', 'a player\'s Blueprint load order is kept'
    assert ini.read_text(encoding='utf-8').split() == 'HookProcessInternal = 1 HookBeginPlay = 1 HookEngineTick = 1 ' \
        'ConsoleEnabled = 1'.split(), ini.read_text(encoding='utf-8')
    theirs = 'HookProcessInternal = 1\nHookBeginPlay = 0\n'
    ini.write_text(theirs, encoding='utf-8')
    modlib._sync_ue4ss(game)
    assert ini.read_text(encoding='utf-8') == theirs, 'hooks the player set are theirs'
    shutil.rmtree(b / 'ue4ss')
    (b / 'dwmapi.dll').unlink()

    # ---- a UE4SS the player installed with another loader dll: the app doesn't put its own over it
    (b / 'ue4ss').mkdir()
    (b / 'ue4ss' / 'UE4SS.dll').write_bytes(b'theirs')
    modlib._ensure_ue4ss(game)
    assert not (b / 'dwmapi.dll').exists() and (b / 'ue4ss' / 'UE4SS.dll').read_bytes() == b'theirs'
    assert not (b / 'ue4ss' / modlib.MARKER).exists()
    shutil.rmtree(b / 'ue4ss')

    # ---- updates of a Lua mod: the app's changed scripts replace the old ones, a script it dropped goes, and a data
    # file the mod changed in the game (its settings) is kept
    app = work / 'app_mods' / 'TheirLua'
    (app / 'Scripts').mkdir(parents=True)
    (app / 'Scripts' / 'main.lua').write_text('-- v1\n', encoding='utf-8')
    (app / 'Scripts' / 'old.lua').write_text('-- dropped in v2\n', encoding='utf-8')
    (app / 'config.json').write_text('{"speed": 1}', encoding='utf-8')
    (app / 'dev.txt').write_text('', encoding='utf-8')
    resource = paths.resource
    paths.resource = lambda *a: app if a == ('data', 'mods', 'TheirLua') else resource(*a)
    modlib._set_lua(game, 'TheirLua', True)
    dst = mods_dir / 'TheirLua'
    assert (dst / modlib.MANIFEST).is_file() and not (dst / 'dev.txt').exists() and not modlib._lua_outdated(b, 'TheirLua')
    (dst / 'config.json').write_text('{"speed": 5}', encoding='utf-8')         # the player's setting
    (dst / 'settings.txt').write_text('mine', encoding='utf-8')               # written by the mod
    (app / 'Scripts' / 'main.lua').write_text('-- v2\n', encoding='utf-8')
    (app / 'Scripts' / 'old.lua').unlink()
    (app / 'config.json').write_text('{"speed": 2}', encoding='utf-8')
    assert modlib._lua_outdated(b, 'TheirLua')
    modlib._set_lua(game, 'TheirLua', True)
    assert (dst / 'Scripts' / 'main.lua').read_text(encoding='utf-8') == '-- v2\n'
    assert not (dst / 'Scripts' / 'old.lua').exists() and (dst / 'settings.txt').read_text(encoding='utf-8') == 'mine'
    assert (dst / 'config.json').read_text(encoding='utf-8') == '{"speed": 5}', 'the player\'s setting is kept'
    assert not modlib._lua_outdated(b, 'TheirLua')
    paths.resource = resource
    modlib._set_lua(game, 'TheirLua', False)

    # ---- the app's UE4SS whose settings the player changed is theirs: left installed when the last mod goes
    modlib._set_lua(game, cheats['folder'], True)
    ini = b / 'ue4ss' / 'UE4SS-settings.ini'
    ini.write_text(ini.read_text(encoding='utf-8').replace('ConsoleEnabled = 0', 'ConsoleEnabled = 1'), encoding='utf-8')
    modlib._set_lua(game, cheats['folder'], False)
    assert (b / 'dwmapi.dll').is_file() and ini.is_file() and not (b / 'ue4ss' / modlib.MARKER).exists()
    shutil.rmtree(b / 'ue4ss')
    (b / 'dwmapi.dll').unlink()

    # ---- refresh: one step failing doesn't stop the others
    ran = []
    real_steps = modlib._refresh_lua, modlib._sync_ue4ss, modlib._refresh_paks

    def broken(g):
        raise OSError('locked')
    modlib._refresh_lua = broken
    modlib._sync_ue4ss = lambda g: ran.append('sync')
    modlib._refresh_paks = lambda g: ran.append('paks')
    try:
        modlib._refreshed.clear()
        modlib.refresh(game)
    finally:
        modlib._refresh_lua, modlib._sync_ue4ss, modlib._refresh_paks = real_steps
    assert ran == ['sync', 'paks'], ran

    # ---- work folders left in the game folder (a file still held when they were removed) go on a later start
    old = game / 'SkiResortSimulator' / '.skilift_left'
    (old / 'in').mkdir(parents=True)
    (old / 'in' / 'global.utoc').write_bytes(b'x')
    keep = game / 'SkiResortSimulator' / 'Content'
    paths.sweep(game / 'SkiResortSimulator', age=3600)
    assert old.is_dir(), 'a fresh one may still be in use'
    paths.sweep(game / 'SkiResortSimulator', age=0)
    assert not old.exists() and keep.is_dir()
finally:
    paths.resource = real_resource
    modlib.MODS.pop('their_pack', None)
    modlib.MODS.pop('their_bp', None)
    modlib.MODS.pop('their_full', None)
    shutil.rmtree(game, ignore_errors=True)
    shutil.rmtree(work, ignore_errors=True)
print('modlib: all checks passed')

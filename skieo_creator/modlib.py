"""Mod library: mods the player can switch on and off from the app, the app author's and other modders' alike (theirs
are packaged into the app the same way by its author, see docs/MODDING.md; 'author' credits them). Players can't add
mods to it. Two kinds:

- 'lua': an in-game UE4SS Lua mod. data/mods/<folder> is copied to Binaries/Win64/ue4ss/Mods/<folder> and enabled with a
  "<folder> : 1" line in ue4ss/Mods/mods.txt (before UE4SS's own Keybinds line, which it wants last). A file MANIFEST in
  the folder records what the app put there, so an update replaces the app's changed files and dropped scripts but
  keeps data files the mod or the player changed. UE4SS itself (MIT, https://github.com/UE4SS-RE/RE-UE4SS), with its
  shared Lua libraries and Blueprint mod loader (UE4SS_LIBS), is installed from data/ue4ss only when the game doesn't
  have it yet; a marker file records that the app put it there, and it is removed again when the last mod that needs it
  is switched off, unless other mods than the app's use it. A UE4SS the player installed is never touched, except for
  the app's own mod folders and their mods.txt lines, and UE4SS's Blueprint mod loader when a Blueprint mod needs it.
- 'pak': cooked content (lifts, buildings, ...). Its zip ships inside the app (data/lifts) and its .pak/.ucas/.utoc
  ('paks') go into Content/Paks/~mods, or for a Blueprint mod (dest='logic') into Content/Paks/LogicMods, where UE4SS's
  BPModLoaderMod loads it. Switching off deletes them. A pak mod can bring an in-game script ('lua', installed and
  removed with it).

Two game assets can only come from one pak: the build menu's table /Game/Data/DT_BuildingEconomy and the snow cap list
/Game/Data/SnowCaps/DA_SnowCapRegistry. So each pak mod declares its building tables ('tables': tables of the game's
BuildingEconomyRow in its paks, with its new rows) and the snow caps of its buildings ('snowcaps'), and refresh() makes
them into STOCK_PAK from the player's own game files: a composite DT_BuildingEconomy over the game's table (renamed to
STOCK_TABLE) and the installed mods' tables, and the game's registry with their entries (engine/shared_assets.py). A mod
made to replace the whole table (most are) gets its copy of it renamed by packaging/package_mod.py, shipped in its zip
('full_tables', <zip>/tables/<name>.uasset/.uexp) and put BEFORE the game's table, so only its own rows stay and the
game's current ones win. Paks the player put in ~mods by hand that bring their own table or snow caps are read the same
way (modscan) and kept in. The game mounts STOCK_PAK above the mods (a ..._<n>_P pak gets a higher order than a plain
..._P one), so it wins over their own copies of these assets; it is remade when the game or the mods change (the game
only picks up a game update's new buildings once the app has run after it), and removed when that fails, so the packs
fall back to their own copies. The app's own packs still carry the composite and registry of the game version they
were built for, for players without the app.

The game must be closed (it locks dwmapi.dll and the paks)."""
import hashlib
import json
import logging
import re
import shutil
import tempfile
import zipfile
from pathlib import Path

from . import install, modscan, paths
from .engine import shared_assets as sa

log = logging.getLogger(__name__)


def _caps(blueprints, folder='/Game/Blueprints/Buildings/'):
    """snow cap entries of buildings whose cap data asset is /Game/Data/SnowCaps/DA_SnowCap_<blueprint>"""
    return [(folder + bp, bp + '_C', '/Game/Data/SnowCaps/DA_SnowCap_' + bp) for bp in blueprints]


ALPINE = ('M01 M02 M03 M04 M05 M06 M07 M08 L01 L02 L03 L04 L05 L06 L07 T01 T02 T03 T04 E01 E02 G01 G02 H01 H02 H03 A01 '
          'A02 T05 T06 T07 E03 L08 L09 C01 C02 C03 F01 F02 S01 S02 S03 W01 W02 V01 V02 V03 V04 I01 I02').split()
MODS = {
    'cheats': dict(kind='lua', folder='OofsCheatMenu', name="Oof's Simple Cheat Menu", key='F6',
                   about='Cheat menu in game: add money or make it infinite, speed time up to 100x or skip ahead, '
                         'force the weather and change the climate (buried in snow? turn snowfall down), max out '
                         'your reputation to unlock everything, spawn guests, switch off accidents, breakdowns and '
                         'tired staff, and build anywhere.'),
    'anarchy': dict(kind='lua', folder='OofsAnarchy', name="Oof's Anarchy", key='Ctrl+A',
                    about='Build anywhere: Ctrl+A switches it on and off in game. While it is on, the buildings and '
                          'lifts you place or move ignore slopes, ground type, trees and rocks, and other buildings. '
                          'A badge under the top bar shows when it is on.'),
    'speed': dict(kind='lua', folder='OofsSpeed', name="Oof's Speed Control",
                  note='Installed: speed buttons under the top bar in game',
                  about="Speed buttons from 1x to 100x under the game's own (top right): click one to run the game "
                        'that fast, click it again to go back to 1x. Past 10x, guests and lifts may glitch.'),
    'r2six': dict(kind='pak', name='Doppelmayr D-Line R2 Six', paks=['ZZZ_DoppelmayrR2Six_P'], lift=True,
                  zip='DLine_R2_Six_LiftMod.zip', tables=['DT_LiftMod_R2Six01'],
                  about='New lift in the build menu: D-Line R2 glass station, six-seat bubble chairs, Doppelmayr '
                        'towers. Costs and unlocks like the High-Speed Six (Elite Resort).'),
    'r2gondola': dict(kind='pak', name='Doppelmayr D-Line R2 Gondola', paks=['ZZZ_DoppelmayrR2Gondola_P'], lift=True,
                      zip='DLine_R2_Gondola_LiftMod.zip', tables=['DT_LiftMod_R2Gond1'],
                      about='New lift in the build menu: D-Line R2 gondola station with Omega V cabins. '
                            'Costs and unlocks like the Gondola (World-Class).'),
    'buildings': dict(kind='pak', name="Oof's Alpine Buildings", paks=['ZZZ_AlpineBuildings_P'],
                      zip='Alpine_Buildings_Pack.zip', tables=['DT_LiftMod_Bldgs01'],
                      snowcaps=_caps('BP_OofGen_' + c for c in ALPINE), about=''),  # the user: no description (2026-11-14)
}
PAK_EXTS = ('.pak', '.ucas', '.utoc')
OWN_LIFT_MOD = 'ZZZ_LiftMod_P.pak'          # the mod author's all-in-one lift pack already contains both R2 lifts ('lift')
MARKER = 'installed-by-skieo-map-creator.txt'
MANIFEST = 'installed-by-skieo-map-creator.json'     # in a Lua mod's folder: {file: sha256} of what the app put there
LEGACY_LUA = {'SkiWeather': 'cheats'}       # Lua mods of older app versions -> the mod that replaced them
UE4SS_LIBS = ('shared', 'BPModLoaderMod', 'BPML_GenericFunctions')   # in data/ue4ss: Lua libraries, Blueprint mod loader
BP_LOADER = ('BPModLoaderMod', 'BPML_GenericFunctions')
NOT_SHIPPED = ('dev.txt', MANIFEST)          # a mod's dev switch (the cheat menu's REPL) never goes to players
# the UE4SS-settings.ini of older app versions (all hooks but EngineTick off, a startup crash workaround that turned out
# not to be UE4SS's, 2026-10-18): replaced by the current one; one the player edited gets those hooks back on only
OLD_SETTINGS = {'0605a497f0afb081ea4c4431fd72c3400aff43f07e116f43848fcf462e6467d7'}     # sha256, app 1.2.0-1.7.6
STOCK_PAK = 'ZZZ_LiftStock_9_P'             # the shared assets of all installed mods (see above)
STOCK_TABLE = 'DT_BuildingStock_0'          # same length as DT_BuildingEconomy: a rename in place
STOCK_STAMP = 'skieo_lift_stock.json'       # in ~mods: the game files and mods STOCK_PAK was made from
STOCK_FORMAT = 3
HAND_TABLE = 'DT_BuildingMod_9%02d'         # a hand-installed mod's whole table, renamed (packaged ones: _001 ...)


def _bin(game_folder):
    return Path(game_folder) / 'SkiResortSimulator' / 'Binaries' / 'Win64'


def _paks_dir(game_folder):
    return Path(game_folder) / 'SkiResortSimulator' / 'Content' / 'Paks'


def _mods_dir(game_folder):
    return _paks_dir(game_folder) / '~mods'


def _pak_dir(game_folder, m):
    return _paks_dir(game_folder) / ('LogicMods' if m.get('dest') == 'logic' else '~mods')


def _pak_files(m):
    return [p + e for p in m['paks'] for e in PAK_EXTS]


def _mods_txt(b):
    return b / 'ue4ss' / 'Mods' / 'mods.txt'


def _enabled_lines(b):
    f = _mods_txt(b)
    return f.read_text(encoding='utf-8', errors='replace').splitlines() if f.is_file() else []


def _line_name(line):
    return line.split(':')[0].strip()


def _set_line(b, folder, on):
    lines = [l for l in _enabled_lines(b) if _line_name(l) != folder]
    if on:
        at = next((i for i, l in enumerate(lines) if _line_name(l) == 'Keybinds'), len(lines))   # UE4SS wants it last
        lines.insert(at, '%s : 1' % folder)
    f = _mods_txt(b)
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text('\n'.join(lines) + '\n', encoding='utf-8')


def _line_on(b, folder):
    return any(_line_name(l) == folder and l.split(':')[-1].strip() == '1' for l in _enabled_lines(b))


def _has_ue4ss(b):
    """UE4SS is installed: the app's way (dwmapi.dll) or the player's own with another loader dll"""
    return (b / 'dwmapi.dll').is_file() or (b / 'ue4ss' / 'UE4SS.dll').is_file()


def _lua_on(b, folder):
    return _has_ue4ss(b) and (b / 'ue4ss' / 'Mods' / folder / 'Scripts' / 'main.lua').is_file() and _line_on(b, folder)


def _pak_on(game_folder, m):
    d = _pak_dir(game_folder, m)
    return all((d / f).is_file() for f in _pak_files(m))


def _is_on(game_folder, m):
    return _lua_on(_bin(game_folder), m['folder']) if m['kind'] == 'lua' else _pak_on(game_folder, m)


def _needs_ue4ss(m):
    return m['kind'] == 'lua' or bool(m.get('lua')) or m.get('dest') == 'logic'


def _lua_folders():
    """every in-game script the app installs: the Lua mods' and the pak mods' own ('lua')"""
    return [m['folder'] for m in MODS.values() if m['kind'] == 'lua'] + [m['lua'] for m in MODS.values() if m.get('lua')]


def status(game_folder):
    b = _bin(game_folder)
    own_lifts = (_mods_dir(game_folder) / OWN_LIFT_MOD).is_file()
    mods = []
    for k, m in MODS.items():
        mods.append(dict(id=k, name=m['name'], kind=m['kind'], about=m['about'], on=_is_on(game_folder, m),
                         key=m.get('key'), note=m.get('note'), author=m.get('author'),
                         menu=bool(m.get('tables') or m.get('full_tables')),
                         included=m.get('lift', False) and own_lifts))
    return dict(ue4ss=_has_ue4ss(b), ours=(b / 'ue4ss' / MARKER).is_file(), mods=mods)


def _ensure_ue4ss(game_folder):
    b = _bin(game_folder)
    src = paths.resource('data', 'ue4ss')
    if (b / 'ue4ss' / MARKER).is_file():                # the app's, with its loader gone (removed by hand)
        if not (b / 'dwmapi.dll').is_file():
            shutil.copy2(src / 'dwmapi.dll', b / 'dwmapi.dll')
    elif not _has_ue4ss(b):
        shutil.copytree(src / 'ue4ss', b / 'ue4ss', dirs_exist_ok=True)
        (b / 'ue4ss' / MARKER).write_text('UE4SS was installed by Ski-E-O Map Creator and is removed when the last '
                                          'mod that needs it is switched off.\n', encoding='utf-8')
        shutil.copy2(src / 'dwmapi.dll', b / 'dwmapi.dll')


def _others(game_folder):
    """mods that use the app's UE4SS but aren't the app's (another modder's Lua mods, Blueprint mods it didn't
    install): the UE4SS the app installed then stays"""
    b = _bin(game_folder)
    mods, ours = b / 'ue4ss' / 'Mods', set(_lua_folders()) | set(LEGACY_LUA) | set(UE4SS_LIBS)
    out = [p.name for p in mods.iterdir() if p.is_dir() and p.name not in ours] if mods.is_dir() else []
    logic = _paks_dir(game_folder) / 'LogicMods'
    our_logic = {f for m in MODS.values() if m.get('dest') == 'logic' for f in _pak_files(m)}
    return out + ([p.name for p in logic.iterdir() if p.is_file() and p.name not in our_logic] if logic.is_dir() else [])


def _maybe_remove_ue4ss(game_folder):
    """remove the UE4SS the app installed once nothing uses it; if the player changed its settings, it is theirs now
    (left in place, no longer the app's)"""
    b = _bin(game_folder)
    if (b / 'ue4ss' / MARKER).is_file() and not any(_is_on(game_folder, m) for m in MODS.values() if _needs_ue4ss(m)) \
            and not _others(game_folder):
        ini = b / 'ue4ss' / 'UE4SS-settings.ini'
        if ini.is_file() and _sha(ini) not in OLD_SETTINGS | {_sha(paths.resource('data', 'ue4ss', 'ue4ss',
                                                                                  'UE4SS-settings.ini'))}:
            (b / 'ue4ss' / MARKER).unlink()
            log.info('UE4SS: left installed (its settings were changed in the game)')
            return
        (b / 'dwmapi.dll').unlink(missing_ok=True)          # UE4SS no longer loads; then remove what we installed
        shutil.rmtree(b / 'ue4ss', ignore_errors=True)


def _sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def _shipped(folder):
    """the app's copy of a Lua mod: (its folder, {file: sha256})"""
    src = paths.resource('data', 'mods', folder)
    return src, {f.relative_to(src).as_posix(): _sha(f) for f in sorted(src.rglob('*'))
                 if f.is_file() and f.name not in NOT_SHIPPED}


def _manifest(dst):
    try:
        return json.loads((dst / MANIFEST).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def _copy_lua(b, folder):
    """the app's files of a Lua mod into the game: scripts always as the app has them, a data file only if the mod or
    the player didn't change it since the app put it there; scripts the app no longer ships are removed"""
    src, new = _shipped(folder)
    dst = b / 'ue4ss' / 'Mods' / folder
    old = _manifest(dst) or {}
    for rel, h in new.items():
        d = dst / rel
        if d.is_file():
            have = _sha(d)
            if have == h or (not rel.endswith('.lua') and rel in old and have != old[rel]):
                continue                                    # up to date, or a data file changed in the game: theirs
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / rel, d)
    for rel in set(old) - set(new):
        if rel.endswith('.lua'):
            (dst / rel).unlink(missing_ok=True)
    dst.mkdir(parents=True, exist_ok=True)
    (dst / MANIFEST).write_text(json.dumps(new, indent=0, sort_keys=True), encoding='utf-8')


def _lua_outdated(b, folder):
    """the app's copy of an installed Lua mod changed (installed by an older app version: compared file by file)"""
    dst = b / 'ue4ss' / 'Mods' / folder
    new = _shipped(folder)[1]
    old = _manifest(dst)
    if old is None:
        return any(not (dst / rel).is_file() or _sha(dst / rel) != h for rel, h in new.items())
    return old != new


def _set_lua(game_folder, folder, on):
    b = _bin(game_folder)
    if on:
        _ensure_ue4ss(game_folder)
        _copy_lua(b, folder)
        _set_line(b, folder, True)
    else:
        _set_line(b, folder, False)
        shutil.rmtree(b / 'ue4ss' / 'Mods' / folder, ignore_errors=True)
        _maybe_remove_ue4ss(game_folder)


def _ensure_bp_loader(game_folder):
    """UE4SS's Blueprint mod loader, which loads the paks in Content/Paks/LogicMods"""
    _ensure_ue4ss(game_folder)
    b = _bin(game_folder)
    for folder in BP_LOADER:
        dst = b / 'ue4ss' / 'Mods' / folder
        if not (dst / 'Scripts' / 'main.lua').is_file():
            shutil.copytree(paths.resource('data', 'ue4ss', 'ue4ss', 'Mods', folder), dst, dirs_exist_ok=True)
        if not _line_on(b, folder):
            _set_line(b, folder, True)


def _set_pak(game_folder, m, on):
    d = _pak_dir(game_folder, m)
    if not on:
        for f in _pak_files(m):
            (d / f).unlink(missing_ok=True)
        return
    with zipfile.ZipFile(paths.resource('data', 'lifts', m['zip'])) as z:
        names = {Path(n).name: n for n in z.namelist() if Path(n).suffix in PAK_EXTS}
        if sorted(names) != sorted(_pak_files(m)):
            raise ValueError('%s: unexpected files in %s' % (m['name'], m['zip']))
        d.mkdir(parents=True, exist_ok=True)
        for fn, member in names.items():
            paths.atomic_write(d / fn, z.read(member))


def set_mod(game_folder, mod_id, on):
    m = MODS[mod_id]
    if m['kind'] == 'lua':
        _set_lua(game_folder, m['folder'], on)
    else:
        if on and m.get('dest') == 'logic':
            _ensure_bp_loader(game_folder)
        _set_pak(game_folder, m, on)
        if m.get('lua'):                                # its in-game script goes with it
            _set_lua(game_folder, m['lua'], on)
        if not on:
            _maybe_remove_ue4ss(game_folder)
        refresh(game_folder)
    return status(game_folder)


# ---------------------------------------------------------------- keeping installed mods in step

_refreshed = set()      # states already handled in this run


def _game_stamp(game_folder):
    return sorted([f.name, f.stat().st_size, f.stat().st_mtime_ns]
                  for f in _paks_dir(game_folder).glob('SkiResortSimulator-*.utoc'))


def _hand_paks(game_folder):
    """the .utoc of paks in ~mods (and its subfolders, which the game mounts too) that the app didn't put there (its pak
    mods, STOCK_PAK and maps aside): [path in ~mods, size, mtime]"""
    mods = _mods_dir(game_folder)
    ours = {p.lower() for m in MODS.values() if m['kind'] == 'pak' for p in m['paks']} | \
        {STOCK_PAK.lower(), install.REGISTRY_PAK.lower()}
    try:
        ours |= {Path(f).stem.lower() for m in install.Game(game_folder).installed().values() for f in m['files']}
    except (OSError, ValueError, KeyError):
        pass
    return sorted([u.relative_to(mods).as_posix(), u.stat().st_size, u.stat().st_mtime_ns] for u in mods.rglob('*.utoc')
                  if u.stem.lower() not in ours and not u.stem.lower().startswith('zzz_mc_')
                  and u.stem.lower() != 'global' and not any(p.startswith('.') for p in u.relative_to(mods).parts))


def _state(game_folder):
    files = [_pak_dir(game_folder, m) / (p + '.utoc') for m in MODS.values() if m['kind'] == 'pak' for p in m['paks']]
    files.append(_mods_dir(game_folder) / (STOCK_PAK + '.utoc'))
    return (str(game_folder), json.dumps(_game_stamp(game_folder)), json.dumps(_hand_paks(game_folder)),
            tuple((f.stat().st_size, f.stat().st_mtime_ns) if f.is_file() else None for f in files))


def _outdated(game_folder, m):
    """pak mods are installed only by the app, so any other version (an older app's, or one copied in by hand) is
    replaced by the app's own; compared by the toc, which hashes every chunk"""
    d = _pak_dir(game_folder, m)
    with zipfile.ZipFile(paths.resource('data', 'lifts', m['zip'])) as z:
        tocs = {Path(n).name: n for n in z.namelist() if n.endswith('.utoc')}
        return any(z.read(tocs[p + '.utoc']) != (d / (p + '.utoc')).read_bytes() for p in m['paks'])


OLD_HOOKS = re.compile(r'^(Hook(?!EngineTick)\w+\s*=\s*)0\s*$', re.M)


def _sync_ue4ss(game_folder):
    """the UE4SS the app installed: libraries it lacks added (never replacing a file), the settings of older app versions
    replaced, and in ones the player edited since, the hooks those versions switched off switched back on"""
    b = _bin(game_folder)
    if not (b / 'ue4ss' / MARKER).is_file():
        return
    src = paths.resource('data', 'ue4ss', 'ue4ss')
    for folder in UE4SS_LIBS:
        dst = b / 'ue4ss' / 'Mods' / folder
        if folder == 'shared' or dst.is_dir():
            for f in (src / 'Mods' / folder).rglob('*'):
                t = dst / f.relative_to(src / 'Mods' / folder)
                if f.is_file() and not t.exists():
                    log.info('UE4SS: adding %s', t.relative_to(b / 'ue4ss'))
                    t.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(f, t)
    ini = b / 'ue4ss' / 'UE4SS-settings.ini'
    if not ini.is_file():
        return
    if _sha(ini) in OLD_SETTINGS:
        log.info('UE4SS: settings of an older app version replaced')
        shutil.copy2(src / 'UE4SS-settings.ini', ini)
        return
    text = ini.read_text(encoding='utf-8', errors='replace')
    hooks = re.findall(r'^Hook(?!EngineTick)\w+\s*=\s*(\d)', text, re.M)
    if hooks and set(hooks) == {'0'}:                   # every hook still off as those versions set them
        log.info('UE4SS: hooks switched back on in edited settings')
        ini.write_text(OLD_HOOKS.sub(r'\g<1>1', text), encoding='utf-8')


def _shared(on):
    """what STOCK_PAK holds for the installed pak mods: the composite's parent tables (package paths: the mods' whole
    copies of the table, the game's own, the mods' own tables), the snow cap entries, and the copies the app ships
    [[name, zip, crc of its files]]"""
    full = [(t, m['zip']) for m in on for t in m.get('full_tables', ())]
    tables = [t if '/' in t else '/Game/Data/' + t for m in on for t in m.get('tables', ())]
    caps = [list(c) for m in on for c in m.get('snowcaps', ())]
    parents = ['/Game/Data/' + t for t, _ in full] + ['/Game/Data/' + STOCK_TABLE] + tables if full or tables else []
    ships = []
    for t, z in full:
        with zipfile.ZipFile(paths.resource('data', 'lifts', z)) as zf:
            ships.append([t, z, [zf.getinfo('tables/%s%s' % (t, e)).CRC for e in ('.uasset', '.uexp')]])
    return parents, caps, ships


def _by_hand(game_folder, work, game_registry):
    """what paks installed by hand add to the build menu and the snow caps, read from their own copies: (their tables
    after the game's, [(renamed whole table, uasset, uexp)] before it, snow cap entries); a pak that can't be read is
    left out (logged)"""
    paks, mods = _paks_dir(game_folder), _mods_dir(game_folder)
    tables, full, caps, stock_keys = [], [], [], None
    have = {}                                           # what each hand pak has; a mod's paks find each other's
    for name, _, _ in _hand_paks(game_folder):
        try:
            have[name] = modscan.assets(mods / name)
        except Exception as e:
            log.warning('mods: could not read %s: %s', name, e)
    known = set().union(*have.values()) if have else set()

    def files_of(name):
        return [(mods / name).with_suffix(e) for e in PAK_EXTS if (mods / name).with_suffix(e).is_file()]
    plain = [f for n, pkgs in have.items() if not pkgs & {modscan.ECONOMY, modscan.REGISTRY} for f in files_of(n)]
    for k, (name, pkgs) in enumerate(have.items()):
        try:
            want = [p for p in (modscan.ECONOMY, modscan.REGISTRY) if p in pkgs]
            if not want:
                continue                                # (read with the plain hand paks: its tables may be there)
            content = modscan.extract(paks, files_of(name), work / ('hand%d' % k), [p.rsplit('/', 1)[1] for p in want],
                                      also=plain)
            n_tables, n_caps, lost = 0, 0, []
            if modscan.ECONOMY in pkgs:
                ua, ue = modscan.read(content, modscan.ECONOMY)
                kind, parents = modscan.building_table(ua, ue, known)
                if kind == 'composite':                 # its own tables, in any of the hand paks
                    mine = [p for p in parents if p in known and p != modscan.STOCK_COPY and p not in tables]
                    tables += mine
                    n_tables = len(mine)
                else:
                    t = HAND_TABLE % len(full)
                    full.append((t, sa.rename_asset(ua, modscan.ECONOMY, '/Game/Data/' + t), ue))
                    n_tables = 1
            if modscan.REGISTRY in pkgs:
                if stock_keys is None:
                    stock_keys = set(sa.snowcap_keys(*game_registry()))
                new, lost = modscan.new_snowcaps(*modscan.read(content, modscan.REGISTRY), stock_keys, known,
                                                 modscan.base_assets(paks))
                caps += [list(c) for c in new if list(c) not in caps]
                n_caps = len(new)
            log.info('mods: %s (installed by hand): %d building tables and %d snow caps kept%s', name, n_tables,
                     n_caps, (', %d snow caps without their data left out' % len(lost)) if lost else '')
        except Exception as e:
            log.warning('mods: could not read %s: %s', name, e)
    return tables, full, caps


def _build_stock(game_folder, parents, caps, ships=(), into=None):
    sim = Path(game_folder) / 'SkiResortSimulator'
    paks = sim / 'Content' / 'Paks'
    work = Path(tempfile.mkdtemp(prefix='.skilift_', dir=sim))
    registry = []

    def game_registry():                                # the game's own snow cap list, read once
        if not registry:
            (work / 'caps').mkdir()
            registry.extend(install.extract_data_asset(paks, work / 'caps', sa.REGISTRY, 'snow cap list',
                                                       sub='Data/SnowCaps')[:2])
        return registry
    try:
        (work / 'table').mkdir()
        ua, ue, so = install.extract_data_asset(paks, work / 'table', 'DT_BuildingEconomy', 'building list')
        files = {'Data/%s.uasset' % STOCK_TABLE: sa.rename_asset(ua, '/Game/Data/DT_BuildingEconomy',
                                                                 '/Game/Data/' + STOCK_TABLE),
                 'Data/%s.uexp' % STOCK_TABLE: ue}
        hand_tables, hand_full, hand_caps = _by_hand(game_folder, work, game_registry)
        if parents:                                     # (only when the app's mods have tables: else the paks as before)
            parents = ['/Game/Data/' + t for t, _, _ in hand_full] + list(parents) + hand_tables
            files['Data/DT_BuildingEconomy.uasset'], files['Data/DT_BuildingEconomy.uexp'] = sa.make_composite(ua, parents)
            for t, tua, tue in hand_full:
                files['Data/%s.uasset' % t], files['Data/%s.uexp' % t] = tua, tue
        for t, z, _ in ships:                           # mods' whole copies of the table, renamed (package_mod.py)
            with zipfile.ZipFile(paths.resource('data', 'lifts', z)) as zf:
                for e in ('.uasset', '.uexp'):
                    files['Data/%s%s' % (t, e)] = zf.read('tables/%s%s' % (t, e))
        if caps:
            rua, rue = game_registry()
            rua, rue = sa.add_snowcaps(rua, rue, [tuple(c) for c in list(caps) + hand_caps])
            files['Data/SnowCaps/%s.uasset' % sa.REGISTRY], files['Data/SnowCaps/%s.uexp' % sa.REGISTRY] = rua, rue
        legacy = work / 'legacy'
        for rel, data in files.items():
            p = legacy / 'SkiResortSimulator' / 'Content' / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (legacy / 'scriptobjects.bin').write_bytes(so)
        out = work / 'out'
        out.mkdir()
        install.run_retoc(['to-zen', '--version', install.ENGINE, str(legacy), str(out / (STOCK_PAK + '.utoc'))])
        for e in PAK_EXTS:
            paths.atomic_write(Path(into or _mods_dir(game_folder)) / (STOCK_PAK + e), (out / (STOCK_PAK + e)).read_bytes())
    finally:
        paths.remove_tree(work)


def _drop_stock(mods):
    for e in PAK_EXTS:
        (mods / (STOCK_PAK + e)).unlink(missing_ok=True)
    (mods / STOCK_STAMP).unlink(missing_ok=True)


def refresh(game_folder):
    """Game closed: updates switched-on mods to the app's versions, the app's UE4SS to its libraries and settings, and
    keeps STOCK_PAK in step with the game and the mods (made when missing or when either changed; removed when no
    installed mod needs it, or when making it fails: the packs then use their own copies). Never raises: it is tried
    again when the game or the mods change, or in the next run."""
    paths.sweep(Path(game_folder) / 'SkiResortSimulator', _mods_dir(game_folder))   # what earlier runs couldn't remove
    try:
        key = _state(game_folder)
    except Exception as e:                              # never let this break the app
        log.warning('mods: could not check the mods: %s', e)
        return
    if key in _refreshed:
        return
    for step in (_refresh_lua, _sync_ue4ss, _refresh_paks):      # each on its own: one failing doesn't stop the rest
        try:
            step(game_folder)
        except Exception as e:
            log.warning('mods: %s failed: %s', step.__name__.strip('_'), e)
    try:
        _refreshed.add(_state(game_folder))
    except Exception:
        _refreshed.add(key)


def _refresh_lua(game_folder):
    b = _bin(game_folder)
    for old, new_id in LEGACY_LUA.items():              # Weather Controls became the cheat menu (it has the weather)
        if _lua_on(b, old):
            log.info('%s: replaced by %s', old, MODS[new_id]['name'])
            _set_lua(game_folder, MODS[new_id]['folder'], True)      # first, so UE4SS stays
            _set_lua(game_folder, old, False)
    for m in MODS.values():                             # a pak mod's script goes with its pak: one that went missing
        if m.get('lua'):                                # (UE4SS removed by hand) comes back, one without it goes
            pak = _pak_on(game_folder, m)
            if pak and not _lua_on(b, m['lua']):
                log.info('%s: installing its in-game script', m['name'])
                _set_lua(game_folder, m['lua'], True)
            elif not pak and (b / 'ue4ss' / 'Mods' / m['lua']).is_dir():
                log.info('%s: removing its in-game script (the mod is not installed)', m['name'])
                _set_lua(game_folder, m['lua'], False)
        if m.get('dest') == 'logic' and _pak_on(game_folder, m):
            _ensure_bp_loader(game_folder)
    for folder in _lua_folders():                       # scripts from an older app version (the weather key was F9,
        if _lua_on(b, folder) and _lua_outdated(b, folder):         # the full game's Report a Bug key)
            log.info('%s: updating to the version in the app', folder)
            _set_lua(game_folder, folder, True)


def _refresh_paks(game_folder):
    mods = _mods_dir(game_folder)
    on = [m for m in MODS.values() if m['kind'] == 'pak' and _pak_on(game_folder, m)]
    for m in on:
        if _outdated(game_folder, m):
            log.info('%s: updating to the version in the app', m['name'])
            _set_pak(game_folder, m, True)
    parents, caps, ships = _shared(on)
    if not parents and not caps:
        _drop_stock(mods)
        return
    stamp = [STOCK_FORMAT, _game_stamp(game_folder), parents, caps, ships, _hand_paks(game_folder)]
    try:
        made_from = json.loads((mods / STOCK_STAMP).read_text(encoding='utf-8'))
    except (OSError, ValueError):
        made_from = None
    if made_from != stamp or not all((mods / (STOCK_PAK + e)).is_file() for e in PAK_EXTS):
        try:
            _build_stock(game_folder, parents, caps, ships)
        except Exception:
            _drop_stock(mods)                           # never leave one of other mods or another game version
            raise
        (mods / STOCK_STAMP).write_text(json.dumps(stamp), encoding='utf-8')
        log.info('mods: shared build menu and snow caps rebuilt (%d tables, %d snow caps)',
                 max(0, len(parents) - 1), len(caps))

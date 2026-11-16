"""Packages a mod someone made for Ski-E-O into the Map Creator's Mod Library (docs/MODDING.md): checks it against the
game and the mods already in the library, and with --write copies its files into data/ (Lua mods: data/mods/<folder>;
paks: data/lifts/<id>.zip) and prints its MODS entry for skieo_creator/modlib.py. It reads the installed game's files
(in a temporary folder inside the game folder, removed after) and never changes them or the mod's own paks.

It is not a security review: a Lua mod runs with the player's full rights. It refuses files that aren't scripts or
text, and lists every risky call (running programs, loading libraries, deleting or writing files) to read before you
approve the mod.

A mod that replaces the build menu's table (DT_BuildingEconomy) gets its copy renamed to DT_BuildingMod_<n> and shipped
in its zip ('full_tables'), and one that replaces the snow cap list gets the entries the game lacks ('snowcaps'): the
Map Creator merges both for every installed mod (modlib STOCK_PAK), which the game mounts above their paks.

usage: python packaging/package_mod.py <the mod as sent: a folder or zip> --id ID --name NAME --author AUTHOR
                                   [--about TEXT] [--key KEY] [--logic] [--write]
--logic: its paks are Blueprint mods (UE4SS's BPModLoaderMod loads them from Content/Paks/LogicMods), when they aren't
in a folder named LogicMods already."""
import argparse
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from skieo_creator import install, modlib, modscan, paths  # noqa: E402
from skieo_creator.engine import shared_assets as sa  # noqa: E402

NOT_MODS = {modscan.LEVELS: 'the map list: maps go in as map packages (the Maps tab), not as mods'}
LIFT_CAPS = {'/Game/Meshes/SnowCaps/SM_SnowCap_BP_Lift_Start', '/Game/Meshes/SnowCaps/SM_SnowCap_BP_Lift_End'}
TABLE = 'DT_BuildingMod_%03d'           # 18 characters like DT_BuildingEconomy (a rename in place)
# UE4SS's own mod folders (a library mod of that name would replace the player's or be deleted with it)
UE4SS_STOCK = ('BPML_GenericFunctions', 'BPModLoaderMod', 'CheatManagerEnablerMod', 'ConsoleCommandsMod',
               'ConsoleEnablerMod', 'Keybinds', 'LineTraceMod', 'SplitScreenMod', 'shared')
TEXT = ('.lua', '.txt', '.json', '.ini', '.cfg', '.md')     # what a Lua mod's folder may ship
# what a Lua mod can do beyond the game: every use is listed to read (hints, not a proof: read all of it)
RISKY = {r'\bos\s*(?:\.|\[\s*["\'])\s*(?!time\b|clock\b|date\b|getenv\b|difftime\b)\w+':
         'the os library: run programs, delete or move files, quit',
         r'\bio\s*(?:\.|\[\s*["\'])\s*(?!write\b|read\b)\w+': 'the io library: open, write or run files',
         r'\b(?:os|io|debug|package)\b(?!\s*(?:\.|\[|:))': 'a system library passed around (hides what it calls)',
         r'\b(?:load|loadstring|loadfile|dofile)\s*\(': 'runs code from a string or file',
         r'\bpackage\s*\.': 'the package library: load native libraries, change where code comes from',
         r'\bdebug\s*\.': 'the debug library: can change any other code',
         r'\b(?:_G|_ENV)\s*\[|\b(?:getfenv|setfenv|rawget\s*\(\s*_G)': 'reaches globals by name (hides what it calls)',
         r'\bExecuteConsoleCommand\b': 'runs game console commands',
         r'\bLoadAsset': 'loads assets (LoadAsset_Blocking froze the game)'}
KEYS = {'F6': 'the cheat menu (F6)', 'INS': "UE4SS's Blueprint mod loader (Insert)", 'Insert': "UE4SS's Blueprint mod "
        'loader (Insert)'}


def library_assets(tmp):
    """{package: mod name} of the pak mods already in the library"""
    out = {}
    for m in modlib.MODS.values():
        if m['kind'] != 'pak':
            continue
        with zipfile.ZipFile(ROOT / 'data' / 'lifts' / m['zip']) as z:
            for n in z.namelist():
                if n.endswith('.utoc'):                         # (retoc reads the .ucas beside it too)
                    for e in ('.utoc', '.ucas'):
                        with z.open(n[:-5] + e) as s, open(tmp / (Path(n).stem + e), 'wb') as d:
                            shutil.copyfileobj(s, d, 1 << 20)
                    out.update({a: m['name'] for a in modscan.assets(tmp / Path(n).name)})
                    for e in ('.utoc', '.ucas'):
                        (tmp / (Path(n).stem + e)).unlink()
    return out


def _taken(names, root, sub):
    """names (lower case) already used by the library: app names, and files in data/<sub>"""
    d = root / 'data' / sub
    return {n.lower() for n in names} | ({p.name.lower() for p in d.iterdir()} if d.is_dir() else set())


def check(mod, mod_id, name, author, about='', key=None, tmp=None, logic=False):
    """-> (MODS entry, problems, notes, {file in data/: source path or bytes}); tmp: a folder for the unpacked mod, which
    the files may point into (the caller removes it)"""
    problems, notes, out = [], [], {}
    if not re.fullmatch(r'[a-z0-9_]+', mod_id) or mod_id in modlib.MODS:
        problems.append('the id must be new and only a-z, 0-9 and _ (taken: %s)' % ', '.join(modlib.MODS))
    taken_keys = {m['key'].lower(): m['name'] for m in modlib.MODS.values() if m.get('key')}
    if key and key.lower() in taken_keys:
        problems.append('the key %s is %s\'s: ask for another' % (key, taken_keys[key.lower()]))
    found = install.find_game()
    if not found or not found[0]:
        return None, ['Ski-E-O was not found: the mod is checked against its files'], notes, out
    sim = Path(found[0]) / 'SkiResortSimulator'
    paks = sim / 'Content' / 'Paks'
    tmp = Path(tmp or tempfile.mkdtemp(prefix='skieo_pkg_'))
    tmp.mkdir(parents=True, exist_ok=True)
    paths.sweep(sim)
    work = Path(tempfile.mkdtemp(prefix='.skipkg_', dir=sim))          # on the game's drive: hard links
    try:
        src = Path(mod)
        if src.is_file():
            with zipfile.ZipFile(src) as z:
                z.extractall(tmp / 'mod')
            src = tmp / 'mod'
        files = [f for f in src.rglob('*') if f.is_file() and '__MACOSX' not in f.parts and not f.name.startswith('._')]

        # ---- Lua mods: folders with Scripts/main.lua (a zip of the folder's contents: named after the zip)
        lua = sorted({f.parent.parent for f in files if f.name.lower() == 'main.lua' and f.parent.name.lower() == 'scripts'})
        if len(lua) > 1:
            problems.append('more than one Lua mod (%s): package them one at a time' % ', '.join(d.name for d in lua))
        folder = None
        if lua:
            d = lua[0]
            folder = Path(mod).stem if d == src else d.name
            if d == src:
                notes.append('the Lua mod is the zip\'s own contents: its folder is named %s after the zip' % folder)
            if not re.fullmatch(r'[A-Za-z0-9_]+', folder):
                problems.append('%s: a Lua mod folder name needs only letters, digits and _' % folder)
            taken = _taken(list(modlib._lua_folders()) + list(modlib.LEGACY_LUA) + list(UE4SS_STOCK), ROOT, 'mods')
            if folder.lower() in taken:
                problems.append('%s: a Lua mod folder of that name is in the library or UE4SS already' % folder)
            if (d / 'dlls').is_dir():
                problems.append('%s: a UE4SS C++ mod (dlls): the library takes Lua mods only' % folder)
            text = ''
            for f in sorted(f for f in files if d in f.parents):
                if f.name == 'dev.txt':
                    notes.append('%s/dev.txt is left out (a dev switch)' % folder)
                    continue
                rel = f.relative_to(d).as_posix()
                if f.suffix.lower() in modlib.PAK_EXTS or any(p.lower() == 'logicmods' for p in f.relative_to(d).parts):
                    continue                                    # the mod's paks: packaged as paks below
                if f.suffix.lower() not in TEXT:
                    problems.append('%s/%s: not a script or text file (the library ships no programs or libraries)'
                                    % (folder, rel))
                    continue
                if f.suffix.lower() == '.lua':                  # (comments left out, keeping the line numbers)
                    t = re.sub(r'--\[(=*)\[.*?\]\1\]', lambda c: '\n' * c.group(0).count('\n'),
                               f.read_text(encoding='utf-8', errors='replace'), flags=re.S)
                    t = re.sub(r'--[^\n]*', '', t)
                    text += t
                    for pat, what in RISKY.items():
                        for mt in re.finditer(pat, t):
                            line = t.count('\n', 0, mt.start()) + 1
                            notes.append('READ BEFORE APPROVING: %s/%s:%d %s (%s)' % (folder, rel, line, mt.group(0), what))
                out['mods/%s/%s' % (folder, rel)] = f
            keys = set(re.findall(r'Key\.(\w+)', text)) | set(re.findall(r'FName\(\s*["\'](\w+)["\']\s*\)', text))
            for k in sorted(keys):
                if k in KEYS:
                    notes.append('%s reads the key %s, as %s does: check they don\'t clash' % (folder, k, KEYS[k]))
            if 'A' in keys and re.search(r'CONTROL|LeftControl|RightControl|Ctrl', text):
                notes.append('%s reads Ctrl+A, as Anarchy does: check they don\'t clash' % folder)
            if re.search(r'\bOOF_\w+', text):
                notes.append('%s uses an OOF_ global, like the app\'s own mods' % folder)

        # ---- paks: .pak/.ucas/.utoc by name; in a LogicMods folder (or --logic): a Blueprint mod
        stems, where = {}, {}
        for f in files:
            if f.suffix.lower() in modlib.PAK_EXTS:
                parts = stems.setdefault(f.stem, {})
                if f.suffix.lower() in parts:
                    problems.append('%s%s is in the mod twice (%s and %s): send one copy' % (
                        f.stem, f.suffix.lower(), where[(f.stem, f.suffix.lower())], f.relative_to(src).parent))
                parts[f.suffix.lower()] = f
                where[(f.stem, f.suffix.lower())] = f.relative_to(src).parent
                parts['logic'] = parts.get('logic', False) or logic or src.name.lower() == 'logicmods' or \
                    any(p.lower() == 'logicmods' for p in f.relative_to(src).parts[:-1])
            elif f.suffix.lower() == '.lua' and any(p.lower() == 'logicmods' for p in f.relative_to(src).parts[:-1]):
                problems.append('%s: a Blueprint mod\'s config.lua is not supported: its ModActor must be at '
                                '/Game/Mods/<pak name>/ModActor' % f.relative_to(src))
        dests = {s['logic'] for s in stems.values()}
        if len(dests) > 1:
            problems.append('some paks are Blueprint mods (LogicMods) and some not: package them as two mods')
        reserved = _taken([p for m in modlib.MODS.values() if m['kind'] == 'pak' for p in m['paks']] +
                          [Path(modlib.OWN_LIFT_MOD).stem, modlib.STOCK_PAK, install.REGISTRY_PAK, 'global'], ROOT, 'lifts')
        library = library_assets(tmp) if stems else {}
        base = modscan.base_assets(paks) if stems else set()
        tables, full, caps = [], [], []
        used = {t for m in modlib.MODS.values() for t in m.get('full_tables', ())}
        for stem, parts in sorted(stems.items()):
            if set(modlib.PAK_EXTS) - set(parts):
                problems.append('%s: needs %s' % (stem, ', '.join(stem + e for e in modlib.PAK_EXTS)))
                continue
            low = stem.lower()
            if low in reserved or low.startswith('zzz_mc_') or low.startswith('skiresortsimulator-'):
                problems.append('%s: the game or the app uses that pak name' % stem)
                continue
            inside = modscan.pak_files(parts['.pak'])
            if inside != 0:                             # an IoStore container's .pak holds none
                problems.append('%s.pak %s: ask for a plain IoStore pak (retoc, or the editor\'s IoStore packaging)' % (
                    stem, 'can\'t be read (not a pak, or encrypted)' if inside is None else
                    'holds %d files outside its IoStore container, which this check can\'t see into' % inside))
            n = re.search(r'_(\d+)_P$', stem, re.I)
            if n and int(n.group(1)) >= 9:
                problems.append('%s: a pak numbered _%s_P loads after the merged build menu and snow caps the app '
                                'makes (%s): ask for it without the number' % (stem, n.group(1), modlib.STOCK_PAK))
            have = modscan.assets(parts['.utoc'])
            for a in sorted(have & set(NOT_MODS)):
                problems.append('%s: replaces %s' % (stem, NOT_MODS[a]))
            clash = sorted((have - modscan.SHARED - LIFT_CAPS) & set(library))
            if clash:
                problems.append('%s: %d assets that %s already has, e.g. %s' % (stem, len(clash), library[clash[0]], clash[0]))
            if parts['logic'] and '/Game/Mods/%s/ModActor' % stem not in have:
                problems.append('%s: a Blueprint mod needs /Game/Mods/%s/ModActor (what UE4SS\'s Blueprint mod loader '
                                'loads)' % (stem, stem))
            if have & LIFT_CAPS:
                notes.append('%s: replaces the game\'s generic lift snow caps (as the R2 lift packs do): those of one '
                             'of them are lost' % stem)
            stock = sorted((have - modscan.SHARED) & base)
            if stock:
                notes.append('%s: replaces %d of the game\'s own assets, e.g. %s' % (stem, len(stock), ', '.join(stock[:5])))
            want = [p for p in (modscan.ECONOMY, modscan.REGISTRY) if p in have]
            if want:
                content = modscan.extract(paks, [parts[e] for e in modlib.PAK_EXTS], work / stem,
                                          [p.rsplit('/', 1)[1] for p in want])
                if modscan.ECONOMY in have:
                    ua, ue = modscan.read(content, modscan.ECONOMY)
                    try:
                        kind, parents = modscan.building_table(ua, ue)
                    except ValueError as e:
                        problems.append('%s: %s' % (stem, e))
                        kind, parents = None, []
                    if kind == 'composite':                      # made like the app's packs: its own tables
                        known = {modscan.STOCK_COPY} | {t if '/' in t else '/Game/Data/' + t
                                                        for m in modlib.MODS.values() for t in m.get('tables', ())}
                        mine = [p for p in parents if p not in known]
                        tables += [p for p in mine if p in have]
                        notes.append('%s: a composite build table over %s: check none of those is a whole copy of '
                                     'the game\'s table' % (stem, ', '.join(mine) or 'only known tables'))
                    elif kind == 'full':                         # the whole table, with its rows added
                        k = 1
                        while TABLE % k in used:
                            k += 1
                        t = TABLE % k
                        used.add(t)
                        full.append(t)
                        out['lifts/%s.zip:tables/%s.uasset' % (mod_id, t)] = sa.rename_asset(ua, modscan.ECONOMY,
                                                                                            '/Game/Data/' + t)
                        out['lifts/%s.zip:tables/%s.uexp' % (mod_id, t)] = ue
                        notes.append('%s: its whole build table goes in as %s, before the game\'s own (its rows of '
                                     'the game\'s buildings give way to the current ones)' % (stem, t))
                if modscan.REGISTRY in have:
                    (work / ('game_' + stem)).mkdir()
                    gua, gue, _ = install.extract_data_asset(paks, work / ('game_' + stem), sa.REGISTRY, 'snow cap list',
                                                             sub='Data/SnowCaps')
                    new, lost = modscan.new_snowcaps(*modscan.read(content, modscan.REGISTRY),
                                                     set(sa.snowcap_keys(gua, gue)), have, base)
                    caps += new
                    for kc in lost:
                        notes.append('%s: the snow cap of %s is left out: its data asset is in neither the mod nor '
                                     'the game' % (stem, kc))
                    notes.append('%s: %d snow caps of its own' % (stem, len(new)))
            for e in modlib.PAK_EXTS:
                out['lifts/%s.zip:%s%s' % (mod_id, stem, e)] = parts[e]
        if not lua and not stems:
            problems.append('no Lua mod (a folder with Scripts/main.lua) and no paks (.pak/.ucas/.utoc) found')
        if stems and (ROOT / 'data' / 'lifts' / (mod_id + '.zip')).exists():
            problems.append('data/lifts/%s.zip exists already' % mod_id)
        if any(not s.get('logic') for s in stems.values()) and not (tables or full or caps):
            notes.append('it adds nothing to the build menu (no building table)')

        if stems:
            entry = dict(kind='pak', name=name, author=author, paks=sorted(stems), zip=mod_id + '.zip')
            if True in dests:
                entry['dest'] = 'logic'
            if folder:
                entry['lua'] = folder
            for k, v in (('tables', tables), ('full_tables', full), ('snowcaps', caps)):
                if v:
                    entry[k] = v
        else:
            entry = dict(kind='lua', folder=folder or '', name=name, author=author)
        if key:
            entry['key'] = key
        entry['about'] = about
        return entry, problems, notes, out
    finally:
        paths.remove_tree(work)


def write(out, root=None):
    """put the checked files into data/ (nothing is written if any target exists)"""
    root = Path(root or ROOT)
    zips, plain = {}, {}
    for rel, data in out.items():
        if ':' in rel:
            z, member = rel.split(':')
            zips.setdefault(z, []).append((member, data))
        else:
            plain[rel] = data
    targets = [root / 'data' / z for z in zips] + sorted({root / 'data' / Path(rel).parts[0] / Path(rel).parts[1]
                                                          for rel in plain})
    there = [t for t in targets if t.exists()]
    if there:
        raise SystemExit('%s exists already: nothing written' % there[0])
    for rel, data in plain.items():
        p = root / 'data' / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(data, p)
    for z, members in zips.items():
        p = root / 'data' / z
        p.parent.mkdir(parents=True, exist_ok=True)
        part = p.with_suffix('.zip.part')
        with zipfile.ZipFile(part, 'w', zipfile.ZIP_STORED) as zf:
            for member, data in members:
                zf.writestr(member, data if isinstance(data, bytes) else Path(data).read_bytes())
        part.replace(p)


def entry_text(mod_id, entry):
    return '    %r: dict(%s),' % (mod_id, ', '.join('%s=%r' % kv for kv in entry.items()))


def main():
    ap = argparse.ArgumentParser(description='Package a mod into the Map Creator\'s Mod Library.')
    ap.add_argument('mod')
    ap.add_argument('--id', required=True)
    ap.add_argument('--name', required=True)
    ap.add_argument('--author', required=True)
    ap.add_argument('--about', default='')
    ap.add_argument('--key')
    ap.add_argument('--logic', action='store_true')
    ap.add_argument('--write', action='store_true')
    a = ap.parse_args()
    tmp = Path(tempfile.mkdtemp(prefix='skieo_pkg_'))
    try:
        entry, problems, notes, out = check(a.mod, a.id, a.name, a.author, a.about, a.key, tmp, a.logic)
        for n in notes:
            print('note:', n)
        for p in problems:
            print('PROBLEM:', p)
        if problems:
            sys.exit('not packaged')
        print('\nfiles: %s' % ', '.join(sorted(out)))
        if a.write:
            write(out)
            print('written to data/; add this to MODS in skieo_creator/modlib.py:\n')
        else:
            print('checked (nothing written; --write to package it). Its MODS entry:\n')
        print(entry_text(a.id, entry))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == '__main__':
    main()

"""Self-check of packaging someone else's mod (packaging/package_mod.py), of the app merging it and mods put in by hand
(modlib STOCK_PAK), and of map packages holding only maps (install.Game.only_a_map), with stand-in mods made from the
game's own files; skipped without the game. Writes only to temporary folders (inside the game folder for hard links).
usage: python tests/test_package_mod.py"""
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'packaging'))
from skieo_creator import install, modlib, modscan, paths  # noqa: E402
from skieo_creator.engine import shared_assets as sa  # noqa: E402
import package_mod as pm  # noqa: E402

found = install.find_game()
if not found or not found[0]:
    print('package mod: skipped (Ski-E-O not found)')
    sys.exit(0)
sim = Path(found[0]) / 'SkiResortSimulator'
paks = sim / 'Content' / 'Paks'
work = Path(tempfile.mkdtemp(prefix='.skilift_test_', dir=sim))          # hard links: on the game's drive
tmp = Path(tempfile.mkdtemp(prefix='skieo_pkgtest_'))
real_resource, real_root = paths.resource, pm.ROOT
CAP = '/Game/Mods/TestHuts/DA_SnowCap_BP_TestHut01'          # same length as the game's Bookstore cap it copies
HUT = ('/Game/Mods/TestHuts/BP_TestHut', 'BP_TestHut_C', CAP)
LOST = ('/Game/Mods/TestHuts/BP_TestHut2', 'BP_TestHut2_C', '/Game/Mods/TestHuts/DA_Nowhere')
GLOBAL = ('global.utoc', 'global.ucas')


def global_state():
    return [((paks / f).stat().st_size, (paks / f).stat().st_mtime_ns) for f in GLOBAL]


global_before = global_state()
try:
    for d in ('t', 'r', 'm', 'c'):
        (work / d).mkdir()
    ua, ue, so = install.extract_data_asset(paks, work / 't', 'DT_BuildingEconomy', 'building list')
    rua, rue, _ = install.extract_data_asset(paks, work / 'r', sa.REGISTRY, 'snow cap list', sub='Data/SnowCaps')
    mua, mue, _ = install.extract_data_asset(paks, work / 'm', 'DA_LevelRegistry', 'map list')
    cua, cue, _ = install.extract_data_asset(paks, work / 'c', 'DA_SnowCap_BP_Bookstore', 'a snow cap', sub='Data/SnowCaps')
    cua = sa.rename_asset(cua, '/Game/Data/SnowCaps/DA_SnowCap_BP_Bookstore', CAP)

    def container(folder, stem, files):
        """an IoStore container made from legacy assets {Content/...: bytes}, like a modder's cooked pak"""
        legacy = work / ('legacy_' + stem + '_' + folder.name)
        for rel, data in files.items():
            p = legacy / 'SkiResortSimulator' / 'Content' / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
        (legacy / 'scriptobjects.bin').write_bytes(so)
        folder.mkdir(parents=True, exist_ok=True)
        install.run_retoc(['to-zen', '--version', install.ENGINE, str(legacy), str(folder / (stem + '.utoc'))])
        return folder

    # a building mod made the usual way: the whole build table (with its rows), the snow cap list with its hut, and a
    # script binding F6 like the cheat menu and writing a file
    nua, nue = sa.add_snowcaps(rua, rue, [HUT, LOST])
    huts = {'Data/DT_BuildingEconomy.uasset': ua, 'Data/DT_BuildingEconomy.uexp': ue,
            'Data/SnowCaps/DA_SnowCapRegistry.uasset': nua, 'Data/SnowCaps/DA_SnowCapRegistry.uexp': nue,
            'Mods/TestHuts/DA_SnowCap_BP_TestHut01.uasset': cua, 'Mods/TestHuts/DA_SnowCap_BP_TestHut01.uexp': cue}
    good = container(tmp / 'TestHuts', 'TestHuts_P', huts)
    (good / 'TestHutScript' / 'Scripts').mkdir(parents=True)
    (good / 'TestHutScript' / 'Scripts' / 'main.lua').write_text(
        'RegisterKeyBind(Key.F6, function() end)\nlocal f = io.open("x.txt", "w")\n', encoding='utf-8')
    (good / 'TestHutScript' / 'dev.txt').write_text('', encoding='utf-8')
    (good / '__MACOSX').mkdir()
    (good / '__MACOSX' / '._TestHuts_P.pak').write_bytes(b'junk')
    entry, problems, notes, out = pm.check(good, 'test_huts', 'Test Huts', 'Someone', 'Huts.', None, tmp / 'unpack1')
    assert not problems, problems
    assert entry['kind'] == 'pak' and entry['paks'] == ['TestHuts_P'] and entry['lua'] == 'TestHutScript', entry
    assert entry['full_tables'] == ['DT_BuildingMod_001'] and 'tables' not in entry, entry
    assert entry['snowcaps'] == [HUT], entry.get('snowcaps')
    assert any('F6' in n for n in notes) and any('whole build table' in n for n in notes), notes
    assert any('BP_TestHut2_C is left out' in n for n in notes), notes      # its cap's data asset is nowhere
    assert any(n.startswith('READ BEFORE APPROVING') and 'main.lua:2 io.open' in n for n in notes), notes
    assert 'mods/TestHutScript/Scripts/main.lua' in out and not any('dev.txt' in k for k in out)
    renamed = out['lifts/test_huts.zip:tables/DT_BuildingMod_001.uasset']
    assert b'DT_BuildingMod_001' in renamed and b'DT_BuildingEconomy' not in renamed

    # packaged into a stand-in data/ folder: the zip the Mod Library installs, and the Lua mod; never over a file
    app = tmp / 'app'
    (app / 'data' / 'lifts').mkdir(parents=True)
    pm.write(out, app)
    z = app / 'data' / 'lifts' / 'test_huts.zip'
    with zipfile.ZipFile(z) as zf:
        assert sorted(zf.namelist()) == sorted(['TestHuts_P.pak', 'TestHuts_P.ucas', 'TestHuts_P.utoc',
                                                'tables/DT_BuildingMod_001.uasset', 'tables/DT_BuildingMod_001.uexp'])
    assert (app / 'data' / 'mods' / 'TestHutScript' / 'Scripts' / 'main.lua').is_file()
    try:
        pm.write(out, app)
        raise AssertionError('wrote over a packaged mod')
    except SystemExit as e:
        assert 'exists already' in str(e)

    # installed with the app's packs: the merged build menu has its table before the game's, the snow caps its hut
    paths.resource = lambda *a: z if a == ('data', 'lifts', 'test_huts.zip') else real_resource(*a)
    parents, caps, ships = modlib._shared([modlib.MODS['r2six'], dict(entry, about='')])
    assert parents == ['/Game/Data/DT_BuildingMod_001', '/Game/Data/DT_BuildingStock_0', '/Game/Data/DT_LiftMod_R2Six01']
    assert caps == [list(HUT)] and ships[0][:2] == ['DT_BuildingMod_001', 'test_huts.zip']
    paths.resource = real_resource

    # the same mod installed BY HAND into a game's ~mods (a stand-in game folder): the app's merged build menu and snow
    # caps keep its buildings, from its own copies
    fake = work / 'game'
    fpaks = fake / 'SkiResortSimulator' / 'Content' / 'Paks'
    (fpaks / '~mods').mkdir(parents=True)
    for f in paks.iterdir():
        if f.suffix in ('.utoc', '.ucas', '.pak') and (f.name.startswith('global.') or f.name.startswith('SkiResortSimulator-')):
            install.os.link(f, fpaks / f.name)
    for e in modlib.PAK_EXTS:
        shutil.copy2(good / ('TestHuts_P' + e), fpaks / '~mods' / ('TestHuts_P' + e))
    # ... and a mod split in two paks, the second in a subfolder: a composite table in one, its rows in the other
    rows = '/Game/Data/DT_SplitModRows_01'                      # (same length as the game's table it copies)
    split_a = container(tmp / 'SplitA', 'SplitA_P', dict(zip(('Data/DT_BuildingEconomy.uasset', 'Data/DT_BuildingEconomy.uexp'),
                                                             sa.make_composite(ua, ['/Game/Data/DT_BuildingStock_0', rows]))))
    split_b = container(tmp / 'SplitB', 'SplitB_P', {'Data/DT_SplitModRows_01.uasset': sa.rename_asset(ua, modscan.ECONOMY, rows),
                                                     'Data/DT_SplitModRows_01.uexp': ue})
    (fpaks / '~mods' / 'SplitMod').mkdir()
    for e in modlib.PAK_EXTS:
        shutil.copy2(split_a / ('SplitA_P' + e), fpaks / '~mods' / ('SplitA_P' + e))
        shutil.copy2(split_b / ('SplitB_P' + e), fpaks / '~mods' / 'SplitMod' / ('SplitB_P' + e))
    assert [h[0] for h in modlib._hand_paks(fake)] == ['SplitA_P.utoc', 'SplitMod/SplitB_P.utoc', 'TestHuts_P.utoc']
    parents, caps, _ = modlib._shared([modlib.MODS['buildings']])
    built = work / 'built'
    built.mkdir()
    modlib._build_stock(fake, parents, caps, (), into=built)
    content = modscan.extract(paks, [built / (modlib.STOCK_PAK + e) for e in modlib.PAK_EXTS], work / 'check',
                              ['DT_BuildingEconomy', sa.REGISTRY], also=[split_b / ('SplitB_P' + e) for e in modlib.PAK_EXTS])
    got = sa.composite_parents(*modscan.read(content, modscan.ECONOMY))      # (the Alpine table's pak isn't read here)
    assert got[:2] == ['/Game/Data/DT_BuildingMod_900', '/Game/Data/DT_BuildingStock_0'] and len(got) == 4, got
    assert got[3] == rows, got                                  # the split mod's rows, from its second pak
    keys = sa.snowcap_keys(*modscan.read(content, modscan.REGISTRY))
    assert HUT[:2] in keys and ('/Game/Blueprints/Buildings/BP_OofGen_M01', 'BP_OofGen_M01_C') in keys

    # what the tool refuses
    def refused(stem, files, why, extra=None, **kw):
        folder = container(tmp / ('bad_' + stem), stem, files) if files else (tmp / ('bad_' + stem))
        folder.mkdir(parents=True, exist_ok=True)
        for rel, data in (extra or {}).items():
            (folder / rel).parent.mkdir(parents=True, exist_ok=True)
            (folder / rel).write_bytes(data)
        _, problems, _, _ = pm.check(folder, 'bad_' + stem.lower(), 'Bad', 'Someone', tmp=tmp / ('unpack_' + stem), **kw)
        assert any(why in p for p in problems), (stem, problems)
    table = {'Data/DT_BuildingEconomy.uasset': ua, 'Data/DT_BuildingEconomy.uexp': ue}
    refused('ZZZ_AlpineBuildings_P', table, 'uses that pak name')
    refused('zzz_alpinebuildings_p', table, 'uses that pak name')                   # any case
    refused('global', table, 'uses that pak name')        # (it would also be written over the game's own global.*)
    refused('Late_9_P', table, 'loads after')
    refused('Maps_P', {'Data/DA_LevelRegistry.uasset': mua, 'Data/DA_LevelRegistry.uexp': mue}, 'the map list')
    refused('Clash_P', {'Data/DT_LiftMod_R2Six01.uasset': sa.rename_asset(ua, '/Game/Data/DT_BuildingEconomy',
                                                                          '/Game/Data/DT_LiftMod_R2Six01'),
                        'Data/DT_LiftMod_R2Six01.uexp': ue}, 'Doppelmayr D-Line R2 Six')
    refused('NoActor_P', table, 'needs /Game/Mods/NoActor_P/ModActor', logic=True)            # a Blueprint mod
    refused('Prog', None, 'not a script or text file', {'Prog/Scripts/main.lua': b'print(1)', 'Prog/tool.dll': b'MZ'})
    refused('Twice_P', table, 'is in the mod twice', {'old/Twice_P.pak': b'x'})
    assert global_state() == global_before, 'the game\'s own global container is untouched'

    def with_files(pak, n):
        """a copy of an IoStore .pak whose index says it holds n files of its own"""
        b = bytearray(Path(pak).read_bytes())
        i = b.rfind(modscan.struct.pack('<I', 0x5A6F12E1))
        off = modscan.struct.unpack_from('<q', b, i + 8)[0]
        modscan.struct.pack_into('<i', b, off + 4 + modscan.struct.unpack_from('<i', b, off)[0], n)
        return bytes(b)
    stuffed = tmp / 'Stuffed'
    shutil.copytree(good, stuffed, ignore=shutil.ignore_patterns('TestHutScript', '__MACOSX'))
    for e in modlib.PAK_EXTS:
        (stuffed / ('TestHuts_P' + e)).rename(stuffed / ('Stuffed_P' + e))
    (stuffed / 'Stuffed_P.pak').write_bytes(with_files(stuffed / 'Stuffed_P.pak', 2))
    _, problems, _, _ = pm.check(stuffed, 'stuffed', 'Stuffed', 'Someone', tmp=tmp / 'unpack_stuffed')
    assert any('holds 2 files outside its IoStore container' in p for p in problems), problems
    keyed = tmp / 'keyed' / 'KeyedMod' / 'Scripts'
    keyed.mkdir(parents=True)
    (keyed / 'main.lua').write_text('print(1)\n', encoding='utf-8')
    _, problems, _, _ = pm.check(tmp / 'keyed', 'keyed', 'Keyed', 'Someone', key='f6', tmp=tmp / 'unpack_k')
    assert any("the key f6 is Oof's Simple Cheat Menu's" in p for p in problems), problems

    # a Lua mod zipped from inside its folder takes the zip's name; one with its paks beside it is both
    zl = tmp / 'CoolScript.zip'
    with zipfile.ZipFile(zl, 'w') as zf:
        zf.writestr('Scripts/main.lua', 'print("hi")\n')
    entry, problems, notes, _ = pm.check(zl, 'cool', 'Cool', 'Someone', tmp=tmp / 'unpack_zip')
    assert not problems and entry == dict(kind='lua', folder='CoolScript', name='Cool', author='Someone', about=''), \
        (entry, problems)
    zb = tmp / 'BothMod.zip'
    with zipfile.ZipFile(zb, 'w') as zf:
        zf.writestr('scripts/main.lua', 'print("hi")\n')                    # (any letter case)
        for e in modlib.PAK_EXTS:
            zf.write(good / ('TestHuts_P' + e), 'TestHuts_P' + e)
    entry, problems, notes, out = pm.check(zb, 'both', 'Both', 'Someone', tmp=tmp / 'unpack_both')
    assert not problems, problems
    assert entry['kind'] == 'pak' and entry['lua'] == 'BothMod' and entry['paks'] == ['TestHuts_P'], entry
    assert 'mods/BothMod/scripts/main.lua' in out and not any(k.startswith('mods/') and '.pak' in k for k in out), out

    # a map package holds only a map: IoStore containers of the map folders yes; the build table (any game asset
    # elsewhere), a .pak without its container, or a .pak holding files of its own, no
    g = install.Game(found[0])
    triple = ['ZZZ_MapOk_P' + e for e in modlib.PAK_EXTS]
    mapdir = container(tmp / 'map_ok', 'ZZZ_MapOk_P', {'Maps/Generated/Map_test_ok_real.uasset': mua,
                                                       'Maps/Generated/Map_test_ok_real.uexp': mue})
    g.only_a_map(dict(name='Ok', files=triple), mapdir)

    def not_a_map(files, folder, why):
        try:
            g.only_a_map(dict(name='Bad', files=files), folder)
            raise AssertionError('accepted: ' + why)
        except install.InstallError as e:
            assert 'not only a map' in str(e) and why in str(e), e
    bad = container(tmp / 'map_bad', 'ZZZ_MapBad_P', table)
    not_a_map(['ZZZ_MapBad_P' + e for e in modlib.PAK_EXTS], bad, 'DT_BuildingEconomy')
    not_a_map(['ZZZ_MapOk_P.pak'], mapdir, 'not a map container')
    (mapdir / 'ZZZ_MapOk_P.pak').write_bytes(with_files(mapdir / 'ZZZ_MapOk_P.pak', 1))
    not_a_map(triple, mapdir, 'not a map container')
finally:
    paths.resource, pm.ROOT = real_resource, real_root
    paths.remove_tree(work)                                 # (it holds hard links to the game's files)
    shutil.rmtree(tmp, ignore_errors=True)
print('package mod: all checks passed')

"""Self-check of the shared build menu and snow caps (skieo_creator/engine/shared_assets.py, modlib's STOCK_PAK) on the
game's own files; skipped without the game. Writes only to a temporary folder.
usage: python tests/test_shared_assets.py"""
import shutil
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from skieo_creator import install, modlib, paths  # noqa: E402
from skieo_creator.engine import shared_assets as sa  # noqa: E402

found = install.find_game()
if not found or not found[0]:
    print('shared assets: skipped (Ski-E-O not found)')
    sys.exit(0)
game = Path(found[0])
paks = game / 'SkiResortSimulator' / 'Content' / 'Paks'
work = Path(tempfile.mkdtemp(prefix='.skilift_test_', dir=game / 'SkiResortSimulator'))   # (hard links: same drive)
try:
    (work / 'a').mkdir()
    (work / 'b').mkdir()
    ua, ue, _ = install.extract_data_asset(paks, work / 'a', 'DT_BuildingEconomy', 'building list')
    rua, rue, _ = install.extract_data_asset(paks, work / 'b', sa.REGISTRY, 'snow cap list', sub='Data/SnowCaps')
    theirs = ('/Game/Mods/Their/BP_Hut', 'BP_Hut_C', '/Game/Mods/Their/DA_Cap_Hut')
    on = [m for m in modlib.MODS.values() if m['kind'] == 'pak'] + [dict(tables=['/Game/Mods/Their/DT_TheirRows'],
                                                                       snowcaps=[theirs])]
    parents, caps, _ = modlib._shared(on)
    assert parents[0] == '/Game/Data/DT_BuildingStock_0' and parents[-1] == '/Game/Mods/Their/DT_TheirRows'

    # the build menu: a composite over the game's table and every installed mod's, in order
    cua, cue = sa.make_composite(ua, parents)
    assert sa.composite_parents(cua, cue) == parents, sa.composite_parents(cua, cue)
    assert len(cue) == 4 + 4 + 4 * len(parents) + 12
    stock = sa.rename_asset(ua, '/Game/Data/DT_BuildingEconomy', '/Game/Data/' + modlib.STOCK_TABLE)
    assert b'DT_BuildingStock_0' in stock and len(stock) == len(ua)

    # the snow caps: the game's entries, then every installed mod's buildings (one each)
    keys0 = sa.snowcap_keys(rua, rue)
    nua, nue = sa.add_snowcaps(rua, rue, [tuple(c) for c in caps])
    keys = sa.snowcap_keys(nua, nue)
    assert keys[:len(keys0)] == keys0 and len(keys) == len(keys0) + len(caps), (len(keys0), len(caps), len(keys))
    assert keys[-1] == theirs[:2]
    assert sa.add_snowcaps(nua, nue, [tuple(c) for c in caps]) == (nua, nue), 'entries it has are not added twice'

    # the pak the game mounts above the mods
    (work / 'out').mkdir()
    modlib._build_stock(game, parents, caps, into=work / 'out')
    listing = install.run_retoc(['list', '--path', str(work / 'out' / (modlib.STOCK_PAK + '.utoc'))]).stdout
    for asset in ('Data/DT_BuildingEconomy.uasset', 'Data/DT_BuildingStock_0.uasset', 'Data/SnowCaps/DA_SnowCapRegistry.uasset'):
        assert asset in listing.replace(chr(92), '/'), (asset, listing[:500])
finally:
    paths.remove_tree(work)                                 # (it holds hard links to the game's files)
print('shared assets: all checks passed (%d parent tables, %d -> %d snow caps)' % (len(parents), len(keys0), len(keys)))

"""Offline checks of the map list entries (skieo_creator/install.py, builder.entry_spec): usage: python tests/test_install.py"""
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from skieo_creator import builder, install  # noqa: E402

# a custom map is never a tutorial map: New Game takes the first tutorial map of the list as THE tutorial map, whose
# "Skip Tutorial" starts it without its starting save (no real lifts and trails)
spec = builder.entry_spec(builder.Names('killingto_ddf8'), 'Killington', 'Northeast', {'PeakElevationFeet': 4241},
                          start_save=True)
assert ['bIsTutorialMap', 'remove'] in spec['set'] and not any(i[0] == 'bIsTutorialMap' and i[1] == 'hex' for i in spec['set'])
assert ['InitialSave', 'initial_save'] in spec['set'] and ['TutorialInitialSave', 'initial_save'] in spec['set']

# ... also maps packaged by 1.7.4 and older (their entries said bIsTutorialMap 01)
old = dict(spec, set=[i for i in spec['set'] if i[0] != 'bIsTutorialMap'] + [['bIsTutorialMap', 'hex', '01']])
fixed = install.custom_entry(old)
assert [i for i in fixed['set'] if i[0] == 'bIsTutorialMap'] == [['bIsTutorialMap', 'remove']], fixed['set']
assert ['DioramaVariantMap', 'ref', 'None', 'None'] in fixed['set'] and 'None' in fixed['add_names']
assert ['InitialSave', 'initial_save'] in fixed['set'], 'the starting save stays'
assert install.custom_entry(fixed)['set'].count(['bIsTutorialMap', 'remove']) == 1

# the map list of maps installed by an older version is rebuilt once
with tempfile.TemporaryDirectory() as tmp:
    g = install.Game(tmp)
    assert not g.registry_stale(), 'nothing installed'
    g.save_state({'format': 1, 'maps': {'mc_x': {'entry': old}}})
    assert g.registry_stale(), 'built by 1.7.4 or older'
    st = g.state()
    st['registry'] = install.REGISTRY_VERSION
    g.save_state(st)
    assert not g.registry_stale()
    assert json.loads(g.state_file.read_text(encoding='utf-8'))['registry'] == install.REGISTRY_VERSION
print('install: all checks passed')

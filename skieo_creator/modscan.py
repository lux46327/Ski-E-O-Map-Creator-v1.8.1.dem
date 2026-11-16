"""Looking inside IoStore paks with retoc: which packages a pak has, and what a mod's own copies of the build menu's
table and the snow cap list add. Used to package other modders' mods (packaging/package_mod.py), to keep mods the player
installed by hand in the app's merged build menu and snow caps (modlib), and to check that a map package holds only a
map (install). Reads paks; never writes into the game's files (the work folders are the caller's)."""
import os
import re
import shutil
import struct
from pathlib import Path

from . import install
from .engine import legacy_header as lh
from .engine import shared_assets as sa

ECONOMY = '/Game/Data/DT_BuildingEconomy'
STOCK_COPY = '/Game/Data/DT_BuildingStock_0'
REGISTRY = '/Game/Data/SnowCaps/' + sa.REGISTRY
LEVELS = '/Game/Data/DA_LevelRegistry'
SHARED = {ECONOMY, STOCK_COPY, REGISTRY, LEVELS}     # one owner each: the game's, or the app's merged one
# where a map package's own packages live (builder.Names; the Map Installer's packages take over levels the same way)
MAP_DIRS = ('/Game/Maps/', '/Game/Generated/', '/Game/InitialSaves/', '/Game/Materials/Terrain/', '/Game/Meshes/SnowShell/')


def package_path(p):
    """'../../../SkiResortSimulator/Content/Data/X.uasset' -> '/Game/Data/X' (plugins: '/<Plugin>/...')"""
    p = p.replace(chr(92), '/')
    m = re.search(r'SkiResortSimulator/Content/(.+)\.(?:uasset|umap)$', p)
    if m:
        return '/Game/' + m.group(1)
    m = re.search(r'/Plugins/(?:.*/)?([^/]+)/Content/(.+)\.(?:uasset|umap)$', p)
    return '/%s/%s' % (m.group(1), m.group(2)) if m else None


def assets(utoc):
    """the packages in an IoStore container (its .ucas must be beside it)"""
    out = set()
    for line in install.run_retoc(['list', '--path', str(utoc)]).stdout.splitlines():
        parts = line.split(None, 3)
        if len(parts) == 4 and parts[2] == 'ExportBundleData':
            p = package_path(parts[3].strip())
            if p:
                out.add(p)
    return out


_base = {}


def base_assets(paks):
    """the game's own packages (cached per game build)"""
    files = sorted(Path(paks).glob('SkiResortSimulator-*.utoc'))
    key = tuple((f.name, f.stat().st_size, f.stat().st_mtime_ns) for f in files)
    if key not in _base:
        _base.clear()
        _base[key] = set().union(*(assets(f) for f in files)) if files else set()
    return _base[key]


def _put(f, dst):
    """f at dst: a hard link where it can be (same drive), else a copy; never writes into an existing file"""
    if dst.exists():
        return
    try:
        os.link(f, dst)
    except OSError:
        shutil.copy2(f, dst)


def extract(paks, files, work, names, also=()):
    """Content/ of the legacy copies of the packages `names` (short names) that the container `files` (its
    .pak/.ucas/.utoc) has, read with the game's global container and the containers `also` (files of other paks whose
    packages it refers to, so retoc can name them; they mustn't have `names` themselves). The mod's files go in first
    and the game's only to names still free, and nothing is written into a file once there, so nothing is ever
    written through a link into the game or a mod."""
    src = Path(work) / 'in'
    src.mkdir(parents=True)
    for f in list(files) + list(also):
        _put(Path(f), src / Path(f).name)
    for f in Path(paks).iterdir():
        if f.name.lower().startswith('global.') and f.suffix.lower() in ('.utoc', '.ucas'):
            _put(f, src / f.name)
    out = Path(work) / 'out'
    install.run_retoc(['to-legacy', '--no-shaders'] + [x for n in names for x in ('--filter', n)] + [str(src), str(out)])
    return out / 'SkiResortSimulator' / 'Content'


def read(content, path):
    """(uasset, uexp) of a /Game/... package from an extract() result"""
    rel = path[len('/Game/'):]
    return (content / (rel + '.uasset')).read_bytes(), (content / (rel + '.uexp')).read_bytes()


def _by_name(path, name, known):
    """a package retoc couldn't name (in a container it didn't read): the one of `known` with that name, if one is"""
    if path and not path.startswith('/Engine/'):
        return path
    hits = sorted(a for a in known if a.rsplit('/', 1)[1] == name)
    return hits[0] if len(hits) == 1 else None


def building_table(ua, ue, known=()):
    """a mod's DT_BuildingEconomy: ('composite', its parent tables, those found by name among `known` packages when
    they're in another pak) or ('full', None) for a whole table of rows"""
    if 'CompositeDataTable' in lh.parse(ua)[1]:
        if ue[:4] != b'\x00\x02\x01\x03':                   # the layout make_composite writes (and the editor cooks)
            raise ValueError('a composite build table of a layout this app does not read')
        found = [_by_name(p, n, known) for p, n in sa.composite_parent_objects(ua, ue)]
        return 'composite', [p for p in found if p]
    return 'full', None


def pak_files(path):
    """how many files a .pak holds outside the IoStore container beside it (retoc's and the editor's .pak beside a
    container hold none: a 347-byte index); None if it can't be read (not a pak, or its index encrypted)"""
    with open(path, 'rb') as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - 1024))
        tail = f.read()
        i = tail.rfind(struct.pack('<I', 0x5A6F12E1))       # the footer's magic
        if i < 1 or tail[i - 1] or i + 24 > len(tail):      # (byte before: the index is encrypted)
            return None
        off, length = struct.unpack_from('<qq', tail, i + 8)
        if not (0 <= off and off + length <= size and length >= 8):
            return None
        f.seek(off)
        idx = f.read(min(length, 4096))
    n = struct.unpack_from('<i', idx, 0)[0]                 # the mount point (FString), then the file count
    at = 4 + (n if n >= 0 else -2 * n)
    return struct.unpack_from('<i', idx, at)[0] if at + 4 <= len(idx) else None


def new_snowcaps(rua, rue, stock_keys, have, base):
    """the entries of a mod's snow cap list that the game's lacks: ([(class package, class name, data asset)], [class
    names left out: their data asset is in neither the mod nor the game])"""
    caps, lost = [], []
    for kp, kc, dp, dn in sa.snowcap_entries(rua, rue):
        if (kp, kc) in stock_keys:
            continue
        if not dp or dp.startswith('/Engine/'):             # retoc names only packages in the paks it read
            hits = sorted(a for a in have | base if a.rsplit('/', 1)[1] == dn)
            dp = hits[0] if len(hits) == 1 else None
        if dp:
            caps.append((kp, kc, dp))
        else:
            lost.append(kc)
    return caps, lost


def not_a_map(have, base):
    """packages a map package must not have: the shared ones, and the game's own outside the map folders"""
    return sorted(p for p in have if p in SHARED or (p in base and not p.startswith(MAP_DIRS)))

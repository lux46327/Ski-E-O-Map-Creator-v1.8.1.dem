"""Game assets that only one pak can own, merged for all installed mods (modlib.refresh): the build menu's table
/Game/Data/DT_BuildingEconomy and the snow cap list /Game/Data/SnowCaps/DA_SnowCapRegistry. Both are made from the
player's own copy of the game's asset, so a game update's new buildings stay in.

- make_composite: DT_BuildingEconomy as a CompositeDataTable over parent tables. The game's table, renamed in place to
  STOCK_TABLE, comes first, then each mod's own table of new rows; a parent later in the list replaces an earlier one's
  row of the same name. The cooked layout was learned from a UE 5.8 sample (lift-models/game/dt_modular.py, where the
  lift packs' copy comes from). UCompositeDataTable properties come first in the unversioned schema: fragments 00 02 /
  01 03 = ParentTables (array of import refs), skip 1, RowStruct; then the object guid flag and an empty row map. The
  export lists RowStruct and the parents as serialize-before-serialize dependencies, and class and template as
  serialize-before-create.
- add_snowcaps: DA_SnowCapRegistry (a TMap of soft placeable class -> USnowCapData, hard values) with extra entries
  appended (lift-models/game/build_liftmod.py snowcap_registry)."""
import struct

from . import legacy_header as lh

CP, EN = '/Script/CoreUObject', '/Script/Engine'


def rename_asset(ua, old_path, new_path):
    """an equal-length rename of an asset (package path and object name), e.g. the game's table -> STOCK_TABLE"""
    old, new = old_path.rsplit('/', 1)[1], new_path.rsplit('/', 1)[1]
    assert len(old) == len(new) and len(old_path) == len(new_path), (old_path, new_path)
    ua, _, _ = lh.edit(ua, rename={old_path: new_path, old: new})
    return lh.rename_package_string(ua, old_path, new_path)


def _exports(ua, f):
    off, cnt = f['exports_offset'][1], f['exports_count'][1]
    nxt = f['cell_imports_offset'][1] if f['cell_imports_offset'][1] > 0 else f['depends_offset'][1]
    return off, cnt, (nxt - off) // cnt


def _set_preload(ua, deps):
    """replace the (single export's) preload dependency list"""
    f = lh.parse(ua)[0]
    pos, old = f['preload_offset'][1], f['preload_count'][1]
    body = struct.pack('<%di' % len(deps), *deps)
    delta = len(body) - 4 * old
    out = bytearray(ua[:pos] + body + ua[pos + 4 * old:])
    struct.pack_into('<i', out, f['preload_count'][0], len(deps))
    struct.pack_into('<i', out, f['total_header_size'][0], f['total_header_size'][1] + delta)
    struct.pack_into('<q', out, f['bulk_data_start'][0], f['bulk_data_start'][1] + delta)
    eo, n_exp, st = _exports(ua, f)
    for i in range(n_exp):
        p = eo + i * st + 36
        struct.pack_into('<q', out, p, struct.unpack_from('<q', out, p)[0] + delta)
    return bytes(out)


def make_composite(stock_ua, parents):
    """(uasset, uexp) of a composite table with the stock table's package and name over `parents` (package paths of
    DataTables with the same row struct, in order)"""
    names0 = lh.parse(stock_ua)[1]
    add = ['CompositeDataTable', 'Default__CompositeDataTable']
    for p in parents:
        add += [p, p.rsplit('/', 1)[1]]
    ua, _, names = lh.edit(stock_ua, add=[n for n in dict.fromkeys(add) if n not in names0])
    idx = {n: i for i, n in enumerate(names)}
    f = lh.parse(ua)[0]
    if f['imports_count'][1] != 5:                          # stock: -1 class DataTable ... -3 Engine, -5 row struct
        raise ValueError('the game\'s building table has changed (%d imports)' % f['imports_count'][1])
    ents = [(idx[CP], 0, idx['Class'], 0, -3, idx['CompositeDataTable'], 0, 0),                     # import 5 (-6)
            (idx[EN], 0, idx['CompositeDataTable'], 0, -3, idx['Default__CompositeDataTable'], 0, 0)]  # import 6 (-7)
    for k, p in enumerate(parents):
        pkg = 7 + 2 * k
        ents.append((idx[CP], 0, idx['Package'], 0, 0, idx[p], 0, 0))
        ents.append((idx[EN], 0, idx['DataTable'], 0, -(pkg + 1), idx[p.rsplit('/', 1)[1]], 0, 0))
    ua, first = lh.add_imports(ua, ents)
    assert first == 5
    refs = [-(7 + 2 * k + 2) for k in range(len(parents))]          # the object import of parent k
    eo = lh.parse(ua)[0]['exports_offset'][1]
    ua = bytearray(ua)
    struct.pack_into('<i', ua, eo + 0, -6)                  # class -> CompositeDataTable
    struct.pack_into('<i', ua, eo + 8, -7)                  # template -> Default__CompositeDataTable
    struct.pack_into('<5i', ua, eo + 76, 0, 1 + len(parents), 0, 2, 0)    # first dep, SBS, CBS, SBC, CBC
    ua = _set_preload(bytes(ua), [-5] + refs + [-6, -7])
    ue = struct.pack('<HHi', 0x0200, 0x0301, len(parents)) + struct.pack('<%di' % len(parents), *refs) + \
        struct.pack('<iii', -5, 0, 0)                       # ParentTables, RowStruct, guid flag, NumRows
    return lh.set_export_size(ua, len(ue)), ue


def _name(names, index, number):
    """an FName: 'X_5' is stored as 'X' with number 6 (cooked packages split trailing numbers off)"""
    return names[index] + ('_%d' % (number - 1) if number else '')


def composite_parent_objects(ua, ue):
    """the parent tables of a composite (00 02 01 03 layout, as make_composite writes it): [(package path, table
    name)]; a package retoc could not name (not in the containers it read) is /Engine/UnknownPackage"""
    f, names, _, _ = lh.parse(ua)
    io = f['imports_offset'][1]
    n = struct.unpack_from('<i', ue, 4)[0]
    out = []
    for r in struct.unpack_from('<%di' % n, ue, 8):
        obj = struct.unpack_from('<8i', ua, io + (-r - 1) * 32)
        pkg = struct.unpack_from('<8i', ua, io + (-obj[4] - 1) * 32)
        out.append((_name(names, pkg[5], pkg[6]), _name(names, obj[5], obj[6])))
    return out


def composite_parents(ua, ue):
    """the parent tables' package paths of a composite"""
    return [p for p, _ in composite_parent_objects(ua, ue)]


def _replace_export(ua, ue, export_name, fn):
    """rewrite one export's serialized data through fn(bytes) -> bytes, fixing the sizes and offsets after it"""
    f, names, _, _ = lh.parse(ua)
    off, cnt, st = _exports(ua, f)
    hdr = len(ua)
    out = bytearray(ua)
    ents = []
    for i in range(cnt):
        p = off + i * st
        ni, nn = struct.unpack_from('<ii', ua, p + 16)
        sz, so = struct.unpack_from('<qq', ua, p + 28)
        ents.append((p, names[ni] + ('_%d' % (nn - 1) if nn else ''), sz, so))
    tgt = [e for e in ents if e[1] == export_name]
    assert len(tgt) == 1, export_name
    p, _, sz, so = tgt[0]
    old = ue[so - hdr:so - hdr + sz]
    new = fn(old)
    delta = len(new) - len(old)
    struct.pack_into('<q', out, p + 28, len(new))
    for q, _, _, so2 in ents:
        if so2 > so:
            struct.pack_into('<q', out, q + 36, so2 + delta)
    pos, val, _ = f['bulk_data_start']
    struct.pack_into('<q', out, pos, val + delta)
    return bytes(out), ue[:so - hdr] + new + ue[so - hdr + sz:]


def _insert_preload(ua, exp_i, group, entries):
    """add FPackageIndex entries to dependency group `group` (0 serialize-before-serialize, 1 create-before-serialize,
    2 serialize-before-create, 3 create-before-create) of export exp_i; shifts the header behind the preload array"""
    f, _, _, _ = lh.parse(ua)
    eo, ec, st = _exports(ua, f)
    po, pc = f['preload_offset'][1], f['preload_count'][1]
    p = eo + exp_i * st
    first = struct.unpack_from('<i', ua, p + 76)[0]
    counts = list(struct.unpack_from('<4i', ua, p + 80))
    at = first + sum(counts[:group + 1])
    ins = po + at * 4
    body = b''.join(struct.pack('<i', e) for e in entries)
    out = bytearray(ua[:ins] + body + ua[ins:])
    counts[group] += len(entries)
    struct.pack_into('<4i', out, p + 80, *counts)
    for i in range(ec):
        q = eo + i * st
        fi = struct.unpack_from('<i', out, q + 76)[0]
        if i != exp_i and fi >= at:
            struct.pack_into('<i', out, q + 76, fi + len(entries))

    def put(name, value):
        pos, _, kind = f[name]
        struct.pack_into('<q' if kind == 'i64' else '<i', out, pos, value)
    put('preload_count', pc + len(entries))
    for n in ('softobj_offset', 'exports_offset', 'imports_offset', 'cell_exports_offset', 'cell_imports_offset',
              'depends_offset', 'asset_registry_offset', 'preload_offset', 'data_resource_offset'):
        v = f[n][1]
        if v > 0 and v > ins:
            put(n, v + len(body))
    put('total_header_size', f['total_header_size'][1] + len(body))
    put('bulk_data_start', f['bulk_data_start'][1] + len(body))
    for i in range(ec):
        q = eo + i * st + 36
        struct.pack_into('<q', out, q, struct.unpack_from('<q', out, q)[0] + len(body))
    return bytes(out)


REGISTRY = 'DA_SnowCapRegistry'


def snowcap_entries(ua, ue):
    """the registry's entries as (class package, class name, data asset package, data asset name); its one export's
    data opens the .uexp. A package retoc could not name (not in the containers it read) is /Engine/UnknownPackage."""
    f, names, _, _ = lh.parse(ua)
    io = f['imports_offset'][1]
    assert ue[:2] == b'\x00\x03', ue[:2].hex()
    out = []
    for k in range(struct.unpack_from('<i', ue, 6)[0]):
        a, an, c, cn, _, ref = struct.unpack_from('<6i', ue, 10 + 24 * k)
        dp = dn = None
        if ref < 0:                                         # the data asset object's import -> its package's
            obj = struct.unpack_from('<8i', ua, io + (-ref - 1) * 32)
            dn = _name(names, obj[5], obj[6])
            if obj[4] < 0:
                pkg = struct.unpack_from('<8i', ua, io + (-obj[4] - 1) * 32)
                dp = _name(names, pkg[5], pkg[6])
        out.append((_name(names, a, an), _name(names, c, cn), dp, dn))
    return out


def snowcap_keys(ua, ue):
    """the registry's entries as (class package, class name)"""
    return [e[:2] for e in snowcap_entries(ua, ue)]


def add_snowcaps(ua, ue, entries):
    """DA_SnowCapRegistry with extra entries [(class package, class name, data asset package)], e.g.
    ('/Game/Blueprints/Buildings/BP_X', 'BP_X_C', '/Game/Data/SnowCaps/DA_SnowCap_BP_X'); classes it has are skipped"""
    have = set(snowcap_keys(ua, ue))
    entries = [e for e in dict.fromkeys(entries) if (e[0], e[1]) not in have]
    if not entries:
        return ua, ue
    names0 = lh.parse(ua)[1]
    want = [x for kp, kc, dp in entries for x in (kp, kc, dp, dp.rsplit('/', 1)[1])]
    ua, _, names = lh.edit(ua, add=[n for n in dict.fromkeys(want) if n not in names0])
    n0 = lh.parse(ua)[0]['imports_count'][1]
    ix = names.index
    imps = []
    for k, (_, _, dp) in enumerate(entries):
        imps.append((ix(CP), 0, ix('Package'), 0, 0, ix(dp), 0, 0))
        imps.append((ix('/Script/SkiResortSimulator'), 0, ix('SnowCapData'), 0, -(n0 + 2 * k + 1), ix(dp.rsplit('/', 1)[1]), 0, 0))
    ua, first = lh.add_imports(ua, imps)
    assert first == n0
    refs = [-(n0 + 2 * k + 1) - 1 for k in range(len(entries))]    # the data asset's object import

    def add_map(d):
        assert d[:2] == b'\x00\x03', d[:2].hex()
        n = struct.unpack_from('<i', d, 6)[0]
        assert len(d) == 10 + 24 * n + 4, (len(d), n)
        body = b''.join(struct.pack('<5i', ix(kp), 0, ix(kc), 0, 0) + struct.pack('<i', r)
                        for (kp, kc, _), r in zip(entries, refs))
        return d[:6] + struct.pack('<i', n + len(refs)) + d[10:10 + 24 * n] + body + d[10 + 24 * n:]
    ua, ue = _replace_export(ua, ue, REGISTRY, add_map)
    return _insert_preload(ua, 0, 1, refs), ue

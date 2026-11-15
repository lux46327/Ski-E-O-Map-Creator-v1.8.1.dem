"""Real trails and lifts from OpenStreetMap, built into a map's starting save.

OpenStreetMap maps ski resorts as aerialway ways (chair lifts, gondolas, cable cars, drag lifts, with
aerialway:occupancy / aerialway:detachable) and piste ways and areas (piste:type=downhill, piste:difficulty,
piste:name). This module fetches them for the map's square (Overpass API) and turns them into the game's own save
records, so a new game on the map starts with the real resort already built:

  lifts   -> LiftSaveData: the closest stock lift (a detachable six -> High-Speed Six, a fixed quad -> fixed quad,
             a gondola -> Gondola, a cable car -> Aerial Tram; drag lifts, which the game doesn't have, -> fixed
             chairs), straight from the bottom station to the top, towers spaced and sized like the game places them,
             a queue line, hubs shared by terminals close together (and with the ticket office)
  trails  -> TrailInfo: named, with the player-rated difficulty from piste:difficulty, as the game's own chain of
             quadratic curves (~100 m each) along the piste; piste areas become bowls
  trees   -> none on the trails or under the lifts (clear_mask() for the forest), and the game's cleared zones in the
             save, as the game writes them when a trail or lift is built
  glades  -> left out (the game has no tree skiing: a glade would become a bare clearing): pistes tagged or named as
             glades, and runs that go through the trees with no cleared corridor in the satellite canopy heights
             (canopy.py), checked along the best smooth path near the OSM line, as it is often drawn a little off
The rules (tower spacing, bowl centre and radius, zones, hours) were read off saves the game wrote. The record layouts
come from data/resort_templates.bin (packaging/make_resort_templates.py): the game's starting save has no lift or trail.
"""
import hashlib
import io
import json
import logging
import math
import re
import struct
import time
import urllib.parse
from collections import Counter, defaultdict

import numpy as np
from PIL import Image, ImageDraw

from . import canopy as chm
from . import geo, net, paths
from .engine import gvas_tree as G

log = logging.getLogger(__name__)

OVERPASS = ('https://overpass-api.de/api/interpreter', 'https://overpass.private.coffee/api/interpreter',
            'https://maps.mail.ru/osm/tools/overpass/api/interpreter')
# public servers that hold one region only (no key, 4 queries at a time per address): used for areas inside it, since they
# would answer an area outside it with an empty result. (name, south, west, north, east, endpoint)
OVERPASS_REGIONAL = (('Europe', 33.0, -25.0, 72.0, 45.0, 'https://ovp.dresel.systems/api/interpreter'),
                     ('North America', 5.0, -170.0, 84.0, -50.0, 'https://ovp.dresel.systems/api-na/interpreter'))


def _servers(box):
    """the Overpass servers to ask for this box (s, w, n, e), in the order to try: the one that answered last, the regional one that
    covers the whole box, then the global ones"""
    s, w, n, e = box
    out = [u for _, s0, w0, n0, e0, u in OVERPASS_REGIONAL if s0 <= s and n <= n0 and w0 <= w and e <= e0] + list(OVERPASS)
    if _GOOD[0] in out:
        out.remove(_GOOD[0])
        out.insert(0, _GOOD[0])
    return out
QUERY = """[out:json][timeout:120];
(
  way["piste:type"="downhill"]({s},{w},{n},{e});
  relation["piste:type"="downhill"]({s},{w},{n},{e});
  way["aerialway"]({s},{w},{n},{e});
  node["aerialway"="station"]({s},{w},{n},{e});
);
out body;
>;
out skel qt;"""
CACHE = paths.APP_DIR / 'cache' / 'osm'
CACHE_DAYS = 7
_GOOD = [None]                                  # the Overpass server that answered last: asked first

# the game's stock lifts (DT_BuildingEconomy row): blueprint, name (as in the build menu), build cost, daily operating
# cost, tower spacing (m), tower height range (cm), tree clearing radius (cm)
LIFTS = {
    'OnePersonFixed': ('/Game/Blueprints/Lifts/BP_FixedChair1', '1-Person Fixed Grip', 12500, 60, 50, 1350, 3000, 1223),
    'TwoPersonFixed': ('/Game/Blueprints/Lifts/BP_FixedChair2', '2-Person Fixed Grip', 39000, 195, 50, 1100, 3000, 1250),
    'FourPersonFixed': ('/Game/Blueprints/Lifts/BP_FixedChair4', '4-Person Fixed Grip', 118000, 590, 50, 1150, 3000, 1300),
    'HighSpeedQuad': ('/Game/Blueprints/Lifts/BP_HighSpeedQuad', 'High-Speed Quad', 381000, 1905, 50, 1300, 3039, 1300),
    'HighSpeedSix': ('/Game/Blueprints/Lifts/BP_HighSpeedSix', 'High-Speed Six', 1202000, 6000, 50, 1100, 3039, 1400),
    'Gondola': ('/Game/Blueprints/Lifts/BP_Gondola', 'Gondola', 4024000, 20100, 50, 2150, 3039, 1500),
    'AerialTram': ('/Game/Blueprints/Lifts/BP_AerialTram', 'Aerial Tram', 14199000, 71000, 240, 4451, 4451, 1600),
}
SURFACE = {'t-bar': 'TwoPersonFixed', 'j-bar': 'OnePersonFixed', 'platter': 'OnePersonFixed',
           'drag_lift': 'OnePersonFixed', 'rope_tow': 'OnePersonFixed', 'magic_carpet': 'OnePersonFixed'}
KIND_NAME = {'chair_lift': 'Chair', 'gondola': 'Gondola', 'cable_car': 'Tram', 'mixed_lift': 'Chondola',
             't-bar': 'T-Bar', 'j-bar': 'J-Bar', 'platter': 'Platter', 'drag_lift': 'Surface Lift',
             'rope_tow': 'Rope Tow', 'magic_carpet': 'Carpet'}
DIFFICULTY = {'novice': 'Beginner', 'easy': 'Beginner', 'intermediate': 'Intermediate', 'advanced': 'Expert',
              'expert': 'Pro', 'extreme': 'Pro', 'freeride': 'Pro'}
RUN_NAME = {'Beginner': 'Green Run', 'Intermediate': 'Blue Run', 'Expert': 'Black Run', 'Pro': 'Double Black'}
WIDTH_M = {'Beginner': 40.0, 'Intermediate': 36.0, 'Expert': 30.0, 'Pro': 26.0}
EXPRESS = re.compile(r'express|high[ -]?speed|\bhs[q6]?\b|detach|bubble', re.I)

MIN_LIFT_M = 60.0                               # shorter lifts (most magic carpets) are left out
MAX_LIFT_M = 7500.0
EDGE_M = 60.0                                   # lift stations must be this far inside the square
CURVE_M = 100.0                                 # trail curve length (the game's are 20-850 m, half 80-150 m)
# ...shorter round bends: one quadratic curve can't follow more turning than this (or an S-bend), and a curve laid
# over a hairpin overshot it and folded back (the game drew loops and stray dashes, e.g. Vail's roads)
CURVE_TURN = 50.0                               # degrees of turning in one curve at most...
CURVE_MIN_M = 12.0                              # ...unless that makes it shorter than this
CURVE_STEP_M = 5.0                              # the line is followed this finely to find its bends
MIN_WIDTH_M = 8.0                               # a trail narrows to fit a bend tighter than half its width (else the
WIDTH_GROW_M = 10.0                             # game draws its edges folded), not below this, widening back by at
                                                # most this much per curve
MIN_TRAIL_M = 120.0
MIN_UNNAMED_M = 350.0
DUP_M = 20.0                                    # a stretch of a run this close to a longer run of the same name...
DUP_LEN_M = 100.0                               # ...for this long is the same run drawn twice (shorter: branches meeting)
TWICE = 'the same run drawn twice'
STATION_M = 120.0                               # an OSM station this close to a terminal names its hub
HUB_M = 150.0                                   # terminals this close share a hub (the game: 106 m and 110 m seen)
OFFICE_HUB_M = 200.0                            # ... and with the ticket office (184 m seen)
OPEN_HOURS = (9.0, 21.0)                        # what the current game version gives new lifts
# glades. The satellite thresholds were set on Stratton, Vail, Beaver Creek and Breckenridge against their gladed=yes
# runs and close-up looks at the imagery: the tree runs found are 0.32-0.90 under trees; cleared runs, even narrow or
# drawn 15 m off, stay under 0.25 (green runs and roads are left alone: there, crowns over a narrow track read as trees)
GLADE_NAME = re.compile(r'\bglade[sd]?\b|\bsous[- ]bois\b', re.I)
GLADE = 'tree-skiing glade'
TREE_M = 5                                      # canopy at least this tall (m) is trees
GLADE_STEP = 5.0                                # along the line (m)
GLADE_OFFSETS = np.arange(-15.0, 15.01, 2.5)    # how far beside its OSM line a cleared run is looked for (m)
GLADE_SHARE = 0.3                               # a run under trees for this share of its best path is a glade
GLADE_COVER = 0.35                              # a piste area with this share of tree canopy is a glade
# the forest round the resort follows the real tree cover (satellite canopy heights): open bowls, meadows and old burns
# stay open and glades keep their own sparse trees, where the generated forest fills everything below the treeline
# (Vail's back bowls are in OSM as runs only, so they came out as narrow trails through a full forest)
COVER_BUF_M = 300.0                             # the real cover this far round the runs, glades and lifts...
COVER_FEATHER_M = 150.0                         # ...blending into the generated forest over this far beyond
COVER_STEP_M = 5.0                              # canopy samples about this far apart
COVER_WIN_M = 25.0                              # tree cover measured over about this window
COVER_TREE_M = 3.0                              # canopy this tall is a tree crown
COVER_FULL = 0.5                                # this share of the ground under crowns is full forest
COVER_ROWS = 128                                # grid rows per canopy call (memory)
COVER_NODATA = 255                              # canopy height meaning "no data" (canopy.heights(nodata=...)): there
                                                # the generated forest stays, never "no trees"


class ResortError(Exception):
    pass


# ---------------------------------------------------------------- fetching

def _bbox(lat, lon, size_m, margin=1.03, rot=0.0):
    g = geo.LocalGrid(lat, lon, rot)
    h = size_m / 2.0 * margin
    la, lo = g.to_latlon(np.array([-h, h, h, -h]), np.array([h, h, -h, -h]))
    return float(la.min()), float(lo.min()), float(la.max()), float(lo.max())


def _complete(raw):
    """raw if it is a whole Overpass answer; a timed-out or out-of-memory query still answers 200 with what it had so
    far and says so in 'remark'"""
    d = json.loads(raw)
    remark = str(d.get('remark') or '')
    if 'elements' not in d or re.search(r'error|timed out|out of memory', remark, re.I):
        raise ValueError(remark[:160] or 'no elements in the answer')
    return raw


def fetch(lat, lon, size_m, cancel=net.NEVER, progress=lambda f, t: None, rot=0.0):
    """raw Overpass JSON (bytes) for the map square, cached CACHE_DAYS days. Overpass answers boxes; a turned square is asked
    for as the one box round its corners (the polygon filter and several smaller boxes were tried: the servers refuse or time out)."""
    s, w, n, e = _bbox(lat, lon, size_m, rot=rot)
    turned = bool(rot) and abs(rot) > 0.05
    f = CACHE / ('%.5f_%.5f_%.5f_%.5f%s.json' % (s, w, n, e, ('_r%.1f_%.5f_%.5f' % (rot, lat, lon)) if turned else ''))
    if f.is_file() and time.time() - f.stat().st_mtime < CACHE_DAYS * 86400:
        try:
            return _complete(f.read_bytes())
        except (OSError, ValueError):
            pass
    progress(0.1, 'Downloading the trails and lifts from OpenStreetMap...')

    def ask(box):
        """one box -> raw answer: from the box cache, else from the servers (the one that answered last first, then the others,
        twice round before giving up). A box that was downloaded stays cached, so a failed run does not repeat it."""
        bf = CACHE / ('box_%.5f_%.5f_%.5f_%.5f.json' % box)
        if bf.is_file() and time.time() - bf.stat().st_mtime < CACHE_DAYS * 86400:
            try:
                return _complete(bf.read_bytes())
            except (OSError, ValueError):
                pass
        q = urllib.parse.quote(QUERY.format(s=box[0], w=box[1], n=box[2], e=box[3]))
        last = None
        order = _servers(box)
        for rnd in range(2):
            for k, url in enumerate(order):
                try:
                    raw = _complete(net.get(url + '?data=' + q, timeout=150 if k == 0 else 60, retries=1, cancel=cancel,
                                            accept='application/json'))
                    log.info('Overpass %s: %d bytes, %d elements', url, len(raw), len(json.loads(raw).get('elements', [])))
                    _GOOD[0] = url
                    try:
                        paths.atomic_write(bf, raw)
                    except OSError:
                        pass
                    return raw
                except (net.NetError, ValueError) as ex:
                    last = ex
                    log.warning('Overpass %s failed: %s', url, ex)
        raise ResortError('The OpenStreetMap servers didn\'t answer right now (%s). They are often busy: try again in a '
                          'few minutes.' % str(last).split(' Check your')[0].rstrip('.'))

    raw = ask((s, w, n, e))              # one box, also for a turned square (the box round its corners)
    paths.atomic_write(f, raw)
    return raw


# ---------------------------------------------------------------- reading OSM

def _num(v):
    m = re.match(r'\s*(\d+(?:\.\d+)?)', str(v or ''))
    return float(m.group(1)) if m else None


def _clean(s):
    return re.sub(r'\s+', ' ', s).strip() if s else None


def lift_row(t, europe):
    """OSM aerialway tags -> (game lift row, what the real lift is) or (None, why it is left out)"""
    kind = t.get('aerialway', '')
    if t.get('disused') == 'yes' or t.get('abandoned') == 'yes' or kind in ('construction', 'proposed', 'disused'):
        return None, 'not running'
    occs = [_num(x) for x in str(t.get('aerialway:occupancy', '')).split(';')]
    occs = [v for v in occs if v]
    occ = int(max(occs)) if occs else None
    cap = _num(t.get('aerialway:capacity'))
    if kind == 'cable_car':
        return 'AerialTram', 'cable car'
    if kind == 'gondola':
        return ('AerialTram', '%d-person cabins' % occ) if occ and occ >= 20 else ('Gondola', 'gondola')
    if kind == 'mixed_lift':
        return 'HighSpeedSix', 'chairs and cabins'
    if kind in SURFACE:
        return SURFACE[kind], kind.replace('_', ' ')
    if kind != 'chair_lift':
        return None, 'aerialway=%s' % (kind or '?')
    det = t.get('aerialway:detachable')
    name = ' '.join(t.get(k, '') for k in ('name', 'name:en', 'description'))
    if det in ('yes', 'no'):
        detachable = det == 'yes'
    elif EXPRESS.search(name) or t.get('aerialway:bubble') == 'yes' or t.get('aerialway:heating') == 'yes':
        detachable = True
    elif occ is not None and occ >= 6:
        detachable = True
    elif occ in (None, 4) and cap:
        detachable = cap >= 2200
    else:
        detachable = occ == 4 and europe            # European quads are mostly detachable, North American ones often not
    if occ is None:
        occ = (6 if cap and cap >= 3000 else 4) if detachable else \
            (2 if not cap else 1 if cap < 700 else 2 if cap < 1300 else 3 if cap < 1700 else 4)
    if occ <= 1:
        return 'OnePersonFixed', 'single chair'
    if occ == 2:
        return 'TwoPersonFixed', 'double chair'
    if occ == 3:
        return ('HighSpeedQuad', 'detachable triple') if detachable else ('FourPersonFixed', 'triple chair')
    if occ == 4:
        return ('HighSpeedQuad', 'detachable quad') if detachable else ('FourPersonFixed', 'fixed quad')
    return 'HighSpeedSix', '%d-seat chair' % occ


def read(osm):
    nodes, ways, rels = {}, {}, []
    for el in osm.get('elements', ()):                   # 'out skel' copies (no tags) never replace the tagged ones
        if el['type'] == 'node':
            if el['id'] not in nodes or el.get('tags'):
                nodes[el['id']] = (el['lat'], el['lon'], el.get('tags', {}))
        elif el['type'] == 'way':
            if el['id'] not in ways or el.get('tags'):
                ways[el['id']] = (el.get('nodes', []), el.get('tags', {}))
        elif el['type'] == 'relation':
            rels.append(el)
    return nodes, ways, rels


# ---------------------------------------------------------------- terrain

class Terrain:
    """the map's heightmap; positions in metres from its top-left corner (x right, y down; with a turned area the top is not north), like trees.plant"""

    def __init__(self, H, fr, lat, lon, size_m, rot=0.0):
        self.H = np.asarray(H, np.float64)
        self.sp, self.sc, self.half, self.size = fr.sp, fr.sc, fr.half, size_m
        self.grid = geo.LocalGrid(lat, lon, rot)
        self.n = self.H.shape[0]

    def xy(self, lat, lon):
        e, n = self.grid.to_xy(np.asarray(lat, np.float64), np.asarray(lon, np.float64))
        return np.asarray(e) + self.half, self.half - np.asarray(n)

    def latlon(self, x, y):
        return self.grid.to_latlon(np.asarray(x, np.float64) - self.half, self.half - np.asarray(y, np.float64))

    def z(self, x, y):
        """ground height in world cm at corner metres x, y (bilinear)"""
        c = np.clip(np.asarray(x, np.float64) / self.sp, 0, self.n - 1.001)
        r = np.clip(np.asarray(y, np.float64) / self.sp, 0, self.n - 1.001)
        c0, r0 = np.floor(c).astype(int), np.floor(r).astype(int)
        fc, fr = c - c0, r - r0
        H = self.H
        h = (H[r0, c0] * (1 - fc) * (1 - fr) + H[r0, c0 + 1] * fc * (1 - fr) + H[r0 + 1, c0] * (1 - fc) * fr +
             H[r0 + 1, c0 + 1] * fc * fr)
        return (h + 32768.0) * self.sc * 100.0

    def world(self, x, y, z=None):
        return dict(X=(float(x) - self.half) * 100.0, Y=(float(y) - self.half) * 100.0,
                    Z=float(self.z(x, y) if z is None else z))

    def inside(self, x, y, margin):
        return margin <= x <= self.size - margin and margin <= y <= self.size - margin


# ---------------------------------------------------------------- geometry helpers

def _cum(P):
    return np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(P, axis=0).T))])


def _length(P):
    return float(_cum(P)[-1]) if len(P) > 1 else 0.0


def _resample(P, step):
    """points every ~step metres along the polyline P (n x 2), both ends kept"""
    d = _cum(P)
    k = max(1, int(round(d[-1] / step)))
    t = np.linspace(0, d[-1], k + 1)
    return np.column_stack([np.interp(t, d, P[:, 0]), np.interp(t, d, P[:, 1])])


def _at(P, frac):
    d = _cum(P)
    return np.array([np.interp(frac * d[-1], d, P[:, 0]), np.interp(frac * d[-1], d, P[:, 1])])


def _inside_runs(P, terrain, margin):
    """the parts of P (resampled at 10 m) inside the square"""
    Q = _resample(P, 10.0)
    runs, cur = [], []
    for q in Q:
        if terrain.inside(q[0], q[1], margin):
            cur.append(q)
        elif cur:
            runs.append(np.array(cur))
            cur = []
    if cur:
        runs.append(np.array(cur))
    return [r for r in runs if len(r) > 1]


def _bezier(p0, c, p2, step_cm):
    """points along a quadratic curve (world dicts) every ~step_cm: k x 2 array of X, Y"""
    a, b, e = (np.array([p['X'], p['Y']]) for p in (p0, c, p2))
    k = max(1, math.ceil(math.hypot(*(e - a)) / step_cm))
    t = np.linspace(0, 1, k + 1)[:, None]
    return (1 - t) ** 2 * a + 2 * (1 - t) * t * b + t * t * e


# ---------------------------------------------------------------- planning

def upkeep(l):
    """what the game charges for the lift every night, open or not: its daily operating cost x (towers + 4) / 8 (read
    off the game's ledger for 19 lifts)"""
    return int(LIFTS[l['row']][3] * (len(l['towers']) + 4) / 8.0 + 0.5)        # halves up, like the game


def plan(osm, terrain, skip=(), canopy=None):
    """OSM data -> dict(lifts, trails, hubs, skipped, glades, notes, tree_check): positions in corner metres / world
    cm, ready for the save. skip: OSM ids of lifts to leave out (the player's choice). canopy: lat, lon -> tree heights
    (m), to find the glades OSM doesn't mark (canopy.heights); without it (tree_check None) or when it fails
    (tree_check False, with a note) only the marked ones are left out"""
    nodes, ways, rels = read(osm)
    europe = -25.0 <= terrain.grid.lon0 <= 45.0 and terrain.grid.lat0 >= 34.0
    skipped = Counter()

    def poly(ids):
        pts = [nodes[i] for i in ids if i in nodes]
        if len(pts) < 2:
            return None
        x, y = terrain.xy([p[0] for p in pts], [p[1] for p in pts])
        P = np.column_stack([x, y])
        P = P[np.concatenate([[True], np.hypot(*np.diff(P, axis=0).T) > 0.05])]
        return P if len(P) > 1 else None

    stations = []                                      # (x, y, name) of named aerialway stations
    for la, lo, t in nodes.values():
        if t.get('aerialway') == 'station' and t.get('name'):
            x, y = terrain.xy(la, lo)
            stations.append((float(x), float(y), _clean(t['name'])))
    for ids, t in ways.values():
        if t.get('aerialway') == 'station' and t.get('name'):
            P = poly(ids)
            if P is not None:
                stations.append((float(P[:, 0].mean()), float(P[:, 1].mean()), _clean(t['name'])))

    # ---- lifts: straight from the bottom station to the top one
    lifts = []
    for wid, (ids, t) in ways.items():
        if 'aerialway' not in t or t['aerialway'] in ('station', 'pylon'):
            continue
        row, why = lift_row(t, europe)
        if row is None:
            skipped['lift (%s)' % why] += 1
            continue
        P = poly(ids)
        if P is None:
            skipped['lift without a line'] += 1
            continue
        a, b = P[0], P[-1]
        if not (terrain.inside(a[0], a[1], EDGE_M) and terrain.inside(b[0], b[1], EDGE_M)):
            skipped['lift reaching outside the square'] += 1
            continue
        L = math.hypot(*(b - a))
        if not MIN_LIFT_M <= L <= MAX_LIFT_M:
            skipped['lift too %s' % ('short' if L < MIN_LIFT_M else 'long')] += 1
            continue
        if terrain.z(*a) > terrain.z(*b):
            a, b = b, a
        lifts.append(dict(osm=wid, name=_clean(t.get('name') or t.get('name:en') or t.get('ref')), row=row, why=why,
                          kind=t['aerialway'], a=a, b=b))
    lifts.sort(key=lambda l: -math.hypot(*(l['b'] - l['a'])))
    unnamed = Counter()
    for l in lifts:
        if not l['name']:
            k = KIND_NAME.get(l['kind'], 'Lift')
            unnamed[k] += 1
            l['name'] = '%s %d' % (k, unnamed[k])
        _lift_geometry(l, terrain)
    left_out = [l for l in lifts if l['osm'] in set(skip)]
    if left_out:
        skipped['lift left out by you'] = len(left_out)
        lifts = [l for l in lifts if l['osm'] not in set(skip)]

    # ---- hubs: terminals close together share one, named after an OSM station nearby or after the lift
    hubs = []
    for l in lifts:
        for end, label in (('bottom', 'Base'), ('top', 'Summit')):
            x, y = l['wp'][0][:2] if end == 'bottom' else l['wp'][-1][:2]
            hub = next((h for h in hubs if math.hypot(h['x'] - x, h['y'] - y) < HUB_M and h['id'] != l.get('hub_bottom')),
                       None)                       # (a short lift's top is still another hub than its bottom)
            if hub is None:
                st = min(stations, key=lambda s: math.hypot(s[0] - x, s[1] - y), default=None)
                near = st and math.hypot(st[0] - x, st[1] - y) < STATION_M and st[2] not in {h['name'] for h in hubs}
                hub = dict(id=G.new_guid(), x=x, y=y, name=st[2] if near else '%s %s' % (l['name'], label))
                hubs.append(hub)
            l['hub_' + end] = hub['id']

    # ---- trails
    rel_tags = {}
    for r in rels:
        if r.get('tags', {}).get('type') == 'multipolygon':
            continue                                   # an area: its member ways are its outline, not runs
        for m in r.get('members', ()):
            if m.get('type') == 'way':
                rel_tags.setdefault(m['ref'], r.get('tags', {}))
    lines, areas, glades, notes = [], [], [], []
    for wid, (ids, t) in ways.items():
        rt = rel_tags.get(wid, {})
        if t.get('piste:type') != 'downhill' and rt.get('piste:type') != 'downhill':
            continue
        if 'aerialway' in t:
            continue
        name = _trail_name(t) or _trail_name(rt)
        diff = DIFFICULTY.get(str(t.get('piste:difficulty') or rt.get('piste:difficulty') or '').strip().lower())
        tags = dict(rt, **t)
        closed = len(ids) > 3 and ids[0] == ids[-1] and t.get('area') != 'no'
        if _gladed(tags):
            glades.append(dict(name=name, closed=closed, P=poly(ids)))
            continue
        if tags.get('piste:grooming') == 'backcountry' and not diff:
            skipped['backcountry route without a grade'] += 1
            continue
        (areas if closed else lines).append(dict(osm=wid, ids=ids, name=name, diff=diff, tags=tags))
    for r in rels:                                     # piste areas mapped as multipolygons: one area per outer ring
        t = r.get('tags', {})
        if t.get('type') != 'multipolygon' or t.get('piste:type') != 'downhill':
            continue
        diff = DIFFICULTY.get(str(t.get('piste:difficulty') or '').strip().lower())
        rings = _rings([m['ref'] for m in r.get('members', ()) if m.get('type') == 'way' and m.get('role', '') in ('outer', '')], ways)
        if _gladed(t):
            glades += [dict(name=_trail_name(t), closed=True, P=poly(ring)) for ring in rings]
            continue
        if t.get('piste:grooming') == 'backcountry' and not diff:
            skipped['backcountry route without a grade'] += 1
            continue
        if not rings:
            skipped['trail area with an open outline'] += 1
        areas += [dict(osm=r['id'], ids=ring, name=_trail_name(t), diff=diff, tags=t) for ring in rings]
    trails = _drawn_twice(_chains(lines, poly, terrain, skipped), terrain, skipped)
    named = {tr['name'].lower() for tr in trails if tr['name']}
    runs = [t['P'] for t in trails] + [g['P'] for g in glades if not g['closed'] and g['P'] is not None]
    bowls = []
    for a in areas:
        if a['name'] and a['name'].lower() in named:
            continue                                       # the same run, also drawn as a line
        b = _bowl(a, poly, terrain)
        if b is None:
            skipped['trail area too small or not inside the square'] += 1
        elif not a['name'] and any(_inside(b['P'], P).sum() >= 10 for P in runs):
            skipped['unnamed piste area drawn round a run'] += 1     # >= 100 m of a run inside it: the same piste
        else:
            bowls.append(b)
    trails += _bowls_drawn_twice(bowls, skipped)
    tree_check = None
    if canopy is not None:                             # the glades OSM doesn't mark
        try:
            trees = _through_trees(trails, terrain, canopy)
            glades += [dict(name=t['name'], closed=t['shape'] == 'Bowl', P=t['P']) for t, g in zip(trails, trees) if g]
            trails = [t for t, g in zip(trails, trees) if not g]
            tree_check = True
        except (net.NetError, chm.CanopyError, OSError) as ex:
            log.warning('tree check failed: %s', ex)
            tree_check = False
            notes.append('The satellite tree heights couldn\'t be downloaded right now, so only the glades marked in '
                         'OpenStreetMap are left out. Switch the option off and on again later to find the others.')
    gnames = {g['name'].lower() for g in glades if g['name']}
    same = [bool(t['name'] and t['name'].lower() in gnames and not t['nogl'] and not t['road'])
            for t in trails]                                                         # the rest of a glade's run
    glades += [dict(name=t['name'], closed=t['shape'] == 'Bowl', P=t['P']) for t, s in zip(trails, same) if s]
    trails = [t for t, s in zip(trails, same) if not s]
    if glades:
        skipped[GLADE] = len(gnames) + sum(not g['name'] for g in glades)
    k = Counter()
    for tr in sorted(trails, key=lambda t: -t['length_cm']):
        if not tr['name']:
            k[tr['difficulty']] += 1
            tr['name'] = '%s %d' % (RUN_NAME[tr['difficulty']], k[tr['difficulty']])
    return dict(lifts=lifts, trails=trails, hubs=hubs, skipped=dict(skipped), glades=glades, notes=notes,
                tree_check=tree_check)


def _gladed(t):
    """True if the piste is marked as tree skiing (gladed=yes, a piste that is itself a wood, a glade by name), False
    if gladed=no says it isn't, else None"""
    g = str(t.get('gladed') or '').strip().lower()
    if g in ('no', 'false', '0'):
        return False
    if g in ('yes', 'true', '1') or t.get('natural') in ('wood', 'forest') or t.get('landuse') == 'forest':
        return True
    return True if GLADE_NAME.search(' '.join(str(t.get(k) or '') for k in ('piste:name', 'name', 'name:en'))) else None


def _through_trees(trails, terrain, canopy):
    """which trails go through the trees with no cleared corridor (by the canopy heights): a run is a glade when its
    best smooth path within 15 m of the OSM line is under trees for GLADE_SHARE of its length (the path may drift one
    2.5 m step per 5 m at the cost of half a tree, so it follows a run drawn a little off but can't weave between the
    trees of a glade); a piste area when GLADE_COVER of it is under trees. Green runs (cat tracks), roads and
    gladed=no pistes are never glades."""
    pts = []
    for t in trails:
        if t['nogl'] or (t['shape'] == 'Corridor' and (t['difficulty'] == 'Beginner' or t['road'])):
            pts.append(np.zeros((0, 2)))
        elif t['shape'] == 'Corridor':
            Q = _resample(t['P'], GLADE_STEP)
            d = np.gradient(Q, axis=0)
            d /= np.maximum(np.hypot(d[:, 0], d[:, 1]), 1e-9)[:, None]
            side = np.column_stack([-d[:, 1], d[:, 0]])
            pts.append((Q[:, None, :] + GLADE_OFFSETS[None, :, None] * side[:, None, :]).reshape(-1, 2))
        else:
            (x0, y0), (x1, y1) = t['P'].min(axis=0), t['P'].max(axis=0)
            X, Y = np.meshgrid(np.arange(x0, x1, 6.0), np.arange(y0, y1, 6.0))
            g = np.column_stack([X.ravel(), Y.ravel()])
            pts.append(g[_inside(t['P'], g)] if len(g) else g)
    allp = np.vstack(pts) if pts else np.zeros((0, 2))
    if not len(allp):
        return [False] * len(trails)
    la, lo = terrain.latlon(allp[:, 0], allp[:, 1])
    tall = np.asarray(canopy(la, lo)).ravel() >= TREE_M
    out, k = [], 0
    for t, p in zip(trails, pts):
        h, k = tall[k:k + len(p)], k + len(p)
        if not len(h):
            out.append(False)
        elif t['shape'] == 'Bowl':
            out.append(bool(h.mean() >= GLADE_COVER))
        else:
            h = h.reshape(-1, len(GLADE_OFFSETS))
            cost = h[0].astype(np.float64)
            for row in h[1:]:
                c = cost.copy()
                c[1:] = np.minimum(c[1:], cost[:-1] + 0.5)
                c[:-1] = np.minimum(c[:-1], cost[1:] + 0.5)
                cost = c + row
            out.append(bool(cost.min() / len(h) >= GLADE_SHARE))
    return out


def _trail_name(t):
    return _clean(t.get('piste:name') or t.get('name') or t.get('piste:ref') or t.get('ref'))


def _rings(way_ids, ways):
    """a multipolygon's outer ways joined end to end into closed rings (node id lists); outlines that don't close are
    dropped"""
    segs = [list(ways[w][0]) for w in way_ids if w in ways and len(ways[w][0]) > 1]
    rings = []
    while segs:
        ring = segs.pop()
        while ring[0] != ring[-1]:
            k = next((i for i, s in enumerate(segs) if ring[-1] in (s[0], s[-1])), None)
            if k is None:
                break
            s = segs.pop(k)
            ring += (s if s[0] == ring[-1] else s[::-1])[1:]
        if len(ring) > 3 and ring[0] == ring[-1]:
            rings.append(ring)
    return rings


def _inside(poly, pts):
    """which of pts (n x 2) lie inside the closed polygon poly (m x 2, last point = first), even-odd rule"""
    x, y = pts[:, :1], pts[:, 1:]
    x0, y0, x1, y1 = poly[:-1, 0], poly[:-1, 1], poly[1:, 0], poly[1:, 1]
    dy = np.where(y1 != y0, y1 - y0, 1e-12)
    return (((y0 > y) != (y1 > y)) & (x < x0 + (x1 - x0) * (y - y0) / dy)).sum(axis=1) % 2 == 1


def _lift_geometry(l, terrain):
    """terminals, towers evenly spaced at most the class's spacing apart along the 3D line (like the game: a 162 m
    chair gets 3 towers, a 6.4 km gondola 127), heights raised so the cable stays clear of the ground, queue line"""
    spacing, h_lo, h_hi = LIFTS[l['row']][4:7]
    a, b = l['a'], l['b']
    za, zb = float(terrain.z(*a)), float(terrain.z(*b))
    L3 = math.hypot(math.hypot(*(b - a)), (zb - za) / 100.0)
    n = max(1, math.ceil(L3 / spacing))
    towers = []
    for i in range(1, n):
        p = a + (b - a) * (i / n)
        towers.append([float(p[0]), float(p[1]), float(terrain.z(*p)), float(h_lo)])
    ends = [(float(a[0]), float(a[1]), za + 700.0, None)] + [(t[0], t[1], None, t) for t in towers] + \
           [(float(b[0]), float(b[1]), zb + 700.0, None)]
    s = np.linspace(0.1, 0.9, 9)
    for _ in range(6):                      # cable (straight between supports) >= 6 m above the ground
        changed = False
        for (xa, ya, ca, ta), (xb, yb, cb, tb) in zip(ends[:-1], ends[1:]):
            ha = ca if ta is None else ta[2] + ta[3]
            hb = cb if tb is None else tb[2] + tb[3]
            need = 600.0 - float((ha + (hb - ha) * s - terrain.z(xa + (xb - xa) * s, ya + (yb - ya) * s)).min())
            for tw in (ta, tb):
                if need > 1.0 and tw is not None and tw[3] < h_hi:
                    tw[3] = min(float(h_hi), tw[3] + need)
                    changed = True
        if not changed:
            break
    d = (b - a) / math.hypot(*(b - a))
    side = np.array([-d[1], d[0]])
    queue = [a - d * 5.2 + side * 2.8, a - d * 9.9 + side * 2.9]       # where the game puts it: behind, to one side
    l['wp'] = [(float(a[0]), float(a[1]), za), (float(b[0]), float(b[1]), zb)]
    l['towers'] = towers
    l['queue'] = [(float(q[0]), float(q[1]), float(terrain.z(*q))) for q in queue]
    l['length_m'] = math.hypot(*(b - a))


def _chains(lines, poly, terrain, skipped):
    """piste ways with the same name joined where they share a node, each piece pointing downhill"""
    groups = defaultdict(list)
    for w in lines:
        groups[w['name'].lower() if w['name'] else ('#', w['osm'])].append(w)
    out = []
    for ws in groups.values():
        segs = []
        for w in ws:
            P = poly(w['ids'])
            if P is None:
                continue
            a, b = w['ids'][0], w['ids'][-1]
            if terrain.z(*P[0]) < terrain.z(*P[-1]):
                P, a, b = P[::-1], b, a
            segs.append(dict(P=P, a=a, b=b, w=w, L=_length(P)))
        by_start = defaultdict(list)
        for i, s in enumerate(segs):
            by_start[s['a']].append(i)
        ends = {s['b'] for s in segs}
        used = set()
        for i0 in sorted(range(len(segs)), key=lambda i: (segs[i]['a'] in ends, -float(terrain.z(*segs[i]['P'][0])))):
            if i0 in used:
                continue
            chain = [i0]
            used.add(i0)
            while True:
                nxt = [j for j in by_start[segs[chain[-1]]['b']] if j not in used]
                if not nxt:
                    break
                chain.append(max(nxt, key=lambda j: segs[j]['L']))
                used.add(chain[-1])
            P = np.vstack([segs[chain[0]]['P']] + [segs[j]['P'][1:] for j in chain[1:]])
            name = segs[chain[0]]['w']['name']
            least = MIN_TRAIL_M if name else MIN_UNNAMED_M
            dl = Counter()
            for j in chain:
                if segs[j]['w']['diff']:
                    dl[segs[j]['w']['diff']] += segs[j]['L']
            diff = dl.most_common(1)[0][0] if dl else None
            tags = [segs[j]['w']['tags'] for j in chain]
            parts = [p for p in _inside_runs(P, terrain, 25.0) if _length(p) >= least]
            if not parts:
                skipped['short trail piece' if name else 'short unnamed piste'] += 1
            for part in parts:
                out.append(_corridor(name, diff, part, tags, terrain))
    return out


def _near(Q, P, d):
    """which points of Q (n x 2) are within d of the polyline P"""
    a, ab = P[:-1], np.diff(P, axis=0)
    ab2 = np.maximum((ab * ab).sum(axis=1), 1e-9)
    out = np.zeros(len(Q), bool)
    for i in range(0, len(Q), 256):                    # points x segments, a chunk of points at a time
        q = Q[i:i + 256, None, :]
        s = np.clip(((q - a) * ab).sum(axis=2) / ab2, 0.0, 1.0)
        v = q - (a + s[..., None] * ab)
        out[i:i + 256] = ((v * v).sum(axis=2) < d * d).any(axis=1)
    return out


def _drawn_twice(corridors, terrain, skipped):
    """the same run drawn twice in OSM (a newer piste line beside the older road that has the run's name, a route
    relation's ways next to a separately drawn run): every stretch of DUP_LEN_M or more lying within DUP_M of a longer
    run of the same name (of any run, for an unnamed one) is cut out, and what is left is kept if still long enough.
    Shorter overlaps are left alone: that is where the branches of a run meet."""
    keep = []
    for t in sorted(corridors, key=lambda t: (t['name'] is None, -t['length_cm'])):
        lo, hi = t['P'].min(axis=0) - DUP_M, t['P'].max(axis=0) + DUP_M
        others = [k['P'] for k in keep if (not t['name'] or (k['name'] or '').lower() == t['name'].lower())
                  and (k['P'].max(axis=0) >= lo).all() and (k['P'].min(axis=0) <= hi).all()]
        Q = _resample(t['P'], 10.0)
        on = np.zeros(len(Q), bool)
        for P in others:
            on |= _near(Q, P, DUP_M)
        d, cut, i = _cum(Q), np.zeros(len(Q), bool), 0
        while i < len(Q):                              # long stretches on another run
            j = i
            while j < len(Q) and on[j] == on[i]:
                j += 1
            if on[i] and d[j - 1] - d[i] >= DUP_LEN_M:
                cut[i:j] = True
            i = j
        if not cut.any():
            keep.append(t)
            continue
        skipped[TWICE] += 1
        least, i = (MIN_TRAIL_M if t['name'] else MIN_UNNAMED_M), 0
        while i < len(Q):                              # what is left of it
            j = i
            while j < len(Q) and cut[j] == cut[i]:
                j += 1
            if not cut[i] and j - i > 1 and d[j - 1] - d[i] >= least:
                keep.append(_corridor(t['name'], t['difficulty'], Q[i:j], t['tags'], terrain))
            i = j
    return keep


def _bowls_drawn_twice(bowls, skipped):
    """a piste area drawn twice (an older way and a newer multipolygon, say): one lying for the most part inside or
    on a larger one of the same name (any one, when it is unnamed) is left out"""
    keep = []
    for b in sorted(bowls, key=lambda b: (b['name'] is None, -b['radius_cm'])):
        O = b['P']
        if any((_inside(k['P'], O) | _near(O, k['P'], DUP_M)).mean() >= 0.8 for k in keep
               if not b['name'] or (k['name'] or '').lower() == b['name'].lower()):
            skipped[TWICE] += 1
        else:
            keep.append(b)
    return keep


def _curve_breaks(P):
    """distances along P where its curves meet: at most CURVE_M apart, and closer round bends so that no curve turns
    more than CURVE_TURN degrees (all turning counted, so an S-bend is split too), none shorter than CURVE_MIN_M but
    a last one that a bend keeps apart"""
    L = _length(P)
    Q = _resample(P, CURVE_STEP_M)
    s = np.linspace(0.0, L, len(Q))                              # Q's points lie on P this far along it
    hd = np.arctan2(*np.diff(Q, axis=0).T[::-1])
    turn = np.abs(np.angle(np.exp(1j * np.diff(hd))))            # at Q[1:-1]
    out, acc, last = [0.0], 0.0, 0.0
    for j in range(1, len(Q) - 1):
        acc += turn[j - 1]
        if s[j] - out[-1] >= CURVE_M or (acc > math.radians(CURVE_TURN) and s[j] - out[-1] >= CURVE_MIN_M):
            out.append(float(s[j]))
            last, acc = acc, 0.0
    if len(out) > 1 and L - out[-1] < CURVE_MIN_M and last + acc <= math.radians(CURVE_TURN):
        out.pop()                                                # a short straight end joins the curve before it
    out.append(L)
    return np.array(out)


def _bend_radius(a, c, b):
    """the tightest radius (m) of the quadratic curve a -> b with control point c"""
    t = np.linspace(0.0, 1.0, 21)[:, None]
    d1 = 2 * (1 - t) * (c - a) + 2 * t * (b - c)
    d2 = 2 * (a - 2 * c + b)
    cross = np.abs(d1[:, 0] * d2[1] - d1[:, 1] * d2[0])
    return float((np.hypot(d1[:, 0], d1[:, 1]) ** 3 / np.maximum(cross, 1e-12)).min())


def _corridor(name, diff, P, tags, terrain):
    """a downhill polyline (corner metres) -> the game's chain of quadratic curves"""
    Q = _resample(P, 10.0)
    zq = terrain.z(Q[:, 0], Q[:, 1]) / 100.0
    slope = np.degrees(np.arctan2(np.abs(np.diff(zq)), np.maximum(np.hypot(*np.diff(Q, axis=0).T), 1e-6)))
    max_slope = float(np.percentile(slope, 95)) if len(slope) else 0.0
    if diff is None:                                   # no grade in OSM: from the incline
        diff = 'Beginner' if max_slope < 15 else 'Intermediate' if max_slope < 24 else 'Expert' if max_slope < 32 else 'Pro'
    width = next((w for w in (_num(t.get('width')) for t in tags) if w and 8 <= w <= 150), None) or WIDTH_M[diff]
    d = _cum(P)
    br = _curve_breaks(P)

    def at(s):
        return np.array([np.interp(s, d, P[:, 0]), np.interp(s, d, P[:, 1])])
    pieces, widths = [], []
    for a, b in zip(br[:-1], br[1:]):
        p0, p2, m = at(a), at(b), at((a + b) / 2)
        c = 2 * m - (p0 + p2) / 2                      # the curve passes through the piste's own midpoint
        pieces.append((p0, c, p2, m))
        widths.append(min(width, max(MIN_WIDTH_M, 1.8 * _bend_radius(p0, c, p2))))
    for i in range(1, len(widths)):                   # widen back gradually after a tight bend
        widths[i] = min(widths[i], widths[i - 1] + WIDTH_GROW_M)
    for i in range(len(widths) - 2, -1, -1):
        widths[i] = min(widths[i], widths[i + 1] + WIDTH_GROW_M)
    curves = []
    for (p0, c, p2, m), w in zip(pieces, widths):
        z0, z2, zm = (float(v) for v in terrain.z(np.array([p0[0], p2[0], m[0]]), np.array([p0[1], p2[1], m[1]])))
        curves.append((terrain.world(*p0, z0), terrain.world(*c, 2 * zm - (z0 + z2) / 2), terrain.world(*p2, z2),
                       w * 100.0))
    grooming = {t.get('piste:grooming') for t in tags} - {None}
    groomed = (diff in ('Beginner', 'Intermediate') or bool(grooming & {'classic', 'yes'})) and \
        not grooming & {'mogul', 'backcountry', 'no'}
    night = any(t.get('piste:lit') == 'yes' or t.get('lit') == 'yes' for t in tags)
    return dict(name=name, difficulty=diff, shape='Corridor', curves=curves, length_cm=_length(P) * 100.0,
                max_slope=max_slope, mid=terrain.world(*_at(P, 0.5)), groomed=groomed, night=night, P=P, width=width,
                road=any('highway' in t for t in tags), nogl=any(_gladed(t) is False for t in tags), tags=tags)


def _bowl(a, poly, terrain):
    """a piste area -> a bowl: outline ~every 100 m, centre = area centroid, radius = sqrt(area / pi) (as the game)"""
    P = poly(a['ids'])
    if P is None or len(P) < 4 or not all(terrain.inside(x, y, 25.0) for x, y in P):
        return None
    per = _length(P)
    O = _resample(P, min(max(per / 28.0, 15.0), 150.0))[:-1]
    x, y = O[:, 0], O[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    cr = x * y1 - x1 * y
    area = cr.sum() / 2.0
    if abs(area) < 15000:                              # 1.5 ha
        return None
    c = np.array([((x + x1) * cr).sum() / (6 * area), ((y + y1) * cr).sum() / (6 * area)])
    z = terrain.z(x, y) / 100.0
    max_slope = math.degrees(math.atan2(float(z.max() - z.min()), 2 * math.sqrt(abs(area) / math.pi))) * 1.6
    diff = a['diff'] or ('Pro' if max_slope > 38 else 'Expert' if max_slope > 26 else 'Intermediate')
    return dict(name=a['name'], difficulty=diff, shape='Bowl', outline=[terrain.world(*p) for p in O],
                center=terrain.world(*c), radius_cm=math.sqrt(abs(area) / math.pi) * 100.0, length_cm=per * 100.0,
                max_slope=min(max_slope, 60.0), mid=terrain.world(*c), groomed=False, night=False,
                P=np.vstack([O, O[:1]]), width=None, road=False, nogl=_gladed(a['tags']) is False)


# ---------------------------------------------------------------- for the app: summary, map lines, base, tree mask

def summary(pl):
    return dict(lifts=len(pl['lifts']), trails=len(pl['trails']),
                lift_types=dict(Counter(LIFTS[l['row']][1] for l in pl['lifts']).most_common()),
                difficulties=dict(Counter(t['difficulty'] for t in pl['trails'])),
                lift_list=sorted((dict(id=l['osm'], name=l['name'], real=l['why'], game=LIFTS[l['row']][1], upkeep=upkeep(l))
                                  for l in pl['lifts']), key=lambda r: r['name'].lower()),
                skipped=pl['skipped'], notes=pl['notes'])


def overlay(pl, terrain):
    """the lifts and trails as lat/lon lines for the map view"""
    def ll(P):
        la, lo = terrain.latlon(P[:, 0], P[:, 1])
        return [[round(float(a), 6), round(float(b), 6)] for a, b in zip(la, lo)]
    out = [dict(kind='lift', name=l['name'], game=LIFTS[l['row']][1], pts=ll(np.array([p[:2] for p in l['wp']])))
           for l in pl['lifts']]
    out += [dict(kind=t['shape'].lower(), name=t['name'], difficulty=t['difficulty'], pts=ll(_resample(t['P'], 25.0)))
            for t in pl['trails']]
    out += [dict(kind='glade', name=g['name'] or 'Glade', closed=g['closed'], pts=ll(_resample(g['P'], 25.0)))
            for g in pl['glades'] if g['P'] is not None]
    return out


def suggest_base(pl, terrain, margin_m=120.0):
    """(lat, lon) for the ticket office: by the bottom of the lift with the most other lift bottoms nearby (the main
    base area), a little behind it, at least margin_m inside the square; None without lifts"""
    if not pl['lifts']:
        return None
    bottoms = np.array([l['wp'][0] for l in pl['lifts']])

    def score(i):
        x, y, z = bottoms[i]
        near = np.hypot(bottoms[:, 0] - x, bottoms[:, 1] - y) < 400
        return near.sum() - (z - bottoms[:, 2].min()) / 100.0 / 150.0     # 150 m higher costs one lift
    i = max(range(len(bottoms)), key=score)
    l = pl['lifts'][i]
    a, b = np.array(l['wp'][0][:2]), np.array(l['wp'][-1][:2])
    p = a - (b - a) / math.hypot(*(b - a)) * 50.0
    m = max(120.0, float(margin_m))
    p = np.clip(p, m, terrain.size - m)
    la, lo = terrain.latlon(p[0], p[1])
    return [float(la), float(lo)]


def clear_mask(pl, size_m, res_m=4.0):
    """(bool raster, res_m): True where no tree may stand (trails, bowls, under the lifts); row = y / res_m"""
    n = int(math.ceil(size_m / res_m)) + 1
    img = Image.new('1', (n, n), 0)
    dr = ImageDraw.Draw(img)

    def px(P):
        return [(float(x) / res_m, float(y) / res_m) for x, y in P]

    def disc(x, y, r):
        dr.ellipse([x - r, y - r, x + r, y + r], fill=1)

    for t in pl['trails']:
        if t['shape'] == 'Bowl':
            dr.polygon(px(t['P']), fill=1)
            continue
        w = (t['width'] + 6.0) / res_m
        pts = px(_resample(t['P'], 8.0))
        dr.line(pts, fill=1, width=max(2, int(round(w))))
        for x, y in pts[::3] + pts[-1:]:
            disc(x, y, w / 2)
    for l in pl['lifts']:
        pts = px([p[:2] for p in l['wp']])
        dr.line(pts, fill=1, width=max(2, int(round(2 * LIFTS[l['row']][7] / 100.0 / res_m))))
        for x, y in pts:
            disc(x, y, 22.0 / res_m)
    return np.array(img, dtype=bool), res_m


def _box_sum(a, r):
    """sum over the (2r+1)^2 window round each cell (zeros beyond the edges)"""
    k = 2 * r + 1
    c = np.zeros((a.shape[0] + 2 * r + 1, a.shape[1] + 2 * r + 1))
    c[1:, 1:] = np.pad(a.astype(np.float64), r).cumsum(0).cumsum(1)
    return c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]


def _real_cover(terrain, canopy, sel, progress=None):
    """the real tree cover as a share (0..1) of full forest per vertex (1 where the cells are unknown), measured from canopy
    heights (canopy: lat, lon -> m, COVER_NODATA where unknown) at the vertices in sel (bool n x n)"""
    n, sp = terrain.n, terrain.sp
    k = max(1, int(round(sp / COVER_STEP_M)))           # samples per vertex cell, each way
    off = ((np.arange(k) + 0.5) / k - 0.5) * sp
    under = np.zeros((n, n))                            # share of a cell's samples under tree crowns
    known = np.zeros((n, n), bool)                      # cells with canopy data
    for r0 in range(0, n, COVER_ROWS):
        if progress:
            progress(r0 / n, 'Loading the real tree cover...')
        r, c = np.nonzero(sel[r0:r0 + COVER_ROWS])
        if not len(r):
            continue
        r = r + r0
        xs = np.repeat(c[:, None] * sp + off, k, axis=1).ravel()
        ys = np.tile(r[:, None] * sp + off, (1, k)).ravel()
        la, lo = terrain.latlon(xs, ys)
        h = np.asarray(canopy(la, lo)).reshape(len(r), k * k)
        ok = h != COVER_NODATA
        cnt = ok.sum(axis=1)
        under[r, c] = ((h >= COVER_TREE_M) & ok).sum(axis=1) / np.maximum(cnt, 1)
        known[r, c] = cnt > 0
    rw = max(1, int(round(COVER_WIN_M / sp / 2)))
    cells = _box_sum(known, rw)
    real = np.where(cells > 0, np.clip(_box_sum(under, rw) / np.maximum(cells, 1.0) / COVER_FULL, 0.0, 1.0), 1.0)
    return real


def tree_cover(pl, terrain, canopy):
    """-> the share (0..1) of the generated forest's density to keep at each terrain vertex (row = y): the real tree
    cover (canopy heights, lat, lon -> m, COVER_NODATA where unknown) within COVER_BUF_M of the runs, glades and lifts,
    blending into 1 over COVER_FEATHER_M beyond; None when the plan has nothing to go round"""
    n, sp = terrain.n, terrain.sp
    img = Image.new('L', (n, n), 0)
    dr = ImageDraw.Draw(img)
    rad = (COVER_BUF_M + COVER_FEATHER_M / 2) / sp      # the blur below ramps this edge over COVER_FEATHER_M

    def px(P):
        return [(float(x) / sp, float(y) / sp) for x, y in P]

    lines = [(t['P'], t['shape'] == 'Bowl') for t in pl['trails']] + \
            [(g['P'], g['closed']) for g in pl['glades'] if g['P'] is not None] + \
            [([p[:2] for p in l['wp']], False) for l in pl['lifts']]
    if not lines:
        return None
    for P, area in lines:
        pts = px(P)
        if area and len(pts) > 2:
            dr.polygon(pts, fill=1)
        if len(pts) > 1:
            dr.line(pts, fill=1, width=max(1, int(round(2 * rad))), joint='curve')
        for x, y in (pts[0], pts[-1]):
            dr.ellipse([x - rad, y - rad, x + rad, y + rad], fill=1)
    fr = max(1, int(round(COVER_FEATHER_M / sp / 2)))
    near = _box_sum(np.array(img, np.float64), fr) / _box_sum(np.ones((n, n)), fr)     # (only the part inside the map)
    sel = near > 1e-3
    real = _real_cover(terrain, canopy, sel)
    return (1.0 - near * (1.0 - real)).astype(np.float32)


def tree_cover_all(terrain, canopy, progress=None):
    """-> the share (0..1) of the generated forest's density to keep at each terrain vertex over the whole map: the real tree
    cover (see _real_cover). It works without trails and lifts; the forest settings (treeline, steepest slope, tree count)
    still apply on top of it."""
    f = _cover_file(terrain)
    if f.is_file() and time.time() - f.stat().st_mtime < COVER_CACHE_DAYS * 86400:
        try:
            q = np.load(f)
            if q.shape == (terrain.n, terrain.n):
                f.touch()
                if progress:
                    progress(1.0, 'Loading the real tree cover...')
                log.info('real tree cover loaded from the cache: %s', f.name)
                return q.astype(np.float32) / 255.0
        except (OSError, ValueError):
            pass
    sel = np.ones((terrain.n, terrain.n), bool)
    cover = _real_cover(terrain, canopy, sel, progress).astype(np.float32)
    try:                                                # kept for the next time (8 bit: 4 MB for the biggest map)
        paths.atomic_write(f, _npy_bytes(np.round(cover * 255).astype(np.uint8)))
        _trim_covers()
    except OSError as ex:
        log.warning('real tree cover not cached: %s', ex)
    return cover


COVER_CACHE = paths.APP_DIR / 'cache' / 'trees'
COVER_CACHE_DAYS = 30
COVER_CACHE_KEEP = 12                                   # files kept (oldest are deleted)


def _cover_file(terrain):
    """the cache file of a map's real tree cover: it depends on where the area is, how it is turned and its grid only"""
    g = terrain.grid
    key = '%.6f_%.6f_%.1f_%.0f_%d' % (g.lat0, g.lon0, getattr(g, 'rot', 0.0), terrain.size, terrain.n)
    return COVER_CACHE / ('cover_%s.npy' % hashlib.sha1(key.encode()).hexdigest()[:20])


def cover_cached(terrain):
    """True if this map's real tree cover is already in the cache (and not too old)"""
    f = _cover_file(terrain)
    try:
        return f.is_file() and time.time() - f.stat().st_mtime < COVER_CACHE_DAYS * 86400
    except OSError:
        return False


def _npy_bytes(a):
    b = io.BytesIO()
    np.save(b, a)
    return b.getvalue()


def _trim_covers():
    try:
        fs = sorted(COVER_CACHE.glob('cover_*.npy'), key=lambda p: p.stat().st_mtime, reverse=True)
        for p in fs[COVER_CACHE_KEEP:]:
            p.unlink(missing_ok=True)
    except OSError:
        pass


# ---------------------------------------------------------------- the save

def _templates():
    tags = G.read_props(G.R(paths.resource('data', 'resort_templates.bin').read_bytes(), 0))
    return {t.name: t for t in tags}


def _set(tags, name, value):
    t = G.get(tags, name)
    if t is None:
        raise ResortError('save template field %s missing' % name)
    t.value = value


def _text(s):
    return {'flags': 2, 'history': -1, 'text': s}


def _vec(p):
    return {'X': float(p['X']), 'Y': float(p['Y']), 'Z': float(p['Z'])}


def _office(tags):
    """(hub id, X, Y) of the starting save's ticket office"""
    for b in G.get(tags, 'Buildings').value:
        cls = G.get(b, 'BuildingClassPath') or G.get(b, 'ClassPath')
        if cls is not None and isinstance(cls.value, dict) and 'TicketOffice' in cls.value.get('asset', ''):
            bd = G.get(b, 'BaseData').value
            tr = G.get(G.get(bd, 'Transform').value, 'Translation').value
            return G.get(bd, 'HubId').value, tr['X'], tr['Y']
    raise ResortError('no ticket office in the starting save')


def add_to_save(is_bytes, pl, terrain):
    """the starting save (2 bytes, int32 GVAS length, GVAS, trailer) with the plan's lifts, trails, hub names and
    cleared zones added -> new bytes"""
    n = struct.unpack_from('<i', is_bytes, 2)[0]
    head, tags, tail = G.parse(is_bytes[6:6 + n])
    trailer = is_bytes[6 + n:]
    T = _templates()
    ts = G.get(tags, 'SaveTimestamp')
    ticks = int(ts.value['Ticks']) if ts is not None else 0

    # lift terminals near the ticket office are in its hub, so arriving guests can ride those lifts (a lift's top stays
    # in its own hub when its bottom is there already)
    office, ox, oy = _office(tags)
    near = {h['id'] for h in pl['hubs']
            if math.hypot((h['x'] - terrain.half) * 100.0 - ox, (h['y'] - terrain.half) * 100.0 - oy) < OFFICE_HUB_M * 100.0}
    ends = []
    for l in pl['lifts']:
        b = office if l['hub_bottom'] in near else l['hub_bottom']
        t = office if l['hub_top'] in near and b != office else l['hub_top']
        ends.append((b, t))

    # Lifts: a root array after Buildings (the starting save has none)
    if G.get(tags, 'Lifts') is not None:
        raise ResortError('the starting save already has lifts')
    proto = T['Lifts'].value[0]
    lifts = []
    for l, (hub_bottom, hub_top) in zip(pl['lifts'], ends):
        e = G.clone(proto)
        bd = G.get(e, 'BaseData').value
        _set(bd, 'ID', G.new_guid())
        xf = G.get(bd, 'Transform').value
        _set(xf, 'Rotation', {'X': 0.0, 'Y': 0.0, 'Z': 0.0, 'W': 1.0})
        _set(xf, 'Translation', _vec(terrain.world(*l['wp'][0])))
        _set(xf, 'Scale3D', {'X': 1.0, 'Y': 1.0, 'Z': 1.0})
        _set(bd, 'DisplayName', _text(l['name']))
        _set(bd, 'ConstructionCost', int(LIFTS[l['row']][2]))
        _set(bd, 'HubId', hub_bottom)
        _set(G.get(bd, 'DesignLocks').value, 'bNoRefund', True)     # came free: bulldozing it pays nothing back
        cls = LIFTS[l['row']][0]
        _set(e, 'LiftClassPath', {'pkg': cls, 'asset': cls.rsplit('/', 1)[1] + '_C', 'sub': ''})
        wps = []
        for x, y, z in l['wp']:
            w = G.clone(G.get(proto, 'Waypoints').value[0])
            _set(w, 'position', _vec(terrain.world(x, y, z)))
            _set(w, 'bIsTerminal', True)
            _set(w, 'bIsAngleStation', False)
            wps.append(w)
        _set(e, 'Waypoints', wps)
        tws = []
        for x, y, z, h in l['towers']:
            w = G.clone(G.get(proto, 'Towers').value[0])
            _set(w, 'BasePosition', _vec(terrain.world(x, y, z)))
            _set(w, 'Height', float(h))
            _set(w, 'TowerId', G.new_guid())
            tws.append(w)
        _set(e, 'Towers', tws)
        _set(e, 'TopHubId', hub_top)
        _set(e, 'Condition', 100.0)
        _set(e, 'BuiltSeasonIndex', 1)
        _set(e, 'QueueLinePoints', [_vec(terrain.world(*q)) for q in l['queue']])
        _set(e, 'QueueRopeLiftCm', [0.0])
        _set(e, 'OpenHour', OPEN_HOURS[0])
        _set(e, 'CloseHour', OPEN_HOURS[1])
        lifts.append(e)
    lt = G.clone(T['Lifts'])
    lt.value = lifts
    tags.insert(next(i for i, t in enumerate(tags) if t.name == 'Buildings') + 1, lt)

    # trails: TrailMapData.RegisteredTrails (first field; the starting save has none), CurrentTrailId = last id used
    tmd = G.get(tags, 'TrailMapData').value
    if G.get(tmd, 'RegisteredTrails') is not None:
        raise ResortError('the starting save already has trails')
    reg = G.clone(T['RegisteredTrails'])
    reg.value = []
    tmd.insert(0, reg)
    cur = G.get(tmd, 'CurrentTrailId')
    tproto = T['RegisteredTrails'].value[0][1]
    zero = {'X': 0.0, 'Y': 0.0, 'Z': 0.0}
    for t in pl['trails']:
        cur.value += 1
        e = G.clone(tproto)
        _set(e, 'TrailId', cur.value)
        _set(e, 'DisplayName', _text(t['name']))
        _set(e, 'PlayerRatedDifficulty', 'ETrailDifficulty::' + t['difficulty'])
        _set(e, 'Shape', 'ETrailShape::' + t['shape'])
        cproto = G.get(e, 'Curve').value
        if t['shape'] == 'Corridor':
            cs = [_curve(cproto, c) for c in t['curves']]
            _set(e, 'Curve', cs[0])
            _set(e, 'AdditionalCurves', cs[1:])
        else:
            _set(e, 'Curve', _curve(cproto, (zero, zero, zero, 2000.0)))
            _set(e, 'BowlOutline', [_vec(p) for p in t['outline']])
            _set(e, 'BowlCenter', _vec(t['center']))
            _set(e, 'BowlRadius', float(t['radius_cm']))
        _set(e, 'MaxSlopeAngle', float(t['max_slope']))
        _set(e, 'Length', float(t['length_cm']))
        _set(e, 'MidpointPosition', _vec(t['mid']))
        _set(e, 'bIsGroomed', bool(t['groomed']))
        _set(e, 'bNightSkiing', bool(t['night']))
        _set(e, 'FirstCreatedAt', {'Ticks': ticks})
        _set(e, 'LastModifiedAt', {'Ticks': ticks})
        reg.value.append((cur.value, e))

    # names of the hubs in use (the ticket office's hub has its own already)
    names = G.get(G.get(tags, 'HubData').value, 'HubNames')
    used = {i for pair in ends for i in pair}
    for h in pl['hubs']:
        if h['id'] in used:
            e = G.clone(T['HubNames'].value[0])
            _set(e, 'HubId', h['id'])
            _set(e, 'Name', _text(h['name']))
            names.value.append(e)

    # cleared zones in the map's level entry: capsules along the lifts and trails, circles at the stations, an
    # outline round each bowl
    zones = G.get(G.get(tags, 'ClearedObstaclesByLevel').value[0][1], 'Zones')
    cap, outl = T['Zones'].value
    for l in pl['lifts']:
        a, b = (terrain.world(x, y, 0.0) for x, y, _ in l['wp'])
        zones.value.append(_zone(cap, a, b, LIFTS[l['row']][7]))
        zones.value += [_zone(cap, p, p, 2200.0) for p in (a, b)]
    for t in pl['trails']:
        if t['shape'] == 'Corridor':
            for p0, c, p2, w in t['curves']:
                B = _bezier(p0, c, p2, 2000.0)
                zones.value += [_zone(cap, {'X': u[0], 'Y': u[1]}, {'X': v[0], 'Y': v[1]}, w / 2.0)
                                for u, v in zip(B[:-1], B[1:])]
        else:
            e = G.clone(outl)
            _set(e, 'Center', {'X': t['center']['X'], 'Y': t['center']['Y']})
            _set(e, 'Radius', float(t['radius_cm']))
            _set(e, 'EndOffset', {'X': 0.0, 'Y': 0.0})
            _set(e, 'Outline', [{'X': p['X'], 'Y': p['Y']} for p in t['outline']])
            zones.value.append(e)

    gv = G.build(head, tags, tail)
    return is_bytes[:2] + struct.pack('<i', len(gv)) + gv + trailer


def _zone(proto, a, b, radius_cm):
    e = G.clone(proto)
    _set(e, 'Center', {'X': float(a['X']), 'Y': float(a['Y'])})
    _set(e, 'Radius', float(radius_cm))
    _set(e, 'EndOffset', {'X': float(b['X'] - a['X']), 'Y': float(b['Y'] - a['Y'])})
    _set(e, 'Outline', [])
    return e


def _curve(proto, c):
    p0, cp, p2, w = c
    e = G.clone(proto)
    _set(e, 'StartPoint', _vec(p0))
    _set(e, 'ControlPoint', _vec(cp))
    _set(e, 'Endpoint', _vec(p2))
    _set(e, 'CorridorWidth', float(w))
    _set(e, 'EndCorridorWidth', 0.0)
    return e

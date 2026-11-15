"""The window's JavaScript calls these methods (pywebview js_api). Long work runs as one background job at a time; the
page gets progress through window.app.onEvent(...) and can also poll job()."""
import base64
import datetime
import io
import json
import logging
import math
import os
import platform
import re
import secrets
import shutil
import threading
import time
import traceback
import sys
import webbrowser
from pathlib import Path

import numpy as np
from PIL import Image

from . import (APP_NAME, VERSION, biomes, builder, canopy, credentials, dem, gamedata, geo, install, modlib, net, paths, resort,
               server, trees, update)

log = logging.getLogger(__name__)
GAME_URL = 'steam://rungameid/' + install.APP_ID
LINKS = {
    'osm': 'https://www.openstreetmap.org/copyright',
    'otm': 'https://opentopomap.org/about',
    'esri': 'https://www.esri.com/en-us/legal/terms/data-attributions',
    'nominatim': 'https://nominatim.org/',
    'photon': 'https://photon.komoot.io/',
    'usgs': 'https://www.usgs.gov/3d-elevation-program',
    'terrain': 'https://registry.opendata.aws/terrain-tiles/',
    'chm': 'https://registry.opendata.aws/dataforgood-fb-forests/',
    # key tutorials (credentials.PROVIDERS)
    'nls_key': 'https://www.maanmittauslaitos.fi/en/rajapinnat/api-avaimen-ohje',
    'nls_terms': 'https://www.maanmittauslaitos.fi/en/terms-of-use-for-the-open-interface',
    'geotorget': 'https://geotorget.lantmateriet.se/',
    'lm_order': 'https://geotorget.lantmateriet.se/geodataprodukter/markhojdmodell-nedladdning-api?view=bestall',
    'lm_portal': 'https://apimanager.lantmateriet.se/devportal/applications',
    'lm_terms': 'https://geotorget.lantmateriet.se/geodataprodukter/markhojdmodell-nedladdning-api',
    'leaflet': 'https://leafletjs.com/',
}
PHOTON = 'https://photon.komoot.io/api/?limit=12&q='
NOMINATIM = 'https://nominatim.openstreetmap.org/search?format=jsonv2&limit=8&q='
MIN_KM, MAX_KM = 3.0, 20.0                  # same 2017x2017 grid at every size: ~10 m between points at 20 km
PREFIX = 'mc_'
ORDER_BASE = 1000
BASE_MARGIN = 40                            # grid cells: the base area (ticket office + parking) stays this far inside
SETTING_KEYS = ('units', 'layer', 'view')
# resort names: plain letters / digits / space and a little punctuation (the page turns accents into plain letters)
NAME_CHARS = re.compile(r"[A-Za-z0-9 '.&()\-]+")
NAME_RULE = "Names can use letters A-Z, numbers, spaces and - ' . & ( )"


class UserError(Exception):
    """a problem the player can fix; shown as is"""


def _friendly(e):
    if isinstance(e, (UserError, install.InstallError, gamedata.GameDataError, dem.DemError, net.NetError,
                      builder.BuildError, resort.ResortError, update.UpdateError)):
        return str(e)
    if isinstance(e, MemoryError):
        return 'Your PC ran out of memory while building the map. Close other programs and try again.'
    if isinstance(e, OSError) and getattr(e, 'winerror', None) in (32, 33):
        return 'A game file is in use. Close Ski-E-O (and the Map Installer) and try again.'
    if isinstance(e, OSError) and e.errno == 28:
        return 'Your disk is full. Free up some space and try again.'
    return 'Something went wrong (%s). Details are in the log -- use "Copy diagnostics" to share it.' % type(e).__name__


def _data_url(img, fmt='JPEG', quality=85):
    b = io.BytesIO()
    img.save(b, fmt, quality=quality) if fmt == 'JPEG' else img.save(b, fmt, optimize=True)
    return 'data:image/%s;base64,%s' % (fmt.lower(), base64.b64encode(b.getvalue()).decode('ascii'))


class Job:
    def __init__(self, kind, api):
        self.id = secrets.token_hex(4)
        self.kind = kind
        self.api = api
        self.cancel = net.CancelToken()
        self.state = 'running'
        self.fraction = 0.0
        self.text = ''
        self.result = None
        self.error = None
        self.needs = None                 # a service whose access key is missing (credentials.PROVIDERS id)
        self._last_emit = 0.0

    def progress(self, fraction, text):
        self.fraction = max(self.fraction, min(1.0, float(fraction)))
        self.text = text
        now = time.monotonic()
        if now - self._last_emit > 0.12:
            self._last_emit = now
            self.api._emit('job', self.as_dict())

    def as_dict(self):
        return dict(id=self.id, kind=self.kind, state=self.state, fraction=round(self.fraction, 3), text=self.text,
                    result=self.result, error=self.error, needs=self.needs)


class Api:
    def __init__(self):
        self._window = None
        self._settings = paths.Settings()
        self._lock = threading.Lock()
        self._job = None
        self._game = None
        self._gd = None
        self._preview = None
        self._search_rate = net.RateLimit(1.1)
        self._registry_checked = False
        self._update = None                    # the newer release check_update found
        self._done = {}                        # main()'s: set 'exe' / 'old' and close the window to restart as them

    # ------------------------------------------------------------ plumbing

    def _attach(self, window):
        self._window = window

    def _emit(self, kind, payload):
        w = self._window
        if w is None:
            return
        try:
            w.evaluate_js('window.app && window.app.onEvent(%s, %s)' % (json.dumps(kind), json.dumps(payload)))
        except Exception:
            pass

    def _run(self, kind, work):
        with self._lock:
            if self._job and self._job.state in ('running', 'waiting'):
                raise UserError('Please wait until the current task has finished.')
            job = self._job = Job(kind, self)

        def target():
            try:
                job.result = work(job)
                job.state = 'done'
            except net.Cancelled:
                job.state = 'cancelled'
                job.text = 'Cancelled'
            except credentials.Needed as e:
                log.info('%s needs an access key for %s', kind, e.provider)
                job.state = 'error'
                job.error = str(e)
                job.needs = e.provider
            except Exception as e:
                log.error('%s failed:\n%s', kind, traceback.format_exc())
                job.state = 'error'
                job.error = _friendly(e)
            self._emit('job', job.as_dict())

        threading.Thread(target=target, daemon=True, name=kind).start()
        return job.as_dict()

    def _safe(fn):
        """API methods return {'ok': True, ...} or {'ok': False, 'error': message} instead of raising into JS"""
        def wrapper(self, *a, **kw):
            try:
                r = fn(self, *a, **kw)
                return dict(r or {}, ok=True) if isinstance(r, dict) or r is None else {'ok': True, 'value': r}
            except Exception as e:
                if not isinstance(e, UserError):
                    log.error('%s failed:\n%s', fn.__name__, traceback.format_exc())
                return {'ok': False, 'error': _friendly(e)}
        wrapper.__name__ = fn.__name__
        return wrapper

    # ------------------------------------------------------------ startup / game

    @staticmethod
    def _clean_incomplete():
        """folders of builds that never finished (app closed or crashed mid-build): no map.json"""
        if not paths.MAPS.is_dir():
            return
        for d in paths.MAPS.iterdir():
            if d.is_dir() and not (d / 'map.json').is_file():
                log.info('removing incomplete build %s', d.name)
                shutil.rmtree(d, ignore_errors=True)

    @_safe
    def name_ok(self, name):
        n = re.sub(r'\s+', ' ', str(name or '')).strip()
        if not n:
            return dict(valid=False, message='')
        if len(n) < 2:
            return dict(valid=False, message='The name needs at least 2 characters.')
        if not NAME_CHARS.fullmatch(n):
            return dict(valid=False, message=NAME_RULE)
        own = self._own_record(n)
        if n.lower() in self._taken_names(exclude_id=PREFIX + own['slug'] if own else None):
            return dict(valid=False, message='You already have a map called "%s".' % n)
        if own:
            return dict(valid=True, replaces=True, message='Map name already exists. Save files will be corrupted!')
        return dict(valid=True, message='')

    @_safe
    def init(self):
        if not self._busy():
            self._clean_incomplete()
        return dict(version=VERSION, app=APP_NAME, game=self._game_status(), biomes=biomes.listing(),
                    settings={k: self._settings.get(k) for k in SETTING_KEYS}, maps=self._maps(), token=server.TOKEN,
                    limits=dict(min_km=MIN_KM, max_km=MAX_KM, min_trees=trees.MIN_TREES, max_trees=trees.max_trees(MAX_KM),
                                trees_per_km2=trees.TREES_PER_KM2,
                                min_slope=trees.MIN_TREE_SLOPE,
                                max_slope=trees.MAX_TREE_SLOPE, default_slope=trees.TREE_SLOPE,
                                default_fade=trees.TREELINE_FADE, max_fade=trees.MAX_TREELINE_FADE))

    def _find_game(self):
        f = self._settings.get('game_folder')
        if f and install.is_valid_game(f):
            return f, install.manifest(f).get('buildid')
        return install.find_game()

    def _game_status(self):
        folder, build = self._find_game()
        if not folder:
            self._game = self._gd = None
            return dict(found=False)
        if not self._game or str(self._game.folder) != str(folder):
            self._game = install.Game(folder, build)
            self._gd = None
        self._game.build = build
        if self._gd is None or self._gd.fp != gamedata.game_fingerprint(folder):
            self._gd = gamedata.GameData(folder)
        install.raise_tree_limit(folder)
        running = install.game_running()
        if not running:
            modlib.refresh(folder)                      # lift packs: keep their building table in step with the game
            if not self._registry_checked and not self._busy():
                self._registry_checked = True           # once a session: the map list of maps installed by an older
                try:                                    # version (e.g. tutorial maps, see install.custom_entry)
                    if self._game.registry_stale():
                        self._game.rebuild_registry()
                        log.info('map list rebuilt for this version')
                except Exception as ex:                 # never let this break the status check
                    log.warning('map list rebuild failed: %s', ex)
        return dict(found=True, folder=str(folder), build=build, running=running, ready=self._gd.ready())

    @_safe
    def game_status(self):
        return self._game_status()

    @_safe
    def pick_game_folder(self):
        r = self._window.create_file_dialog(20, directory='')            # 20 = FileDialog.FOLDER
        if not r:
            return dict(game=self._game_status(), changed=False)
        p = r[0] if isinstance(r, (list, tuple)) else r
        for cand in (p, os.path.dirname(p), os.path.dirname(os.path.dirname(p))):
            if install.is_demo(cand):
                raise UserError('That is the Ski-E-O demo. The Map Creator works with the full game (Ski-E-O! Ski '
                                'Resort Tycoon) only.')
            if install.is_valid_game(cand):
                self._settings.set(game_folder=str(cand))
                return dict(game=self._game_status(), changed=True)
        raise UserError('That folder doesn\'t look like the Ski-E-O game folder (the one that contains '
                        '"SkiResortSimulator").')

    def _require_game(self):
        st = self._game_status()
        if not st['found']:
            raise UserError('Ski-E-O was not found. Use "Locate game" and pick the game folder.')
        return st

    def _prepare(self, job, base=0.0, span=1.0):
        if not self._gd.ready():
            self._gd.prepare(lambda f, t: job.progress(base + span * f, t))

    @_safe
    def prepare_game(self):
        self._require_game()
        return self._run('prepare', lambda job: (self._prepare(job), self._game_status())[1])

    # ------------------------------------------------------------ map page helpers

    @_safe
    def search(self, query):
        q = (query or '').strip()
        if not q:
            return dict(results=[])
        m = re.fullmatch(r'\s*(-?\d+(?:\.\d+)?)\s*[, ]\s*(-?\d+(?:\.\d+)?)\s*', q)
        if m and abs(float(m.group(1))) <= 90 and abs(float(m.group(2))) <= 180:
            return dict(results=[dict(label='%.5f, %.5f' % (float(m.group(1)), float(m.group(2))),
                                      lat=float(m.group(1)), lon=float(m.group(2)), kind='coordinates')])
        try:
            out = self._photon(q)
        except (net.NetError, ValueError, KeyError) as e:
            log.warning('photon search failed: %s', e)
            out = []
        if not out:
            out = self._nominatim(q)
        return dict(results=out[:10])

    @staticmethod
    def _rank(key, value, name):
        n = name.lower()
        if value == 'winter_sports' or ('ski' in n and key in ('leisure', 'landuse', 'tourism', 'sport', 'amenity')):
            return 3, 'Ski area'
        if value in ('peak', 'volcano', 'mountain_range', 'ridge', 'massif', 'hill'):
            return 2, value.replace('_', ' ').capitalize()
        if key == 'place' or (key == 'boundary' and value == 'administrative'):
            return 1, (value if key == 'place' else 'place').replace('_', ' ').capitalize()
        if key in ('highway', 'building', 'shop', 'office') or value in ('residential', 'house'):
            return -2, value.replace('_', ' ').capitalize()
        return 0, value.replace('_', ' ').capitalize()

    @staticmethod
    def _fit_km(w, s, e, n):
        """square size that holds a ski area's outline with some room around it"""
        lat = (s + n) / 2
        dx = abs(e - w) * 111320 * math.cos(math.radians(lat))
        dy = abs(n - s) * 110574
        return float(np.clip(round(max(dx, dy) * 1.6 / 500.0) / 2.0, MIN_KM, MAX_KM))

    def _photon(self, q):
        from urllib.parse import quote
        self._search_rate.wait()
        data = json.loads(net.get(PHOTON + quote(q[:200]), timeout=20, retries=1, per_host=1,
                                  accept='application/json').decode('utf-8'))
        out, seen = [], set()
        for i, f in enumerate(data.get('features', [])):
            p = f.get('properties', {})
            lon, lat = f['geometry']['coordinates'][:2]
            name = p.get('name') or p.get('street') or ''
            if not name:
                continue
            where = ', '.join(x for x in (p.get('state') or p.get('county'), p.get('country')) if x)
            label = name + (', ' + where if where else '')
            if label in seen:
                continue
            seen.add(label)
            score, kind = self._rank(p.get('osm_key', ''), p.get('osm_value', ''), name)
            r = dict(label=label, lat=float(lat), lon=float(lon), kind=kind, name=name, _s=(-score, i))
            ext = p.get('extent')                                  # [west, north, east, south]
            if ext and len(ext) == 4:
                w, n_, e, s = (float(v) for v in ext)
                r.update(lat=(n_ + s) / 2, lon=(w + e) / 2)
                if score == 3:
                    r['size_km'] = self._fit_km(w, s, e, n_)
            out.append(r)
        out.sort(key=lambda r: r.pop('_s'))
        return out

    def _nominatim(self, q):
        from urllib.parse import quote
        self._search_rate.wait()
        data = net.get(NOMINATIM + quote(q[:200]), timeout=20, retries=1, per_host=1, accept='application/json')
        out = []
        for r in json.loads(data.decode('utf-8')):
            try:
                name = (r.get('name') or r.get('display_name', '').split(',')[0]).strip()
                score, kind = self._rank(r.get('category', ''), r.get('type', ''), name)
                out.append(dict(label=r.get('display_name', '')[:160], lat=float(r['lat']), lon=float(r['lon']),
                                kind=kind, name=name, _s=(-score, -float(r.get('importance') or 0))))
            except (KeyError, ValueError):
                continue
        out.sort(key=lambda r: r.pop('_s'))
        return out

    @_safe
    def defaults(self, lat, lon):
        return biomes.defaults(float(lat), float(lon))

    @_safe
    def set_setting(self, key, value):
        if key in SETTING_KEYS:
            self._settings.set(**{key: value})

    @_safe
    def mod_library(self):
        st = self._game_status()
        return dict(found=False) if not st['found'] else dict(found=True, running=st['running'], **modlib.status(st['folder']))

    @_safe
    def set_mod(self, mod_id, on):
        st = self._game_status()
        if not st['found']:
            raise UserError('Ski-E-O was not found.')
        if mod_id not in modlib.MODS:
            raise UserError('Unknown mod.')
        if install.game_running():
            raise UserError('Close Ski-E-O first, then try again.')
        if on and next(m for m in modlib.status(st['folder'])['mods'] if m['id'] == mod_id)['included']:
            raise UserError('Your own lift mod (ZZZ_LiftMod_P) already has this lift. Installing it twice would clash.')
        log.info('mod %s -> %s', mod_id, 'on' if on else 'off')
        return dict(found=True, running=False, **modlib.set_mod(st['folder'], mod_id, bool(on)))

    # ------------------------------------------------------------ access keys of national elevation services

    @_safe
    def key_info(self, provider):
        if provider not in credentials.PROVIDERS:
            raise UserError('Unknown service.')
        return credentials.info(provider)

    @_safe
    def key_set(self, provider, values):
        if provider not in credentials.PROVIDERS:
            raise UserError('Unknown service.')
        ok, msg = credentials.set_key(provider, values or {})
        if not ok:
            raise UserError(msg)
        log.info('access key for %s entered (this session only)', provider)
        return dict(note=msg)

    @_safe
    def key_skip(self, provider):
        if provider not in credentials.PROVIDERS:
            raise UserError('Unknown service.')
        credentials.skip(provider)
        log.info('access key for %s skipped: free worldwide data is used there', provider)

    @_safe
    def link(self, name):
        if name in LINKS:
            webbrowser.open(LINKS[name])

    @_safe
    def play(self):
        os.startfile(GAME_URL)

    @_safe
    def diagnostics(self):
        st = {}
        try:
            st = self._game_status()
        except Exception as e:
            st = {'error': repr(e)}
        head = ['%s %s' % (APP_NAME, VERSION), 'Windows %s' % platform.version(), 'game: %s' % json.dumps(st),
                'app folder: %s' % paths.APP_DIR, '']
        return dict(text='\n'.join(head) + paths.log_tail(250))

    # ------------------------------------------------------------ preview

    @_safe
    def preview(self, lat, lon, size_km, rot=0):
        lat, lon, size_km, rot = float(lat), float(lon), float(size_km), dem.norm_rot(rot)
        if not (MIN_KM <= size_km <= MAX_KM):
            raise UserError('The area must be between %g and %g km wide.' % (MIN_KM, MAX_KM))
        if abs(lat) > 84:
            raise UserError('Elevation data does not cover the polar regions.')
        return self._run('preview', lambda job: self._do_preview(job, lat, lon, size_km, rot))

    def _do_preview(self, job, lat, lon, size_km, rot=0.0):
        size_m = size_km * 1000.0
        d, src, datasets = dem.load_sources(lat, lon, size_m, job.cancel, lambda f, t: job.progress(0.75 * f, t), rot=rot)
        job.progress(0.78, 'Analysing the terrain...')
        H, fr = builder.heights(d, size_m)
        slope = builder.slope_deg(H, fr)
        job.cancel.check()
        row, col = builder.suggest_base(H, fr)
        g = geo.LocalGrid(lat, lon, rot)
        blat, blon = g.to_latlon(col * fr.sp - fr.half, fr.half - row * fr.sp)
        job.progress(0.85, 'Rendering the preview...')
        dio = builder.render_preview(H, fr, W=960, Hh=540, step=10)
        job.cancel.check()
        shade = self._shaded_relief(d, fr)
        step = 16
        grid = np.round(d[::step, ::step]).astype(int).tolist()
        relief = float(d.max() - d.min())
        warnings = []
        if relief < 150:
            warnings.append('This area is very flat (%.0f m of relief). Pick an area with a hill or mountain.' % relief)
        if float((slope > 45).mean()) > 0.25:
            warnings.append('A lot of this area is cliffs steeper than 45 degrees. Skiers need gentler slopes.')
        self._preview = dict(lat=lat, lon=lon, size_km=size_km, rot=rot, dem=d, src=src, base=[float(blat), float(blon)])
        return dict(lat=lat, lon=lon, size_km=size_km, rot=rot, source=dem.SOURCES[src]['name'], source_id=src, datasets=list(datasets),
                    credit=dem.SOURCES[src]['credit'], peak_m=float(d.max()), base_m=float(d.min()),
                    mean_m=float(d.mean()), relief_m=relief, mean_slope=float(slope.mean()), steep=float((slope > 35).mean()),
                    base=[float(blat), float(blon)], diorama=_data_url(dio, 'JPEG', 82), shade=_data_url(shade, 'PNG'),
                    grid=dict(step_m=fr.sp * step, n=len(grid), data=grid), warnings=warnings,
                    defaults=biomes.defaults(float(blat), float(blon)))

    @_safe
    def osm(self):
        """the real resort's trails and lifts (OpenStreetMap) on the loaded terrain: counts, map lines"""
        if not self._preview:
            raise UserError('Load the terrain first.')
        return self._run('osm', lambda job: self._do_osm(job, self._preview))

    @_safe
    def trees(self):
        """the real tree cover of the loaded terrain (satellite canopy heights): downloads it now, so the build finds it cached"""
        if not self._preview:
            raise UserError('Load the terrain first.')
        return self._run('trees', lambda job: self._do_trees(job, self._preview))

    def _do_trees(self, job, pv):
        terrain = self._osm_terrain(pv)
        try:
            cover = resort.tree_cover_all(terrain, lambda la, lo: canopy.heights(
                la, lo, job.cancel, lambda f, t: None, nodata=resort.COVER_NODATA),      # one text and one bar: the rows'
                lambda f, t: job.progress(f, t))
        except (net.NetError, canopy.CanopyError) as ex:
            raise UserError('The tree cover could not be downloaded right now (%s). Try again in a moment.'
                            % str(ex).split(' Check your')[0].rstrip('.'))
        return dict(percent=int(round(100 * float(cover.mean()))))

    @staticmethod
    def _osm_terrain(pv):
        size_m = pv['size_km'] * 1000.0
        H, fr = builder.heights(pv['dem'], size_m)
        return resort.Terrain(H, fr, pv['lat'], pv['lon'], size_m, pv.get('rot', 0.0))

    def _do_osm(self, job, pv):
        raw = resort.fetch(pv['lat'], pv['lon'], pv['size_km'] * 1000.0, job.cancel, lambda f, t: job.progress(0.7 * f, t),
                           rot=pv.get('rot', 0.0))
        job.progress(0.75, 'Fitting the trails and lifts to the terrain...')
        terrain = self._osm_terrain(pv)
        pl = resort.plan(json.loads(raw), terrain, canopy=lambda la, lo: canopy.heights(
            la, lo, job.cancel, lambda f, t: job.progress(0.75 + 0.2 * f, t)))
        if not pl['lifts'] and not pl['trails']:
            raise UserError('The trails in this square are all glades (skiing through the trees), which the game doesn\'t '
                            'have yet, and there are no lifts.' if pl['glades'] else
                            'OpenStreetMap has no ski trails or lifts inside this square.')
        pv['osm'] = raw
        return dict(summary=resort.summary(pl), lines=resort.overlay(pl, terrain))

    @_safe
    def diorama(self, height_modifier=1.0, height_offset=0.0):
        """re-render the inline diorama preview with the given height modifier and offset

        height_modifier: multiplies terrain relief around the mean (0.1-2)
        height_offset: shifts altitude up/down in meters (-2000..2000); it only changes the shape where land
        would go below 0 m, which is put to 1 m
        """
        pv = self._preview
        if not pv:
            raise UserError('Load the terrain first.')
        d = np.asarray(pv['dem'], np.float64)
        hm = float(np.clip(float(height_modifier), 0.1, 2.0))
        ho = float(np.clip(float(height_offset), -builder.HEIGHT_OFFSET_MAX, builder.HEIGHT_OFFSET_MAX))
        if hm != 1.0 or ho != 0.0:
            d_mean = d.mean()
            d = d_mean + (d - d_mean) * hm + ho
        d = np.where(d < 0, 1.0, d)
        size_m = pv['size_km'] * 1000.0
        try:
            H, fr = builder.heights(d, size_m)
            img = builder.render_preview(H, fr, W=960, Hh=540, step=10)
            return _data_url(img, 'JPEG', 82)
        except Exception:
            log.warning('Diorama render failed with modifier=%.1f', hm, exc_info=True)
            raise UserError('Could not render the preview with these settings. Try a smaller height modifier.')

    @_safe
    def view3d(self, treeline_m=None, height_modifier=1.0, height_offset=0.0):
        """heights + colour texture of the loaded terrain for the 3D view (served from the local server)

        height_modifier: multiplies terrain relief around the mean (0.1-2)
        height_offset: shifts altitude up/down in meters
        """
        pv = self._preview
        if not pv:
            raise UserError('Load the terrain first.')
        from . import view3d
        tl = float(treeline_m) if treeline_m is not None else 0.0
        hm = float(np.clip(float(height_modifier), 0.1, 2.0))
        ho = float(np.clip(float(height_offset), -builder.HEIGHT_OFFSET_MAX, builder.HEIGHT_OFFSET_MAX))
        heights, meta, albedo = view3d.build(pv['dem'], pv['size_km'] * 1000.0, tl, hm, ho)
        ver = secrets.token_hex(4)
        server.BLOBS['heights'] = (heights, 'application/octet-stream')
        server.BLOBS['albedo'] = (albedo, 'image/jpeg')
        rot = pv.get('rot', 0.0)
        g = geo.LocalGrid(pv['lat'], pv['lon'], rot)
        half = pv['size_km'] * 500.0
        base = pv.get('base')
        bx = by = None
        if base:
            x, y = g.to_xy(base[0], base[1])
            bx, by = float(x), float(y)
        cla, clo = g.to_latlon(np.array([-half, half, half, -half]), np.array([half, half, -half, -half]))   # the 4 corners
        r, c = np.unravel_index(int(np.argmax(pv['dem'])), pv['dem'].shape)
        sp = pv['size_km'] * 1000.0 / (pv['dem'].shape[0] - 1)
        return dict(meta, version=ver, base=[bx, by] if bx is not None else None,
                    peak=[float(c * sp - half), float(half - r * sp)],
                    bbox=dict(n=float(cla.max()), s=float(cla.min()), w=float(clo.min()), e=float(clo.max())),
                    rot=float(rot), center=[float(pv['lat']), float(pv['lon'])])

    @staticmethod
    def _shaded_relief(d, fr, n=512):
        k = (d.shape[0] - 1) // (n - 1)
        z = d[::k, ::k][:n, :n].astype(np.float64)
        gy, gx = np.gradient(z, fr.sp * k)
        nz = 1 / np.sqrt(gx * gx + gy * gy + 1)
        L = np.array([-0.5, 0.5, 0.7])
        L /= np.linalg.norm(L)
        sh = np.clip((-gx * L[0] + gy * L[1] + L[2]) * nz, 0, 1)        # row 0 = north: +gy points south
        zn = (z - z.min()) / max(z.max() - z.min(), 1.0)
        lo, hi = np.array([70, 110, 80]), np.array([240, 240, 245])
        col = lo[None, None] * (1 - zn[..., None]) + hi[None, None] * zn[..., None]
        col = col * (0.45 + 0.75 * sh[..., None])
        rgba = np.dstack([np.clip(col, 0, 255), np.full(z.shape, 255.0)]).astype(np.uint8)
        return Image.fromarray(rgba, 'RGBA')

    # ------------------------------------------------------------ create

    @_safe
    def create(self, params):
        p = self._validate(params)
        return self._run('create', lambda job: self._do_create(job, p))

    def _own_record(self, name):
        """the map made with this app that has this name (it is replaced by a new one with the same name), or None"""
        n = name.strip().lower()
        return next((r for r in self._records() if r['name'].strip().lower() == n), None)

    def _taken_names(self, exclude_id=None):
        names = set()
        if self._game:
            names |= {m['name'].strip().lower() for i, m in self._game.installed().items() if i != exclude_id}
        for rec in self._records():
            if PREFIX + rec['slug'] != exclude_id:
                names.add(rec['name'].strip().lower())
        return names

    def _validate(self, params):
        st = self._require_game()
        pv = self._preview
        name = re.sub(r'\s+', ' ', str(params.get('name') or '')).strip()
        if not (2 <= len(name) <= 40) or any(ord(c) < 32 for c in name):
            raise UserError('Give the map a name of 2 to 40 characters.')
        if not NAME_CHARS.fullmatch(name):
            raise UserError(NAME_RULE + '.')
        own = self._own_record(name)
        if name.lower() in self._taken_names(exclude_id=PREFIX + own['slug'] if own else None):
            raise UserError('A map called "%s" already exists. Pick another name.' % name)
        if not pv or abs(pv['lat'] - float(params['lat'])) > 1e-7 or abs(pv['lon'] - float(params['lon'])) > 1e-7 \
                or abs(pv['size_km'] - float(params['size_km'])) > 1e-9 \
                or abs(pv.get('rot', 0.0) - dem.norm_rot(params.get('rot', 0))) > 0.05:
            raise UserError('The area changed since the terrain preview. Press "Load terrain" again first.')
        biome = params.get('biome')
        if biome not in biomes.BIOMES:
            raise UserError('Pick a biome.')
        osm = pv.get('osm') if params.get('osm') else None
        if params.get('osm') and not osm:
            raise UserError('The real trails and lifts are not loaded yet. Switch the option off and on again.')
        osm_skip = sorted({int(i) for i in params.get('osm_skip') or ()})       # lifts the player left out
        size_m = pv['size_km'] * 1000.0
        sp, half = size_m / (builder.G - 1), size_m / 2
        base = params['base']
        if osm:                            # the ticket office at the real resort's main base, among the lifts kept
            terrain = self._osm_terrain(pv)
            base = resort.suggest_base(resort.plan(json.loads(osm), terrain, skip=osm_skip), terrain,
                                       margin_m=(BASE_MARGIN + 2) * sp) or base
        g = geo.LocalGrid(pv['lat'], pv['lon'], pv.get('rot', 0.0))
        bx, by = g.to_xy(float(base[0]), float(base[1]))
        col, row = (float(bx) + half) / sp, (half - float(by)) / sp
        if not (BASE_MARGIN <= row <= builder.G - 1 - BASE_MARGIN and BASE_MARGIN <= col <= builder.G - 1 - BASE_MARGIN):
            raise UserError('Put the base area marker inside the square (not right at its edge).')
        treeline_m = float(params.get('treeline_m', biomes.default_treeline(biome, pv['lat'])))
        height_modifier = float(np.clip(float(params.get('height_modifier', 1.0)), 0.1, 2.0))
        height_offset = float(np.clip(float(params.get('height_offset', 0)), -builder.HEIGHT_OFFSET_MAX, builder.HEIGHT_OFFSET_MAX))
        if height_offset == 0:
            raise UserError('Height offset must be a non-zero value.')
        return dict(name=name, replace=own['slug'] if own else None, lat=pv['lat'], lon=pv['lon'], rot=pv.get('rot', 0.0), size_m=size_m, size_km=pv['size_km'], biome=biome,
                    treeline=float(np.clip(treeline_m, 0, 9000)), valley=float(np.clip(float(params.get('valley_m') or 0), 0, 9000)),
                    snow=float(np.clip(float(params.get('snow', 1.0)), 0.2, 3.0)),
                    max_trees=int(np.clip(int(float(params.get('max_trees') or trees.DEFAULT_TREES)), trees.MIN_TREES, trees.max_trees(pv['size_km']))),
                    tree_slope=float(np.clip(float(params.get('tree_slope') or trees.TREE_SLOPE), trees.MIN_TREE_SLOPE, trees.MAX_TREE_SLOPE)),
                    treeline_fade=float(np.clip(float(params.get('treeline_fade', trees.TREELINE_FADE)), 0, trees.MAX_TREELINE_FADE)),
                    height_modifier=height_modifier, height_offset=height_offset,
                    acres=int(np.clip(int(params.get('acres') or 0) or self._acres(size_m), 10, 50000)),
                    base_rc=[row, col], base_latlon=[float(base[0]), float(base[1])],
                    source=pv['src'], seed=secrets.randbelow(2 ** 31 - 1) + 1, tg=secrets.randbelow(2 ** 31 - 2) + 1,
                    game=st, osm=osm, osm_skip=osm_skip, real_trees=bool(params.get('real_trees')))

    @staticmethod
    def _acres(size_m):
        return int(round(size_m * size_m / 4046.86 * 0.06 / 10.0) * 10)

    def _do_create(self, job, p):
        self._prepare(job, 0.0, 0.05)
        taken = {r['slug'] for r in self._records()} | {i[len(PREFIX):] for i in self._game.installed() if i.startswith(PREFIX)}
        old = self._record(p['replace']) if p.get('replace') else None        # same name as a saved map: it is built anew in its place
        slug = old['slug'] if old else builder.new_slug(p['name'], taken)
        spec = dict((k, p[k]) for k in ('name', 'lat', 'lon', 'rot', 'size_m', 'biome', 'treeline', 'valley', 'snow', 'max_trees',
                                        'tree_slope', 'treeline_fade', 'height_modifier', 'height_offset', 'acres', 'base_rc', 'base_latlon', 'seed', 'tg', 'source'))
        spec['slug'] = slug
        if old:
            spec['version'] = int(old.get('version', 1)) + 1
        if p.get('real_trees'):            # kept with the map, so a rebuild places the trees the same way
            spec['real_trees'] = True
        if p['osm']:                       # kept with the map, so a rebuild makes the same trails and lifts
            paths.atomic_write(paths.MAPS / slug / 'osm.json', p['osm'])
            spec.update(osm=True, osm_skip=p['osm_skip'])
        d = self._preview['dem'] if self._preview else None
        if d is None:
            d, _ = dem.load(p['lat'], p['lon'], p['size_m'], job.cancel, lambda f, t: job.progress(0.05 + 0.1 * f, t), prefer=p['source'],
                            rot=p['rot'])
        rec = self._build_and_package(job, spec, d, 0.05, 0.9, order=old.get('order', self._next_order()) if old else self._next_order())
        if old:
            rec['version'] = spec['version']
            paths.atomic_write(paths.MAPS / slug / 'map.json', json.dumps(rec, indent=1).encode('utf-8'))
        self._install_when_closed(job, rec, 0.9)
        return self._map_view(rec)

    def _next_order(self):
        used = [m.get('order', 0) for m in (self._game.installed().values() if self._game else [])]
        used += [r.get('order', 0) for r in self._records()]
        return max([ORDER_BASE] + used) + 10

    def _build_and_package(self, job, spec, d, a, b, order):
        slug = spec['slug']
        out = paths.MAPS / slug
        out.mkdir(parents=True, exist_ok=True)
        res = builder.build(spec, d, self._gd, out, job.cancel, lambda f, t: job.progress(a + (b - a) * f, t))
        res['preview'].resize((640, 360), Image.LANCZOS).save(out / 'preview.jpg', quality=85)
        pkg_name = re.sub(r'[^A-Za-z0-9 _-]+', '', spec['name']).strip().replace(' ', '_') or slug
        man = dict(id=PREFIX + slug, name=spec['name'], version=int(spec.get('version', 1)), order=order,
                   files=res['files'], entry=res['entry'], game_build=self._game.build, format=builder.ENTRY_FORMAT,
                   creator=dict(version=VERSION, lat=spec['lat'], lon=spec['lon'], size_m=spec['size_m'], biome=spec['biome']))
        pkg = out / (pkg_name + '.skimap')
        install.make_package(pkg, man, out)
        rec = dict(slug=slug, name=spec['name'], order=order, spec=spec, stats=res['stats'], package=pkg.name,
                   files=res['files'], game_fp=self._gd.fp, game_build=self._game.build, creator=VERSION, recipe=builder.recipe(spec, res['stats']),
                   created=datetime.datetime.now().isoformat(timespec='seconds'))
        paths.atomic_write(out / 'map.json', json.dumps(rec, indent=1).encode('utf-8'))
        return rec

    def _install_when_closed(self, job, rec, a):
        pkg = paths.MAPS / rec['slug'] / rec['package']
        if install.game_running():
            job.state = 'waiting'
            job.progress(a, 'Map built. Close Ski-E-O to finish installing it...')
            while install.game_running():
                job.cancel.sleep(2.0)
            job.state = 'running'
            job.cancel.sleep(3.0)                                  # let the game release its files
        job.progress(a + 0.02, 'Installing into Ski-E-O...')
        self._game.install(str(pkg), lambda t: job.progress(a + 0.05, t))
        job.progress(1.0, 'Installed')

    # ------------------------------------------------------------ my maps

    @staticmethod
    def _records():
        out = []
        if not paths.MAPS.is_dir():
            return out
        for d in paths.MAPS.iterdir():
            try:
                rec = json.loads((d / 'map.json').read_text(encoding='utf-8'))
                if (d / rec['package']).is_file():
                    out.append(rec)
            except (OSError, ValueError, KeyError):
                continue
        return sorted(out, key=lambda r: r.get('created', ''), reverse=True)

    def _record(self, slug):
        if not re.fullmatch(r'[a-z0-9_]{14}', str(slug)):
            raise UserError('Unknown map.')
        try:
            return json.loads((paths.MAPS / slug / 'map.json').read_text(encoding='utf-8'))
        except (OSError, ValueError):
            raise UserError('That map\'s files are missing.')

    def _map_view(self, rec):
        inst = self._game.installed() if self._game else {}
        m = inst.get(PREFIX + rec['slug'])
        installed = bool(m) and all((self._game.mods / f).is_file() for f in m['files'])
        thumb = paths.MAPS / rec['slug'] / 'preview.jpg'
        stale = bool(self._gd and rec.get('game_fp') and rec['game_fp'] != self._gd.fp) \
            or rec.get('recipe', 1) < builder.recipe(rec['spec'])     # made by an older creator: rebuild for its fixes
        s = rec['spec']
        return dict(slug=rec['slug'], name=rec['name'], created=rec.get('created'), installed=installed, stale=stale,
                    lat=s['lat'], lon=s['lon'], rot=s.get('rot', 0.0), size_km=s['size_m'] / 1000.0, biome=s['biome'],
                    biome_label=biomes.BIOMES.get(s['biome'], {}).get('label', s['biome']), stats=rec.get('stats', {}),
                    thumb=_data_url(Image.open(thumb), 'JPEG', 80) if thumb.is_file() else None)

    def _maps(self):
        return [self._map_view(r) for r in self._records()]

    @_safe
    def maps(self):
        self._game_status()
        return dict(maps=self._maps())

    @_safe
    def install_map(self, slug):
        rec = self._record(slug)
        self._require_game()

        def work(job):
            self._install_when_closed(job, rec, 0.0)
            return self._map_view(rec)
        return self._run('install', work)

    @_safe
    def uninstall_map(self, slug):
        rec = self._record(slug)
        self._require_game()
        if install.game_running():
            raise UserError('Close Ski-E-O first, then try again.')

        def work(job):
            job.progress(0.2, 'Removing %s from the game...' % rec['name'])
            self._game.uninstall(PREFIX + slug, lambda t: job.progress(0.5, t))
            return self._map_view(rec)
        return self._run('uninstall', work)

    @_safe
    def delete_map(self, slug):
        rec = self._record(slug)
        self._require_game()
        if install.game_running():
            raise UserError('Close Ski-E-O first, then try again.')

        def work(job):
            if PREFIX + slug in self._game.installed():
                job.progress(0.3, 'Removing %s from the game...' % rec['name'])
                self._game.uninstall(PREFIX + slug, lambda t: job.progress(0.6, t))
            shutil.rmtree(paths.MAPS / slug, ignore_errors=True)
            return dict(slug=slug, deleted=True)
        return self._run('delete', work)

    @_safe
    def rebuild_map(self, slug):
        rec = self._record(slug)
        self._require_game()

        def work(job):
            self._prepare(job, 0.0, 0.05)
            s = dict(rec['spec'], version=int(rec.get('version', 1)) + 1)
            d, _ = dem.load(s['lat'], s['lon'], s['size_m'], job.cancel, lambda f, t: job.progress(0.05 + 0.15 * f, t),
                            prefer=s['source'], rot=s.get('rot', 0.0))
            new = self._build_and_package(job, s, d, 0.2, 0.9, order=rec.get('order', self._next_order()))
            new['version'] = s['version']
            paths.atomic_write(paths.MAPS / slug / 'map.json', json.dumps(new, indent=1).encode('utf-8'))
            self._install_when_closed(job, new, 0.9)
            return self._map_view(new)
        return self._run('rebuild', work)

    @_safe
    def export_map(self, slug):
        rec = self._record(slug)
        src = paths.MAPS / slug / rec['package']
        docs = os.path.join(os.path.expanduser('~'), 'Documents')
        r = self._window.create_file_dialog(30, directory=docs if os.path.isdir(docs) else '',     # 30 = FileDialog.SAVE
                                            save_filename=rec['package'], file_types=('Ski-E-O map (*.skimap)',))
        if not r:
            return dict(saved=False)
        dst = r[0] if isinstance(r, (list, tuple)) else r
        if not dst.lower().endswith('.skimap'):
            dst += '.skimap'
        shutil.copyfile(src, dst)
        return dict(saved=True, path=dst, size_mb=round(os.path.getsize(dst) / 1e6, 1))

    @_safe
    def repair(self):
        self._require_game()
        if install.game_running():
            raise UserError('Close Ski-E-O first, then try again.')

        def work(job):
            job.progress(0.3, 'Rebuilding the game\'s map list...')
            self._game.rebuild_registry()
            return {}
        return self._run('repair', work)

    # ------------------------------------------------------------ jobs

    @_safe
    def job(self):
        return self._job.as_dict() if self._job else {}

    @_safe
    def cancel(self):
        if self._job and self._job.state in ('running', 'waiting'):
            self._job.cancel.cancel()

    def _busy(self):
        return bool(self._job and self._job.state in ('running', 'waiting'))

    # ------------------------------------------------------------ updates (the footer's Check for updates)

    @_safe
    def check_update(self):
        """the newest release on GitHub against this version"""
        if not getattr(sys, 'frozen', False):
            return dict(state='source', version=VERSION)
        try:
            rel = update.release()
        except (net.NetError, ValueError, KeyError, TypeError) as ex:
            log.info('update check failed: %s', ex)
            raise UserError('GitHub could not be reached to look for updates. Check your internet connection and try '
                            'again.')
        if not update.is_newer(rel):
            return dict(state='latest', version=VERSION)
        self._update = rel
        return dict(state='newer', version=rel['version'], current=VERSION, size_mb=max(1, rel['size'] >> 20),
                    notes=update.notes(rel['notes'], 400))

    @_safe
    def install_update(self):
        if not self._update:
            raise UserError('Look for updates first.')
        return self._run('update', lambda job: self._do_update(job, self._update))

    def _do_update(self, job, rel):
        """download, check and swap in the new exe (update.py), then close the window: main() starts the new one"""
        def progress(n, total):
            job.cancel.check()
            job.progress(0.95 * n / total if total else 0.0, 'Downloading %d of %d MB...' % (n >> 20, total >> 20))
        exe = Path(sys.executable)
        new = update.download(rel, exe.parent, progress)
        job.progress(0.97, 'Installing...')
        self._done['exe'], self._done['old'] = update.swap(new, exe)
        log.info('updated to %s from the app, restarting', rel['version'])
        threading.Timer(1.5, self._close).start()          # the page says "Restarting" first
        return dict(version=rel['version'])

    def _close(self):
        try:
            self._window.destroy()
        except Exception:                                   # noqa: BLE001  (closed already)
            pass

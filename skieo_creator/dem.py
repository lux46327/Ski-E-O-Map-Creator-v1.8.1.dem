"""Elevation for a square terrain window, sampled onto the game's 2017 x 2017 landscape grid (row 0 = north).

Resolution is chosen per window: every source is downloaded at the window's grid spacing (size / 2016), never finer
than 2 m and never finer than the source itself, from the most detailed product each country publishes. Large windows
therefore pull coarse data (or coarse internal levels of cloud-optimised GeoTIFFs), small windows the full detail.

Sources:
  * National and regional surveys, listed below in priority order (the first source with data at a point
    wins; a window across a border uses both countries' surveys), with AWS Terrain Tiles under all of them. Two ways
    of reading them: GeoTIFF files read in part over HTTP (`_tiles`, `_cog_mosaic`) or a coverage / image service
    asked for a GeoTIFF of the window (`_service`, `_wcs_grid`). Sources are only used inside their own countries
    (data/borders.npz).
      - USA          USGS Seamless 1-meter DEM (S1M; 10 km cloud-optimised GeoTIFFs, contiguous states, as far as
                     produced), then USGS 3DEP: the public 3DEPElevation ImageServer (best available, down to 1 m),
                     requested at the window's resolution
      - Canada       NRCan HRDEM Mosaic (Open Government Licence - Canada) through the CCMEO STAC API: the 1 m mosaic
                     (collection hrdem-mosaic-1m, which holds the provinces' lidar, British Columbia's included) when
                     the window's grid is finer than 2 m, else the 2 m mosaic (hrdem-mosaic-2m); about a fifth of
                     Canada, the populated south. North of ~60 N the ArcticDEM-based HRDEM (2 m, hrdem-arcticdem; a
                     surface model) fills in at the lowest priority; elsewhere Canada uses Terrain Tiles
      - Austria      BEV airborne laser scan terrain model, 1 m (CC BY 4.0): 50 km cloud-optimised GeoTIFFs in ETRS89-LAEA
                     (EPSG:3035), newest edition first (2025, 2024), wherever it is published, including the
                     provinces; elsewhere the Terrain Tiles' own 10 m DGM (data.gv.at) is kept sharp
      - Germany      Bavaria DGM1 (1 m, 1 km GeoTIFF tiles), where it exists; the rest of Germany uses Terrain Tiles
      - Switzerland  swisstopo swissALTI3D (2 m tiles via the swisstopo STAC API) while the window's grid is finer than
                     10 m; swissALTIRegio (10 m, one cloud-optimised GeoTIFF) for coarser grids and everywhere around
                     Switzerland it reaches (~100 km; the French and Italian surveys take precedence where they have data)
      - France       IGN LiDAR HD terrain model (0.5 m, read at the window's grid) where it is flown; IGN RGE ALTI on its
                     5 m grid for the rest; both Geoplateforme WMS-R in Lambert-93
      - Italy        regional lidar first where a region serves it per window: South Tyrol (2.5 m, whole
                     province; CC0, GeoServer WCS); INGV TINITALY 1.1 (10 m, CC BY 4.0), WCS 2.0 in UTM 32N, everywhere else
      - Spain        IGN MDT05 (5 m, CC BY 4.0), WCS coverage Elevacion25830_5 on its native UTM 30N grid
                     (Elevacion4258_5, ETRS89 geographic, as the fallback and for the Canary Islands)
      - Poland       GUGiK NMT, 1 m (WCS of the national geoportal)
      - Slovakia     UGKK SR DMR 5.0, 1 m (WCS of the INSPIRE service)
      - Czechia      CUZK DMR 5G, 2 m (ArcGIS ImageServer)
      - England      Environment Agency LIDAR Composite DTM, 1 m (WCS, OGL v3), where it is flown
      - Scotland     Scottish public-sector LiDAR DTM, 1 m (OGL v3): the newest survey phase of each 10 km square,
                     found in the public bucket's listing
      - Iceland      IslandsDEM 10 m (CC BY 4.0), one GeoTIFF read in parts
      - New Zealand  LINZ 1 m DEM from lidar where it exists, then the national 8 m DEM (CC BY 4.0), Topo50 sheet files
      - Australia    Geoscience Australia 5 m lidar DEM (CC BY 4.0, WCS), where it exists
      - Sweden       Lantmäteriet Markhöjdmodell (1 m, read at the window's grid), cloud-optimised GeoTIFF sheets
                     (collection dtm-cog) found through the public STAC search. Downloading needs a free key that the
                     app asks for (see credentials.py); without it Sweden uses Terrain Tiles
      - Norway       Kartverket national terrain model (1 m, CC BY 4.0), WCS in UTM 33N
      - Finland      National Land Survey elevation model (2 m, CC BY 4.0), WCS in ETRS-TM35FIN; needs a free NLS API
                     key that the app asks for (see credentials.py); without it Finland uses Terrain Tiles
      - Japan        GSI elevation tiles: 1 m from airborne lidar (DEM1A) where published, then 5 m from lidar
                     (DEM5A) or aerial photos (DEM5B, DEM5C), and the 10 m model (DEM10B) for the rest; map tiles
                     like Terrain Tiles
    A source is only asked for the part of the window it is needed for (inside its country and not yet covered by
    a source listed before it), sources of different countries are fetched at the same time, and a source whose
    part is already covered is not asked at all.
    Each national grid is resampled onto the window, checked against a Terrain Tiles base, and stitched by delta
    surface fill (see _blend): at every seam both sides are bent halfway, so they meet in the middle, and there are
    no steps where two surveys meet or where Terrain Tiles take over. A source on another height datum (a constant
    offset of more than DATUM_OFFSET_M against its surroundings) has that offset removed first.
  * '3dep2', '3dep' and 'terrarium': the Map Creator's first terrain kinds, unchanged, so that maps made with them
    rebuild the same (see _legacy_3dep); '3dep2' is USGS 3DEP alone, 'terrarium' is AWS Terrain Tiles (terrarium PNG,
    open data, global), the fallback everywhere

No-data in any source (sea, lakes, areas a survey does not cover) is filled from AWS Terrain Tiles, which cover the
whole globe, corrected to meet the surrounding survey data, so there is no step at the edge of the source's data.

Every national source is read as GeoTIFF (Japan's exists only as PNG elevation tiles). Only the window is downloaded from every source: the coverage services
(3DEP, IGN France and Spain, TINITALY, Kartverket, NLS, the German, Polish, Slovak, Czech, English and Australian ones) are asked
for the window's box, and the cloud-optimised GeoTIFFs (swisstopo, NRCan, Lantmäteriet, BEV, USGS, LINZ, Scotland) are read by
rasterio with HTTP range requests, fetching just the internal tiles that overlap it. Terrain Tiles come as fixed 256 px web tiles, so only the tiles
touching the window are fetched (no surrounding ring).

All sources are resampled with cubic convolution onto a local transverse Mercator grid centred on the window (see geo.py).
Standard libraries throughout: STAC catalogues (swisstopo, NRCan, Lantmäteriet) are searched with pystac-client,
every GeoTIFF is read with rasterio (cloud-optimised ones directly over HTTP, coarsest fitting overview, window only)
and coordinates are transformed with PROJ (rasterio.warp). Downloads are retried RETRIES times.
"""
import hashlib
import io
import json
import logging
import math
import re
import threading
import time
import warnings
from concurrent.futures import ThreadPoolExecutor

import numpy as np
from PIL import Image

from . import credentials, geo, net, paths

log = logging.getLogger(__name__)
G = 2017
CACHE_VERSION = 10
S1M_BUCKET = 'https://prd-tnm.s3.amazonaws.com/'      # USGS Seamless 1-meter DEM, 10 km COGs
S1M_CRS = 'EPSG:6350'                                  # NAD83(2011) / Conus Albers
TDEP_URL = ('https://elevation.nationalmap.gov/arcgis/rest/services/3DEPElevation/ImageServer/exportImage?'
            'bbox={w:.7f},{s:.7f},{e:.7f},{n:.7f}&bboxSR=4326&imageSR=4326&size={nx},{ny}&format=tiff&pixelType=F32'
            '&noData=-9999&interpolation=RSP_BilinearInterpolation&f=image')
TERRARIUM_URL = 'https://s3.amazonaws.com/elevation-tiles-prod/terrarium/{z}/{x}/{y}.png'
# GSI Japan elevation tiles (same tile scheme): dem1a = 1 m from airborne lidar (zoom 17, where published),
# dem5a = 5 m from airborne lidar, dem5b / dem5c = 5 m from aerial
# photogrammetry, each up to zoom 15 and only where surveyed; dem = 10 m (from the 1:25 000 maps), all of Japan, zoom 14
GSI_URL = 'https://cyberjapandata.gsi.go.jp/xyz/{layer}/{z}/{x}/{y}.png'
SWISS_STAC_API = 'https://data.geo.admin.ch/api/stac/v1'      # STAC APIs, searched with pystac-client
CCMEO_STAC_API = 'https://datacube.services.geo.ca/stac/api'
SOURCE_PROVIDER = {'NLS Finland 2 m': 'nls', 'Lantmateriet Sweden 1 m': 'lantmateriet'}   # sources that need a key -> credentials.PROVIDERS
LM_TOKEN_URL = 'https://apimanager.lantmateriet.se/oauth2/token'
LM_STAC_API = 'https://api.lantmateriet.se/stac-hojd/v1'
SWISS_COG_URL = ('https://data.geo.admin.ch/ch.swisstopo.swissaltiregio/swissaltiregio/'
                 'swissaltiregio_2056_5728.tif')     # one cloud-optimised GeoTIFF; used if the STAC lookup fails
IGN_WMS_URL = ('https://data.geopf.fr/wms-r?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap'
               '&LAYERS={layer}&STYLES=&FORMAT=image/geotiff&CRS=EPSG:2154'
               '&BBOX={x0:.1f},{y0:.1f},{x1:.1f},{y1:.1f}&WIDTH={nx}&HEIGHT={ny}')   # EPSG:2154 axis order: E, N
# RGE ALTI: the high-resolution elevation layer first, the Lambert-93 RGE ALTI pyramid as the fallback
IGN_LAYERS = ('ELEVATION.ELEVATIONGRIDCOVERAGE.HIGHRES', 'RGEALTI-MNT_PYR-ZIP_FXX_LAMB93_WMS')
# LiDAR HD terrain model (MNT, 0.5 m, from IGN's nationwide LiDAR HD programme): float32, no-data outside its coverage
IGN_LIDAR_LAYERS = ('IGNF_LIDAR-HD_MNT_ELEVATION.ELEVATIONGRIDCOVERAGE.LAMB93',)
FR_LIDAR_RES = 0.5
# RGE ALTI is requested on its 5 m grid: much of it (mountains without lidar) is 5 m data, and asking the server for a
# finer grid makes it repeat pixels (a stair pattern every 5 m). Where LiDAR HD exists, it is used instead.
FR_RGE_RES = 5.0
MIN_DL_RES = 0.0          # a floor for the download resolution in m; 0 = none: every source is fetched at the
                          # window's own grid spacing (the grid is always G x G, so that is never more than ~G x G
                          # pixels per source, however small the window)
MAX_CROP_PX = 40_000_000  # largest crop read from one GeoTIFF (~320 MB as float64); bigger means a missing overview
RETRIES = 3               # every download is retried this many times after a failed first attempt
SWISS_RES = 10.0          # Switzerland: swissALTIRegio, 10 m
SWISS3D_RES = 2.0         # Switzerland: swissALTI3D tiles, 2 m
SWISS3D_MAX_TILES = 400   # 1 km tiles; windows needing more use swissALTIRegio
KARTVERKET_WCS_URL = ('https://wcs.geonorge.no/skwms1/wcs.hoyde-dtm-nhm-25833?service=WCS&version=1.0.0'
                      '&request=GetCoverage&coverage=nhm_dtm_topo_25833&crs=EPSG:25833&format=GeoTIFF'
                      '&bbox={x0:.0f},{y0:.0f},{x1:.0f},{y1:.0f}&width={nx}&height={ny}')
MML_WCS_URL = ('https://avoin-karttakuva.maanmittauslaitos.fi/ortokuvat-ja-korkeusmallit/wcs/v2?service=WCS&version=2.0.1'
               '&request=GetCoverage&CoverageID=korkeusmalli_2m&format=image/tiff&geotiff:compression=LZW'
               '&SUBSET=E({x0:.0f},{x1:.0f})&SUBSET=N({y0:.0f},{y1:.0f}){scale}&api-key={key}')
IDEE_WCS_URL = ('https://servicios.idee.es/wcs-inspire/mdt?service=WCS&version=1.0.0&request=GetCoverage'
                '&coverage=Elevacion4258_5&crs=EPSG:4258&format={fmt}'
                '&bbox={x0:.8f},{y0:.8f},{x1:.8f},{y1:.8f}&width={nx}&height={ny}')
# MDT05 on its native ETRS89 / UTM 30N grid (the whole peninsula and the Balearics, zones 29 and 31 included as an
# extended zone 30): requested on whole 5 m pixels, the server does not resample, so there are no stripes. The
# geographic (EPSG:4258) coverage, which the server reprojects with nearest neighbour, is only the fallback and the
# source for the Canary Islands.
IDEE_UTM_URL = ('https://servicios.idee.es/wcs-inspire/mdt?service=WCS&version=1.0.0&request=GetCoverage'
                '&coverage=Elevacion25830_5&crs=EPSG:25830&format={fmt}'
                '&bbox={x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}&width={nx}&height={ny}')
IDEE_FORMATS = ('GeoTIFF', 'image/tiff', 'GTiff')    # the first one the server answers with a TIFF is kept
ES_RES = 5.0              # Spain: MDT05, 5 m
# Italy, regional lidar (served per window; the other Alpine regions only offer bulk tile downloads)
BZ_WCS_URL = ('https://geoservices9.civis.bz.it/geoserver/ows?service=WCS&version=1.0.0&request=GetCoverage'
              '&coverage={cov}&crs=EPSG:25832&format=GeoTIFF'
              '&bbox={x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}&width={nx}&height={ny}')
BZ_COV = 'p_bz-Elevation:DigitalTerrainModel-2.5m'         # the whole province
CA_RES = 2.0              # Canada: HRDEM Mosaic, 2 m
LM_RES = 1.0             # Sweden: Markhöjdmodell, 1 m
NO_RES = 1.0              # Norway: the national terrain model, 1 m
FI_RES = 2.0              # Finland: the NLS elevation model, 2 m
IT_RES = 10.0             # Italy: TINITALY, 10 m
TINITALY_WCS_URL = ('https://tinitaly.pi.ingv.it/TINItaly_1_1/wcs?service=WCS&version=2.0.1&request=GetCoverage'
                    '&coverageId=TINItaly_1_1__tinitaly_dem&format=image%2Ftiff%3Bapplication%3Dgeotiff'
                    '&subset={ax}({x0:.0f},{x1:.0f})&subset={ay}({y0:.0f},{y1:.0f}){scale}')

SOURCES = {
    '3dep2': dict(name='USGS 3DEP (10 m)', credit='Elevation: USGS 3D Elevation Program (public domain)'),
    '3dep': dict(name='USGS 3DEP (10 m)', credit='Elevation: USGS 3D Elevation Program (public domain)'),
    'national': dict(name='National surveys (1-10 m)',
                     credit='Elevation: USGS 3D Elevation Program (public domain); swisstopo swissALTI3D and swissALTIRegio; IGN LiDAR HD and RGE ALTI; INGV TINITALY 1.1 (Tarquini et al. 2023, '
                            'CC BY 4.0); Kartverket Nasjonal hoydemodell (hoydedata.no, CC BY 4.0, resampled); '
                            'National Land Survey of Finland elevation model (CC BY 4.0, resampled); '
                            'IGN Spain MDT05 (CC BY 4.0, resampled); '
                            'Geospatial Information Authority of Japan elevation tiles (GSI Tiles); '
                            'BEV Austria ALS DTM (CC BY 4.0); Bayerische Vermessungsverwaltung DGM1 (CC BY 4.0); '
                            'GUGiK Poland NMT; UGKK SR DMR 5.0 (CC BY 4.0); CUZK DMR 5G (CC BY 4.0); Environment Agency LIDAR Composite DTM (OGL v3); '
                            'Natturufraedistofnun IslandsDEM (CC BY 4.0); LINZ NZ 8m DEM and 1 m lidar DEM (CC BY 4.0); Scottish public-sector LiDAR DTM (OGL v3);  Geoscience Australia 5 m DEM (CC BY 4.0); '
                            'Provincia autonoma di Bolzano DTM (CC0); '
                            'Natural Resources Canada HRDEM Mosaic and ArcticDEM-based HRDEM (Open Government Licence - '
                            'Canada; ArcticDEM by the Polar Geospatial Center); '
                            '\u00a9Lantm\u00e4teriet Markh\u00f6jdmodell; '
                            'Terrain Tiles on AWS incl. DGM Austria (data.gv.at, CC BY 4.0)'),
    'terrarium': dict(name='Terrain Tiles (~30 m)', credit='Elevation: Terrain Tiles on AWS (Mapzen; SRTM, GMTED, ETOPO1, 3DEP and others)'),
}

# A national value is treated as no-data when it lies more than MAX_DEV_M outside the range Terrain Tiles span within
# ~DEV_RADIUS_M around it: only absurd values (unflagged no-data, filler). Terrain Tiles themselves can be 500-600 m
# off in steep terrain (seen at the Grand Canyon and in Glacier National Park), so real relief must not be judged by
# them.
MAX_DEV_M = 1000.0
DEV_RADIUS_M = 500.0

# Seams (see _blend): the two sides meet in the middle: each gets half of the height difference measured along the
# seam as a smooth correction, faded out over BLEND_M_PER_M metres per metre of difference (between BLEND_MIN_M and
# BLEND_MAX_M) on its own side. Where the resolutions differ by at least
# DETAIL_RATIO, the finer side is also blurred progressively towards the seam (a blur that grows smoothly from nothing, over
# DETAIL_FADE_PX of the coarser source's pixels, to DETAIL_SIGMA of them at the seam), so the change of sharpness is gradual.
BLEND_M_PER_M = 150.0
BLEND_MIN_M = 150.0
BLEND_MAX_M = 2000.0
DETAIL_RATIO = 2.0
DETAIL_FADE_PX = 8.0       # width of the high-to-low detail transition, in pixels of the coarser side ...
DETAIL_FADE_MIN_M = 60.0   # ... within these limits
DETAIL_FADE_MAX_M = 400.0
DETAIL_SIGMA = 0.45        # blur at the seam, in pixels of the coarser side (a 30 m pixel looks like sigma ~13 m)
SEAM_SMOOTH_M = 100.0     # the seam difference that is spread far is averaged along the seam over this distance
SEAM_CLOSE_CELLS = 4.0    # every seam is smoothed over about this many grid cells on each side at full resolution
BLEND_CELL_M = 8.0        # cell size of the grid the seam corrections are worked out on (see _blend)
SLIVER_M = 60.0           # parts of a source narrower than this (slivers along a border) are dropped and filled
GAP_M = 200.0             # Terrain Tiles areas narrower than this (holes, strips between surveys) are filled from
                          # the surveys around them rather than kept as the coarse side
# Every source is smoothed before stitching, with a Gaussian of ARTIFACT_SMOOTH x the pixel it was downloaded at
# (blocky pixels and terraces of coarse data become smooth slopes); where a server's resampling left a periodic
# pattern (see stripes), with half that pattern's period
ARTIFACT_SMOOTH = 0.6
STRIPE_LIMIT = 3.0
TERRAIN_RES_M = 30.0      # Terrain Tiles: effective resolution of the smoothed base (10 m where they hold Austria's DGM)
TERRAIN_FINE_RES_M = 10.0
DATUM_OFFSET_M = 12.0     # a near-constant offset above this against the surroundings is taken as another height datum
SEAM_WARN_M = 3.0         # height offsets between the two sides of a seam above this are logged as warnings
LAST_SEAMS = []           # the seams of the last stitched window, as measured by _blend (read by the live test)
FETCH_PARALLEL = 3        # countries whose sources are fetched at the same time
FETCH_MARGIN = 16         # cells added around the part of the window a source is asked for
MIN_NEED_CELLS = 50       # a source is not asked for fewer open cells than this
MAX_GAP = 0.05            # share of the window the surveys may leave open: up to it the gaps are interpolated, above it swissALTIRegio
                          # and Terrain Tiles are fetched and later surveys of a country are asked for the rest
DEBUG_HOOK = None         # the live test sets this to a function(name, grid) to keep intermediate grids


class DemError(Exception):
    pass


def _redact(msg):
    """error/log text without credentials (the NLS API key travels in the URL)"""
    return re.sub(r'(api-key=)[^&\s\'"]+', r'\1***', str(msg))


def _cancelled(cancel):
    """True once the user cancelled: works with net.CancelToken (.cancelled), Event-like objects and callables"""
    try:
        if hasattr(cancel, 'cancelled'):
            return bool(cancel.cancelled)
        if hasattr(cancel, 'is_set'):
            return bool(cancel.is_set())
        return bool(cancel()) if callable(cancel) else False
    except Exception:
        return False


def _check_cancel(cancel):
    """raise the app's own cancellation exception if the user cancelled"""
    if _cancelled(cancel):
        raise getattr(net, 'Cancelled', net.NetError)()


def grid_res(spacing, native):
    """download resolution on whole multiples of a source's native pixel (so a server that picks pixels by nearest
    neighbour decimates evenly instead of repeating some pixels), never finer than MIN_DL_RES"""
    return native * max(1, math.ceil(dl_res(spacing, native) / native - 1e-6))


def dl_res(spacing, native):
    """resolution to download a source at: the window's grid spacing, but never finer than MIN_DL_RES or the source"""
    return max(spacing, MIN_DL_RES, native)


def terrarium_zoom(lat, spacing, zmax, min_res=MIN_DL_RES):
    """finest tile zoom whose pixels are still no smaller than the window's needs (>= min_res), <= zmax"""
    target = max(spacing, min_res)
    m_per_px0 = 156543.034 * max(math.cos(math.radians(lat)), 0.05)    # zoom 0, 256 px tiles
    z = int(math.floor(math.log2(m_per_px0 / target)))
    return int(min(max(z, 0), zmax))


def in_us(lat, lon):
    return any(a <= lon <= c and b <= lat <= d for a, b, c, d in US_BOXES)


def _window_bbox(lat, lon, size_m):
    h = size_m / 2 * 1.5 / 111320.0                       # generous: covers the rotated corners of the local grid
    return lon - h / max(math.cos(math.radians(lat)), 0.05), lat - h, lon + h / max(math.cos(math.radians(lat)), 0.05), lat + h


def _hits(boxes, bbox):
    """_intersects for one box or a tuple of boxes"""
    return any(_intersects(b, bbox) for b in boxes) if isinstance(boxes[0], tuple) else _intersects(boxes, bbox)


def _intersects(box, bbox):
    return box[0] <= bbox[2] and bbox[0] <= box[2] and box[1] <= bbox[3] and bbox[1] <= box[3]


def in_national(lat, lon, size_m):
    bb = _window_bbox(lat, lon, size_m)
    lo, la = np.meshgrid(np.linspace(bb[0], bb[2], 5), np.linspace(bb[1], bb[3], 5))
    at = _in_country(lo, la, ('AUT',))
    if (at if at is not None else (_intersects(AT_BOX, bb) and np.ones(lo.shape, bool))).any():
        return True
    return any(_intersects(b, bb) for b in (FR_BOX, REGIO_BOX, IT_BOX, NO_BOX, FI_BOX, ES_BOX, CA_BOX, SE_BOX, JP_BOX) + US_BOXES + NEW_BOXES)


_GRID_LATLON = {}


def _grid_latlon_exact(lat, lon, size_m, n=G, rot=0.0):
    g = geo.LocalGrid(lat, lon, rot)
    s = np.arange(n) * (size_m / (n - 1)) - size_m / 2
    X, Y = np.meshgrid(s, -s)
    return g.to_latlon(X, Y)


def grid_latlon(lat, lon, size_m, n=G, rot=0.0):
    """latitude, longitude (float64, n x n, row 0 = the top of the window) of the window's grid points; the window is
    turned clockwise by `rot` degrees about its centre (0: north is up). The map projection is evaluated
    exactly on a 127 x 127 lattice and interpolated linearly in between (the error is under a millimetre: latitude
    and longitude are almost linear over a window), which is ~30 times faster than evaluating the series at every one of
    the 4 to 16 million points. The last window is kept, since a fetch and its checks ask for the same grid."""
    key = (round(lat, 9), round(lon, 9), round(size_m, 3), n, round(float(rot or 0), 4))
    hit = _GRID_LATLON.get('last')
    if hit and hit[0] == key:
        return hit[1].copy(), hit[2].copy()
    K = 126
    if (n - 1) % K:                                         # not a multiple of the lattice: the exact way
        LA, LO = _grid_latlon_exact(lat, lon, size_m, n, rot)
    else:
        g = geo.LocalGrid(lat, lon, rot)
        sk = np.arange(K + 1) * (size_m / K) - size_m / 2
        X, Y = np.meshgrid(sk, -sk)
        la, lo = g.to_latlon(X, Y)
        t = np.arange(n) * (K / (n - 1))                    # lattice coordinate of every row / column
        i0 = np.minimum(t.astype(int), K - 1)
        w = np.zeros((n, K + 1))
        w[np.arange(n), i0] = 1 - (t - i0)
        w[np.arange(n), i0 + 1] = t - i0
        LA, LO = w @ la @ w.T, w @ lo @ w.T
    _GRID_LATLON['last'] = (key, LA, LO)
    return LA.copy(), LO.copy()


# ---------------------------------------------------------------- resampling / smoothing without scipy

def _keys(t):
    """cubic convolution weights (a = -0.5) for the four taps at offsets -1, 0, 1, 2"""
    a = -0.5
    t2, t3 = t * t, t * t * t
    return ((a * (t3 - 2 * t2 + t)), ((a + 2) * t3 - (a + 3) * t2 + 1), (-(a + 2) * t3 + (2 * a + 3) * t2 - a * t),
            (a * (t2 - t3)))


SAMPLE_THREADS = 4        # threads for sampling a grid from an image


def sample_cubic(img, rows, cols):
    """img[rows, cols] by cubic convolution at fractional pixel-centre coordinates (edge clamped; NaN spreads).
    The image is padded by three pixels of its own edge, so the 16 taps are plain gathers from one flat array (about twice as
    fast as clamping every tap); a very large image is sampled the slower way instead, to avoid a copy of it."""
    h, w = img.shape
    if img.size > 16_000_000:
        return _sample_cubic_clamped(img, rows, cols)
    W4 = w + 6
    pf = np.pad(np.asarray(img, np.float64), 3, mode='edge').ravel()
    offs = [i * W4 + j for i in range(4) for j in range(4)]
    out = np.empty(rows.shape, np.float64)
    step = 64

    def chunk(a):
        # beyond one pixel outside the image every tap reads the edge: the same as clamping the coordinate
        r = np.clip(rows[a:a + step], -1.0, float(h))
        c = np.clip(cols[a:a + step], -1.0, float(w))
        r0, c0 = np.floor(r), np.floor(c)
        wr, wc = _keys(r - r0), _keys(c - c0)
        base = (r0.astype(np.int64) + 2) * W4 + (c0.astype(np.int64) + 2)
        acc, k = 0.0, 0
        for i in range(4):
            row = 0.0
            for j in range(4):
                row = row + wc[j] * pf.take(base + offs[k])
                k += 1
            acc = acc + wr[i] * row
        out[a:a + step] = acc

    starts = range(0, rows.shape[0], step)
    if rows.shape[0] > 4 * step:                            # numpy releases the GIL in these array operations
        with ThreadPoolExecutor(SAMPLE_THREADS) as ex:
            list(ex.map(chunk, starts))
    else:
        for a in starts:
            chunk(a)
    return out


def _sample_cubic_clamped(img, rows, cols):
    h, w = img.shape
    out = np.empty(rows.shape, np.float64)
    step = 256
    for a in range(0, rows.shape[0], step):
        r, c = rows[a:a + step], cols[a:a + step]
        r0, c0 = np.floor(r).astype(np.int64), np.floor(c).astype(np.int64)
        wr, wc = _keys(r - r0), _keys(c - c0)
        acc = np.zeros(r.shape, np.float64)
        for i in range(4):
            ri = np.clip(r0 + i - 1, 0, h - 1)
            row_acc = np.zeros(r.shape, np.float64)
            for j in range(4):
                row_acc += wc[j] * img[ri, np.clip(c0 + j - 1, 0, w - 1)]
            acc += wr[i] * row_acc
        out[a:a + step] = acc
    return out


def _sample_inside(img, rows, cols):
    """sample_cubic, NaN for points outside the image"""
    h, w = img.shape
    v = sample_cubic(img, rows, cols)
    v[(rows < -0.5) | (cols < -0.5) | (rows > h - 0.5) | (cols > w - 0.5)] = np.nan
    return v


def _box(a, w, axis):
    """running mean of odd width w along an axis (edges repeated), by a cumulative sum: O(N) whatever the width"""
    r = w // 2
    pad = [(r + 1, r) if ax == axis else (0, 0) for ax in (0, 1)]
    c = np.cumsum(np.pad(a, pad, mode='edge'), axis=axis)
    n = a.shape[axis]
    if axis == 0:
        return (c[w:w + n] - c[:n]) / w
    return (c[:, w:w + n] - c[:, :n]) / w


def gaussian(a, sigma):
    """Gaussian blur (edges repeated). Narrow kernels are applied exactly; from sigma 1.5 on, three running means
    whose widths give the same variance (the classic approximation, within ~3 % of a true Gaussian), so the cost does
    not grow with sigma."""
    if sigma <= 0:
        return a
    out = a.astype(np.float64)
    if sigma < 1.5:
        rad = int(math.ceil(4 * sigma))
        k = np.exp(-0.5 * (np.arange(-rad, rad + 1) / sigma) ** 2)
        k /= k.sum()
        for axis in (0, 1):
            pad = np.pad(out, [(rad, rad) if ax == axis else (0, 0) for ax in (0, 1)], mode='edge')
            acc = np.zeros_like(out)
            n = out.shape[axis]
            for i, kv in enumerate(k):
                acc += kv * (pad[i:i + n, :] if axis == 0 else pad[:, i:i + n])
            out = acc
        return out
    wl = int(math.floor(math.sqrt(4 * sigma * sigma + 1)))
    wl -= 1 - wl % 2                                        # odd, at most the ideal width
    m = int(round((12 * sigma * sigma - 3 * wl * wl - 12 * wl - 9) / (-4.0 * wl - 4)))
    for i in range(3):
        w = wl if i < m else wl + 2
        if w > 1:
            out = _box(_box(out, w, 0), w, 1)
    return out


def _block_mean(a, k):
    """mean over k x k blocks, ignoring NaN (all-NaN blocks stay NaN); the last row/column of blocks may be partial"""
    h, w = a.shape
    H, W = -(-h // k), -(-w // k)
    p = np.full((H * k, W * k), np.nan)
    p[:h, :w] = a
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        return np.nanmean(p.reshape(H, k, W, k), axis=(1, 3))


def _upsample_linear(small, k, shape):
    """inverse of _block_mean: bilinear back to `shape`, block centres at (i + 0.5) * k - 0.5"""
    def axis(n, m):
        f = np.clip((np.arange(n) + 0.5) / k - 0.5, 0, m - 1)
        i0 = np.minimum(np.floor(f).astype(np.int64), max(m - 2, 0))
        return i0, np.minimum(i0 + 1, m - 1), f - i0
    r0, r1, fr = axis(shape[0], small.shape[0])
    c0, c1, fc = axis(shape[1], small.shape[1])
    top = small[r0][:, c0] * (1 - fc) + small[r0][:, c1] * fc
    bot = small[r1][:, c0] * (1 - fc) + small[r1][:, c1] * fc
    return top * (1 - fr)[:, None] + bot * fr[:, None]


_blur = gaussian          # (wide blurs once needed their own shortcut)


# ---------------------------------------------------------------- coordinates and GeoTIFF reading (rasterio)

PROJ_STEP = 8             # grid points are projected on every 8th row/column and interpolated in between


def _project(LA, LO, crs):
    """WGS84 lat/lon grid -> x, y in `crs` (an EPSG string or a rasterio CRS), with PROJ (rasterio.warp). Projections
    are smooth, so only every PROJ_STEP-th point is transformed exactly and the rest interpolated (error < 1 mm)."""
    from rasterio.warp import transform
    H, W = LA.shape
    ri = np.unique(np.r_[np.arange(0, H, PROJ_STEP), H - 1])
    ci = np.unique(np.r_[np.arange(0, W, PROJ_STEP), W - 1])
    la, lo = LA[np.ix_(ri, ci)], LO[np.ix_(ri, ci)]
    xs, ys = transform('EPSG:4326', crs, lo.ravel(), la.ravel())
    xs, ys = np.asarray(xs, np.float64).reshape(la.shape), np.asarray(ys, np.float64).reshape(la.shape)

    def up(a):                                              # bilinear back to the full grid
        r = np.interp(np.arange(H), ri, np.arange(len(ri)))
        c = np.interp(np.arange(W), ci, np.arange(len(ci)))
        r0 = np.minimum(np.floor(r).astype(np.int64), len(ri) - 2)
        c0 = np.minimum(np.floor(c).astype(np.int64), len(ci) - 2)
        fr, fc = (r - r0)[:, None], (c - c0)[None, :]
        top = a[r0][:, c0] * (1 - fc) + a[r0][:, c0 + 1] * fc
        bot = a[r0 + 1][:, c0] * (1 - fc) + a[r0 + 1][:, c0 + 1] * fc
        return top * (1 - fr) + bot * fr
    return up(xs), up(ys)


def _gdal_env(auth=None):
    """GDAL settings for reading cloud-optimised GeoTIFFs over HTTP: range requests only, RETRIES retries, and HTTP
    a bearer token when `auth` is a string or basic authentication when it is (user, password). rasterio.Env is per thread: enter it in each one."""
    import rasterio
    opts = dict(GDAL_DISABLE_READDIR_ON_OPEN='EMPTY_DIR', GDAL_HTTP_MAX_RETRY=str(RETRIES), GDAL_HTTP_RETRY_DELAY='2',
                GDAL_HTTP_TIMEOUT='120', GDAL_HTTP_MULTIRANGE='YES', GDAL_HTTP_MERGE_CONSECUTIVE_RANGES='YES',
                VSI_CACHE='TRUE', GDAL_INGESTED_BYTES_AT_OPEN='65536')
    if isinstance(auth, str):                                # bearer token
        opts.update(GDAL_HTTP_HEADERS='Authorization: Bearer ' + auth)
    elif auth:
        opts.update(GDAL_HTTP_AUTH='BASIC', GDAL_HTTP_USERPWD='%s:%s' % auth)
    return rasterio.Env(**opts)


# ---------------------------------------------------------------- country borders (data/borders.npz)

_BORDERS = {}


def _borders_file():
    try:
        return paths.resource('data', 'borders.npz')
    except AttributeError:                                  # paths without resource(): the source tree
        from pathlib import Path
        return Path(__file__).resolve().parent.parent / 'data' / 'borders.npz'


def _borders():
    """Country outlines (OpenStreetMap boundaries via geo-maps, simplified by at most 1 m, including territorial
    waters; built by packaging/build_borders.py), loaded once. -> dict, or None if the file is missing (no clipping)"""
    if 'd' not in _BORDERS:
        try:
            with np.load(_borders_file()) as z:
                _BORDERS['d'] = {k: z[k] for k in z.files}
        except (OSError, ValueError) as e:
            log.warning('country borders unavailable (%s): national sources are not clipped to their countries', e)
            _BORDERS['d'] = None
    return _BORDERS['d']


def _poly_boxes():
    """(lon_min, lat_min, lon_max, lat_max) of the outer ring of every outline in the border file, or None"""
    b = _borders()
    if b is None:
        return None
    if 'boxes' not in _BORDERS:
        xy, ro, pr = b['xy'], b['ring_off'], b['poly_ring']
        out = np.empty((len(pr) - 1, 4))
        for pi in range(len(out)):
            c = xy[ro[pr[pi]]:ro[pr[pi] + 1]]
            out[pi] = (c[:, 0].min(), c[:, 1].min(), c[:, 0].max(), c[:, 1].max())
        _BORDERS['boxes'] = out * 1e-6
    return _BORDERS['boxes']


def _outline_box(codes, rough):
    """box around the outlines of the countries `codes` whose middle lies within a degree of the `rough` box"""
    pb, b = _poly_boxes(), _borders()
    if pb is None:
        return rough
    mid = np.column_stack([(pb[:, 0] + pb[:, 2]) / 2, (pb[:, 1] + pb[:, 3]) / 2])
    want = [i for i, c in enumerate(b['countries']) if str(c) in codes]
    sel = (np.isin(b['poly_country'], want) & (mid[:, 0] >= rough[0] - 1) & (mid[:, 0] <= rough[2] + 1)
           & (mid[:, 1] >= rough[1] - 1) & (mid[:, 1] <= rough[3] + 1))
    if not sel.any():
        return rough
    q = pb[sel]
    return (math.floor(q[:, 0].min() * 100) / 100, math.floor(q[:, 1].min() * 100) / 100,
            math.ceil(q[:, 2].max() * 100) / 100, math.ceil(q[:, 3].max() * 100) / 100)


def _in_country(lon, lat, codes):
    """points (arrays) inside the outline of the countries `codes`, or None when the border file is unavailable"""
    pb, b = _poly_boxes(), _borders()
    if pb is None:
        return None
    lon, lat = np.asarray(lon, np.float64), np.asarray(lat, np.float64)
    want = [i for i, c in enumerate(b['countries']) if str(c) in codes]
    sel = np.flatnonzero(np.isin(b['poly_country'], want) & (pb[:, 0] <= lon.max()) & (pb[:, 2] >= lon.min())
                         & (pb[:, 1] <= lat.max()) & (pb[:, 3] >= lat.min()))
    inside = np.zeros(lon.shape, bool)
    xy, ro, pr = b['xy'], b['ring_off'], b['poly_ring']
    for pi in sel:
        c = xy[ro[pr[pi]]:ro[pr[pi] + 1]].astype(np.float64) * 1e-6
        x1, y1 = c[:, 0], c[:, 1]
        x2, y2 = np.roll(x1, -1), np.roll(y1, -1)
        for k in range(lon.size):                           # few points: one crossing count each
            px, py = lon.flat[k], lat.flat[k]
            cross = (y1 > py) != (y2 > py)
            with np.errstate(divide='ignore', invalid='ignore'):
                xc = x1 + (py - y1) * (x2 - x1) / (y2 - y1)
            if (cross & (px < xc)).sum() % 2:
                inside.flat[k] = True
    return inside


# coverage boxes of the national sources (lon_min, lat_min, lon_max, lat_max): the extent of each country's outline in
# data/borders.npz (_outline_box; the rough box in each call picks the mainland out of far-away territories and is the
# fallback if the file is missing). The data's own no-data areas define the real borders, the boxes only decide which
# services are worth asking. Regional surveys (South Tyrol, Bavaria, England, Scotland) are not in that file
CH_BOX = _outline_box(('CHE', 'LIE'), (5.95, 45.81, 10.50, 47.82))
REGIO_BOX = (4.52, 44.84, 11.99, 48.79)   # swissALTIRegio's extent (Switzerland + ~100 km around)
FR_BOX = _outline_box(('FRA',), (-5.20, 41.30, 9.60, 51.10))
BZ_BOX = (10.38, 46.21, 12.48, 47.10)     # South Tyrol (Provincia autonoma di Bolzano)
IT_BOX = _outline_box(('ITA',), (6.52, 35.17, 18.60, 47.10))
NO_BOX = _outline_box(('NOR',), (4.00, 57.90, 31.20, 71.30))
FI_BOX = _outline_box(('FIN',), (19.00, 59.60, 31.60, 70.10))
ES_BOX = _outline_box(('ESP',), (-18.40, 27.50, 4.40, 43.90))     # incl. Balearic and Canary Islands
CA_BOX = _outline_box(('CAN',), (-141.10, 41.60, -52.50, 83.20))
CA_NORTH_BOX = (CA_BOX[0], 59.50, CA_BOX[2], CA_BOX[3])           # the ArcticDEM-based HRDEM: north of ~60 N
SE_BOX = _outline_box(('SWE',), (10.90, 55.30, 24.20, 69.10))
JP_BOX = _outline_box(('JPN',), (122.90, 20.40, 153.99, 45.60))
AT_BOX = _outline_box(('AUT',), (9.53, 46.37, 17.17, 49.02))
BY_BOX = (8.97, 47.27, 13.84, 50.57)      # Bavaria
PL_BOX = _outline_box(('POL',), (14.12, 49.00, 24.15, 54.84))
SK_BOX = _outline_box(('SVK',), (16.83, 47.73, 22.57, 49.62))
CZ_BOX = _outline_box(('CZE',), (12.09, 48.55, 18.86, 51.06))
EN_BOX = (-6.42, 49.86, 1.77, 55.82)      # England
IS_BOX = _outline_box(('ISL',), (-24.60, 63.20, -13.40, 66.60))
NZ_BOX = _outline_box(('NZL',), (166.30, -47.40, 178.70, -34.30))
AU_BOX = _outline_box(('AUS',), (112.90, -43.70, 153.70, -9.80))
SC_BOX = (-8.70, 54.60, -0.70, 60.95)      # Scotland
NEW_BOXES = (BY_BOX, PL_BOX, SK_BOX, CZ_BOX, EN_BOX, IS_BOX, NZ_BOX, AU_BOX, SC_BOX)
# 3DEP: CONUS, Alaska, Hawaii, Puerto Rico with the Virgin Islands (their outlines in data/borders.npz)
US_BOXES = (_outline_box(('USA',), (-125.0, 24.4, -66.8, 49.5)), _outline_box(('USA',), (-170.0, 51.0, -129.5, 71.6)),
            _outline_box(('USA',), (-160.5, 18.8, -154.6, 22.4)), _outline_box(('PRI', 'VIR'), (-67.4, 17.8, -65.2, 18.6)))


def _ne_mask(lat, lon, size_m, codes, cells=G, rot=0.0):
    """Grid points of the window (centre lat/lon, size) inside the given countries (ISO A3 codes; None: any of the
    countries in the border file), or None when the border file is unavailable. The outlines of data/borders.npz are
    drawn onto the window's own local grid with rasterio."""
    from rasterio.features import rasterize
    from rasterio.transform import Affine
    b = _borders()
    if b is None:
        return None
    sp = size_m / (cells - 1)
    g = geo.LocalGrid(lat, lon, rot)
    LA, LO = g.to_latlon(np.array([-1, 1, 1, -1]) * size_m * 0.75, np.array([-1, -1, 1, 1]) * size_m * 0.75)
    w, s_, e, n = math.floor(LO.min()), math.floor(LA.min()), math.floor(LO.max()), math.floor(LA.max())
    want = [i for i, c in enumerate(b['countries']) if codes is None or str(c) in codes]
    tiles = b['poly_tile']
    sel = np.flatnonzero(np.isin(b['poly_country'], want) & (tiles[:, 0] >= w) & (tiles[:, 0] <= e)
                         & (tiles[:, 1] >= s_) & (tiles[:, 1] <= n))
    out = np.zeros((cells, cells), bool)
    if not len(sel):
        return out
    xy, ro, pr = b['xy'], b['ring_off'], b['poly_ring']
    shapes = []
    for pi in sel:
        rings = []
        for r in range(pr[pi], pr[pi + 1]):
            c = xy[ro[r]:ro[r + 1]].astype(np.float64) * 1e-6
            x, y = g.to_xy(c[:, 1], c[:, 0])
            rings.append(np.column_stack([x, y]).tolist())
        shapes.append(({'type': 'Polygon', 'coordinates': rings}, 1))
    tf = Affine(sp, 0, -size_m / 2 - sp / 2, 0, -sp, size_m / 2 + sp / 2)   # pixel centres on the grid points
    return rasterize(shapes, out_shape=(cells, cells), transform=tf, fill=0, dtype='uint8').astype(bool)


# ---- the borders as OpenStreetMap has them now. data/borders.npz is a snapshot; where a window holds a border, the
# border lines are fetched live (Overpass API, one small query per window, kept on disk) and drawn onto the window's grid.
# They cut the window into pieces; each piece is a whole country (or not) according to the snapshot, so the border
# runs exactly along OSM's line, at the grid's own resolution. Any failure leaves the snapshot's mask as it is.

OSM_BORDERS = True
OVERPASS_URLS = ('https://overpass-api.de/api/interpreter', 'https://overpass.kumi.systems/api/interpreter')
OSM_PIECE_SHARE = 0.85    # a piece belongs to the countries when at least this share of its land does (not: at most 1 - this)
_OSM = {}                 # small in-memory caches: ('lines', bbox) -> lines, ('labels', window) -> piece labels
OSM_TIMEOUT_S = 8.0       # per request: the border refinement must never hold up a terrain load
OSM_RETRY_AFTER_S = 600.0 # after every server failed, Overpass is left alone for this long
_OSM_DOWN = [0.0]         # time.monotonic() until which Overpass is skipped


def _osm_remember(key, value, keep=6):
    _OSM[key] = value
    while len(_OSM) > keep * 2:
        _OSM.pop(next(iter(_OSM)))
    return value


def _osm_border_lines(w, s, e, n, cancel=net.NEVER):
    """country border lines of OpenStreetMap (admin_level 2) inside the box -> list of [(lon, lat), ...], or None if
    Overpass cannot be reached. The box is rounded outwards to 0.01 degrees, so windows next to each other share it."""
    w, s = math.floor(w * 100) / 100, math.floor(s * 100) / 100
    e, n = math.ceil(e * 100) / 100, math.ceil(n * 100) / 100
    key = ('lines', w, s, e, n)
    if key in _OSM:
        return _OSM[key]
    f = paths.DEMS / ('osm-%s.json' % hashlib.sha1(('%.2f|%.2f|%.2f|%.2f' % (w, s, e, n)).encode()).hexdigest()[:16])
    try:
        return _osm_remember(key, json.loads(f.read_text()))
    except (OSError, ValueError):
        pass
    if time.monotonic() < _OSM_DOWN[0]:                      # failed a moment ago: do not wait for it again
        return None
    box = '(%.2f,%.2f,%.2f,%.2f)' % (s, w, n, e)
    q = '[out:json][timeout:25];rel["boundary"="administrative"]["admin_level"="2"]%s;way(r)%s;out geom%s;' % (box, box, box)
    import urllib.parse
    last = None
    for url in OVERPASS_URLS:
        try:
            data = net.get(url + '?data=' + urllib.parse.quote(q), timeout=OSM_TIMEOUT_S, retries=0, cancel=cancel, per_host=2)
            els = json.loads(data.decode('utf-8'))['elements']
            lines = [[(p['lon'], p['lat']) for p in el['geometry']] for el in els
                     if el.get('type') == 'way' and len(el.get('geometry') or []) > 1]
            try:
                f.write_text(json.dumps(lines))
            except OSError:
                pass
            return _osm_remember(key, lines)
        except (net.NetError, ValueError, KeyError) as e_:
            if _cancelled(cancel):
                raise
            last = e_
    _OSM_DOWN[0] = time.monotonic() + OSM_RETRY_AFTER_S
    log.warning('OpenStreetMap borders unavailable (%s): the borders of the built-in file are used for the next %d min',
                _redact(last), OSM_RETRY_AFTER_S // 60)
    return None


def _label4(free):
    """connected pieces (4-neighbourhood) of the True cells -> int32 labels 1.., 0 where not free. Union-find over the
    runs of every row (no scipy)"""
    H, W = free.shape
    d = np.diff(np.concatenate([np.zeros((H, 1), np.int8), free.astype(np.int8), np.zeros((H, 1), np.int8)], axis=1), axis=1)
    rs, c0 = np.nonzero(d == 1)
    _, c1 = np.nonzero(d == -1)
    nr = len(rs)
    parent = list(range(nr))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    first = np.searchsorted(rs, np.arange(H + 1)).tolist()
    c0l, c1l = c0.tolist(), c1.tolist()
    for r in range(1, H):
        i, j, i1, j1 = first[r - 1], first[r], first[r], first[r + 1]
        while i < i1 and j < j1:
            if c0l[i] < c1l[j] and c0l[j] < c1l[i]:
                a, b = find(i), find(j)
                if a != b:
                    parent[b] = a
            if c1l[i] < c1l[j]:
                i += 1
            else:
                j += 1
    ids, lab = {}, np.zeros((H, W), np.int32)
    for k in range(nr):
        lab[rs[k], c0l[k]:c1l[k]] = ids.setdefault(find(k), len(ids) + 1)
    return lab


def _place_wall_cells(lab, wall, segs, size_m, sp, max_work=4e8):
    """cells the border line crosses get the label of the piece on the same side of the line as their centre. segs:
    (S, 4) line segments x0, y0, x1, y1 in the window's metres. Each cell takes the side of its nearest segment and the
    label of the neighbour (4-neighbourhood) on that side."""
    rr, cc = np.nonzero(wall & (lab == 0))
    if not len(rr) or len(rr) * len(segs) > max_work:
        return lab
    px, py = -size_m / 2 + cc * sp, size_m / 2 - rr * sp
    a, d = segs[:, :2], segs[:, 2:] - segs[:, :2]
    dd = np.maximum((d * d).sum(axis=1), 1e-12)
    near = np.empty(len(rr), np.int64)
    step = max(1, int(2e6 // len(segs)))
    for i in range(0, len(rr), step):
        qx, qy = px[i:i + step, None] - a[:, 0], py[i:i + step, None] - a[:, 1]
        t = np.clip((qx * d[:, 0] + qy * d[:, 1]) / dd, 0.0, 1.0)
        near[i:i + step] = np.argmin((qx - t * d[:, 0]) ** 2 + (qy - t * d[:, 1]) ** 2, axis=1)
    ax, ay, dx, dy = a[near, 0], a[near, 1], d[near, 0], d[near, 1]
    side = np.sign(dx * (py - ay) - dy * (px - ax))            # which side of its nearest segment the centre is on
    H, W = lab.shape
    out = lab.copy()
    todo = side != 0
    for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
        r2, c2 = np.clip(rr + dr, 0, H - 1), np.clip(cc + dc, 0, W - 1)
        nl = lab[r2, c2]
        qx, qy = -size_m / 2 + c2 * sp, size_m / 2 - r2 * sp
        ns = np.sign(dx * (qy - ay) - dy * (qx - ax))
        ok = todo & (nl > 0) & (ns == side)
        out[rr[ok], cc[ok]] = nl[ok]
        todo &= ~ok
    return out


def _osm_pieces(lat, lon, size_m, cells, rot=0.0):
    """the window's grid cut into pieces by OSM's border lines: int32 labels (0 = on a line, filled from the neighbours
    where thin), or None when there are no lines or Overpass is unreachable"""
    key = ('labels', round(lat, 6), round(lon, 6), round(size_m, 1), cells, round(float(rot or 0), 3))
    if key in _OSM:
        return _OSM[key]
    from rasterio.features import rasterize
    from rasterio.transform import Affine
    g = geo.LocalGrid(lat, lon, rot)
    LA, LO = g.to_latlon(np.array([-1, 1, 1, -1]) * size_m * 0.75, np.array([-1, -1, 1, 1]) * size_m * 0.75)
    lines = _osm_border_lines(LO.min(), LA.min(), LO.max(), LA.max())
    if not lines:
        return _osm_remember(key, None)
    shapes, segs = [], []
    for ln in lines:
        c = np.asarray(ln, np.float64)
        x, y = g.to_xy(c[:, 1], c[:, 0])
        xy = np.column_stack([x, y])
        shapes.append(({'type': 'LineString', 'coordinates': xy.tolist()}, 1))
        segs.append(np.concatenate([xy[:-1], xy[1:]], axis=1))
    sp = size_m / (cells - 1)
    tf = Affine(sp, 0, -size_m / 2 - sp / 2, 0, -sp, size_m / 2 + sp / 2)
    # thin lines (one cell wide, 8-connected: nothing leaks through): the cells they cross are then placed by which side of
    # the line their centre is on, not by their neighbours, so the border is accurate to a fraction of a cell
    wall = rasterize(shapes, out_shape=(cells, cells), transform=tf, fill=0, dtype='uint8').astype(bool)
    if not wall.any():
        return _osm_remember(key, None)
    lab = _label4(~wall)
    lab = _place_wall_cells(lab, wall, np.concatenate(segs), size_m, sp)
    for _ in range(3):                                      # what is left (no neighbour on its side): the nearest piece
        un = lab == 0
        if not un.any():
            break
        new = lab.copy()
        for dr, dc in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            src = np.zeros_like(lab)
            src[max(dr, 0):cells + min(dr, 0), max(dc, 0):cells + min(dc, 0)] = \
                lab[max(-dr, 0):cells + min(-dr, 0), max(-dc, 0):cells + min(-dc, 0)]
            np.copyto(new, src, where=un & (new == 0) & (src > 0))
        lab = new
    return _osm_remember(key, lab)


def country_mask(lat, lon, size_m, codes, cells=G, rot=0.0):
    """Grid points of the window (centre lat/lon, size) inside the given countries (ISO A3 codes), or None when the
    border file is unavailable. Where the window holds a border of these countries, the border follows the lines of
    OpenStreetMap (see above) instead of the file's outline."""
    m = _ne_mask(lat, lon, size_m, codes, cells, rot)
    if m is None or not OSM_BORDERS or not m.any():
        return m
    land = _ne_mask(lat, lon, size_m, None, cells, rot)
    if land is None or not (land & ~m).any():                # no border of these countries in the window
        return m
    try:
        lab = _osm_pieces(lat, lon, size_m, cells, rot)
        if lab is None:
            return m
        k = int(lab.max()) + 1
        tot = np.bincount(lab[land], minlength=k)
        ins = np.bincount(lab[m & land], minlength=k)
        share = ins / np.maximum(tot, 1)
        take_in, take_out = (share >= OSM_PIECE_SHARE) & (tot > 0), (share <= 1 - OSM_PIECE_SHARE) & (tot > 0)
        take_in[0] = take_out[0] = False                     # (cells that no line piece reaches: as the file has them)
        sel = land & (take_in | take_out)[lab]
        out = m.copy()
        out[sel] = take_in[lab][sel]
        log.info('borders from OpenStreetMap: %d cells moved (%.2f %% of the window)', int((out != m).sum()),
                 100 * float((out != m).mean()))
        return out
    except net.Cancelled:
        raise
    except Exception as e:                                   # never let the refinement fail a terrain load
        log.warning('OpenStreetMap borders not used (%s: %s)', type(e).__name__, _redact(e))
        return m


# ---------------------------------------------------------------- GeoTIFF helpers

def _read_tiff(data, what):
    """GeoTIFF bytes (a coverage service's reply) -> (float64 image, NaN for no-data; (x0, y0, sx, sy) of the top-left
    pixel corner, or None without georeferencing). Decoded by rasterio (GDAL), whatever the compression."""
    import rasterio
    from rasterio.io import MemoryFile
    if data[:2] not in (b'II', b'MM'):                       # a multipart reply (WCS 2.0: GML, then the GeoTIFF)?
        k = min([i for i in (data.find(b'II*\x00'), data.find(b'MM\x00*')) if i > 0] or [-1])
        if k < 0:
            raise DemError('%s returned no elevation image (%r)' % (what, data[:120]))
        data = data[k:]
    try:
        with warnings.catch_warnings(), MemoryFile(data) as mf, mf.open() as ds:
            warnings.simplefilter('ignore', rasterio.errors.NotGeoreferencedWarning)   # handled below (gt None)
            img = ds.read(1, masked=True).astype(np.float64).filled(np.nan)
            t = ds.transform
            gt = (t.c, t.f, t.a, -t.e) if ds.crs is not None or not t.is_identity else None
    except rasterio.errors.RasterioError as e:
        raise DemError('cannot decode the %s GeoTIFF: %s' % (what, e))
    img[~np.isfinite(img) | (img < -1000) | (img > 9000)] = np.nan
    return img, gt


# ---------------------------------------------------------------- sources

def _usgs(LA, LO, bbox, spacing, cancel, progress):
    """3DEP at the grid points (NaN where it has no data), or None if it has none in the window"""
    lat = float(LA.mean())
    pad_lat = 3 * spacing / 111320.0
    pad_lon = pad_lat / max(math.cos(math.radians(lat)), 0.05)
    s, n = LA.min() - pad_lat, LA.max() + pad_lat
    w, e = LO.min() - pad_lon, LO.max() + pad_lon
    spacing = dl_res(spacing, 0.0)                          # best available (1 m+) at the window's grid
    ny = int(min(4000, max(256, math.ceil((n - s) * 111320.0 / spacing))))
    nx = int(min(4000, max(256, math.ceil((e - w) * 111320.0 * math.cos(math.radians(lat)) / spacing))))
    progress(0.1, 'Downloading %s...' % _shown('USGS 3DEP 3 m', spacing))
    data = net.get(TDEP_URL.format(w=w, s=s, e=e, n=n, nx=nx, ny=ny) + '&adjustAspectRatio=false', timeout=300,
                   retries=RETRIES, cancel=cancel)
    img, _ = _read_tiff(data, 'USGS')
    progress(0.7, 'Resampling elevation...')
    ph, pw = img.shape
    ref = _georef(data)                                     # the server widens the latitude span: use where the image really is
    if ref:
        west, north, dx, dy = ref
        rows = (north - LA) / dy - 0.5
        cols = (LO - west) / dx - 0.5
    else:
        rows = (n - LA) / (n - s) * ph - 0.5
        cols = (LO - w) / (e - w) * pw - 0.5
    dem = sample_cubic(img, rows, cols)
    return None if not np.isfinite(dem).any() else dem


def _s1m_names(X, Y):
    """names of the 10 km S1M tiles under points in EPSG:6350: n<top edge km>[w|e]<left edge km>, e.g. n2200w2080"""
    names = []
    for ty in range(int(math.floor(Y.min() / 1e4)), int(math.floor(Y.max() / 1e4)) + 1):
        for tx in range(int(math.floor(X.min() / 1e4)), int(math.floor(X.max() / 1e4)) + 1):
            top, left = (ty + 1) * 10, tx * 10
            if top > 0:
                names.append('n%04d%s%04d' % (top, 'w' if left < 0 else 'e', abs(left)))
    return names


def _usgs_s1m(LA, LO, bbox, spacing, cancel, progress):
    """USGS Seamless 1-meter DEM (S1M): one lidar surface without project seams, published since 2025 as 10 km
    cloud-optimised GeoTIFFs in Albers (EPSG:6350) for the contiguous states, as far as they are produced. The newest
    file of each tile is found in the public bucket's listing; only the window is read."""
    X, Y = _project(LA, LO, S1M_CRS)
    progress(0.0, 'Finding tiles...')
    hrefs = []
    for name in _s1m_names(X, Y):
        _check_cancel(cancel)
        prefix = 'StagedProducts/Elevation/S1M/%s%s/%s/' % (name[:3], name[5:8], name)
        xml = net.get(S1M_BUCKET + '?list-type=2&prefix=' + prefix, timeout=60, retries=RETRIES, cancel=cancel)
        keys = sorted(re.findall(r'<Key>([^<]+\.tif)</Key>', xml.decode('utf-8', 'replace')))
        if keys:
            hrefs.append(S1M_BUCKET + keys[-1])             # the date is the end of the name: the last is the newest
    if not hrefs:
        return None
    return _cog_mosaic(hrefs, LA, LO, 1.0, spacing, 'USGS seamless 1 m', cancel, progress)


# ---- the first two kinds of terrain of the Map Creator, kept as they were: a map made with one of these ids rebuilds with
# the same terrain (a resort built on it does not float or sink). New maps use 'national' (below), which falls back to them.

def _georef(data):
    """(west, north, degrees per pixel x, degrees per pixel y) from a GeoTIFF's ModelTiepoint / ModelPixelScale, or
    None when the tags are missing"""
    import tifffile
    with tifffile.TiffFile(io.BytesIO(data)) as t:
        tags = t.pages[0].tags
        sc, tp = tags.get('ModelPixelScaleTag'), tags.get('ModelTiepointTag')
        if not (sc and tp):
            return None
        i, j, x, y = tp.value[0], tp.value[1], tp.value[3], tp.value[4]      # pixel (i, j) corner at (x, y)
        return x - i * sc.value[0], y + j * sc.value[1], sc.value[0], sc.value[1]


def _legacy_3dep(lat, lon, size_m, cancel, progress, exact=True, rot=0.0):
    """exact: the image's real extent (see SOURCES); False reproduces the old, squeezed terrain of '3dep' maps"""
    import tifffile
    LA, LO = grid_latlon(lat, lon, size_m, G, rot)
    pad_lat = 3 * size_m / (G - 1) / 111320.0
    pad_lon = pad_lat / max(math.cos(math.radians(lat)), 0.05)
    s, n = LA.min() - pad_lat, LA.max() + pad_lat
    w, e = LO.min() - pad_lon, LO.max() + pad_lon
    spacing = size_m / (G - 1)
    ny = int(min(4000, max(256, math.ceil((n - s) * 111320.0 / spacing * 1.1))))
    nx = int(min(4000, max(256, math.ceil((e - w) * 111320.0 * math.cos(math.radians(lat)) / spacing * 1.1))))
    progress(0.1, 'Downloading %s...' % _shown('USGS 3DEP 10 m', spacing))
    url = TDEP_URL.format(w=w, s=s, e=e, n=n, nx=nx, ny=ny) + ('&adjustAspectRatio=false' if exact else '')
    data = net.get(url, timeout=300, retries=3, cancel=cancel)
    if data[:2] not in (b'II', b'MM'):
        raise DemError('USGS returned no elevation image (%r)' % data[:80])
    img = tifffile.imread(io.BytesIO(data)).astype(np.float64)
    if img.ndim != 2:
        img = img[..., 0]
    if (img < -1000).any() or not np.isfinite(img).all():
        raise DemError('USGS has no elevation for part of this area')
    progress(0.7, 'Resampling elevation...')
    ph, pw = img.shape
    ref = _georef(data) if exact else None
    if ref:                                          # where the image really is (pixel centres at +0.5)
        west, north, dx, dy = ref
        rows = (north - LA) / dy - 0.5
        cols = (LO - west) / dx - 0.5
    else:
        rows = (n - LA) / (n - s) * ph - 0.5
        cols = (LO - w) / (e - w) * pw - 0.5
    return np.maximum(sample_cubic(img, rows, cols), 0.0)


def _legacy_terrarium_tile(z, x, y, cancel):
    x %= 2 ** z
    f = paths.DEMS / 'terrarium' / str(z) / str(x) / ('%d.png' % y)
    data = None
    if f.is_file():
        data = f.read_bytes()
    if not data:
        data = net.get(TERRARIUM_URL.format(z=z, x=x, y=y), timeout=60, retries=4, cancel=cancel, per_host=6)
        paths.atomic_write(f, data)
    a = np.asarray(Image.open(io.BytesIO(data)).convert('RGB')).astype(np.float64)
    return a[..., 0] * 256 + a[..., 1] + a[..., 2] / 256 - 32768


def _legacy_terrarium(lat, lon, size_m, cancel, progress, rot=0.0):
    LA, LO = grid_latlon(lat, lon, size_m, G, rot)
    if abs(lat) > 84:
        raise DemError('Elevation tiles do not cover the poles')
    z = 13
    px, py = _lonlat_to_px(LO, LA, z)
    x0, x1 = int(px.min()) // 256 - 1, int(px.max()) // 256 + 1
    y0, y1 = int(py.min()) // 256 - 1, int(py.max()) // 256 + 1
    tiles = [(tx, ty) for ty in range(y0, y1 + 1) for tx in range(x0, x1 + 1)]
    mosaic = np.zeros(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256), np.float64)
    done = [0]

    def one(t):
        tx, ty = t
        tile = _legacy_terrarium_tile(z, tx, ty, cancel)
        mosaic[(ty - y0) * 256:(ty - y0 + 1) * 256, (tx - x0) * 256:(tx - x0 + 1) * 256] = tile
        done[0] += 1
        progress(0.05 + 0.6 * done[0] / len(tiles), 'Downloading %s (%d of %d)...' % (_shown('AWS Terrain Tiles 30 m', size_m / (G - 1)), done[0], len(tiles)))

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, tiles))
    progress(0.7, 'Resampling elevation...')
    dem = sample_cubic(mosaic, py - y0 * 256 - 0.5, px - x0 * 256 - 0.5)
    # coarse source (~30 m outside the US): smooth the stair steps of the 16-bit tiles; stronger on small windows
    sigma = float(np.clip(3.0 * math.sqrt(8000.0 / size_m), 2.0, 5.0))
    return np.maximum(gaussian(dem, sigma), 0.0)


_used = threading.local()   # the datasets the last fetch on this thread used (read by load_sources)


def _lonlat_to_px(lon, lat, z):
    n = 256 * 2 ** z
    x = (lon + 180.0) / 360.0 * n
    s = np.sin(np.radians(np.clip(lat, -85.05, 85.05)))
    y = (0.5 - np.log((1 + s) / (1 - s)) / (4 * np.pi)) * n
    return x, y


def _decode_terrarium(rgb):
    return rgb[..., 0] * 256 + rgb[..., 1] + rgb[..., 2] / 256 - 32768


def _decode_gsi(rgb):
    """GSI elevation PNG: x = 2^16 R + 2^8 G + B in 0.01 m; x = 2^23 (128, 0, 0) is no data, above it negative"""
    x = rgb[..., 0] * 65536 + rgb[..., 1] * 256 + rgb[..., 2]
    return np.where(x == 2 ** 23, np.nan, np.where(x < 2 ** 23, x, x - 2 ** 24) * 0.01)


def _tile(url, decode, z, x, y, cancel, cache=None, missing_ok=False):
    """one 256 px Web Mercator elevation tile -> metres (NaN = no data); None if missing_ok and the server has none"""
    x %= 2 ** z
    f = paths.DEMS / cache / str(z) / str(x) / ('%d.png' % y) if cache else None
    data = f.read_bytes() if f is not None and f.is_file() else None
    if not data:
        data = net.get(url.format(z=z, x=x, y=y), timeout=60, retries=RETRIES, cancel=cancel, per_host=6,
                       not_found_ok=missing_ok)
        if data is None:
            return None
        if f is not None:
            paths.atomic_write(f, data)
    return decode(np.asarray(Image.open(io.BytesIO(data)).convert('RGB')).astype(np.float64))


def _tile_sample(LA, LO, z, url, decode, cancel, progress, what, cache=None, missing_ok=False, need=None):
    """elevation tiles of zoom z sampled at the grid points (only the tiles the grid touches are fetched; with `need`,
    a boolean mask of the points that are wanted, only the tiles those points touch)
    -> values (NaN where the tiles have no data), or None if no tile has any"""
    if np.abs(LA).max() > 84:
        raise DemError('Elevation tiles do not cover the poles')
    px, py = _lonlat_to_px(LO, LA, z)
    x0, x1 = int(math.floor(px.min() - 2)) // 256, int(math.floor(px.max() + 2)) // 256
    y0, y1 = int(math.floor(py.min() - 2)) // 256, int(math.floor(py.max() + 2)) // 256
    if need is not None and need.any() and not need.all():
        wx, wy = px[need], py[need]
        want = set()
        for dx in (-2, 2):
            for dy in (-2, 2):
                tx, ty = np.floor((wx + dx) / 256).astype(np.int64), np.floor((wy + dy) / 256).astype(np.int64)
                want.update(zip(tx.tolist(), ty.tolist()))
        tiles = sorted((tx, ty) for tx, ty in want if x0 <= tx <= x1 and y0 <= ty <= y1)
    else:
        tiles = [(tx, ty) for ty in range(y0, y1 + 1) for tx in range(x0, x1 + 1)]
    mosaic = np.full(((y1 - y0 + 1) * 256, (x1 - x0 + 1) * 256), np.nan)
    done = [0]

    def one(t):
        tx, ty = t
        tile = _tile(url, decode, z, tx, ty, cancel, cache, missing_ok)
        if tile is not None:
            mosaic[(ty - y0) * 256:(ty - y0 + 1) * 256, (tx - x0) * 256:(tx - x0 + 1) * 256] = tile
        done[0] += 1
        progress(done[0] / len(tiles), 'Downloading %s (%d of %d)...' % (_dl(what), done[0], len(tiles)))

    with ThreadPoolExecutor(6) as ex:
        list(ex.map(one, tiles))
    if not np.isfinite(mosaic).any():
        return None
    return sample_cubic(mosaic, py - y0 * 256 - 0.5, px - x0 * 256 - 0.5)


def _terrarium_sample(LA, LO, z, cancel, progress):
    """unsmoothed Terrain Tiles elevation at the grid points, from zoom z"""
    return _tile_sample(LA, LO, z, TERRARIUM_URL, _decode_terrarium, cancel, progress, 'elevation tiles',
                        cache='terrarium')


def _gsi(layers, zmax):
    """a source from GSI Japan's elevation tiles: the first layer, its gaps filled from the following ones.
    The zoom is the finest whose pixels are at least 3/4 of the window's grid spacing, so a 2 m grid gets the
    ~1.9 m zoom 16, not zoom 15"""
    def fetch(LA, LO, bbox, spacing, cancel, progress, need=None):
        z = terrarium_zoom(float(LA.mean()), 0.75 * spacing, zmax, min_res=0.0)
        out = None
        for i, layer in enumerate(layers):
            if out is None:
                r0, r1, c0, c1 = 0, LA.shape[0], 0, LA.shape[1]
                want = need
            else:                                           # the following layers: only the box of what is missing
                gap = ~np.isfinite(out)
                if (gap if need is None else gap & need).mean() <= MAX_GAP:   # nearly complete: the following layers are not downloaded
                    break
                rows, cols = np.nonzero(gap.any(axis=1))[0], np.nonzero(gap.any(axis=0))[0]
                r0, r1, c0, c1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
                want = gap if need is None else gap & need   # only the tiles the open part of what is wanted touches
                want = want[r0:r1, c0:c1]
            v = _tile_sample(LA[r0:r1, c0:c1], LO[r0:r1, c0:c1], z, GSI_URL.replace('{layer}', layer), _decode_gsi,
                             cancel, lambda f, t, i=i: progress((i + f) / len(layers), t), 'Japanese elevation',
                             missing_ok=True, need=want)
            if v is None:
                continue
            if out is None:
                out = v
            else:
                out[r0:r1, c0:c1] = np.where(np.isfinite(out[r0:r1, c0:c1]), out[r0:r1, c0:c1], v)
        return out
    fetch.wants_need = True
    return fetch


def _terrarium_sigma(size_m):
    # coarse source (~30 m outside the US): smooth the stair steps of the upsampled tiles; stronger on small windows
    return float(np.clip(3.0 * math.sqrt(8000.0 / size_m), 2.0, 5.0))


# ---- STAC catalogues (pystac-client) and cloud-optimised GeoTIFFs (rasterio)

STATS = {'cog_bytes': 0}  # estimated bytes read from cloud-optimised GeoTIFFs (for the live test's report)


def _stac_client(api_url, auth=None):
    """pystac-client Client for a STAC API, with RETRIES retries and a 60 s timeout; `auth` = bearer token"""
    from pystac_client import Client, ConformanceClasses
    from pystac_client.stac_api_io import StacApiIO
    headers = {'Authorization': 'Bearer ' + auth} if isinstance(auth, str) else None
    client = Client.open(api_url, headers=headers, stac_io=StacApiIO(max_retries=RETRIES, timeout=60))
    if not client.conforms_to(ConformanceClasses.ITEM_SEARCH):   # some catalogues under-declare what they support
        client.add_conforms_to('ITEM_SEARCH')
    return client


def _stac_items(api_url, collection, bbox, cancel, max_items=2000, auth=None):
    """all items of `collection` intersecting bbox (lon/lat), via the standard STAC item search"""
    import pystac_client.exceptions as pce
    import requests
    try:
        search = _stac_client(api_url, auth).search(collections=[collection], bbox=list(bbox), limit=100,
                                              max_items=max_items)
        items = []
        for it in search.items():
            _check_cancel(cancel)
            items.append(it)
        return items
    except (pce.APIError, requests.RequestException, ValueError) as e:
        raise net.NetError('STAC search %s/%s failed: %s' % (api_url, collection, e))


def _asset_href(item, keys=(), contains=None):
    """href of the item's GeoTIFF asset: the first of `keys` present, else the first .tif asset (optionally one whose
    href contains `contains`). Scheme-less hrefs get https://."""
    cands = [item.assets[k] for k in keys if k in item.assets]
    cands += [a for a in item.assets.values() if a.href.split('?')[0].lower().endswith(('.tif', '.tiff'))
              and (contains is None or contains in a.href)]
    if not cands:
        return None
    h = cands[0].href
    return h if '://' in h else 'https://' + h.lstrip('/')


def _cog_window(url, box_fn, spacing, what, auth=None):
    """Read the part of a cloud-optimised GeoTIFF covering the window with rasterio, from the coarsest internal
    level whose pixels are <= the window's spacing, never one finer than MIN_DL_RES. Only the internal tiles that
    overlap are downloaded (GDAL range requests). box_fn(crs) -> (x0, y0, x1, y1) of the window in that CRS.
    -> (img with NaN, (left, top, px), crs) or None if the window misses the file"""
    import rasterio
    from rasterio.windows import Window
    href = url if url.startswith('/vsi') else '/vsicurl/' + url
    with _gdal_env(auth):
        try:
            with rasterio.open(href) as ds:
                t, crs = ds.transform, ds.crs
                if t.b or t.d:
                    raise DemError('%s is not north-up' % what)
                res = abs(t.a)
                levels = [(1, None)] + [(f, i) for i, f in enumerate(ds.overviews(1))]
                ok = [(f, i) for f, i in levels if res * f >= MIN_DL_RES - 1e-6]
                if not ok:
                    raise DemError('%s has no internal level at %.0f m or coarser' % (what, MIN_DL_RES))
                fit = [(f, i) for f, i in ok if res * f <= max(spacing, MIN_DL_RES) + 1e-6]
                f, level = max(fit) if fit else min(ok)
            opts = {} if level is None else {'overview_level': level}
            with rasterio.open(href, **opts) as ds:
                t = ds.transform
                px, py = abs(t.a), abs(t.e)
                bx0, by0, bx1, by1 = box_fn(crs)
                c0, c1 = int(math.floor((bx0 - t.c) / px)) - 2, int(math.ceil((bx1 - t.c) / px)) + 2
                r0, r1 = int(math.floor((t.f - by1) / py)) - 2, int(math.ceil((t.f - by0) / py)) + 2
                c0, r0, c1, r1 = max(0, c0), max(0, r0), min(ds.width, c1), min(ds.height, r1)
                if c1 <= c0 or r1 <= r0:
                    return None
                if (c1 - c0) * (r1 - r0) > MAX_CROP_PX:
                    raise DemError('%s: window would need %dx%d px at %.1f m (no coarser internal level); skipped'
                                   % (what, c1 - c0, r1 - r0, px))
                win = Window(c0, r0, c1 - c0, r1 - r0)
                img = ds.read(1, window=win, masked=True).astype(np.float64).filled(np.nan)
                STATS['cog_bytes'] += _window_bytes(ds, win)
        except rasterio.errors.RasterioError as e:
            raise net.NetError('%s: cannot read %s: %s' % (what, url, e))
    img[(img < -1000) | (img > 9000)] = np.nan
    log.info('%s: %dx%d px at %.1f m read from %s', what, c1 - c0, r1 - r0, px, url.rsplit('/', 1)[-1])
    return img, (t.c + c0 * px, t.f - r0 * py, px), crs


def _window_bytes(ds, win):
    """compressed size of the internal tiles a window read touched (an estimate of the download)"""
    try:
        bh, bw = ds.block_shapes[0]
        total = 0
        for j in range(int(win.row_off) // bh, (int(win.row_off + win.height) - 1) // bh + 1):
            for i in range(int(win.col_off) // bw, (int(win.col_off + win.width) - 1) // bw + 1):
                total += ds.block_size(1, j, i)
        return total
    except Exception:
        return 0


def _cog_mosaic(hrefs, LA, LO, native, spacing, what, cancel, progress, auth=None, missing_ok=False):
    """Window of several cloud-optimised GeoTIFFs (e.g. adjacent tiles of one product) sampled at the grid points.
    Files sharing a CRS and pixel size are pasted into one mosaic first (no seams between tiles); the first file in
    `hrefs` wins where files overlap. -> values (NaN = no data) or None"""
    import threading
    read_spacing = dl_res(spacing, native)
    proj, lock = {}, threading.Lock()

    def box(crs):                                           # the window's box in a file's CRS (projected once per CRS)
        key = crs.to_string()
        with lock:
            if key not in proj:
                proj[key] = _project(LA, LO, crs)
            X, Y = proj[key]
        pad = 3 * read_spacing
        return X.min() - pad, Y.min() - pad, X.max() + pad, Y.max() + pad

    parts = [None] * len(hrefs)
    done = [0]

    def one(i):
        _check_cancel(cancel)
        try:
            parts[i] = _cog_window(hrefs[i], box, read_spacing, what, auth)
        except net.NetError as e:
            if not (missing_ok and '404' in str(e)):        # tiles that do not exist (sea, outside the product) are fine
                raise
        done[0] += 1
        progress(0.1 + 0.9 * done[0] / len(hrefs), 'Downloading %s (%d of %d)...' % (_dl(what), done[0], len(hrefs)))

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, range(len(hrefs))))
    groups = {}                                             # (crs, pixel size) -> parts, in href order
    for part in parts:
        if part is not None:
            groups.setdefault((part[2].to_string(), round(part[1][2], 6)), []).append(part)
    out = None
    for (key, px), ps in groups.items():
        gx0 = min(p[1][0] for p in ps)
        gy1 = max(p[1][1] for p in ps)
        W = max(int(round((p[1][0] - gx0) / px)) + p[0].shape[1] for p in ps)
        H = max(int(round((gy1 - p[1][1]) / px)) + p[0].shape[0] for p in ps)
        mosaic = np.full((H, W), np.nan, np.float32)
        for img, (x0, y0, _), _ in reversed(ps):            # reversed: earlier files are pasted last, so they win
            c, r = int(round((x0 - gx0) / px)), int(round((gy1 - y0) / px))
            np.copyto(mosaic[r:r + img.shape[0], c:c + img.shape[1]], img.astype(np.float32), where=np.isfinite(img))
        X, Y = proj[key]
        v = _sample_grid(mosaic, gx0, gy1, px, X, Y, spacing)
        out = v if out is None else np.where(np.isfinite(out), out, v)
    if out is None or not np.isfinite(out).any():
        return None
    return out


def _sample_grid(img, x0, y0, px, X, Y, spacing):
    """sample a north-up grid (top-left corner x0, y0; square pixels px) at X, Y; block-averaged first when the
    window's spacing is at least twice the source resolution, so fine detail does not alias"""
    k = int(spacing // px)
    if k >= 2:
        img, px = _block_mean(np.asarray(img, np.float64), k), px * k
    return _sample_inside(np.asarray(img, np.float64), (y0 - Y) / px - 0.5, (X - x0) / px - 0.5)


def _swiss_3d(LA, LO, bbox, spacing, cancel, progress):
    """swissALTI3D, 2 m, for windows whose grid is finer than swissALTIRegio's 10 m; Switzerland and Liechtenstein"""
    if dl_res(spacing, SWISS3D_RES) >= SWISS_RES:
        return None                                         # swissALTIRegio is just as detailed for this window
    progress(0.0, 'Finding tiles...')
    best = {}
    for it in _stac_items(SWISS_STAC_API, 'ch.swisstopo.swissalti3d', bbox, cancel):
        m = re.match(r'swissalti3d_(\d{4})_(\d{4}-\d{4})$', it.id)
        href = _asset_href(it, contains='_2_2056_')          # each tile comes as a 2 m and a 0.5 m GeoTIFF: only the 2 m one is used
        if not (m and href):
            continue
        year, tile = int(m.group(1)), m.group(2)
        if tile not in best or year > best[tile][0]:        # newest survey of each 1 km tile
            best[tile] = (year, href)
    if not best:
        return None
    if len(best) > SWISS3D_MAX_TILES:
        log.info('window needs %d swissALTI3D tiles; using swissALTIRegio instead', len(best))
        return None
    return _cog_mosaic([b[1] for b in best.values()], LA, LO, SWISS3D_RES, spacing, 'swisstopo', cancel, progress)


def _swiss(LA, LO, bbox, spacing, cancel, progress):
    progress(0.0, 'Finding tiles...')
    url = SWISS_COG_URL
    try:                                                    # the one full-coverage item of the collection
        item = _stac_client(SWISS_STAC_API).get_collection('ch.swisstopo.swissaltiregio').get_item('swissaltiregio')
        url = (item and _asset_href(item)) or url
    except Exception as e:                                  # catalogue unreachable: the file's known address
        if _cancelled(cancel):
            raise
        log.info('swissALTIRegio STAC lookup failed (%s), using %s', e, url)
    return _cog_mosaic([url], LA, LO, SWISS_RES, spacing, 'swissALTIRegio', cancel, progress)


# ---- national coverage services (Italy, France)

def _wcs_grid(make_url, X, Y, res, chunk_m, what, cancel, progress, zero_is_nodata=False, timeout=300):
    """Request a coverage service on a fixed grid (pixel edges on multiples of `res` in its CRS) in chunks of at most
    chunk_m, only over the window's box, and sample it at X, Y. make_url(x0, y0, x1, y1, nx, ny) -> URL of a GeoTIFF.
    `res` and `chunk_m` may be (x, y) pairs, for grids whose pixels are not square (geographic coordinates).
    -> values at X, Y (NaN where the service has no data) or None"""
    rx, ry = res if isinstance(res, tuple) else (res, res)
    cx, cy = chunk_m if isinstance(chunk_m, tuple) else (chunk_m, chunk_m)
    gx0, gy0 = math.floor((X.min() - 3 * rx) / rx) * rx, math.floor((Y.min() - 3 * ry) / ry) * ry
    gx1, gy1 = math.ceil((X.max() + 3 * rx) / rx) * rx, math.ceil((Y.max() + 3 * ry) / ry) * ry
    nx_all, ny_all = int(round((gx1 - gx0) / rx)), int(round((gy1 - gy0) / ry))
    sx, sy = max(1, int(cx // rx)), max(1, int(cy // ry))
    mosaic = np.full((ny_all, nx_all), np.nan)
    parts = [(c, r) for r in range(0, ny_all, sy) for c in range(0, nx_all, sx)]
    done, got = [0], [0]

    def one(p):
        c, r = p
        nx, ny = min(sx, nx_all - c), min(sy, ny_all - r)
        x0, y1 = gx0 + c * rx, gy1 - r * ry
        img, _ = _read_tiff(net.get(make_url(x0, y1 - ny * ry, x0 + nx * rx, y1, nx, ny), timeout=timeout, retries=RETRIES,
                                    cancel=cancel), what)
        if img.shape != (ny, nx):                           # e.g. a native-resolution reply: average it down
            k = img.shape[0] / ny
            if abs(k - round(k)) > 1e-6 or abs(img.shape[1] / nx - k) > 1e-6:
                raise DemError('%s returned %s instead of %dx%d' % (what, img.shape, ny, nx))
            img = _block_mean(img, int(round(k)))[:ny, :nx]
        if zero_is_nodata:
            img[img == 0] = np.nan
        mosaic[r:r + ny, c:c + nx] = img
        got[0] += 1
        done[0] += 1
        progress(done[0] / len(parts), 'Downloading %s (%d of %d)...' % (_dl(what), done[0], len(parts)))

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(one, parts))
    if not got[0] or not np.isfinite(mosaic).any():
        return None
    return _sample_inside(mosaic, (gy1 - Y) / ry - 0.5, (X - gx0) / rx - 0.5)


def _idee_format(make_url, cx, cy, d, cancel):
    """find the server's name for GeoTIFF with a tiny request around (cx, cy); -> name or None"""
    for f in IDEE_FORMATS:
        try:
            data = net.get(make_url(f, cx, cy, cx + 4 * d[0], cy + 4 * d[1], 4, 4), timeout=60, retries=RETRIES,
                           cancel=cancel)
        except net.NetError:
            if _cancelled(cancel):
                raise
            continue
        if data[:2] in (b'II', b'MM'):
            return f
    return None


def _spain(LA, LO, bbox, spacing, cancel, progress):
    lat0, lon0 = float(LA.mean()), float(LO.mean())
    if lon0 > -10.5 and lat0 > 35.5:                        # peninsula and Balearics: native UTM 30N grid
        X, Y = _project(LA, LO, 'EPSG:25830')
        r = grid_res(spacing, ES_RES)

        def utm(f, x0, y0, x1, y1, nx, ny):
            return IDEE_UTM_URL.format(fmt=f, x0=x0, y0=y0, x1=x1, y1=y1, nx=nx, ny=ny)
        cx, cy = math.floor(float(X.mean()) / r) * r, math.floor(float(Y.mean()) / r) * r
        fmt = _idee_format(utm, cx, cy, (r, r), cancel)
        if fmt:
            try:
                return _wcs_grid(lambda *a: utm(fmt, *a), X, Y, r, 2000 * r, 'Spanish', cancel, progress,
                                 zero_is_nodata=True)
            except (net.NetError, DemError) as e:
                if _cancelled(cancel):
                    raise
                log.warning('MDT05 on its UTM grid failed (%s): trying the geographic coverage', _redact(e))
        else:
            log.warning('MDT05 on its UTM grid returned no GeoTIFF: trying the geographic coverage')
    ry = dl_res(spacing, ES_RES) / 111320.0                 # the window's grid (>= 5 m) in ETRS89 degrees
    rx = ry / max(math.cos(math.radians(lat0)), 0.05)

    def geo(f, x0, y0, x1, y1, nx, ny):
        return IDEE_WCS_URL.format(fmt=f, x0=x0, y0=y0, x1=x1, y1=y1, nx=nx, ny=ny)
    fmt = _idee_format(geo, lon0, lat0, (rx, ry), cancel)
    if not fmt:
        raise DemError('IGN Spain returned no GeoTIFF for any of %s' % (IDEE_FORMATS,))
    # chunks of ~10 km; values of 0 are the sea or outside Spain
    return _wcs_grid(lambda *a: geo(fmt, *a), LO, LA, (rx, ry), (2000 * rx, 2000 * ry), 'Spanish', cancel, progress,
                     zero_is_nodata=True)


def _canada(LA, LO, bbox, spacing, cancel, progress):
    progress(0.0, 'Finding tiles...')
    # the 1 m mosaic when the window's grid is finer than 2 m (it holds the provinces' lidar, British Columbia's
    # included), else the 2 m one; both are the same product on the same tiles
    for coll, res in (('hrdem-mosaic-1m', 1.0), ('hrdem-mosaic-2m', CA_RES)):
        if res < CA_RES and spacing >= CA_RES:
            continue
        hrefs = [h for h in (_asset_href(it, ('dtm',)) for it in _stac_items(CCMEO_STAC_API, coll, bbox, cancel)) if h]
        if hrefs:
            v = _cog_mosaic(hrefs, LA, LO, res, spacing, 'Canadian', cancel, progress)
            if v is not None and np.isfinite(v).any():
                return v
            break                   # tiles listed but empty here: the 2 m mosaic has the same tiles, so skip reading them
    return None                                             # no HRDEM here: Terrain Tiles cover it


def _canada_arctic(LA, LO, bbox, spacing, cancel, progress):
    """NRCan's ArcticDEM-based HRDEM (2 m) for northern Canada. It is a surface model, so outside the treeless north
    it includes vegetation; it is listed after the lidar HRDEM and only fills what that leaves empty. Its CRS is read
    from each file."""
    progress(0.0, 'Finding tiles...')
    hrefs = [h for h in (_asset_href(it, ('dsm', 'dtm')) for it in _stac_items(CCMEO_STAC_API, 'hrdem-arcticdem',
                                                                                bbox, cancel)) if h]
    if not hrefs:
        return None
    return _cog_mosaic(hrefs, LA, LO, CA_RES, spacing, 'northern Canadian', cancel, progress)


_LM_TOKEN = {}


def _lm_token(cancel=None):
    """OAuth2 client-credentials access token of the Lantmäteriet developer-portal app (cached until it nearly expires)"""
    import base64
    import time
    import requests
    cached = _LM_TOKEN.get('t')
    if cached and cached[1] > time.time() + 60:
        return cached[0]
    k = credentials.get('lantmateriet')
    if not k:
        raise DemError('no Lantmateriet key: enter it in the app (or set LM_CLIENT_ID and LM_CLIENT_SECRET) to use the Swedish model')
    cred = base64.b64encode(('%s:%s' % (k['key'], k['secret'])).encode()).decode()
    last = None
    for _ in range(RETRIES):
        _check_cancel(cancel)
        try:
            r = requests.post(LM_TOKEN_URL, data={'grant_type': 'client_credentials'}, timeout=30,
                              headers={'Authorization': 'Basic ' + cred})
            r.raise_for_status()
            js = r.json()
            _LM_TOKEN['t'] = (js['access_token'], time.time() + float(js.get('expires_in', 3600)))
            return _LM_TOKEN['t'][0]
        except (requests.RequestException, ValueError, KeyError) as e:
            last = e
    raise net.NetError('Lantmateriet token request failed: %s' % last)


def _sweden(LA, LO, bbox, spacing, cancel, progress):
    # The sheets are public in the STAC search; the file server (dl1.lantmateriet.se) wants the OAuth2 access token of an
    # API-portal application whose Geotorget account has the (free) permission "Markhöjdmodell Nedladdning" in production.
    progress(0.0, 'Finding tiles...')
    hrefs = [h for h in (_asset_href(it) for it in _stac_items(LM_STAC_API, 'dtm-cog', bbox, cancel)) if h]
    if not hrefs:
        return None
    token = _lm_token(cancel)
    # the 1 m model, read at the coarsest internal level that still resolves the window (never finer than the window's grid needs)
    try:
        return _cog_mosaic(hrefs, LA, LO, LM_RES, spacing, 'Swedish', cancel, progress, auth=token)
    except net.NetError as e:
        if '401' in str(e) or '403' in str(e):
            raise DemError('Lantmateriet refused the key (HTTP 401/403). Check that "Markhöjdmodell Nedladdning" is ordered '
                           'in Geotorget for production, and that the key comes from the production keys of an application.')
        raise


def _norway(LA, LO, bbox, spacing, cancel, progress):
    X, Y = _project(LA, LO, 'EPSG:25833')                   # Kartverket serves the whole country in UTM 33N
    url = lambda x0, y0, x1, y1, nx, ny: KARTVERKET_WCS_URL.format(x0=x0, y0=y0, x1=x1, y1=y1, nx=nx, ny=ny)
    # the service returns 0.0 for sea and for areas it does not cover (e.g. Sweden): treat that as no data
    r = dl_res(spacing, NO_RES)
    return _wcs_grid(url, X, Y, r, 4000 * r, 'Norwegian', cancel, progress, zero_is_nodata=True)


def _finland(LA, LO, bbox, spacing, cancel, progress):
    key = (credentials.get('nls') or {}).get('key')
    if not key:
        raise DemError('no NLS API key: enter it in the app (or set MML_API_KEY) to use the Finnish elevation model')
    X, Y = _project(LA, LO, 'EPSG:3067')                    # ETRS-TM35FIN
    chunk = 10000.0                                         # the service's limit per request is 10 x 10 km
    r = FI_RES * max(1, round(dl_res(spacing, FI_RES) / FI_RES))   # a multiple of the native 2 m

    def scaled(x0, y0, x1, y1, nx, ny):                     # ask the server for the coarser grid directly
        return MML_WCS_URL.format(x0=x0, y0=y0, x1=x1, y1=y1, key=key, scale='&SCALESIZE=E(%d),N(%d)' % (nx, ny))

    def native(x0, y0, x1, y1, nx, ny):                     # 2 m reply, averaged down by _wcs_grid
        return MML_WCS_URL.format(x0=x0, y0=y0, x1=x1, y1=y1, key=key, scale='')

    if r <= FI_RES:                                         # 5 km chunks: 2500 x 2500 px each
        return _wcs_grid(native, X, Y, FI_RES, 5000.0, 'Finnish', cancel, progress)
    try:
        return _wcs_grid(scaled, X, Y, r, chunk, 'Finnish', cancel, progress)
    except (DemError, net.NetError) as e:
        if _cancelled(cancel):
            raise
        log.info('NLS refused the scaled request (%s); fetching 2 m and averaging to %.0f m', _redact(e), r)
        return _wcs_grid(native, X, Y, r, 5000.0, 'Finnish', cancel, progress)   # 5 km chunks keep 2 m in memory


def _italy(LA, LO, bbox, spacing, cancel, progress):
    X, Y = _project(LA, LO, 'EPSG:32632')                   # TINITALY: WGS 84 / UTM 32N for all of Italy
    out = np.full(LA.shape, np.nan)
    k = int(dl_res(spacing, IT_RES) // IT_RES)              # 1 = native 10 m; >1 = the server averages it down
    scale = '&SCALEFACTOR=%.6f' % (1.0 / k) if k > 1 else ''
    chunk, pad = 8000.0 * max(1, int(dl_res(spacing, IT_RES) // IT_RES)), 40.0   # 800 x 800 px per request
    xs = np.arange(math.floor(X.min() / 10) * 10, X.max() + 1, chunk)
    ys = np.arange(math.floor(Y.min() / 10) * 10, Y.max() + 1, chunk)
    parts = [(x0, y0) for x0 in xs for y0 in ys]
    done, got = [0], [0]

    def one(p):
        x0, y0 = p
        x1, y1 = min(x0 + chunk, X.max() + 1e-6), min(y0 + chunk, Y.max() + 1e-6)
        sel = (X >= x0) & (X <= x1) & (Y >= y0) & (Y <= y1)
        if not sel.any():
            return
        data = None
        # the request box is aligned to TINITALY's 10 m cell edges, so a reply without georeferencing still has a
        # known grid: exactly the requested cells
        bx0, by0 = math.floor((x0 - pad * k) / IT_RES) * IT_RES, math.floor((y0 - pad * k) / IT_RES) * IT_RES
        bx1, by1 = math.ceil((x1 + pad * k) / IT_RES) * IT_RES, math.ceil((y1 + pad * k) / IT_RES) * IT_RES
        for ax, ay in (('E', 'N'), ('x', 'y')):           # GeoServer names the axes after the CRS; try both spellings
            try:
                data = net.get(TINITALY_WCS_URL.format(ax=ax, ay=ay, x0=bx0, x1=bx1, y0=by0, y1=by1, scale=scale),
                               timeout=180, retries=RETRIES, cancel=cancel)
                if data[:2] in (b'II', b'MM'):
                    break
            except net.NetError:
                if _cancelled(cancel):
                    raise
                data = None
        if not data or data[:2] not in (b'II', b'MM'):
            log.info('TINITALY has nothing for %.0f,%.0f', x0, y0)
            return
        img, gt = _read_tiff(data, 'TINITALY')
        if gt is None:
            # plain TIFF: TINITALY's 10 m cells have edges on multiples of 10 m and the request box is aligned to
            # them, so the image spans exactly the requested box
            h, w = img.shape
            gt = (bx0, by1, (bx1 - bx0) / w, (by1 - by0) / h)
            log.info('TINITALY sent no georeferencing; using the requested box')
        gx0, gy0, sx, sy = gt
        out[sel] = _sample_inside(img, (gy0 - Y[sel]) / sy - 0.5, (X[sel] - gx0) / sx - 0.5)
        got[0] += 1

    def wrapped(p):
        one(p)
        done[0] += 1
        progress(done[0] / len(parts), 'Downloading %s (%d of %d)...' % (_dl('Italian'), done[0], len(parts)))

    with ThreadPoolExecutor(4) as ex:
        list(ex.map(wrapped, parts))
    return out if got[0] else None


def _ign(LA, LO, spacing, layers, native, what, cancel, progress):
    """IGN Geoplateforme WMS-R in Lambert-93 on whole multiples of the source's pixel; the first layer that answers
    is kept for the whole window. -> values at the grid (NaN = no data) or None"""
    X, Y = _project(LA, LO, 'EPSG:2154')                    # Lambert-93
    r = grid_res(spacing, native)
    pad = 4 * r
    # pixel edges on (k + 0.5) * r, so the requested grid stays put however the window moves
    x0 = (math.floor((X.min() - pad) / r) - 0.5) * r
    y1 = (math.ceil((Y.max() + pad) / r) + 0.5) * r
    nx_all = int(math.ceil((X.max() + pad - x0) / r))
    ny_all = int(math.ceil((y1 - (Y.min() - pad)) / r))
    step = 4000                                              # Geoplateforme limit is 5010 px per side
    mosaic = np.full((ny_all, nx_all), np.nan)
    parts = [(c, rr) for rr in range(0, ny_all, step) for c in range(0, nx_all, step)]
    done, got, layer = [0], [0], [None]

    def fetch(c, rr):
        nx, ny = min(step, nx_all - c), min(step, ny_all - rr)
        bx0, by1 = x0 + c * r, y1 - rr * r
        last = None
        for lay in ([layer[0]] if layer[0] else layers):
            try:
                data = net.get(IGN_WMS_URL.format(layer=lay, x0=bx0, y0=by1 - ny * r, x1=bx0 + nx * r, y1=by1,
                                                  nx=nx, ny=ny), timeout=300, retries=RETRIES, cancel=cancel)
                img, _ = _read_tiff(data, what)
            except (net.NetError, DemError) as e:
                if _cancelled(cancel):
                    raise
                last = e
                continue
            if img.shape != (ny, nx):
                last = DemError('%s returned %s instead of %dx%d' % (what, img.shape, ny, nx))
                continue
            layer[0] = lay
            mosaic[rr:rr + ny, c:c + nx] = img
            got[0] += 1
            return
        raise last or DemError('%s returned nothing' % what)

    for c, rr in parts:                                      # sequential: the first answer decides the layer
        fetch(c, rr)
        done[0] += 1
        progress(done[0] / len(parts), 'Downloading %s (%d of %d)...' % (_dl(what), done[0], len(parts)))
    log.info('%s on a %.1f m grid from layer %s', what, r, layer[0])
    if not got[0] or not np.isfinite(mosaic).any():
        return None
    return _sample_grid(mosaic, x0, y1, r, X, Y, spacing)


def _italy_regional(LA, LO, spacing, make_url, epsgs, native, what, cancel, progress, zero_is_nodata=False):
    """a regional WCS 1.0 on whole multiples of its native pixel, in the first of `epsgs` it accepts"""
    last = None
    for epsg in epsgs:
        X, Y = _project(LA, LO, 'EPSG:%d' % epsg)
        r = grid_res(spacing, native)
        try:
            return _wcs_grid(lambda *a, e=epsg: make_url(e, *a), X, Y, r, 2000 * r, what, cancel, progress,
                             zero_is_nodata=zero_is_nodata)
        except (net.NetError, DemError) as e:
            if _cancelled(cancel):
                raise
            last = e
    raise last


def _south_tyrol(LA, LO, bbox, spacing, cancel, progress):
    return _italy_regional(LA, LO, spacing, lambda e, x0, y0, x1, y1, nx, ny: BZ_WCS_URL.format(
        cov=BZ_COV, x0=x0, y0=y0, x1=x1, y1=y1, nx=nx, ny=ny), (25832,), 2.5, 'South Tyrol', cancel, progress)


def _france_lidar(LA, LO, bbox, spacing, cancel, progress):
    return _ign(LA, LO, spacing, IGN_LIDAR_LAYERS, FR_LIDAR_RES, 'LiDAR HD', cancel, progress)


def _france(LA, LO, bbox, spacing, cancel, progress):
    return _ign(LA, LO, spacing, IGN_LAYERS, FR_RGE_RES, 'RGE ALTI', cancel, progress)


# Order = priority. Any number of sources may overlap: at every point the source listed first that has (valid) data
# there is used; later sources only fill what earlier ones leave empty, and AWS Terrain Tiles fill whatever is left.
# Each source can be clipped to its own countries (ISO codes, from data/borders.npz), because some services return
# coarse filler data beyond their border. Where two sources meet, the finer one is kept and the coarser one is bent to
# meet it (see _blend).

# ---- more national sources. Each uses one of the two access paths every other source uses:
#   * GeoTIFF files read in part over HTTP (_cog_mosaic): `_tiles` builds the file names of a regular tile grid
#   * a coverage / image service asked for a GeoTIFF of the window (_wcs_grid): `_service`

def _tiles(what, crs, tile_m, url_fn, native, max_tiles=400):
    """source made of GeoTIFF tiles on a regular grid in `crs`; url_fn(x0, y0) -> URL(s) of the tile whose lower-left
    corner is x0, y0 (several URLs = editions, newest first). Tiles that do not exist are skipped."""
    def fetch(LA, LO, bbox, spacing, cancel, progress):
        X, Y = _project(LA, LO, crs)
        xs = range(int(math.floor(X.min() / tile_m)), int(math.floor(X.max() / tile_m)) + 1)
        ys = range(int(math.floor(Y.min() / tile_m)), int(math.floor(Y.max() / tile_m)) + 1)
        if len(xs) * len(ys) > max_tiles:
            raise DemError('%s: the window needs %d tiles (limit %d)' % (what, len(xs) * len(ys), max_tiles))
        urls = [url_fn(x * tile_m, y * tile_m) for y in ys for x in xs]
        for edition in range(max(len(u) for u in urls)):
            hrefs = [u[edition] for u in urls if len(u) > edition]
            v = _cog_mosaic(hrefs, LA, LO, native, spacing, what, cancel, progress, missing_ok=True)
            if v is not None and np.isfinite(v).any():
                return v
        return None
    return fetch


def _service(what, url, epsg, native, formats=('GeoTIFF', 'image/tiff', 'GTiff'), chunk_px=2000, zero_is_nodata=False,
             timeout=300):
    """source behind a coverage or image service: `url` is a template with {fmt}, {x0}, {y0}, {x1}, {y1}, {nx}, {ny},
    asked on whole multiples of the native pixel in EPSG:<epsg> (None: geographic, in degrees). The server's name for
    GeoTIFF is found with a tiny request, as services differ in it."""
    def fetch(LA, LO, bbox, spacing, cancel, progress):
        r = grid_res(spacing, native)
        if epsg is None:
            X, Y = LO, LA
            ry = r / 111320.0
            res = (ry / max(math.cos(math.radians(float(LA.mean()))), 0.05), ry)
        else:
            X, Y = _project(LA, LO, 'EPSG:%d' % epsg)
            res = (r, r)

        def make(f, x0, y0, x1, y1, nx, ny):
            return url.format(fmt=f, x0=x0, y0=y0, x1=x1, y1=y1, nx=nx, ny=ny)
        fmt = formats[0]
        if len(formats) > 1:
            fmt = _idee_format(make, float(X.mean()), float(Y.mean()), res, cancel)
            if fmt is None:
                raise DemError('%s: the service did not answer with a GeoTIFF' % what)
        return _wcs_grid(lambda *a: make(fmt, *a), X, Y, res, (chunk_px * res[0], chunk_px * res[1]), what, cancel,
                         progress, zero_is_nodata=zero_is_nodata, timeout=timeout)
    return fetch


_WCS10 = ('?service=WCS&version=1.0.0&request=GetCoverage&coverage=%s&crs=EPSG:%d&format={fmt}'
          '&bbox={x0:.8f},{y0:.8f},{x1:.8f},{y1:.8f}&width={nx}&height={ny}')


def _nz_sheet(x0, y0):
    """LINZ Topo50 sheet code of the 24 x 36 km sheet whose lower-left corner is x0, y0 in NZTM (EPSG:2193), offset
    from the sheet grid's origin (linz/argo-tasks mapsheet.ts); the rows BI, BO and CI do not exist"""
    cx, c = int(round((x0 - 988000) / 24000)), int(round((6234000 - (y0 + 36000)) / 36000))
    for skip in (16, 22, 42):
        if c >= skip:
            c += 1
    c += ord('S') - ord('A')
    return '%s%s%02d' % (chr(c // 26 + 65), chr(c % 26 + 65), cx)


def _nz_tiles(LA, LO, bbox, spacing, cancel, progress):
    """LINZ 8 m DEM: one cloud-optimised GeoTIFF per Topo50 sheet (24 x 36 km, a grid that is not square and starts
    at 988000, 6234000), on AWS Open Data"""
    X, Y = _project(LA, LO, 'EPSG:2193')
    xs = range(int(math.floor((X.min() - 988000) / 24000)), int(math.floor((X.max() - 988000) / 24000)) + 1)
    ys = range(int(math.floor((6234000 - Y.max()) / 36000)), int(math.floor((6234000 - Y.min()) / 36000)) + 1)
    hrefs = [NZ_URL % _nz_sheet(988000 + x * 24000, 6234000 - (y + 1) * 36000) for y in ys for x in xs]
    return _cog_mosaic(hrefs, LA, LO, 8.0, spacing, 'New Zealand', cancel, progress, missing_ok=True)

NZ_URL_1M = 'https://nz-elevation.s3-ap-southeast-2.amazonaws.com/new-zealand/new-zealand/dem_1m/2193/%s.tiff'


def _nz_sheets(LA, LO):
    X, Y = _project(LA, LO, 'EPSG:2193')
    xs = range(int(math.floor((X.min() - 988000) / 24000)), int(math.floor((X.max() - 988000) / 24000)) + 1)
    ys = range(int(math.floor((6234000 - Y.max()) / 36000)), int(math.floor((6234000 - Y.min()) / 36000)) + 1)
    return [_nz_sheet(988000 + x * 24000, 6234000 - (y + 1) * 36000) for y in ys for x in xs]


def _nz_lidar(LA, LO, bbox, spacing, cancel, progress):
    """LINZ 1 m DEM from lidar: the same Topo50 sheets as the 8 m model, but only where lidar exists (a sheet that is
    not there is skipped; the 8 m model and Terrain Tiles fill the rest)"""
    hrefs = [NZ_URL_1M % n for n in _nz_sheets(LA, LO)]
    return _cog_mosaic(hrefs, LA, LO, 1.0, spacing, 'New Zealand lidar', cancel, progress, missing_ok=True)


SRSP_BUCKET = 'https://srsp-open-data.s3.eu-west-2.amazonaws.com/'
# newest survey first: Scotland's lidar is published per survey phase, in 10 km Ordnance Survey squares
SRSP_PREFIXES = ['lidar/phase-%d/dtm/27700/gridded/' % p for p in (6, 5, 4, 3, 2, 1)]    # (the coastal and island surveys use other tiles)


def _os_square(e, n):
    """name of the 10 km Ordnance Survey square (e.g. NT26) containing the British National Grid point e, n (metres)"""
    e1, n1 = int(e // 100000), int(n // 100000)
    l1 = (19 - n1) - (19 - n1) % 5 + (e1 + 10) // 5
    l2 = (19 - n1) * 5 % 25 + e1 % 5
    letter = lambda i: chr(i + 65 + (1 if i > 7 else 0))      # the grid has no letter I
    return '%s%s%d%d' % (letter(l1), letter(l2), int(e % 100000 // 10000), int(n % 100000 // 10000))


def _scotland(LA, LO, bbox, spacing, cancel, progress):
    """Scotland's public-sector lidar DTM (0.5 or 1 m, OGL): the newest survey of each 10 km square, found by a
    listing of the public bucket (only squares that exist are there); only the window is read"""
    X, Y = _project(LA, LO, 'EPSG:27700')
    squares = sorted({_os_square(x, y) for x in np.arange(X.min() // 1e4 * 1e4 + 5e3, X.max() + 1e4, 1e4)
                      for y in np.arange(Y.min() // 1e4 * 1e4 + 5e3, Y.max() + 1e4, 1e4)})
    progress(0.0, 'Finding tiles...')

    def find(sq):
        _check_cancel(cancel)
        for pre in SRSP_PREFIXES:
            xml = net.get(SRSP_BUCKET + '?list-type=2&prefix=' + pre + sq + '_', timeout=60, retries=RETRIES,
                          cancel=cancel)
            keys = sorted(re.findall(r'<Key>([^<]+\.tif)</Key>', xml.decode('utf-8', 'replace')))
            if keys:                                           # the 1 m file of the survey (the 50 cm one only if it is the only one)
                return SRSP_BUCKET + ([k for k in keys if '50CM' not in k.upper()] or keys)[0]
        return None

    with ThreadPoolExecutor(4) as ex:
        hrefs = [h for h in ex.map(find, squares) if h]
    if not hrefs:
        return None
    return _cog_mosaic(hrefs, LA, LO, 1.0, spacing, 'Scottish lidar', cancel, progress, missing_ok=True)


def _iceland(LA, LO, bbox, spacing, cancel, progress):
    return _cog_mosaic([IS_URL], LA, LO, 10.0, spacing, 'Icelandic', cancel, progress)


AT_URL = 'https://data.bev.gv.at/download/ALS/DTM/%s/ALS_DTM_CRS3035RES50000mN%dE%d.tif'     # edition, northing, easting
AT_EDITIONS = ('20250915', '20240915')
BY_URL = 'https://download1.bayernwolke.de/a/dgm/dgm1/%d_%d.tif'                              # km east, km north
NZ_URL = 'https://nz-elevation.s3-ap-southeast-2.amazonaws.com/new-zealand/new-zealand-contour/dem_8m/2193/%s.tiff'
IS_URL = 'https://ftp.natt.is/gisdata/raster/IslandsDEMv1.0_10x10m_isn2016_zmasl.tif'
_austria = _tiles('Austrian', 'EPSG:3035', 50000, lambda x, y: [AT_URL % (e, y, x) for e in AT_EDITIONS], 1.0)
_bavaria = _tiles('Bavarian', 'EPSG:25832', 1000, lambda x, y: [BY_URL % (x // 1000, y // 1000)], 1.0, max_tiles=150)
_poland = _service('Polish', 'https://mapy.geoportal.gov.pl/wss/service/PZGIK/NMT/GRID1/WCS/DigitalTerrainModelFormatTIFF'
                   + _WCS10 % ('DTM_PL-KRON86-NH_TIFF', 2180), 2180, 1.0)
_slovakia_raw = _service('Slovak', 'https://inspirews.skgeodesy.sk/geoserver/el/ows' + _WCS10 % ('el:EL.GridCoverage', 3046),
                         3046, 1.0)
SK_GEOID_M = 43.4         # the Slovak DMR 5.0 service gives heights above the ellipsoid; the geoid is ~43-44 m above it


def _slovakia(LA, LO, bbox, spacing, cancel, progress):
    """Slovak DMR 5.0 as heights above sea level: the ellipsoid-to-geoid offset (43.4 m, varying by about 1 m over the
    country) is taken off here, so a window that lies wholly in Slovakia is right too, not only one where a neighbour
    shows the offset (_blend removes what is left of it there)"""
    v = _slovakia_raw(LA, LO, bbox, spacing, cancel, progress)
    return None if v is None else v - SK_GEOID_M

_england = _service('English', 'https://environment.data.gov.uk/spatialdata/lidar-composite-digital-terrain-model-dtm-1m/wcs'
                    + _WCS10 % ('13787b9a-26a4-4775-8523-806d13af58fc:Lidar_Composite_Elevation_DTM_1m', 27700), 27700, 1.0,
                    chunk_px=800, timeout=90)     # small requests: the server answers 504 to big ones (observed 2-7 min per window)
_australia = _service('Australian', 'https://services.ga.gov.au/gis/services/DEM_LiDAR_5m_2025/MapServer/WCSServer'
                      + _WCS10 % ('1', 4283), None, 5.0)
_czechia = _service('Czech', 'https://ags.cuzk.gov.cz/arcgis2/rest/services/dmr5g/ImageServer/exportImage'
                    '?bbox={x0:.2f},{y0:.2f},{x1:.2f},{y1:.2f}&bboxSR=32633&imageSR=32633&size={nx},{ny}&format={fmt}'
                    '&pixelType=F32&noData=-9999&interpolation=RSP_BilinearInterpolation&f=image', 32633, 2.0,
                    formats=('tiff',))


# ---------------------------------------------------------------- the national sources: priority, coverage, resolution

NATIONAL = (('LiDAR HD France 0.5 m', FR_BOX, _france_lidar, ('FRA',)), ('RGE ALTI 5 m', FR_BOX, _france, ('FRA',)),
            ('South Tyrol 2.5 m', BZ_BOX, _south_tyrol, ('ITA',)),
            ('TINITALY 10 m', IT_BOX, _italy, ('ITA',)),
            ('swissALTI3D 2 m', CH_BOX, _swiss_3d, ('CHE', 'LIE')),
            ('swissALTIRegio 10 m', REGIO_BOX, _swiss, None),            # deliberately not clipped: reaches ~100 km out
            ('Kartverket 1 m', NO_BOX, _norway, ('NOR',)), ('NLS Finland 2 m', FI_BOX, _finland, ('FIN',)),
            ('MDT05 Spain 5 m', ES_BOX, _spain, ('ESP',)), ('HRDEM Canada 2 m', CA_BOX, _canada, ('CAN',)),
            ('Lantmateriet Sweden 1 m', SE_BOX, _sweden, ('SWE',)), ('USGS S1M 1 m', US_BOXES[:1], _usgs_s1m, ('USA', 'PRI', 'VIR')),
            ('USGS 3DEP 3 m', US_BOXES, _usgs, ('USA', 'PRI', 'VIR')),
            ('HRDEM Canada ArcticDEM 2 m', CA_NORTH_BOX, _canada_arctic, ('CAN',)),
            ('GSI Japan 1 m', JP_BOX, _gsi(('dem1a_png',), 17), ('JPN',)),
            ('GSI Japan 5 m', JP_BOX, _gsi(('dem5a_png', 'dem5b_png', 'dem5c_png'), 15), ('JPN',)),
            ('GSI Japan 10 m', JP_BOX, _gsi(('dem_png',), 14), ('JPN',)),
            ('BEV Austria 1 m', AT_BOX, _austria, ('AUT',)),
            ('Bavaria 1 m', BY_BOX, _bavaria, ('DEU',)),
            ('Poland 1 m', PL_BOX, _poland, ('POL',)), ('Slovakia 1 m', SK_BOX, _slovakia, ('SVK',)),
            ('Czechia 2 m', CZ_BOX, _czechia, ('CZE',)), ('England 1 m', EN_BOX, _england, ('GBR',)),
            ('Scotland 1 m', SC_BOX, _scotland, ('GBR',)),
            ('Iceland 10 m', IS_BOX, _iceland, ('ISL',)), ('New Zealand 1 m', NZ_BOX, _nz_lidar, ('NZL',)),
            ('New Zealand 8 m', NZ_BOX, _nz_tiles, ('NZL',)),
            ('Australia 5 m', AU_BOX, _australia, ('AUS',)))
# sources that cover only part of their country: what they leave open there is Terrain Tiles, not a hole in a survey
PART_OF_COUNTRY = {'Bavaria 1 m', 'England 1 m', 'Australia 5 m', 'Scotland 1 m',
                   'New Zealand 1 m', 'USGS S1M 1 m'}
# sources that cover their whole country (or all of the part of it that matters): where one of them is already as fine as
# the window's grid, the finer surveys listed before it are not downloaded (they would only be averaged down)
WHOLE_COUNTRY = {'RGE ALTI 5 m', 'TINITALY 10 m', 'USGS 3DEP 3 m', 'GSI Japan 5 m', 'GSI Japan 10 m', 'New Zealand 8 m'}
# native resolution of each source in metres: at a seam the finer one is kept as it is (see _blend)
SOURCE_RES = {'LiDAR HD France 0.5 m': FR_LIDAR_RES, 'RGE ALTI 5 m': FR_RGE_RES, 'South Tyrol 2.5 m': 2.5, 'TINITALY 10 m': IT_RES, 'swissALTI3D 2 m': SWISS3D_RES,
              'swissALTIRegio 10 m': SWISS_RES, 'Kartverket 1 m': NO_RES, 'NLS Finland 2 m': FI_RES, 'MDT05 Spain 5 m': ES_RES,
              'HRDEM Canada 2 m': CA_RES, 'Lantmateriet Sweden 1 m': LM_RES, 'USGS S1M 1 m': 1.0, 'USGS 3DEP 3 m': 3.0, 'HRDEM Canada ArcticDEM 2 m': 2.0,
              'GSI Japan 1 m': 1.0, 'GSI Japan 5 m': 5.0, 'GSI Japan 10 m': 10.0, 'BEV Austria 1 m': 1.0,
              'Bavaria 1 m': 1.0, 'Poland 1 m': 1.0, 'Slovakia 1 m': 1.0, 'Czechia 2 m': 2.0,
              'England 1 m': 1.0, 'Iceland 10 m': 10.0, 'New Zealand 8 m': 8.0, 'Australia 5 m': 5.0, 'Scotland 1 m': 1.0, 'New Zealand 1 m': 1.0}


# ---------------------------------------------------------------- naming and gap filling

# the datasets a map was made from are shown under their official names; internally the surveys keep their short names
# (the stitching tells them apart by resolution)
OFFICIAL = {'LiDAR HD France 0.5 m': 'IGN LIDAR HD',
            'RGE ALTI 5 m': 'IGN RGE ALTI',
            'South Tyrol 2.5 m': 'Bolzano DTM',
            'TINITALY 10 m': 'INGV TINITALY',
            'swissALTI3D 2 m': 'swissALTI3D',
            'swissALTIRegio 10 m': 'swissALTIRegio',
            'Kartverket 1 m': 'Kartverket',
            'NLS Finland 2 m': 'Korkeusmalli',
            'MDT05 Spain 5 m': 'IGN MDT05',
            'HRDEM Canada 2 m': 'NRCan HRDEM',
            'HRDEM Canada ArcticDEM 2 m': 'NRCan ArcticDEM',
            'Lantmateriet Sweden 1 m': 'Markh\u00f6jdmodell',
            'USGS S1M 1 m': 'USGS S1M',
            'USGS 3DEP 3 m': 'USGS 3DEP',
            'GSI Japan 1 m': 'GSI DEM1A',
            'GSI Japan 5 m': 'GSI DEM5',
            'GSI Japan 10 m': 'GSI DEM10B',
            'BEV Austria 1 m': 'BEV Austria ALS DTM',
            'Bavaria 1 m': 'Bavaria DGM1',
            'Poland 1 m': 'GUGiK Poland NMT',
            'Slovakia 1 m': 'UGKK SR DMR 5.0',
            'Czechia 2 m': 'CUZK DMR 5G',
            'England 1 m': 'England LIDAR DTM',
            'Scotland 1 m': 'Scottish LIDAR DTM',
            'Iceland 10 m': 'Natturufraedistofnun IslandsDEM',
            'New Zealand 1 m': 'LINZ NZ Lidar DEM',
            'New Zealand 8 m': 'LINZ NZ DEM',
            'Australia 5 m': 'Geoscience Australia DEM',
            # the two global sources: Terrain Tiles (30 m, 10 m where they hold Austria's DGM) and the USGS 3DEP service
            # used on its own (its own pixel is 10 m)
            'AWS Terrain Tiles 30 m': 'AWS Terrain Tiles', 'AWS Terrain Tiles 10 m': 'AWS Terrain Tiles',
            'USGS 3DEP 10 m': 'USGS 3DEP'}
SOURCE_RES.update({'AWS Terrain Tiles 30 m': TERRAIN_RES_M, 'AWS Terrain Tiles 10 m': TERRAIN_FINE_RES_M, 'USGS 3DEP 10 m': 10.0})
# the name shown while a dataset downloads (what the download helpers were called with)
_DOWNLOAD = {'Australian': 'Australia 5 m', 'Austrian': 'BEV Austria 1 m',
             'Bavarian': 'Bavaria 1 m', 'Canadian': 'HRDEM Canada 2 m',
             'northern Canadian': 'HRDEM Canada ArcticDEM 2 m', 'Czech': 'Czechia 2 m',
             'English': 'England 1 m', 'Finnish': 'NLS Finland 2 m', 'Icelandic': 'Iceland 10 m',
             'Italian': 'TINITALY 10 m', 'South Tyrol': 'South Tyrol 2.5 m',
             'Japanese elevation': 'GSI DEM', 'New Zealand': 'New Zealand 8 m',
             'New Zealand lidar': 'New Zealand 1 m', 'Norwegian': 'Kartverket 1 m',
             'Polish': 'Poland 1 m', 'Scottish lidar': 'Scotland 1 m', 'Slovak': 'Slovakia 1 m',
             'Spanish': 'MDT05 Spain 5 m', 'Swedish': 'Lantmateriet Sweden 1 m',
             'swisstopo': 'swissALTI3D 2 m', 'swissALTIRegio': 'swissALTIRegio 10 m',
             'USGS seamless 1 m': 'USGS S1M 1 m', 'elevation tiles': 'AWS Terrain Tiles 30 m'}
_SHOWN = set(OFFICIAL.values())


def _aws_names(fine):
    """the Terrain Tiles entries of a window: 30 m where they are the base, 10 m where they hold Austria's DGM (fine: mask)"""
    return (['AWS Terrain Tiles 30 m'] if not fine.all() else []) + (['AWS Terrain Tiles 10 m'] if fine.any() else [])


def _default_names(src, spacing):
    """the datasets of a window made from one global source alone (no list was kept), with their sampled resolutions"""
    one = {'3dep2': 'USGS 3DEP 10 m', '3dep': 'USGS 3DEP 10 m', 'terrarium': 'AWS Terrain Tiles 30 m'}.get(src)
    return _listed([one], spacing) if one else []
_WINDOW = {'spacing': None}   # grid spacing of the window being fetched (the resolutions shown are worked out from it)


def _res_text(name, spacing):
    """the resolution a survey is really downloaded at in a window: the window's grid spacing, but never finer than the
    survey's own pixel (dl_res, the rule the downloads use)"""
    return ('%.1f' % dl_res(spacing, float(SOURCE_RES[name]))).rstrip('0').rstrip('.') + ' m'


def _shown(name, spacing=None):
    """the name shown for a dataset: its official name and the resolution it was downloaded at in this window"""
    official = OFFICIAL.get(name)
    spacing = spacing or _WINDOW['spacing']
    if official is None or not spacing:
        return official or name
    return '%s %s' % (official, _res_text(name, spacing))


def _dl(what):
    return _shown(_DOWNLOAD.get(what, what))


def _listed(names, spacing=None):
    """dataset names -> the names shown and saved with the map, each once, in the order they were used"""
    return list(dict.fromkeys(_shown(n, spacing) for n in names))


def _fill_open(a, k=8):
    """a with its NaN gaps interpolated from the data around them: block means (k x k) -> the empty blocks are filled by
    spreading the neighbours inwards and relaxing them smooth -> bilinear back to full resolution"""
    open_ = ~np.isfinite(a)
    if not open_.any() or open_.all():
        return a
    c = _block_mean(a, k)
    m0 = np.isfinite(c)
    v, m = np.where(m0, c, 0.0), m0.copy()
    nb = lambda x: (np.pad(x, 1)[:-2, 1:-1] + np.pad(x, 1)[2:, 1:-1] + np.pad(x, 1)[1:-1, :-2] + np.pad(x, 1)[1:-1, 2:])
    while not m.all():
        n = nb(m.astype(np.float64))
        new = ~m & (n > 0)
        if not new.any():
            break
        v[new] = nb(np.where(m, v, 0.0))[new] / n[new]
        m |= new
    free = ~m0
    for _ in range(60):                                     # relax the filled blocks towards a smooth surface
        pad = np.pad(v, 1, mode='edge')
        avg = (pad[:-2, 1:-1] + pad[2:, 1:-1] + pad[1:-1, :-2] + pad[1:-1, 2:]) / 4
        v[free] = avg[free]
    return np.where(open_, _upsample_linear(v, k, a.shape), a)


# ---- stitching

def _seam_fade(d, ring, seam, L, along_m, spacing):
    """A correction field from seam differences `d` (given on the `ring` cells): every cell takes the difference of
    the nearest part of the seam, averaged along it over ~along_m (where that average has no support, further out,
    over doubling scales up to ~L/3: a normalised-convolution pyramid), times a smoothstep that falls from 1 at the
    seam line `seam` to 0 at distance L. A few blurs and a distance estimate: cheap at any size."""
    s = max(1.0, along_m / spacing)
    s_max = min(max(s, (L or 3 * max(d.shape) * spacing) / (3.0 * spacing)), max(d.shape))   # L None: no fade
    rf = ring.astype(np.float64)
    dv = np.where(ring, d, 0.0)
    ext, have = np.zeros(d.shape), np.zeros(d.shape)
    while True:
        w = _blur(rf, s)
        e = _blur(dv, s) / np.maximum(w, 1e-12)
        a = np.clip(w / 0.05, 0.0, 1.0) * (1 - have)        # finer scales win where they have support
        ext += a * e
        have += a
        if s >= s_max or have.min() > 0.999:
            break
        s = min(2 * s, s_max)
    ext += (1 - have) * e
    if not L:
        return ext
    t = np.clip(1.0 - _dist_approx(seam, L / spacing) * spacing / L, 0.0, 1.0)
    return ext * (t * t * (3 - 2 * t))


def _norm_blur(v, m, sigma):
    """Gaussian average of v over the cells in mask m (normalised convolution); also defined just outside m"""
    mf = m.astype(np.float64)
    return _blur(np.where(m, v, 0.0), sigma) / np.maximum(_blur(mf, sigma), 1e-9)


def _opened(m, width_m, spacing):
    """m without the parts narrower than ~width_m (morphological opening with Gaussian blurs: cheap, any size)"""
    sd = max(1.0, width_m / (2.0 * spacing))
    core = _blur(m.astype(np.float64), sd) > 0.85
    return m & (_blur(core.astype(np.float64), sd) > 0.1)    # 0.1: reaches a little past the original edge


def _blend(base, layers, spacing, res=None, base_res=None, holes=None):
    """Stitch national layers (NaN = no data, at most one layer per point) and the Terrain Tiles base (complete).

    Delta surface fill (Grohman, Kroenung & Strebeck 2006, the method used to fill SRTM's voids), meeting in the
    middle: the regions are placed from the coarsest resolution to the finest (ties: listed order); where a region
    meets the already placed data, the height difference along their common seam (both sides averaged over a pixel
    of the coarser source) is split in two: each side is bent by half of it, carried in from the nearest part of the
    seam and faded to zero with a smoothstep over BLEND_M_PER_M metres per metre of difference (see _seam_fade). A
    short second pass shares what is left right at the seam the same way.

    The corrections are smooth fields, so all of this is worked out on a grid of ~BLEND_CELL_M cells (block means of
    the sources): one correction field per region, which is then interpolated back and added to that region's
    full-resolution data. Only the last step runs at full resolution: at every seam the surface is lightly smoothed
    over a few cells, and where the resolutions differ by DETAIL_RATIO or more the finer side's detail fades out
    towards the seam (a Gaussian blur whose width grows smoothly over a band of DETAIL_FADE_PX coarse pixels).

    Slivers of a source along a border (narrower than SLIVER_M) are dropped. Terrain Tiles are a side of a seam only
    beyond the surveys' countries; inside a surveyed country (`holes`: lakes and other no-data of a survey) and
    wherever they are narrower than GAP_M (strips between two surveys) they are a gap instead: filled last, bent to
    the surveys on all sides, which joins them.
      res: {layer name: native resolution in m}; base_res: resolution of the base per cell (array) or a number;
      holes: cells inside a surveyed country where its survey has no data (bool array) or None
      base None: a single survey covers the whole window, so there is nothing to stitch and no Terrain Tiles are needed"""
    LAST_SEAMS[:] = []
    if base is None:
        return np.array(layers[0][1], np.float64)
    if not layers:
        return base
    res = res or {}
    shape = base.shape
    k = max(2, int(round(BLEND_CELL_M / spacing)))          # block size of the working grid
    sc = spacing * k

    def down(a):
        return _block_mean(a, k)

    def up(a):
        return _upsample_linear(a, k, shape)

    def up_mask(m):
        return np.repeat(np.repeat(m, k, 0), k, 1)[:shape[0], :shape[1]]

    base_c = down(base)
    cshape = base_c.shape
    regions = []                                            # (sort key, name, coarse mask, coarse values, resolution)
    full = {}                                               # name -> (full-resolution mask, values)
    covered_c = np.zeros(cshape, bool)
    for i, (name, v) in enumerate(layers):
        m = np.isfinite(v)
        if not m.any():
            continue
        mc = down(m.astype(np.float64)) >= 0.5
        mo = _opened(mc, SLIVER_M, sc)
        drop = mc & ~mo
        if drop.any():                                      # slivers (and the partly covered cells around them)
            drop = gaussian(drop.astype(np.float64), 1.0) > 0.05
            m = m & ~up_mask(drop)
            log.debug('blend %s: %.2f %% of the window are slivers, filled from around', name, 100 * drop.mean())
        vc = down(np.where(m, v, np.nan))
        mc = mo & np.isfinite(vc)
        if not mc.any():                                    # nothing but slivers: dropped altogether
            continue
        covered_c |= mc
        r = max(float(res.get(name, 5.0)), spacing)
        regions.append(((-r, i), name, mc, np.where(mc, vc, 0.0), r))
        full[name] = (m, v)
    covered = np.zeros(shape, bool)
    for m, _ in full.values():
        covered |= m
    m0 = ~covered_c
    gap = np.zeros(cshape, bool)
    r0 = TERRAIN_RES_M
    if m0.any():
        if base_res is not None:
            r0 = float(np.median(down(base_res)[m0])) if isinstance(base_res, np.ndarray) else float(base_res)
        r0 = max(r0, spacing)
        gap = m0 & ~_opened(m0, GAP_M, sc)
        if holes is not None:
            gap |= m0 & (down(holes.astype(np.float64)) >= 0.5)
        regions.append(((-r0, -1), 'Terrain Tiles', m0 & ~gap, base_c, r0))
    regions.sort(key=lambda t: t[0])                         # coarsest first
    if gap.any():
        regions.append(((0, 0), 'gap', gap, base_c, r0))
    out = np.full(cshape, np.nan)                            # the composite on the working grid
    fixed = np.zeros(cshape, bool)
    fixed_res = np.zeros(cshape)
    field = {}                                              # name -> correction field of that region (working grid)
    datum = {}                                              # name -> constant height offset removed from that region
    soften = []                                             # (blur sigma at the seam in full-resolution cells, ramp 0..1)
    for _, name, m, v, r in regions:
        if not m.any():
            continue
        field[name] = np.zeros(cshape)
        ring0 = fixed & (gaussian(m.astype(np.float64), 2.0) > 0.05) if fixed.any() else fixed
        if ring0.sum() < 4:
            out[m], fixed_res[m] = v[m], r
            fixed |= m
            continue
        rc = max(r, float(np.median(fixed_res[ring0])))     # the coarser of the two sides
        sig = max(1.5, rc / sc) if name != 'gap' else 1.5   # a gap follows what is right around it
        ring = fixed & (gaussian(m.astype(np.float64), sig) > 0.05)
        # difference across the seam, both sides relative to the base (so slopes do not bias the one-sided averages)
        # and averaged over a pixel of the coarser side; continued over the seam by the normalised averages
        ref = _norm_blur(out - base_c, fixed, sig)
        own = _norm_blur(v - base_c, m, sig) if name not in ('Terrain Tiles', 'gap') else 0.0
        d = (ref - own)[ring]
        if name not in ('Terrain Tiles', 'gap') and d.size:
            # a source on another height datum (e.g. heights above the ellipsoid, ~44 m off in central Europe) differs
            # from its surroundings by a near-constant amount; that is removed whole instead of being bent over the seam
            med0 = float(np.median(d))
            mad0 = 1.4826 * float(np.median(np.abs(d - med0)))
            if abs(med0) > DATUM_OFFSET_M and mad0 < 0.25 * abs(med0):
                log.warning('%s: constant height offset of %.1f m against its surroundings (another height datum?) removed',
                            name, -med0)
                v = v + med0
                datum[name] = med0
                own = _norm_blur(v - base_c, m, sig)
                d = (ref - own)[ring]
        seam, seam_f = _seam_lines(m, fixed)                # this region's / the placed cells along the seam
        dfull = np.zeros(cshape)
        if name == 'gap':                                   # a hole or strip: filled from what is right around it,
            dfull[ring] = d                                 # with no fade (every gap cell is between surveys)
            field[name] = _seam_fade(dfull, ring, seam, None, 2 * sc, sc)
            out[m] = v[m] + field[name][m]
            fixed_res[m] = r
            fixed |= m
            continue
        # only the regional part is spread far: outliers (cliffs, where a few metres of horizontal offset between two
        # surveys mean tens of metres in height) are clipped and the rest is averaged along the seam
        med = float(np.median(d))
        mad = 1.4826 * float(np.median(np.abs(d - med))) + 0.5
        dfull[ring] = np.clip(d, med - 3 * mad, med + 3 * mad)
        d = np.where(ring, _norm_blur(dfull, ring, SEAM_SMOOTH_M / sc), 0.0)
        p90 = float(np.percentile(np.abs(d[ring]), 90))
        L = min(max(BLEND_M_PER_M * p90, BLEND_MIN_M, 4 * rc), BLEND_MAX_M)
        LAST_SEAMS.append(dict(a=name, b='the coarser data around it', step_m=round(-med, 2), p90_m=round(p90, 2),
                               fade_m=round(L), cells=int(ring.sum())))
        (log.warning if abs(med) > SEAM_WARN_M else log.info)(
            'seam of %s (%.0f m) with %.0f m data: differs by %.1f m (p90 %.1f m), each side bent by half over %.0f m',
            name, r, rc, -med, p90, L)
        # the two sides meet in the middle: each takes half of the difference, faded out over L on its own side
        mine = 0.5 * _seam_fade(d, ring, seam, L, SEAM_SMOOTH_M, sc)
        theirs = 0.5 * _seam_fade(d, ring, seam_f, L, SEAM_SMOOTH_M, sc) if seam_f.any() else np.zeros(cshape)
        out[m] = v[m] + mine[m]
        out[fixed] -= theirs[fixed]
        # short pass: what is left right at the seam, averaged along it over a coarse pixel, is shared the same way
        # and faded out within a few coarse pixels on both sides
        edge = fixed & (gaussian(m.astype(np.float64), 1.0) > 0.01)
        if edge.any() and seam.any():
            q = out - base_c                                # relative to the base again: slopes cancel
            e = _norm_blur(q, fixed, 1.0) - _norm_blur(q, m, 1.0)
            Ls = max(3.0 * rc, 3.0 * sc)
            mine2 = 0.5 * _seam_fade(e, edge, seam, Ls, rc, sc)
            out[m] += mine2[m]
            mine = mine + mine2
            if seam_f.any():
                t2 = 0.5 * _seam_fade(e, edge, seam_f, Ls, rc, sc)
                out[fixed] -= t2[fixed]
                theirs = theirs + t2
        for other in field:                                 # every placed region carries its share
            if other != name:
                field[other] -= theirs
        field[name] = mine
        # detail: fade the finer side's detail out towards the seam where the resolutions differ a lot
        coarse_nb = fixed & (fixed_res >= DETAIL_RATIO * r)
        if coarse_nb.sum() >= 4:
            line = _seam_lines(m, coarse_nb)[0]
            W = min(max(DETAIL_FADE_PX * rc, DETAIL_FADE_MIN_M), DETAIL_FADE_MAX_M)
            t = np.clip(1.0 - _dist_approx(line, W / sc) * sc / W, 0.0, 1.0)
            soften.append((DETAIL_SIGMA * rc / spacing, t * t * (3.0 - 2.0 * t)))    # smoothstep: no kink at either end
        fixed_res[m] = r
        fixed |= m
    # back to full resolution: every region's own data plus its correction field
    res_full = base + up(field.get('Terrain Tiles', np.zeros(cshape)))
    if 'gap' in field:
        g = up_mask(gaussian(gap.astype(np.float64), 1.0) > 0.3) & ~covered
        res_full[g] = (base + up(field['gap']))[g]
    owner = np.zeros(shape, np.int8)
    for i, (name, (m, v)) in enumerate(full.items(), 1):
        res_full[m] = v[m] + datum.get(name, 0.0) + up(field[name])[m]
        owner[m] = i
    # every seam: a light smoothing over a few cells closes what the working grid could not resolve
    edge = np.zeros(shape, bool)
    edge[:, 1:] |= owner[:, 1:] != owner[:, :-1]
    edge[1:, :] |= owner[1:, :] != owner[:-1, :]
    if edge.any():
        t = np.clip(gaussian(edge.astype(np.float64), SEAM_CLOSE_CELLS) * 2.5 * SEAM_CLOSE_CELLS, 0.0, 1.0)
        res_full = res_full + t * (gaussian(res_full, 0.75 * SEAM_CLOSE_CELLS) - res_full)
    if soften:                                               # high to low detail: blurred more the nearer the coarse data
        sig = np.zeros(shape)
        for sd, t in soften:
            sig = np.maximum(sig, sd * up(t))
        res_full = _variable_blur(res_full, sig)
    return res_full


def _variable_blur(z, sig, min_sig=0.4):
    """z blurred by a Gaussian whose sigma (in cells) is sig, cell by cell: the blurred images at a ladder of sigmas
    (x1.5 apart), each cell interpolated between its two nearest. Only the box where sig matters is worked on."""
    top = float(sig.max())
    if top < min_sig:
        return z
    rows, cols = np.nonzero((sig >= min_sig).any(axis=1))[0], np.nonzero((sig >= min_sig).any(axis=0))[0]
    pad = int(3 * top) + 2
    r0, r1 = max(rows[0] - pad, 0), min(rows[-1] + pad + 1, z.shape[0])
    c0, c1 = max(cols[0] - pad, 0), min(cols[-1] + pad + 1, z.shape[1])
    zc, sg = z[r0:r1, c0:c1], sig[r0:r1, c0:c1]
    levels = [0.0]
    v = max(min_sig, 0.6)
    while v < top:
        levels.append(v)
        v *= 1.5
    levels.append(top)
    imgs = [zc] + [gaussian(zc, lv) for lv in levels[1:]]
    lv = np.array(levels)
    idx = np.clip(np.searchsorted(lv, sg, side='right') - 1, 0, len(lv) - 2)
    frac = np.clip((sg - lv[idx]) / (lv[idx + 1] - lv[idx]), 0.0, 1.0)
    out = np.array(zc, np.float64)
    for j in range(len(lv) - 1):
        m = idx == j
        if m.any():
            out[m] = (1 - frac[m]) * imgs[j][m] + frac[m] * imgs[j + 1][m]
    res = np.array(z, np.float64)
    res[r0:r1, c0:c1] = out
    return res


def _seam_lines(m, fixed):
    """-> (cells of m next to a fixed cell, fixed cells next to a cell of m), 4-neighbourhood"""
    a, b = np.zeros(m.shape, bool), np.zeros(m.shape, bool)
    a[:, 1:] |= m[:, 1:] & fixed[:, :-1]
    a[:, :-1] |= m[:, :-1] & fixed[:, 1:]
    a[1:, :] |= m[1:, :] & fixed[:-1, :]
    a[:-1, :] |= m[:-1, :] & fixed[1:, :]
    b[:, 1:] |= fixed[:, 1:] & m[:, :-1]
    b[:, :-1] |= fixed[:, :-1] & m[:, 1:]
    b[1:, :] |= fixed[1:, :] & m[:-1, :]
    b[:-1, :] |= fixed[:-1, :] & m[1:, :]
    return a, b


def _dist_approx(mask, reach):
    """approximate distance (in cells) to the nearest True cell, accurate up to ~reach (from a Gaussian blur)"""
    sd = max(1.0, reach / 2.5)
    g = np.clip(_blur(mask.astype(np.float64), sd), 1e-12, None)
    # a line of True cells blurred: g = g0 * exp(-d^2 / 2 sd^2), g0 ~ 1 / (sqrt(2 pi) sd)
    g0 = 1.0 / (math.sqrt(2 * math.pi) * sd)
    return np.where(mask, 0.0, sd * np.sqrt(np.maximum(2 * np.log(g0 / g), 0.0)))


def stripes(v, spacing):
    """Periodic pattern in a source grid, the mark of a server resampling by nearest neighbour (pixels repeated at a
    fixed interval). The second derivative along each axis is Fourier-transformed per complete row/column and
    averaged; nearest-neighbour stairs make a raised band of frequencies, compared here with the band just below it
    (natural terrain's spectrum falls or stays flat towards shorter periods). Periods from 2.2 cells to 30 m.
    -> (strength, period in m, axis 'x' or 'y') of the stronger axis, or None"""
    best = None
    for ax in (1, 0):
        a = v if ax == 1 else v.T
        rows = a[np.isfinite(a).all(axis=1)]                # complete rows only (no-data edges are not a pattern)
        if len(rows) < 32:
            continue
        rows = rows[:: max(1, len(rows) // 256)]
        dd = np.diff(rows, 2, axis=1)
        sp = np.abs(np.fft.rfft(dd - dd.mean(axis=1, keepdims=True), axis=1)).mean(axis=0)
        f = np.fft.rfftfreq(dd.shape[1])
        cs = np.concatenate([[0.0], np.cumsum(sp)])

        def band(a0, b0):
            i0, i1 = np.searchsorted(f, a0), np.searchsorted(f, b0)
            return (cs[i1] - cs[i0]) / max(i1 - i0, 1)
        cands = f[(f > spacing / 30.0) & (f < 1 / 2.2)][::4]
        if len(cands) < 5:
            continue
        rr = np.array([band(0.97 * c, 1.03 * c) / max(band(0.6 * c, 0.85 * c), 1e-12) for c in cands])
        k = int(np.argmax(rr))
        if best is None or rr[k] > best[0]:
            best = (float(rr[k]), spacing / cands[k], 'x' if ax == 1 else 'y')
    return best


def _smooth_source(name, v, spacing):
    """the per-source smoothing: ARTIFACT_SMOOTH x its download pixel, or half the period of a detected pattern"""
    r = grid_res(spacing, float(SOURCE_RES.get(name, 5.0)))
    sd = ARTIFACT_SMOOTH * r / spacing
    st = stripes(v, spacing)
    why = '%.1f m pixels' % r
    if st and st[0] > STRIPE_LIMIT:
        sd = max(sd, 0.5 * st[1] / spacing)
        why = 'a periodic pattern every %.1f m along %s (%.1f x)' % (st[1], st[2], st[0])
    if sd < 0.5:
        return v
    f = np.isfinite(v)
    out = _norm_blur(v, f, sd)
    log.info('%s smoothed over %.1f m (%s)', name, sd * spacing, why)
    return np.where(f, out, np.nan)


def _bad_values(v, tt, spacing):
    """values that cannot be terrain: further than MAX_DEV_M outside the min..max of the raw Terrain Tiles within
    ~DEV_RADIUS_M, or 0 where Terrain Tiles are well above sea level (unflagged no-data)"""
    k = max(2, int(DEV_RADIUS_M / 2 / spacing))
    h, w = tt.shape
    H, W = -(-h // k), -(-w // k)
    p = np.pad(tt, ((0, H * k - h), (0, W * k - w)), mode='edge').reshape(H, k, W, k)
    lo, hi = p.min(axis=(1, 3)), p.max(axis=(1, 3))
    lp, hp = np.pad(lo, 1, mode='edge'), np.pad(hi, 1, mode='edge')
    lo = np.min([lp[i:i + H, j:j + W] for i in range(3) for j in range(3)], axis=0)
    hi = np.max([hp[i:i + H, j:j + W] for i in range(3) for j in range(3)], axis=0)
    lo = np.repeat(np.repeat(lo, k, 0), k, 1)[:h, :w]
    hi = np.repeat(np.repeat(hi, k, 1), k, 0)[:h, :w]
    with np.errstate(invalid='ignore'):
        return (v < lo - MAX_DEV_M) | (v > hi + MAX_DEV_M) | ((v == 0) & (tt > 50))


def _suspect_zeros(v, spacing):
    """True when exact 0 values look like unflagged no-data: zeros with well elevated land around them. Zeros on a coast, a
    sea or a lowland are normal for a survey, and are no reason to download Terrain Tiles to check them."""
    ok = np.isfinite(v)
    z = ok & (v == 0)
    if not z.any():
        return False
    nz = ok & ~z
    if not nz.any():
        return False
    sig = max(2.0, 150.0 / spacing)
    num = gaussian(np.where(nz, v, 0.0), sig)
    den = gaussian(nz.astype(np.float64), sig)
    with np.errstate(invalid='ignore', divide='ignore'):
        ring = np.where(den > 0.05, num / den, 0.0)
    return bool((z & (ring > 50.0)).any())


def _fetch_national(lat, lon, size_m, cancel, progress, rot=0.0):
    n = G
    LA, LO = grid_latlon(lat, lon, size_m, n, rot)
    spacing = size_m / (n - 1)
    _WINDOW['spacing'] = spacing
    bbox = (float(LO.min()), float(LA.min()), float(LO.max()), float(LA.max()))

    todo = [(nm, fn, cc) for nm, box, fn, cc in NATIONAL if _hits(box, bbox)]
    inside = {}                                             # countries -> mask of the window inside them
    for _, _, cc in todo:
        if cc and cc not in inside:
            inside[cc] = country_mask(lat, lon, size_m, cc, n, rot)
    # sources that need a key: ask for it (credentials.Needed) before anything is downloaded, unless the player chose to
    # do without; a window that only touches the country at its edge does not need it
    for nm, fn, cc in list(todo):
        pid = SOURCE_PROVIDER.get(nm)
        if not pid:
            continue
        m = inside.get(cc)
        if m is not None and m.sum() < MIN_NEED_CELLS:
            continue
        if credentials.is_skipped(pid):
            log.info('%s left out: no key (the player chose to do without)', nm)
            todo.remove((nm, fn, cc))
        else:
            credentials.require(pid)

    # Terrain Tiles are downloaded only when needed (get_tt): where the national surveys leave part of the window open, to
    # stitch two surveys together, or to check a survey's suspicious values. Up to zoom 15 (~3-4 m) where they hold
    # Austria's 10 m DGM, so the base stays sharp there; zoom 13 elsewhere, where they are ~30 m and get smoothed
    hi = _intersects(AT_BOX, bbox)
    tt_box = {}
    tt_lock = threading.Lock()

    def get_tt():
        with tt_lock:
            if 'v' not in tt_box:
                z = terrarium_zoom(lat, spacing, 15 if hi else 13)
                tt_box['v'] = _terrarium_sample(LA, LO, z, cancel, lambda f, t: progress(0.02 + 0.28 * f, t))
            return tt_box['v']

    austria = np.zeros(LA.shape, bool)
    if _intersects(AT_BOX, bbox):
        austria = country_mask(lat, lon, size_m, ('AUT',), n, rot)
        if austria is None:                                 # no border file: the box
            austria = (LO >= AT_BOX[0]) & (LO <= AT_BOX[2]) & (LA >= AT_BOX[1]) & (LA <= AT_BOX[3])
    fine_aws = austria

    def make_base():
        tt = get_tt()
        coarse = gaussian(tt, _terrarium_sigma(size_m))
        if fine_aws.any():
            sharp = np.clip(_blur(fine_aws.astype(np.float64), max(2.0, 300.0 / spacing)), 0.0, 1.0)
            b = sharp * gaussian(tt, 0.75) + (1 - sharp) * coarse
        else:
            b = coarse
        # the Terrain Tiles seabed becomes sea level; survey data blended over it keep their own heights, so land below
        # sea level that a survey covers (Death Valley, Dutch polders in a survey) stays below 0
        return np.maximum(b, 0.0)

    done = [0]

    def fetch(name, fn, need):
        """one source, asked only for the box of the cells it is needed for -> full-size grid (NaN elsewhere) or None"""
        rows, cols = np.nonzero(need.any(axis=1))[0], np.nonzero(need.any(axis=0))[0]
        r0, r1 = max(rows[0] - FETCH_MARGIN, 0), min(rows[-1] + FETCH_MARGIN + 1, n)
        c0, c1 = max(cols[0] - FETCH_MARGIN, 0), min(cols[-1] + FETCH_MARGIN + 1, n)
        la, lo = LA[r0:r1, c0:c1], LO[r0:r1, c0:c1]
        sub = (float(lo.min()), float(la.min()), float(lo.max()), float(la.max()))
        n0 = done[0]
        try:
            extra = dict(need=need[r0:r1, c0:c1]) if getattr(fn, 'wants_need', False) else {}
            v = fn(la, lo, sub, spacing, cancel,
                   lambda f, t: progress(0.30 + 0.58 * min(n0 + f, len(todo)) / len(todo), t), **extra)
        except (DemError, net.NetError, ValueError, KeyError, OSError) as e:
            if _cancelled(cancel):
                raise
            log.warning('%s skipped: %s', name, _redact(e))
            return None
        finally:
            done[0] += 1
        if v is None:
            return None
        with np.errstate(invalid='ignore'):                 # Terrain Tiles are only fetched to check values that look wrong
            odd = ((v < -500) | (v > 9000)).any() or _suspect_zeros(v, spacing)
        bad = _bad_values(v, get_tt()[r0:r1, c0:c1], spacing) if odd else np.zeros(v.shape, bool)
        if bad.any():
            log.info('%s: %.2f %% of its values are implausible and dropped', name, 100 * bad.mean())
            v[bad] = np.nan
        v = _smooth_source(name, v, spacing)                # pixels, terraces, resampling patterns -> smooth slopes
        out = np.full(LA.shape, np.nan)
        out[r0:r1, c0:c1] = v
        if DEBUG_HOOK:
            DEBUG_HOOK('source__' + name, out)
        return out

    def chain(cc):
        """the sources of one country (or group), in listed order; a later one is only asked for what is left"""
        left = inside[cc].copy() if inside.get(cc) is not None else np.ones(LA.shape, bool)
        got = []
        mine = [nm for nm, _, c in todo if c == cc]
        for name, fn, c in todo:
            if c != cc:
                continue
            res = SOURCE_RES.get(name, 5.0)
            later = mine[mine.index(name) + 1:]
            if any(t in WHOLE_COUNTRY and res < SOURCE_RES.get(t, 5.0) <= spacing for t in later):
                log.info('%s skipped: finer than the window needs (grid %.1f m)', name, spacing)
                continue
            if left.sum() < MIN_NEED_CELLS:
                log.info('%s skipped: %s', name, 'already covered' if got else 'the window is outside its country')
                continue
            if got and left.mean() <= MAX_GAP:              # a finer survey has it nearly all: the rest is interpolated
                log.info('%s skipped: only %.1f %% of the window is left open', name, 100 * left.mean())
                continue
            v = fetch(name, fn, left)
            if v is not None:
                v[~left] = np.nan                           # outside its country, or covered by an earlier source
                left &= ~np.isfinite(v)
                got.append((name, v))
        return got

    # the countries' own sources: different countries never overlap, so their chains are fetched side by side
    clipped = [cc for cc in dict.fromkeys(c for _, _, c in todo) if cc]
    by_name = {}
    with ThreadPoolExecutor(max(1, min(FETCH_PARALLEL, len(clipped)))) as ex:
        for got in ex.map(chain, clipped):
            by_name.update(got)
    taken = np.zeros(LA.shape, bool)
    for v in by_name.values():
        taken |= np.isfinite(v)
    # sources that are not tied to a country (swissALTIRegio) fill what the countries' own sources left open
    for name, fn, cc in todo:
        if cc:
            continue
        need = ~taken
        if need.sum() < MIN_NEED_CELLS:
            log.info('%s skipped: already covered', name)
            continue
        if name == 'swissALTIRegio 10 m' and need.mean() <= MAX_GAP:
            log.info('%s skipped: only %.1f %% of the window is left open', name, 100 * need.mean())
            continue
        v = fetch(name, fn, need)
        if v is not None:
            v[taken] = np.nan
            taken |= np.isfinite(v)
            by_name[name] = v
    layers = []
    holes = np.zeros(LA.shape, bool)                        # in a surveyed country, but no data from its survey
    for name, _, cc in todo:                                # listed order
        v = by_name.get(name)
        if v is None:
            continue
        frac = np.isfinite(v).mean()
        log.info('%s covers %.1f%% of the window', name, 100 * frac)
        if frac > 0:
            layers.append((name, v))
            if inside.get(cc) is not None and name not in PART_OF_COUNTRY:   # its own no-data (lakes...): to be filled, not a seam
                holes |= inside[cc]
    holes &= ~taken
    if not layers and not fine_aws.any():
        raise DemError('No national elevation data for this window')
    if len(layers) == 1 and np.isfinite(layers[0][1]).all():
        # one survey over the whole window: no Terrain Tiles are downloaded
        log.info('%s covers the whole window: no Terrain Tiles needed', layers[0][0])
        _used.names = [layers[0][0]]
        return _blend(None, layers, spacing)
    if layers and not fine_aws.any():
        have = np.logical_or.reduce([np.isfinite(v) for _, v in layers])
        gap = 1.0 - float(have.mean())
        if gap <= MAX_GAP:
            # the surveys cover the window, up to small gaps (a strip between two surveys, a lake): they are stitched with
            # each other and the gaps are interpolated, nothing is downloaded
            log.info('%s cover %.1f %% of the window: %s, no Terrain Tiles needed', ' + '.join(nm for nm, _ in layers),
                     100 * (1 - gap), 'the gaps are interpolated' if gap > 0 else 'the whole window')
            _used.names = [name for name, _ in layers]
            comb = np.full(LA.shape, np.nan)
            for _, v in layers:
                comb = np.where(np.isfinite(comb), comb, v)
            return _blend(_fill_open(comb), layers, spacing, SOURCE_RES, None, None)
    progress(0.9, 'Stitching elevation across borders...')
    _used.names = [name for name, _ in layers] + _aws_names(fine_aws)
    base = make_base()
    if not layers:
        LAST_SEAMS[:] = []
        return base                                          # no-data in every layer: from Terrain Tiles
    base_res = np.where(fine_aws, TERRAIN_FINE_RES_M, TERRAIN_RES_M)
    return _blend(base, layers, spacing, SOURCE_RES, base_res, holes)


# '3dep2', '3dep' and 'terrarium' are the Map Creator's first terrain kinds, unchanged (see _legacy_3dep); 'national' is the
# multi-source terrain (national surveys, USGS 3DEP, Terrain Tiles) that new maps use
FETCH = {'3dep2': lambda lat, lon, size_m, cancel, progress, rot=0.0: _legacy_3dep(lat, lon, size_m, cancel, progress, True, rot),
         '3dep': lambda lat, lon, size_m, cancel, progress, rot=0.0: _legacy_3dep(lat, lon, size_m, cancel, progress, False, rot),
         'national': _fetch_national, 'terrarium': _legacy_terrarium}


# ---------------------------------------------------------------- entry point

def norm_rot(rot):
    """rotation of the area in degrees clockwise (the compass bearing of the top of the map), as -180 <= r < 180 rounded to
    0.1 degree; 0 = north up"""
    try:
        r = round(((float(rot or 0.0) + 180.0) % 360.0) - 180.0, 1)
    except (TypeError, ValueError):
        return 0.0
    return 0.0 if abs(r) < 0.05 else r


def cache_key(lat, lon, size_m, source, rot=0.0):
    s = '%d|%.6f|%.6f|%.1f|%s|%s' % (CACHE_VERSION, lat, lon, size_m, source, credentials.cache_tag())
    if norm_rot(rot):                                       # (north-up windows keep their cache entries)
        s += '|rot%.1f' % norm_rot(rot)
    return hashlib.sha1(s.encode()).hexdigest()[:20]


def _sources_file(f):
    return f.with_suffix('.json')


def load_sources(lat, lon, size_m, cancel=net.NEVER, progress=lambda f, t: None, prefer=None, rot=0.0):
    """-> (dem metres float32 (G, G), source id, names of the datasets used). Cached per window (the names too).
    rot: the area is turned clockwise by this many degrees about its centre (row 0 is its top edge, not north)."""
    log.debug('load_sources() called: lat=%.5f, lon=%.5f, size_m=%.0f, prefer=%s, rot=%.1f', lat, lon, size_m, prefer, rot)
    rot = norm_rot(rot)
    if prefer:
        order = [prefer]
        log.debug('Using preferred source: %s', prefer)
    else:
        order = (['national'] if in_national(lat, lon, size_m) else []) + (['3dep2'] if in_us(lat, lon) else []) + ['terrarium']
        log.debug('Auto-selected source order: %s', order)
    errors = []
    for src in order:
        log.debug('Trying elevation source: %s', src)
        f = paths.DEMS / ('%s.npy' % cache_key(lat, lon, size_m, src, rot))
        if f.is_file():
            log.debug('Cache file found: %s', f)
            try:
                dem = np.load(f)
                if dem.shape == (G, G):
                    f.touch()
                    try:
                        names = json.loads(_sources_file(f).read_text(encoding='utf-8'))
                    except (OSError, ValueError):
                        names = []
                    names = names if {re.sub(r' [0-9.]+ m$', '', n) for n in names} <= _SHOWN \
                        and all(re.search(r' [0-9.]+ m$', n) for n in names) else []     # labelled by an earlier version (or without the resolution): fetched again
                    if not names and src != 'national':
                        names = _default_names(src, size_m / (G - 1))
                    if names:
                        log.debug('Elevation loaded from cache: shape=%s, sources=%s', dem.shape, names)
                        progress(1.0, 'Elevation loaded from cache')
                        return dem, src, names
                    log.debug('Cache file has no list of datasets: fetched again')
            except (OSError, ValueError) as e:
                log.debug('Failed to load cache file: %s', e)
                pass
        t = time.time()
        _used.names = []
        try:
            log.debug('Fetching elevation from source: %s', src)
            _WINDOW['spacing'] = size_m / (G - 1)
            dem = FETCH[src](lat, lon, size_m, cancel, progress, rot=rot)
        except (DemError, net.NetError) as e:
            if _cancelled(cancel):
                raise
            log.warning('%s failed: %s', src, _redact(e))
            errors.append(_redact(e))
            continue
        names = _listed(_used.names, size_m / (G - 1)) or _default_names(src, size_m / (G - 1))
        dem = dem.astype(np.float32)
        buf = io.BytesIO()
        np.save(buf, dem)
        log.debug('Saving elevation cache: %s (%d bytes)', f, len(buf.getvalue()))
        paths.atomic_write(f, buf.getvalue())
        paths.atomic_write(_sources_file(f), json.dumps(names).encode('utf-8'))
        _trim_cache()
        log.info('elevation %s for %.5f,%.5f %.0f m in %.1f s: %.0f..%.0f m (%s)', src, lat, lon, size_m,
                 time.time() - t, dem.min(), dem.max(), ', '.join(names))
        progress(1.0, 'Elevation ready')
        return dem, src, names
    log.error('All elevation sources failed: %s', errors)
    raise DemError(errors[-1] if errors else 'No elevation source covers this area')


def load(lat, lon, size_m, cancel=net.NEVER, progress=lambda f, t: None, prefer=None, rot=0.0):
    """-> (dem metres float32 (G, G), source id). Cached per window."""
    log.debug('load() called: lat=%.5f, lon=%.5f, size_m=%.0f, prefer=%s, rot=%.1f', lat, lon, size_m, prefer, rot)
    dem, src, _ = load_sources(lat, lon, size_m, cancel, progress, prefer, rot)
    log.debug('load() returned: source=%s, shape=%s, min=%.1f, max=%.1f', src, dem.shape, dem.min(), dem.max())
    return dem, src


def _trim_dir(d, keep, pattern='*.npy'):
    try:
        files = sorted(d.glob(pattern), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    for f in files[keep:]:
        try:
            f.unlink()
            f.with_suffix('.json').unlink(missing_ok=True)
        except OSError:
            pass


def _trim_cache(keep=24):
    _trim_dir(paths.DEMS, keep)

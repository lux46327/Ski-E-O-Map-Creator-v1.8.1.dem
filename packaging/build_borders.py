"""Build data/borders.npz: country outlines that dem.py uses to keep each national elevation survey inside its own
country (some services return coarse filler data beyond their border).

Source: geo-maps "countries-maritime-1m" (https://github.com/simonepri/geo-maps, release v0.6.0): OpenStreetMap's
country boundaries, simplified by at most 1 m. They include each country's territorial waters (12 nautical miles), so
clipping never cuts a survey's own coast. Data (c) OpenStreetMap contributors, ODbL 1.0 (data/borders-LICENSE.txt).

Only the countries dem.py clips are kept. Each is split into 1 x 1 degree pieces, so dem.py loads only the pieces a
terrain window touches. Coordinates are stored as integer micro-degrees (~0.1 m).

    python packaging/build_borders.py countries-maritime-1m.geo.json data/borders.npz

Needs shapely (only for building; the app itself does not).
"""
import json
import math
import sys

import numpy as np
from shapely.geometry import box, mapping, shape
from shapely.validation import make_valid

COUNTRIES = ('FRA', 'ITA', 'CHE', 'LIE', 'NOR', 'FIN', 'SWE', 'ESP', 'CAN', 'USA', 'PRI', 'VIR', 'AUT', 'JPN', 'DEU', 'POL', 'SVK', 'CZE', 'NZL', 'AUS', 'ISL', 'GBR')


def polygons(g):
    if g.is_empty:
        return []
    if g.geom_type == 'Polygon':
        return [g]
    if g.geom_type in ('MultiPolygon', 'GeometryCollection'):
        return [p for part in g.geoms for p in polygons(part)]
    return []                                               # lines/points from the tile cut


def main(src, dst):
    feats = {f['properties']['A3']: f for f in json.load(open(src, encoding='utf-8'))['features']}
    xy, ring_off, poly_ring, poly_country, poly_tile = [], [0], [0], [], []
    for ci, code in enumerate(COUNTRIES):
        g = make_valid(shape(feats[code]['geometry']))
        w, s, e, n = g.bounds
        npoly = 0
        for lon in range(math.floor(w), math.ceil(e)):
            for lat in range(math.floor(s), math.ceil(n)):
                cell = box(lon, lat, lon + 1, lat + 1)
                if not g.intersects(cell):
                    continue
                for p in polygons(g.intersection(cell)):
                    for ring in [p.exterior] + list(p.interiors):
                        c = np.round(np.asarray(ring.coords)[:, :2] * 1e6).astype(np.int64)
                        xy.append(c)
                        ring_off.append(ring_off[-1] + len(c))
                    poly_ring.append(len(ring_off) - 1)
                    poly_country.append(ci)
                    poly_tile.append((lon, lat))
                    npoly += 1
        print('%s: %d pieces' % (code, npoly))
    xy = np.concatenate(xy)
    assert np.abs(xy).max() < 2 ** 31
    np.savez_compressed(dst, xy=xy.astype(np.int32), ring_off=np.asarray(ring_off, np.int64),
                        poly_ring=np.asarray(poly_ring, np.int64), poly_country=np.asarray(poly_country, np.uint8),
                        poly_tile=np.asarray(poly_tile, np.int16), countries=np.asarray(COUNTRIES),
                        source=np.asarray('geo-maps countries-maritime-1m v0.6.0, (c) OpenStreetMap contributors, '
                                          'ODbL 1.0'))
    print('%d vertices, %d rings, %d pieces -> %s' % (len(xy), len(ring_off) - 1, len(poly_country), dst))


if __name__ == '__main__':
    main(*sys.argv[1:3])

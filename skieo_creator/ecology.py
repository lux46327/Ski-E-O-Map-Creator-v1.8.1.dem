"""Where each tree species grows, the way the game's own maps have it. The game's forests were generated offline by its
developers (the game only loads them), so data/tree_patterns.json holds what its maps show, per biome: how each species'
share shifts with a tree's place in the forest's height range, the slope, the sun, wetness and ridges (a multinomial
model on those terrain classes), and each species' sizes and conditions by height; packaging/make_tree_patterns.py
learns it from the game's maps. The terrain features are computed here, the same way for the game's maps and ours."""
import json

import numpy as np

from . import paths

CELL_M = 20.0                   # the terrain features are computed on cells about this big
SLOPE_EDGES = (8.0, 16.0, 24.0, 32.0)
HEAT_EDGES = (0.4, 0.6)
WET_EDGES = (0.33, 0.66)
RIDGE_EDGES = (-0.5, 0.5)
BANDS = 10
_patterns = None


def patterns():
    global _patterns
    if _patterns is None:
        _patterns = json.loads(paths.resource('data', 'tree_patterns.json').read_text(encoding='utf-8'))
    return _patterns


def _box_mean(a, r):
    """mean over the (2r+1) x (2r+1) cells round each cell (edges repeated)"""
    k = 2 * r + 1
    c = np.cumsum(np.cumsum(np.pad(a.astype(np.float64), r, mode='edge'), 0), 1)
    c = np.pad(c, ((1, 0), (1, 0)))
    return ((c[k:, k:] - c[:-k, k:] - c[k:, :-k] + c[:-k, :-k]) / (k * k)).astype(np.float32)


def _rank(a):
    """0..1 between the 2nd and 98th percentile"""
    lo, hi = np.percentile(a, [2, 98])
    return np.clip((a - lo) / max(float(hi - lo), 1e-6), 0.0, 1.0).astype(np.float32)


def _flow(E):
    """cells that drain through each cell, itself included (D8: each cell to its steepest lower neighbour)"""
    n0, n1 = E.shape
    p = np.pad(E, 1, mode='edge')
    ids = np.pad(np.arange(n0 * n1).reshape(n0, n1), 1, mode='edge')
    best = np.zeros(E.shape, np.float32)
    rcv = np.full(E.shape, -1, np.int64)
    for dy in (-1, 0, 1):
        for dx in (-1, 0, 1):
            if dy or dx:
                drop = (E - p[1 + dy:1 + dy + n0, 1 + dx:1 + dx + n1]) / np.hypot(dy, dx)
                lower = drop > best
                best[lower], rcv[lower] = drop[lower], ids[1 + dy:1 + dy + n0, 1 + dx:1 + dx + n1][lower]
    acc, to = [1.0] * (n0 * n1), rcv.ravel().tolist()
    for i in np.argsort(-E, axis=None).tolist():          # from the top down: a cell passes on all it gathered
        j = to[i]
        if j >= 0:
            acc[j] += acc[i]
    return np.asarray(acc, np.float32).reshape(n0, n1)


def grid(H, sp, sc, hmin):
    """the map's heights (m) on cells of ~CELL_M (rows run south, columns east): (E, metres per cell)"""
    f = max(1, int(round(CELL_M / sp)))
    n = (H.shape[0] - 1) // f
    E = ((H[:n * f, :n * f].astype(np.float32) + 32768) * sc + hmin).reshape(n, f, n, f).mean(axis=(1, 3))
    return E, f * sp


def features(E, cell, lat):
    """per cell: slope (deg); heat (0..1: the midday sun on the ground, flat 0.5, turned toward the warmer afternoon,
    from the south in the north and the north in the south); wet (0..1: rank of the topographic wetness index, where
    water gathers on flat ground); ridge (the height above the ground within 300 m, in standard deviations)"""
    gy, gx = np.gradient(E, cell)
    tan_s = np.hypot(gx, gy)
    nz = 1.0 / np.sqrt(1.0 + tan_s * tan_s)
    az, el = np.radians(202.5 if lat >= 0 else 337.5), np.radians(float(np.clip(90.0 - abs(lat), 20.0, 70.0)))
    inc = -gx * nz * np.cos(el) * np.sin(az) + gy * nz * np.cos(el) * np.cos(az) + nz * np.sin(el)
    tpi = E - _box_mean(E, max(1, int(300.0 / cell)))
    return dict(slope=np.degrees(np.arctan(tan_s)).astype(np.float32),
                heat=np.clip(0.5 + 0.5 * (inc - np.sin(el)) / (1.0 - np.sin(el)), 0.0, 1.0).astype(np.float32),
                wet=_rank(np.log(_flow(E) * cell / np.maximum(tan_s, 0.01))),
                ridge=(tpi / max(float(tpi.std()), 1e-3)).astype(np.float32))


def design(band, slope, heat, wet, ridge):
    """one-hot terrain classes per tree (band: 0..BANDS-1): (trees, BANDS + 5 + 3 + 3 + 3) floats"""
    cols = [np.eye(BANDS, dtype=np.float32)[np.clip(band, 0, BANDS - 1)],
            np.eye(len(SLOPE_EDGES) + 1, dtype=np.float32)[np.digitize(slope, SLOPE_EDGES)],
            np.eye(len(HEAT_EDGES) + 1, dtype=np.float32)[np.digitize(heat, HEAT_EDGES)],
            np.eye(len(WET_EDGES) + 1, dtype=np.float32)[np.digitize(wet, WET_EDGES)],
            np.eye(len(RIDGE_EDGES) + 1, dtype=np.float32)[np.digitize(ridge, RIDGE_EDGES)]]
    return np.concatenate(cols, axis=1)


def species_probs(model, X):
    """each species' probability per tree under a biome's model ({'species', 'coef', 'bias'})"""
    z = X @ np.asarray(model['coef'], np.float32) + np.asarray(model['bias'], np.float32)
    z -= z.max(axis=1, keepdims=True)
    p = np.exp(z)
    return p / p.sum(axis=1, keepdims=True)

"""Learns data/tree_patterns.json from the game's own maps: per biome, how each species' share shifts with a tree's
place in its forest's height range, slope, sun, wetness and ridges, and each species' sizes and conditions by height.
The game's forests were generated offline by its developers; this measures them. Extract the maps first (retoc
to-legacy with -f DA_BakedObstacles_Map_ -f Materials/Terrain/Generated/, see docs/DEVELOPMENT.md), then:
usage: python packaging/make_tree_patterns.py <extracted Content folder> [--check]"""
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from skieo_creator import biomes, ecology, trees  # noqa: E402

CONTENT = Path(sys.argv[1])
G = trees.G


def norm(s):
    return re.sub(r'[^a-z0-9]', '', s.lower().replace('mtn', 'mountain'))


STOCK = {norm(n): (lat, b) for n, lat, lon, b in biomes.STOCK}


def stock(slug):
    k = norm(slug)
    return STOCK.get(k) or next((v for kk, v in STOCK.items() if kk.startswith(k) or kk == 'the' + k), None)


def game_maps():
    gen = CONTENT / 'Generated'
    for f in sorted(gen.glob('DA_BakedObstacles_Map_*.uexp')):
        slug = re.sub(r'_real$', '', f.stem[len('DA_BakedObstacles_Map_'):])
        if 'diorama' in slug or (not f.stem.endswith('_real') and (gen / (f.stem + '_real.uexp')).exists()):
            continue
        h = CONTENT / 'Materials/Terrain/Generated' / slug / ('H_%s_Out.uexp' % slug)
        info = stock(slug)
        if h.exists() and info:
            yield slug, f, h, info


def terrain(hpath, x, y, z):
    """the map's heights (m) on ecology cells, fitted to its own trees' z (size and height scale)"""
    ue = hpath.read_bytes()
    g = next(n for n in (8065, 4033, 2017, 1009) if len(ue) - 24 - n * n * 4 > 0)   # the texture's side
    st = len(ue) - 24 - g * g * 4
    if b'PF_R32_FLOAT' in ue[:st]:
        T = np.frombuffer(ue[st:st + g * g * 4], '<f4').reshape(g, g).astype(np.float64)
    else:
        T = np.frombuffer(ue[st:st + g * g * 4], np.uint8).reshape(g, g, 4)[..., 0] / 255.0
    best = None
    sel = np.random.default_rng(0).choice(len(x), min(len(x), 40000), replace=False)
    for size in np.arange(np.ceil(max(x.max(), y.max()) / 50) * 50, max(x.max(), y.max()) + 400, 25.0):
        sp = size / (g - 1)
        r, c = np.clip((y[sel] / sp).astype(int), 0, g - 1), np.clip((x[sel] / sp).astype(int), 0, g - 1)
        A = np.vstack([T[r, c], np.ones(len(sel))]).T
        coef = np.linalg.lstsq(A, z[sel], rcond=None)[0]
        rms = float(np.sqrt(np.mean((A @ coef - z[sel]) ** 2)))
        if best is None or rms < best[0]:
            best = (rms, size, coef)
    rms, size, (a, b) = best
    sp = size / (g - 1)
    f = max(1, int(round(ecology.CELL_M / sp)))
    n = (g - 1) // f
    E = (a * T[:n * f, :n * f] + b).reshape(n, f, n, f).mean(axis=(1, 3)).astype(np.float32)
    return E, f * sp, size, rms


def load(slug, opath, hpath, lat):
    d = trees.read_skob(opath.read_bytes())
    r = np.frombuffer(d['records'], np.uint8).reshape(-1, trees.STRIDE)
    x = r[:, 0:4].copy().view('<i4').ravel() / 1000.0
    y = r[:, 4:8].copy().view('<i4').ravel() / 1000.0
    z = r[:, 8:12].copy().view('<i4').ravel() / 1000.0
    v = r[:, 18:20].copy().view('<u2').ravel()
    if len(v) < 1000:
        print('  %-17s no forest' % slug)
        return None
    ents = trees.table_entries(d['table'])
    sp = np.array([e[0].replace('DA_TreeSpecies_', '') for e in ents])[v]
    size = np.array([e[1] for e in ents], np.int64)[v]
    cond = np.array([e[2] for e in ents], np.int64)[v]
    E, cell, msize, rms = terrain(hpath, x, y, z)
    F = ecology.features(E, cell, lat)
    ri, ci = np.clip((y / cell).astype(int), 0, E.shape[0] - 1), np.clip((x / cell).astype(int), 0, E.shape[1] - 1)
    zl, zh = np.percentile(z, [1, 99])
    band = np.clip(((z - zl) / max(zh - zl, 1.0) * ecology.BANDS).astype(int), 0, ecology.BANDS - 1)
    X = ecology.design(band, F['slope'][ri, ci], F['heat'][ri, ci], F['wet'][ri, ci], F['ridge'][ri, ci])
    print('  %-17s %7d trees, %4.0f m map (fit %.1f m rms), %s' % (slug, len(x), msize, rms,
          ', '.join('%s %.0f%%' % (s, 100 * c / len(sp)) for s, c in zip(*np.unique(sp, return_counts=True)))))
    return dict(slug=slug, X=X, sp=sp, band=band, size=size, cond=cond)


def fit(X, y, S, iters=600, l2=1e-3):
    """multinomial logistic regression (Adam, full batch) on the distinct rows of X with their species counts:
    coef (D, S), bias (S)"""
    rows, inv = np.unique(X, axis=0, return_inverse=True)
    C = np.zeros((len(rows), S))
    np.add.at(C, (inv.ravel(), y), 1)
    n = C.sum()
    W, b = np.zeros((X.shape[1], S)), np.log(C.sum(0) / n + 1e-6)
    mW, vW, mb, vb = np.zeros_like(W), np.zeros_like(W), np.zeros_like(b), np.zeros_like(b)
    for t in range(1, iters + 1):
        z = rows @ W + b
        z -= z.max(1, keepdims=True)
        p = np.exp(z)
        p /= p.sum(1, keepdims=True)
        R = p * C.sum(1, keepdims=True) - C                   # gradient of the summed NLL wrt the logits
        gW = rows.T @ R / n + 2 * l2 * W
        gb = R.sum(0) / n
        for g, m, v, P in ((gW, mW, vW, W), (gb, mb, vb, b)):
            m *= 0.9
            m += 0.1 * g
            v *= 0.999
            v += 0.001 * g * g
            P -= 0.05 * (m / (1 - 0.9 ** t)) / (np.sqrt(v / (1 - 0.999 ** t)) + 1e-8)
    return W, b


def nll(W, b, X, y):
    z = X @ W + b
    z -= z.max(1, keepdims=True)
    lp = z - np.log(np.exp(z).sum(1, keepdims=True))
    return float(-lp[np.arange(len(y)), y].mean())


def main():
    by = {}
    for slug, o, h, (lat, biome) in game_maps():
        by.setdefault(biome, []).append((slug, o, h, lat))
    out = dict(source='learned from the game\'s own maps by packaging/make_tree_patterns.py',
               features=dict(bands=ecology.BANDS, slope=ecology.SLOPE_EDGES, heat=ecology.HEAT_EDGES,
                             wet=ecology.WET_EDGES, ridge=ecology.RIDGE_EDGES), biomes={})
    for biome, ms in sorted(by.items()):
        print('== %s' % biome)
        data = [d for d in (load(s, o, h, lat) for s, o, h, lat in ms) if d]
        if not data:
            print('   no trees')
            continue
        names = sorted(set(np.concatenate([d['sp'] for d in data])))
        S = len(names)
        for d in data:
            d['y'] = np.searchsorted(names, d['sp'])
        X, y = np.concatenate([d['X'] for d in data]), np.concatenate([d['y'] for d in data])
        if not len(y):
            continue
        if len(data) > 1 and '--check' in sys.argv:                  # does it hold on a map it has not seen?
            for k, d in enumerate(data):
                tr = [e for j, e in enumerate(data) if j != k]
                Xt, yt = np.concatenate([e['X'] for e in tr]), np.concatenate([e['y'] for e in tr])
                W, b = fit(Xt, yt, S)
                prior = np.log(np.bincount(yt, minlength=S) / len(yt) + 1e-9)
                Wb, bb = fit(Xt[:, :ecology.BANDS], yt, S)
                print('    held-out %-16s chance %.3f  height only %.3f  full %.3f' % (
                    d['slug'], float(-prior[d['y']].mean()), nll(Wb, bb, d['X'][:, :ecology.BANDS], d['y']),
                    nll(W, b, d['X'], d['y'])))
        W, b = fit(X, y, S)
        # sizes and conditions: per species and height band, (size, condition) shares (size * 4 + condition)
        sc = np.zeros((S, ecology.BANDS, 16))
        for d in data:
            np.add.at(sc, (d['y'], d['band'], d['size'] * 4 + d['cond']), 1)
        per_sp = sc.sum(1, keepdims=True)
        sc = (sc + 0.5 * per_sp / np.maximum(per_sp.sum(2, keepdims=True), 1)) / np.maximum(
            sc.sum(2, keepdims=True) + 0.5, 1e-9)
        out['biomes'][biome] = dict(maps=[d['slug'] for d in data], trees=int(len(y)), species=list(map(str, names)),
                                    coef=np.round(W, 4).tolist(), bias=np.round(b, 4).tolist(),
                                    size_cond=np.round(sc, 4).tolist())
        print('   %d trees, species %s, fit %.3f (chance %.3f)' % (len(y), names, nll(W, b, X, y),
              float(-np.log(np.bincount(y, minlength=S)[y] / len(y)).mean())))
    (ROOT / 'data' / 'tree_patterns.json').write_text(json.dumps(out, separators=(',', ':')), encoding='utf-8')
    print('wrote data/tree_patterns.json: %d biomes' % len(out['biomes']))


if __name__ == '__main__':
    main()

# Developing the Map Creator

How the maps are built, how to run and build the app from source, where things are, and how a release is made.
For players, see the [README](../README.md).

## How it works

1. **Elevation**: USGS 3DEP 1/3 arc-second (~10 m) inside the US, AWS Terrain Tiles (~30 m) elsewhere
   (`dem.py`). It is resampled onto the game's 2017 x 2017 landscape grid on a local transverse Mercator projection
   (`geo.py`).
2. **Game data**: `gamedata.py` uses retoc to extract a donor map (Mad River Glen) and a few assets from the
   player's game into a cache, and dry-runs every writer on them before the first build.
3. **Build** (`builder.py`): the donor map is copied, and these parts are rewritten:
   - **Heights and scale:** landscape heights and all their mip levels (made the way Unreal makes them), edge-normal
     rings and grid scale (`engine/terrain_write.py`, `engine/provider_write.py`); component bounds and collision;
     the map frame (size, height scale); and the edge wall, whose edge the terrain is fitted to (`engine/map_frame.py`).
   - **Forest:** in the game's baked-obstacle format (`trees.py`): stands of the tree species the game's own maps of
     the biome have, mixed and placed by height, slope, sun, wetness and ridges as there (`ecology.py`,
     `data/tree_patterns.json`, see below), conifers only near the summits (`biomes.py`).
   - **Snow piles:** written from a cooked template mesh (`shells.py`, `data/shell_template.*`).
   - **Everything else:** terrain material overrides (`engine/material_params.py`), the height texture, the map
     preview, the starting save (ticket office on the base area), and the map list entry. Every renamed string keeps
     its length.
   - **Real trails and lifts** (optional, `resort.py`): the ski area's OpenStreetMap lifts and pistes become the
     game's own lift and trail records in the starting save (read and written with `engine/gvas_tree.py`, record
     layouts from `data/resort_templates.bin`), each run's curves as wide as its real cut through the forest in the
     satellite canopy heights (`resort._cuts`), the forest leaves their corridors clear, and the map list entry's
     `InitialSave` makes New Game start from that save. Glades are left out: the ones OSM marks, and runs under tree
     canopy with no cleared corridor in the satellite canopy heights (`canopy.py`). A run drawn twice in OSM is built
     once. Within 300 m of the runs, glades and lifts the forest follows the real tree cover from the same canopy
     heights (`resort.tree_cover`), so open bowls and meadows stay open.
4. **Pack and install**: retoc `to-zen` packs a `ZZZ_MC_<name>_P` pak. `install.py` adds the map to the game's
   map list (`ZZZ_Registry_P`) and copies it into `Content/Paks/~mods`.

The window is a local web UI (`web/`: Leaflet map, three.js 3D preview) shown by pywebview / WebView2. `server.py`
serves it on 127.0.0.1, with a token-protected tile proxy on its own port.

The Mod Library (`modlib.py`) copies the in-game Lua mods from `data/mods` into the game's `Binaries/Win64/ue4ss/Mods`
(installing UE4SS from `data/ue4ss` when the game doesn't have it) and the pak mods from `data/lifts` into
`Content/Paks/~mods` (Blueprint mods: `Content/Paks/LogicMods`). The build menu's table and the snow cap list can only
come from one pak, so it merges them for all installed mods into its own pak, made from the player's game files
(`engine/shared_assets.py`), keeping what mods installed by hand add (`modscan.py`, which also checks that a map
package holds only a map). Mods by other modders are packaged into it with `packaging/package_mod.py`:
[MODDING.md](MODDING.md).

## Run from source

Windows 10/11, Python 3.12, Ski-E-O! installed through Steam.

```
py -3.12 -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py
```

## Build the exe

```
packaging\build.bat
```

This makes `dist\SkiEO-Map-Creator.exe`, a single file that bundles `web/`, `data/` and `tools/retoc.exe`.

## Data learned from the game

`data/tree_patterns.json` holds how each biome's tree species are spread over the game's own maps. To make it again
(after a game update that changes the maps' forests), extract the maps' forests and height textures, then run the
learner on them:

```
tools\retoc.exe to-legacy --no-shaders -f DA_BakedObstacles_Map_ -f Materials/Terrain/Generated/ <game>\SkiResortSimulator\Content\Paks <out>
python packaging/make_tree_patterns.py <out>\SkiResortSimulator\Content --check
```

## Layout

| Path | What |
|---|---|
| `skieo_creator/` | app: `main.py` (window), `api.py` (calls from the page), `builder.py`, `trees.py`, `shells.py`, `dem.py`, `install.py`, `modlib.py`, `update.py` ... |
| `skieo_creator/engine/` | writers for the cooked map data (heightmaps, providers, bounds, collision, frame, headers, materials) |
| `web/` | the UI (HTML / CSS / JS) and vendored Leaflet + three.js |
| `data/` | the cooked snow-shell template; `resort_templates.bin`, blank lift / trail save records (from `packaging/make_resort_templates.py`); the Mod Library's Lua mods (`mods/`), lift and building packs (`lifts/`) and UE4SS (`ue4ss/`) |
| `tools/` | retoc.exe (MIT, https://github.com/trumank/retoc) and its license, both shipped in the exe. Nothing else goes here: `verify_exe.py` fails the release build on any file in `tools/`, `web/` or `data/` the exe doesn't ship |
| `packaging/` | PyInstaller spec, build script, icon, version info, credits (`THIRD-PARTY.txt`), `verify_exe.py`; developer scripts the exe doesn't ship, such as `make_tree_patterns.py` and `package_mod.py` (below) |
| `docs/` | this file and the README's screenshots |
| `tests/ui_drive.py` | scripted UI sessions with screenshots (`search`, `3d`, `3d-offline`, `numbox`, `osm`, ...) |
| `tests/test_resort.py` | self-check of the trail and lift import rules on made-up data |
| `tests/test_dem.py` | self-check of reading where the USGS elevation image really is (its GeoTIFF tags) |
| `tests/test_update.py` | self-check of the self-update (release lookup, checksums, swapping the exe) without the network |
| `tests/test_install.py` | self-check of the map list entries (never a tutorial map, the once-only rebuild of older ones) |
| `tests/test_main.py` | self-check of the empty-window guard (a second try, then a message) with a stand-in window |
| `.github/workflows/release.yml` | builds, checks, hashes and attests the exe and attaches it to each release |

## Releasing

1. Bump `VERSION` in `skieo_creator/__init__.py` and the versions in `packaging/version_info.txt`, and add a
   `## vX.Y.Z` section to `CHANGELOG.md`.
2. On GitHub: **Releases → Draft a new release**, create the tag `vX.Y.Z`, and publish. The description can stay
   empty.
3. The workflow builds the exe from that tag, checks it against the source, and attaches it and `SHA256SUMS.txt` to
   the release, with the notes from `CHANGELOG.md`. It stops if the tag doesn't match the versions in step 1.

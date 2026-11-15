# Changelog

Maps made with an older version show **Rebuild recommended** in My Maps: one click on Rebuild gives them the fixes.

## v1.7.6.dem
### What's new
- **Rotate the area** with a slider or a turn handle on the map.
- **Sharper terrain** from national elevation surveys in many countries, stitched across borders, with AWS Terrain Tiles as fill.
- **Height modifier and height offset** for reshaping the terrain.
- **Real tree cover** support for terrains without lifts,: trees grow where the satellite data says they do.
- **Replace Map**: build a map under an existing name to rebuild it with new settings (the name field warns first).
- **More reliable trails and lifts download** (one request, regional servers first), also for rotated areas.
- Footer with all elevation sources and licences.
- No update check in this build.


## v1.7.6
- **Mod Library: two new mods**, each on its own (no cheat menu needed) or together with it:
  - **Oof's Anarchy**: build anywhere. **Ctrl+A** switches it on and off in game. While it is on, the buildings and
    lifts you place or move ignore slopes, ground type, trees and rocks, and other buildings, and a badge under the
    top bar says so. It is off each time the game starts.
  - **Oof's Speed Control**: speed buttons from 1x to 100x under the game's own (top right). Click one to run the game
    that fast, click the lit one again to go back to 1x. They show while the game shows its top bar.
- **No more empty window when WebView2 is broken.** The Map Creator's window is drawn by Microsoft Edge WebView2, and
  when WebView2 could not start (for example a copy that Windows still lists but whose files are gone, which tools
  that remove Microsoft Edge often leave behind), the window just stayed empty. Now the Map Creator notices, tries
  once more with a fresh browser profile and graphics acceleration off (and keeps starting that way if that helped),
  and otherwise says what went wrong and how to repair WebView2.
- The log now records the Windows version and display language at each start.

## v1.7.5
- **Real trails and lifts: no more empty resort after "Skip Tutorial".** Custom maps were marked as tutorial maps (left
  over from the demo days), and the game treats the first tutorial map in its list as THE tutorial map. In regions
  listed before Tahoe (Canadian Rockies, Scandes, Alps, Japan, Korea, China, Australia, New Zealand, the Andes,
  Hawaii), that was a custom map instead of Sugar Bowl: New Game offered the tutorial on every start, and **Skip
  Tutorial** started the map without its lifts and trails. Custom maps are no longer tutorial maps.
- Maps you already installed are fixed the next time the Map Creator opens while the game is closed (no rebuild
  needed). A game you already started without its lifts and trails stays that way: start a New Game on the map.
- **Check for updates** next to the version number (bottom right): looks for a newer version on GitHub any time, and
  updates and restarts the Map Creator on yes, with a progress bar and Cancel.
- **Oof's Alpine Buildings: the cabins no longer clear a big empty square of trees.** The game sizes the patch of
  trees a building clears (and the ground it flattens) to every model in the building, and the cabins still carried
  the game cabin's porch props (axes, barrels, ski racks), hidden but in place, so a small cabin cleared up to 3.7 m
  of extra forest on each side, up to 63% more than its own size. The props are gone now. Installed packs update
  by themselves the next time the Map Creator opens while the game is closed; buildings you already placed keep
  their cleared ground.

## v1.7.4
- **Updates itself.** When it starts, the Map Creator looks for a newer version on GitHub and asks before updating.
  On yes it downloads the new exe (with a progress bar), checks it against the release's SHA-256, puts it in place of
  the old one and starts it. If anything goes wrong, this version simply opens as it is. Keep the exe in a folder of
  your own (Desktop, Documents, Downloads) so it can replace itself.

## v1.7.3
- **Real trails and lifts: no more trails drawn as loops and stray dashes.** A trail is a chain of the game's curves,
  and the Map Creator cut every run into 100 m pieces: over a hairpin or a sharp bend (cat tracks and roads, like
  Vail's Gitalong Road) a curve overshot the bend and folded back, so the game drew the trail as loops. Now the curves
  are cut at the bends and follow them, and a trail narrows where a bend is too tight for its width (at Vail: 16
  trails with folded curves before, now none worth seeing).
- Maps made with the real trails and lifts show **Rebuild recommended**: Rebuild gives them the fixed trails.

## v1.7.2
- **Real trails and lifts: the forest round the resort is the real one.** The Map Creator plants its own forest
  everywhere below the treeline, and OpenStreetMap often maps open bowls only as the runs through them (Vail's back
  bowls are), so they came out as narrow trails cut through a full forest. Now, within 300 m of the runs, glades and
  lifts, the trees follow the real tree cover from the satellite tree heights: open bowls, meadows and old burns stay
  open, glades keep their own sparse trees, and the forest further out is as before.
- Maps made with the real trails and lifts show **Rebuild recommended**: Rebuild gives them the real forest.

## v1.7.1
- **US maps: the terrain is where it really is.** The USGS elevation service sends a taller area than the one asked
  for, and the Map Creator stretched it over the map anyway: the terrain of every US map came out squeezed north-south
  towards the middle of the map (by about a quarter at Killington's latitude), so peaks and ridges away from the middle
  sat hundreds of metres from their real spots. With the real trails and lifts on, the lifts and trails were in their
  real places but the ridges under them were not (Superstar Express ended below the ridge it climbs). New maps get the
  real terrain: Killington Peak lands within 30 m of the real one (was 700 m off). Maps outside the US were not
  affected.
- **To fix a US map, create it again** (same place, same size). Rebuild keeps the old terrain on purpose, so a resort
  you already built on it doesn't end up floating or buried.

## v1.7.0
- **Oof's Alpine Buildings** (Mod Library), reworked:
  - **Doors at every entrance**. Hotels and base lodges have a front entrance and side entrances.
  - **Snow on everything open to the sky**: every building has its own snow cap, like the game's own buildings: roofs,
    turret cones, steep A-frame roofs, porch and balcony tops. Porches and decks under a roof stay free of snow.
  - **Sorted by what they look like**: every big building with many windows (the grand lodges, the giants, the modern
    hotels, apartments and inns) is a **Hotel** now, and the three lakeside estates (a glazed great room between gabled
    pavilions on a stone terrace) are **Base Lodges** (food, rest and warmth for day skiers). No Grand Lodges.
  - **Plain names** in the build menu: Cabin 1-29, Hotel 1-18 and Base Lodge 1-3.
  - **Cabins are single-family homes**: 4 beds each, $30,400 to build and $152 a day to run.
  - **Hotels and base lodges hold guests by their size** (their floor area), and building and running one costs at
    most 1.3 times the game's own building of the same kind (the biggest hotel cost $5.4 million before, now $2.9
    million; the small inns are $670,000).
  - **They sell what the game's own building sells**: beds to rent in the cabins and hotels (Bunk, Private Room,
    Suite), and food, drinks and hand warmers in the base lodges.
  - The boulders around the buildings are gone.
- **Mod Library**: an Install and an Uninstall button for each mod instead of the switch.

## v1.6.2
- **Real trails and lifts: no more runs painted twice.** OpenStreetMap often has a run drawn twice (a newer piste line
  next to the older road that carries the run's name, or a second mapper's line): the map got two trails with the same
  name on top of each other (13 at Stratton). A run is now built once; where only part of it was drawn twice, the rest
  is kept. Branches of a run that meet stay as they are.
- Maps made with the real trails and lifts in 1.6.1 show **Rebuild recommended**.
- **Treeline fade** starts at **sharp** (was 200 m): the forest stops at the treeline. Raise it to thin the forest out
  below the treeline instead.

## v1.6.1
- **Real trails and lifts leave out glades** (skiing through the trees). The game has no tree skiing yet: a glade
  became a bare clearing, or a big empty patch where it was mapped as an area. Left out:
  - runs marked as glades in OpenStreetMap (gladed=yes, or "Glade" in the name),
  - and runs that go through the trees with no cleared corridor, from satellite tree heights (Meta / WRI canopy
    height map). A run mapped a little beside its clearing still counts as cleared, and green runs and roads (cat
    tracks under the trees) are always kept.
  The map shows the glades left out as grey dotted lines, so you can check them with the Satellite view.
- Maps made with the real trails and lifts in 1.6.0 show **Rebuild recommended**: rebuild them to clear out the glades.

## v1.6.0
- **Real trails and lifts** (new switch under Your resort): builds the real ski area into the map from
  OpenStreetMap, so a **New Game** on it starts with the resort already there:
  - **Every lift** as the closest lift in the game, in its real place, with its real name: a six-pack becomes a
    High-Speed Six, an express quad a High-Speed Quad, a fixed quad a 4-Person Fixed Grip, a double a 2-Person Fixed
    Grip, gondolas Gondolas, cable cars Aerial Trams (T-bars, platters and carpets, which the game doesn't have,
    become fixed-grip chairs). Towers stand where the game would put them, and lift stations close together share a
    base area, named after the real station where OpenStreetMap has one.
  - **Every trail** with its name and rating (green, blue, black, double black), along its real line down the
    mountain; open piste areas become bowls. No trees grow on the trails or under the lifts.
  - The map shows the trails and lifts before you build, with the list of lifts and what each costs to run.
- Lifts cost upkeep every night, open or not, and a real resort's lifts cost far more than a new game earns at
  first (Beaver Creek's 19: about $239,000 a night). Untick lifts to leave them out (build them in the game later),
  or turn on **Sandbox** (no costs) in the game's Advanced Options when you start the resort. The lifts came free,
  so bulldozing one pays nothing back.

## v1.5.0
- **Oof's Alpine Buildings** (Mod Library): 50 new buildings in the build menu (under Comfort), all made from scratch
  for the pack out of the game's own materials (wood, stone, metal roofs, windows that light up at night):
  - **Two giants**: the Grand Summit Lodge (a glazed great hall between two stone chimneys, cross-gabled timber wings,
    a trussed porte-cochere) and the Grand Alpine Palace Hotel (green copper roofs, turrets, a grand portico).
  - **Timber-frame mountain homes**: walkout homes with covered decks and stone chimneys through glazed gables, homes
    with heavy-truss porticos on river-rock columns and rusty shed awnings.
  - **Log cabins, A-frames, Swiss chalets, a guesthouse and townhouses.**
  - **Modern**: villas, and hotels and apartment houses with larch balconies and dark metal top floors.
  - **Inns, grand lodges, hotels and three lakeside estates.**
  Homes work like the Cabin, the big ones like the Grand Lodge or the Hotel: same unlock and upkeep, more to build the
  bigger they are, and room for more guests.
- The R2 lift packs and the buildings pack share the build menu: switch on any of them and you get all of their
  content.

## v1.4.0
- **Full game**: works with **Ski-E-O! Ski Resort Tycoon** on Steam, finds it by itself, and Play starts it. The demo
  is no longer supported (its game files are encrypted since its last update). Maps made with an older version
  show **Rebuild recommended**: rebuild them once for the full game.
- **Custom maps are real size only**: the Map size switch (Real Size / Diorama) in Advanced Options is hidden for them.
- **Oof's Simple Cheat Menu** (Mod Library, **F6** in game) replaces Weather Controls and keeps all of its weather
  controls. Four tabs:
  - **Money**: add $100K to $100M, pay off all loans, infinite money (never below $100M), income multiplier up to 10x.
  - **Time**: speeds 1x to 100x, pause, skip ahead an hour, 6 hours, a day or a month, jump to morning, noon, sunset
    or night, freeze the clock.
  - **Weather**: force sunny, cloudy, snowing or blizzard; turn snowfall, storms and temperature up or down
    (buried in snow? lower the snowfall); re-roll the winter.
  - **Resort**: level up or jump to the top level (unlocks everything), add XP, add guests, and god mode switches:
    no accidents, no breakdowns, staff never get tired, build anywhere (slopes, trees, overlapping).
  If you had Weather Controls on, the app swaps it for the cheat menu by itself. F9 is now the full game's Report a Bug.
- **R2 lifts cost what the game's own lift of the same kind costs**, to build and to run, and unlock at the same
  level: the R2 Six like the High-Speed Six ($721,200+, Elite Resort), the R2 Gondola like the Gondola ($2,414,400+,
  World-Class). Before, both cost what the double chair does and were available almost from the start.
- **The R2 lifts install only through the Mod Library** (no more copying files into `~mods` by hand). The app keeps
  them up to date: a pack from an older version, or one copied in by hand, is replaced with the app's own.
- **The R2 lifts no longer hide new buildings**: with an R2 lift switched on, the full game's Base Lodge and autumn
  decorations were missing from the build menu. The app now copies the game's building list from your own game
  files, and copies it again after a game update the next time the app starts.

## v1.3.0
- **Millions of trees**: the game normally shows no trees at all on a map with more than 1.5 million. The creator now
  raises that limit for you: it changes that one number in `skieogame.exe` when it starts and before it installs a
  map, so it comes back by itself after a game update ("Verify integrity of game files" in Steam undoes it).
- **The tree slider follows the map size**: picking a size sets it to the game's own forest density (about 19,000
  trees per km²: 2.7 million on a 12 km map, 7.5 million on 20 km), which is also the most. You can still lower it.
- **Snowfall** shows the yearly snowfall the game will show for the map next to the multiplier, e.g. 1.10 × (385″/yr).
- **ft | m switch** next to "Your resort" (the same as Units at the bottom).
- Larger maps with many trees can take **up to 10 minutes** to fully load in game: the forest fills in square by
  square and the game runs slowly until it is done (the app says so under the tree slider).
- **Trees up to** starts at **42°** (was 33°), about where the game's own forests stop: steeper cliffs stay bare rock.
- A map never gets more trees than you set (it could go a few hundred over, and past the game's limit that wipes
  every tree).

## v1.2.0
- **Mod Library** (the brown button at the bottom): flip a switch to install a mod, flip it back to remove it.
  - **Weather Controls** (F9 in game): force sunny / cloudy / snowing / blizzard, and turn snowfall, storms and
    temperature up or down live. Fixes resorts getting buried in snow. Installs the UE4SS mod loader too if you
    don't have it, and removes it again when switched off.
  - **Doppelmayr D-Line R2 Six** and **R2 Gondola** lifts: switch them on and they appear in the build menu.
- **Satellite** map view next to Topo and Streets.
- **Treeline fade**: the forest thins out gradually below the treeline instead of stopping in a straight line
  (default 200 m; 0 = the old sharp edge).
- **Max trees** goes up to 1,490,000 (was 1,000,000). The game shows no trees at all from 1.5 million.
- Maps up to **20 km** wide (was 12). The game's terrain grid stays the same size, so bigger maps are coarser
  (about 10 m between height points at 20 km).

## v1.1.10
- Number boxes accept European decimals: `0,93` works like `0.93`, and `3.500 m` counts as thousands.

## v1.1.9
- Fixed resort names with accents (like ü or é) breaking the game's map list.
- Names use letters, numbers, spaces and `- ' . & ( )` only. Accents become plain letters automatically
  (Zürs → Zurs).

## v1.1.8
- Fixed installing, rebuilding and the game status failing on non-English Windows (German and others).

## v1.1.7
- Max trees goes up to 1,000,000 (higher counts made the game drop all trees).

## v1.1.6
- Fixed the thin lines across the terrain for good, and the terrain lighting looking too steep.

## v1.1.5
- Full forest right up to the "Trees up to" angle, no thinning before it.

## v1.1.4
- New **Trees up to** slider: the steepest slope that still gets trees (default 33°).
- Removed the Share buttons.

## v1.1.3
- No more repeating stripes on big rock faces (larger rock texture).

## v1.1.2
- Trees no longer grow on bare rock (33° and steeper).
- First fix for the lines along terrain tile borders.

## v1.1.1
- No trees on cliffs.

## v1.1.0
- Fixed cracks in far-away terrain.
- Fixed see-through gaps between the terrain and the map's edge walls.
- New **Max trees** slider for better frame rates on slower PCs.
- Type exact values next to every slider.
- Notice after installing: the first game start after a new map usually crashes; just start it again.
- The 3D preview no longer gets stuck loading on slow or no internet.

## v1.0.0
- First release.

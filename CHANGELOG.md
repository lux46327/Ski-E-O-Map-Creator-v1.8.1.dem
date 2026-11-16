# Changelog

Maps made with an older version show **Rebuild recommended** in My Maps: one click on Rebuild gives them the fixes.

## v1.8.1.dem
Based on the original 1.8.1.
### Recently changed
- **Lock area.** After the terrain is loaded, a "Lock area" switch in the area card pins the square: it can no longer be dragged,
  resized or turned (map, handles, sliders and number boxes) until you unlock it. Searching for a place or pressing Show on a saved map unlocks it to move the square, and it locks again once the terrain of the new spot is loaded.
- **3D view: overlays.** Four overlays (Buildability, Slope difficulty, Trails & lifts, Trees) can be switched on in any combination, on top of each other and of the Terrain or
  Topo map surface:
  - **Buildability**, the game's own overlay: red where the ground is steeper than 22° ("Too steep"), buildable ground left
    unpainted.
  - **Slope difficulty** in the game's four tiers (Beginner under 16°, Intermediate 16–27°, Expert 27–33°, Extreme over
    33°), in the game's four Trail rating styles (North American, Alpine, French & Nordic, Japanese) with the game's own colours (double
    black as white). The
    default is Automatic, the style of the map's region (Japan, the French and Nordic countries, North America, else Alpine),
    as in the game. The slope limits are the same in all four styles, as in the game. With a legend.
  - **Trails & lifts**, the real trails and lifts from OpenStreetMap drawn on the terrain as on the map (difficulty colours,
    lifts dashed). They use the ones already loaded, else they are downloaded (and cached).
  - **Trees**, a simplified map of the tree species of the biome (from the same model as the real forest), with the share of
    each species. It follows the treeline, valley, tree slope, height modifier and offset settings. If the map's real tree cover is
    already downloaded (the cache), its values set how dense the species are drawn (sparse where there are few real trees,
    open where there are none). The treeline fade is shown in turquoise behind the species, stronger towards the treeline.
    Nothing is downloaded for the overlay.
  They follow the height modifier and offset while the 3D view is open.
- **Leave out real lifts and trails on the map.** Click a lift or a trail on the 2D map to leave it out of the build (it is
  shown at 10% opacity) and click again to take it back. The lists under "The lifts in the game" and the new "The trails in
  the game" follow the clicks, and the other way round. What is left out is removed from the 3D view's Trails & lifts overlay
  and from the map that is built. **Tick all / Untick all** buttons above each list do all lifts or all trails at once. It is saved with the map, so Show restores it.
- **Show** on a saved map in My Maps loads everything the map was built with: position, size, rotation, name, biome,
  treeline, snow, valley, slope, treeline fade, tree count, height modifier and offset, and real trails and lifts and
  real tree cover when the map used them. It uses the cached elevation and tree cover, and the trails and lifts saved
  with the map, instead of downloading them again.

### What's new
- **Rotate the area** with a slider or a turn handle on the map.
- **Sharper terrain** from national elevation surveys in many countries, stitched across borders, with AWS Terrain Tiles as fill.
- **Height modifier and height offset** for reshaping the terrain.
- **Real tree cover** support for terrains without lifts,: trees grow where the satellite data says they do.
- **Replace Map**: build a map under an existing name to rebuild it with new settings (the name field warns first).
- **More reliable trails and lifts download** (one request, regional servers first), also for rotated areas.
- Footer with all elevation sources and licences.
- No update check in this build.

## v1.8.1
- **Wooded summits, no dead patches.** Dead trees came a whole stand at a time, and near the summits whole stands were
  krummholz (low, wind-bent shrubs, many of them dead ones), so the tops looked bare. Now dead trees stand one by one
  among the living, as often as on the game's own maps, and near the tops krummholz grows between full-size conifers,
  only living ones. No more dying trees.
- Maps show **Rebuild recommended**: rebuild them for the new forests.

## v1.8.0
- **Forests like the game's own.** Trees grow in stands, their species mixed the way the game's own maps of the
  region have them (learned from those maps): in the Northeast mostly spruce and fir with birch, and maple and oak on
  the lower slopes; in the Alps spruce with birch, pine and larch; and so on for every region. Broadleaf trees stay off
  the summits: up there, to the treeline, it's conifers.
- **No more lag with the trees hidden.** Hiding the trees (the toggle on the right) made custom maps stutter: the game
  then goes over every group of trees each frame, and custom maps had far more groups than the game's own. Forests in
  stands have fewer than the game's own maps (Stratton: 117,000 before, 29,000 now).
- **Real trails at their real width.** With **Real trails and lifts**, each run is as wide as its cut through the
  forest in the satellite tree heights, so cat tracks are narrow and the big runs wide (they were all 26 to 40 m), and
  the forest is cleared along the real cut. Runs in the open keep their usual width. Resorts you already started keep
  their trails: start a New Game on the rebuilt map to get the new ones.
- **Mod Library: ready for other modders' mods.** Mods by other modders can be added to the Mod Library (checked and
  packaged by Oof, credited to their author). The build menus and snow caps of all installed mods are merged, so the
  buildings of several packs all show up, and a game update's new buildings stay in. The UE4SS the Map Creator
  installs now comes with UE4SS's standard Lua libraries and Blueprint mod loader and its usual settings, and it is
  never removed while other mods use it. Modders: see [docs/MODDING.md](docs/MODDING.md).
- **Oof's Anarchy** and **Oof's Speed Control** hide their badge and buttons under the pause menu, the map, and the
  settings and save screens.
- **Oof's Simple Cheat Menu:** "no tired staff" works in every resort (it changed settings the game had replaced with
  a new game's own).
- Map packages can't replace other mods' files or hold anything but a map. The Map Creator no longer reads the game's
  186 MB exe every few seconds while the game runs, and cleans up work folders it had to leave in the game folder.
- Maps show **Rebuild recommended**: rebuild them for the new forests (and, with Real trails and lifts, the new trail
  widths).

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

# Mods for the Mod Library

The Map Creator's Mod Library installs and removes mods for players with one click. It only lists mods that ship
inside the app: other modders send their finished mod to Oof, who checks and packages it (below) and puts it in a
release. Players can't add mods to it themselves, and map packages (the Maps tab) can only hold maps.

## Making a mod that fits

**Lua mods (UE4SS)**

- One folder, `<YourMod>/Scripts/main.lua`, with scripts and text files only (`.lua`, `.txt`, `.json`, `.ini`, `.cfg`,
  `.md`): no `.dll`, `.exe` or other programs, and no UE4SS C++ mods (`dlls/`).
- When the mod is updated, its scripts are replaced, but data files it changed in the game (its settings) are kept.
  Uninstalling it removes its folder.
- The Map Creator installs UE4SS (3.0.1 beta, git 83330635) if the player doesn't have it. That UE4SS includes the
  `shared` Lua libraries (`require("UEHelpers")`) and the Blueprint mod loader, and runs with the stock hooks on, so
  `RegisterHook`, `RegisterBeginPlayPostHook`, `NotifyOnNewObject` and the rest are all available. A UE4SS the player
  installed themselves is used as it is.
- Taken (refused): the folder names `OofsCheatMenu`, `OofsAnarchy`, `OofsSpeed`, `OofsSkiPatrolHQ` and `SkiWeather`,
  and UE4SS's own (`shared`, `BPModLoaderMod`, `BPML_GenericFunctions`, `Keybinds`, `ConsoleCommandsMod`,
  `ConsoleEnablerMod`, `CheatManagerEnablerMod`, `LineTraceMod`, `SplitScreenMod`), in any letter case.
- Used by the app's own mods, so best avoided (flagged when packaging): globals starting with `OOF_`, and the keys
  **F6** (cheat menu), **Ctrl+A** (Anarchy) and **Insert** (UE4SS reloads Blueprint mods). A mod's own key for the
  Mod Library can't be one of those.

**Pak mods**

- IoStore files: `.pak`, `.ucas` and `.utoc`, cooked for the game's engine, UE 5.8 (retoc's `UE5_7` container version
  works), one copy of each. Everything goes in the IoStore container: a `.pak` that holds files of its own (older,
  non-IoStore packaging) is refused, since the check can't see into it.
- **Blueprint mods** (a `ModActor` loaded by UE4SS's Blueprint mod loader) go in a folder named `LogicMods`. Their actor
  must be at `/Game/Mods/<pak name>/ModActor`; a `config.lua` for another path isn't supported.
- Any pak name except the game's and the Map Creator's own, in any letter case: `global`, `SkiResortSimulator-*`,
  `ZZZ_DoppelmayrR2Six_P`, `ZZZ_DoppelmayrR2Gondola_P`, `ZZZ_AlpineBuildings_P`, `ZZZ_SkiPatrolHQ_P`, `ZZZ_LiftMod_P`,
  `ZZZ_LiftStock_9_P`, `ZZZ_Registry_P` and `ZZZ_MC_*` (custom maps). A number of 9 or more before `_P` (e.g.
  `MyMod_9_P`) loads after the Map Creator's merged build menu and snow caps, and is refused.
- **New buildings and lifts:** add them the usual way. Copy the game's `/Game/Data/DT_BuildingEconomy` with your rows
  added, and add your buildings to `/Game/Data/SnowCaps/DA_SnowCapRegistry` if they have snow caps. When the mod is
  packaged, the Map Creator merges your rows and snow caps with the game's current ones and with every other installed
  mod's, so all of them show up together (IoStore mods players put in `~mods` by hand keep theirs too). It remakes the merged
  build menu when it runs after a game update, so the update's new buildings show up from then on.
- Limits of that merge: your copies of the game's own rows give way to the current game's, so a mod can't change the
  game's own buildings (their prices, for example) this way, and a row the game later removes comes back from your
  copy. A game update that changes the building table's format needs the mod packaged again, like the Map Creator's own
  packs.
- Don't replace `/Game/Data/DA_LevelRegistry`, the map list: custom maps go in through the Maps tab as map packages.
  Replacing other game assets is fine when that's the point of the mod: say so when you send it.
- The R2 lift packs replace the game's generic lift snow caps (`SM_SnowCap_BP_Lift_Start` and `_End`), so lift mods
  that rely on those have no snow on their stations while an R2 pack is installed.
- The Map Creator patches one instruction of the game's exe (the tree limit). Don't patch the exe.

**Send Oof:** the mod's files (a zip), its name, one or two sentences for the Mod Library, the key players press (if
any), and your OK to ship it in the Map Creator.

## Packaging a mod (Oof)

1. Check it against the game and the mods already in the library (the game must be installed; nothing is written):

   ```
   python packaging/package_mod.py TheirMod.zip --id their_mod --name "Their Mod" --author "Their Name" --about "What it does."
   ```

   Add `--logic` for a Blueprint mod whose paks aren't in a `LogicMods` folder. It reports **problems**, which stop
   it: a taken pak or folder name, a taken key (`--key`), a late-loading pak number, a `.pak` holding files of its own,
   the map list, assets another library mod has, files that aren't scripts or text in a Lua mod, a Blueprint mod
   without its `ModActor`, a file twice, more than one Lua mod, or mixed Blueprint and normal paks. It also reports
   **notes**: key clashes, `OOF_` globals, game assets the mod replaces, its whole build table renamed to
   `DT_BuildingMod_<n>`, and its snow caps.
2. **It is not a security review.** A Lua mod runs with the player's full rights. Each use of the `os`, `io`, `debug`
   and `package` libraries, code loaded from strings or files, globals reached by name, and console commands is a
   `READ BEFORE APPROVING` note with the file and line. Those are hints: read all of the scripts before approving, and
   only package mods from people you trust.
3. Sort out the problems with the modder, then run it again with `--write`. That copies the Lua mod into
   `data/mods/<folder>` and the paks (and the renamed build table) into `data/lifts/<id>.zip`, refuses to write over
   anything already there, and prints the mod's entry. Paste the entry into `MODS` in `skieo_creator/modlib.py`.
4. Test it from source (`python run.py`, see [DEVELOPMENT.md](DEVELOPMENT.md)): install it in the Mod Library, start
   the game, and check that its buildings show up in the build menu next to the game's and the other mods', and that
   its key works.
5. Release a new version.

How the app installs mods and merges the build menu and snow caps: `skieo_creator/modlib.py`,
`skieo_creator/modscan.py` and `skieo_creator/engine/shared_assets.py`.

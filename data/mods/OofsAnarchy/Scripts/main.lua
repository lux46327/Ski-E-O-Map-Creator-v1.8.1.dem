-- Oof's Anarchy for Ski-E-O! Ski Resort Tycoon (UE4SS Lua mod). Ctrl+A switches it on and off.
-- While it is on, the building or lift you place or move skips the game's placement checks: slope, ground type, trees
-- and rocks in the way, other buildings. Switched off, the game's own checks are back. A badge under the top bar shows
-- while it is on; it is off whenever the game starts.
-- The checks are each placeable's PlacementValidationComponent settings; the actors being placed are in the
-- PlacementManagerComponent, the ones being moved in the MovePlaceableComponent. Everything runs on the game thread.
local TAG = "[OofsAnarchy] "
local M = rawget(_G, "OOF_ANARCHY") or {}       -- the same table if this file runs again: no second loops
_G.OOF_ANARCHY = M

local function log(s) print(TAG .. s .. "\n") end
local function guarded(name, fn)
  return function(...)
    local ok, err = pcall(fn, ...)
    if not ok then log(name .. ": " .. tostring(err)) end
  end
end
local function valid(o) return o ~= nil and o:IsValid() end
local function find(name)                        -- FindFirstOf walks every object: callers keep what it finds
  local o = FindFirstOf(name)
  if valid(o) then return o end
end

------------------------------------------------------------------------------------------------- placement checks
local RELAXED = { MaxSlopeAngle = 89.0, ConformingMaxSlopeAngle = 89.0, AllowedSurfaceTypes = 0x7FFFFFFF,
                  bCheckObstacles = false, bCheckOtherPlaceables = false }
M.on = M.on or false
local relaxed = {}                               -- component -> the game's own values, to put back when off
local pm, mv, searchIn = nil, nil, 0

local function relax(actor)
  if not valid(actor) then return end
  local ok, v = pcall(function() return actor.ValidationComponent end)
  if not (ok and valid(v)) then return end
  local key = v:GetFullName()
  if not relaxed[key] then
    local o, already = {}, true
    for k, want in pairs(RELAXED) do
      o[k] = v[k]
      if o[k] ~= want then already = false end
    end
    if already then return end                   -- the cheat menu's "build anywhere": it puts them back; look again later
    relaxed[key] = { comp = v, values = o }
  end
  for k, want in pairs(RELAXED) do if v[k] ~= want then v[k] = want end end
end

local function restore()
  for key, e in pairs(relaxed) do
    if valid(e.comp) then
      for k, val in pairs(e.values) do pcall(function() e.comp[k] = val end) end
    end
    relaxed[key] = nil
  end
end

local function tick()
  if not M.on then
    if next(relaxed) then restore() end
    return
  end
  if not (valid(pm) and valid(mv)) then
    searchIn = searchIn - 1
    if searchIn <= 0 then
      searchIn = 30                              -- ticks run every other frame: about once a second
      if not valid(pm) then pm = find("PlacementManagerComponent") end
      if not valid(mv) then mv = find("MovePlaceableComponent") end
    end
  end
  if valid(pm) then
    relax(pm.BuildingPreviewActor)
    relax(pm.LiftPreviewActor)
  end
  if valid(mv) then
    relax(mv.HeldActor)
    relax(mv.HeldLift)
  end
  for key, e in pairs(relaxed) do if not valid(e.comp) then relaxed[key] = nil end end
end

------------------------------------------------------------------------------------------------------------ badge
local C = { panel = { R = 0.006, G = 0.012, B = 0.022, A = 0.90 }, amber = { R = 0.95, G = 0.55, B = 0.05, A = 1 },
            dim = { R = 0.45, G = 0.50, B = 0.56, A = 1 } }
local P = M.P or {}
M.P = P
local tree
local function new(cn) return StaticConstructObject(StaticFindObject("/Script/UMG." .. cn), tree) end
local function text(s, size, color, bold)
  local t = new("TextBlock")
  t:SetText(FText(s))
  local f = t.Font                                -- edit the default font in place: a partial struct table crashes
  f.Size = size
  f.TypefaceFontName = FName(bold and "Bold" or "Regular")
  t:SetFont(f)
  t:SetColorAndOpacity({ SpecifiedColor = color, ColorUseRule = 0 })
  return t
end

local function build(pc)
  if valid(P.widget) then pcall(function() P.widget:RemoveFromParent() end) end
  local w = StaticFindObject("/Script/UMG.Default__WidgetBlueprintLibrary"):Create(pc,
    StaticFindObject("/Script/SkiResortSimulator.CardPlaneWidget"), pc)
  tree = w.WidgetTree
  local canvas = new("CanvasPanel")
  tree.RootWidget = canvas
  local border = new("Border")
  border:SetBrushColor(C.panel)
  border:SetPadding({ Left = 12, Top = 5, Right = 12, Bottom = 6 })
  local cs = canvas:AddChildToCanvas(border)
  cs:SetAnchors({ Minimum = { X = 0.5, Y = 0 }, Maximum = { X = 0.5, Y = 0 } })  -- top centre, under the top bar
  cs:SetAlignment({ X = 0.5, Y = 0 })
  cs:SetPosition({ X = 0, Y = 76 })
  cs:SetAutoSize(true)
  local row = new("HorizontalBox")
  border:SetContent(row)
  row:AddChildToHorizontalBox(text("ANARCHY ON", 11, C.amber, true)):SetVerticalAlignment(2)
  local hint = row:AddChildToHorizontalBox(text("Ctrl+A switches it off", 9, C.dim, false))
  hint:SetPadding({ Left = 10, Top = 0, Right = 0, Bottom = 0 })
  hint:SetVerticalAlignment(2)
  w:SetVisibility(1)                              -- collapsed until shown
  w:AddToViewport(900)
  P.widget, P.shown = w, false
end

-- the game's top bar is on screen: not in menus or loading screens, and no game screen over it (the top bar stays
-- "visible" under the pause menu)
local ui
local SCREENS = { "PauseMenuWidget", "MapViewWidget", "SettingsMenuWidget", "SaveLoadMenuWidget", "PhotoModeWidget" }
local function hudShown()
  local bar = valid(ui) and ui.TopStatusBarWidget or nil
  if not (valid(bar) and bar:IsVisible() and (bar:IsInViewport() or valid(bar:GetParent()))) then return false end
  for _, n in ipairs(SCREENS) do
    local w = ui[n]
    if valid(w) and w:IsVisible() then return false end
  end
  return true
end

------------------------------------------------------------------------------------------------------------ loops
local slow = 0
function M.background()                           -- 4 times a second, and at once on Ctrl+A
  slow = slow + 1
  if not valid(ui) and slow % 4 == 1 then ui = find("UIManagerComponent") end
  local show = M.on and hudShown()
  if show and not (valid(P.widget) and P.widget:IsInViewport()) then
    local pc = find("PlayerController")
    if pc then build(pc) end
  end
  if valid(P.widget) and show ~= P.shown then
    P.widget:SetVisibility(show and 3 or 1)       -- 3: on screen but never in the way of a click
    P.shown = show
  end
end

local pc, pcIn, frame = nil, 0, 0
local KEY_A = { KeyName = FName("A") }
local CTRL_L, CTRL_R = { KeyName = FName("LeftControl") }, { KeyName = FName("RightControl") }
function M.input()                                -- every frame: "just pressed" lasts one frame
  frame = frame + 1
  if not valid(pc) then
    if frame < pcIn then return end
    pcIn = frame + 30
    pc = find("PlayerController")
    if not pc then return end
  end
  if pc:WasInputKeyJustPressed(KEY_A) and (pc:IsInputKeyDown(CTRL_L) or pc:IsInputKeyDown(CTRL_R)) then
    M.on = not M.on
    log(M.on and "on" or "off")
    M.background()
  end
  if frame % 2 == 0 then tick() end
end

if not M.started then
  M.started = true
  LoopInGameThreadAfterFrames(1, guarded("input", function() M.input() end))
  LoopInGameThreadAfterFrames(15, guarded("background", function() M.background() end))
  log("loaded - Ctrl+A switches anarchy on and off")
end

return M

-- Oof's Speed Control for Ski-E-O! Ski Resort Tycoon (UE4SS Lua mod).
-- Speed buttons from 1x to 100x under the game's own speed buttons (top right): click one to run the game at that
-- speed, click the lit one again to go back to 1x. Speeds past the game's own 10x lift the world's time-dilation cap.
-- The buttons show only while the game shows its top bar. They go through the game's own TimeSubsystem, on the game
-- thread, and are polled (UE4SS Lua can't bind UMG delegates).
local TAG = "[OofsSpeed] "
local M = rawget(_G, "OOF_SPEED") or {}          -- the same table if this file runs again: no second loops
_G.OOF_SPEED = M

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

------------------------------------------------------------------------------------------------------------ speed
local SPEEDS = { 1, 2, 3, 5, 10, 25, 50, 100 }
local ts, ui
local function setSpeed(rate)
  if not valid(ts) then return end
  if rate > 10 then                              -- the game's own buttons stop at 10x; the world caps time dilation
    for _, w in ipairs(FindAllOf("WorldSettings") or {}) do pcall(function() w.MaxGlobalTimeDilation = 1000 end) end
  end
  ts:ResumeTime()
  ts:SetTimeRate(rate)
end
local function current()                         -- the speed now, 0 while paused
  if not valid(ts) then return nil end
  if ts:IsTimePaused() then return 0 end
  return ts:GetTimeRate()
end
local function same(a, b) return a ~= nil and math.abs(a - b) < 0.01 end
local function click(v)
  if v ~= 1 and same(current(), v) then setSpeed(1) else setSpeed(v) end    -- the lit one again: back to 1x
end

---------------------------------------------------------------------------------------------------------- buttons
local C = {
  panel = { R = 0.006, G = 0.012, B = 0.022, A = 0.90 }, text = { R = 0.86, G = 0.89, B = 0.93, A = 1 },
  btn = { R = 0.09, G = 0.12, B = 0.16, A = 1 }, fast = { R = 0.55, G = 0.33, B = 0.03, A = 1 },
  lit = { R = 0.05, G = 0.22, B = 0.50, A = 1 },
}
local P = M.P or { buttons = {} }
M.P = P
local tree
local function new(cn) return StaticConstructObject(StaticFindObject("/Script/UMG." .. cn), tree) end
local function text(s, size, color)
  local t = new("TextBlock")
  t:SetText(FText(s))
  local f = t.Font                                -- edit the default font in place: a partial struct table crashes
  f.Size = size
  f.TypefaceFontName = FName("Bold")
  t:SetFont(f)
  t:SetColorAndOpacity({ SpecifiedColor = color, ColorUseRule = 0 })
  return t
end

local function build(pc)
  if valid(P.widget) then pcall(function() P.widget:RemoveFromParent() end) end
  P.buttons = {}
  local w = StaticFindObject("/Script/UMG.Default__WidgetBlueprintLibrary"):Create(pc,
    StaticFindObject("/Script/SkiResortSimulator.CardPlaneWidget"), pc)
  tree = w.WidgetTree
  local canvas = new("CanvasPanel")
  canvas:SetVisibility(4)                         -- self hit-test invisible: the rest of the screen stays clickable
  tree.RootWidget = canvas
  local border = new("Border")
  border:SetBrushColor(C.panel)
  border:SetPadding({ Left = 4, Top = 4, Right = 4, Bottom = 4 })
  local cs = canvas:AddChildToCanvas(border)
  cs:SetAnchors({ Minimum = { X = 1, Y = 0 }, Maximum = { X = 1, Y = 0 } })      -- top right, under the game's own
  cs:SetAlignment({ X = 1, Y = 0 })
  cs:SetPosition({ X = -57, Y = 76 })
  cs:SetAutoSize(true)
  local row = new("HorizontalBox")
  border:SetContent(row)
  for _, v in ipairs(SPEEDS) do
    local b = new("Button")
    local t = text(v .. "x", 9, C.text)
    t:SetJustification(1)
    b:SetContent(t)
    local size = new("SizeBox")
    size:SetWidthOverride(44)
    size:SetContent(b)
    row:AddChildToHorizontalBox(size):SetPadding({ Left = 2, Top = 0, Right = 2, Bottom = 0 })
    P.buttons[#P.buttons + 1] = { w = b, v = v, was = false, lit = nil }
  end
  w:SetVisibility(1)                              -- collapsed until the game shows its top bar
  w:AddToViewport(900)
  P.widget, P.shown = w, false
end

local function paint()                            -- light the button of the speed now
  local cur = current()
  for _, b in ipairs(P.buttons) do
    local lit = same(cur, b.v)
    if lit ~= b.lit and valid(b.w) then
      b.lit = lit
      b.w:SetBackgroundColor(lit and C.lit or (b.v > 10 and C.fast or C.btn))
    end
  end
end

local function poll()                             -- a click: pressed, then released over the button
  for _, b in ipairs(P.buttons) do
    if valid(b.w) then
      local p = b.w:IsPressed()
      if b.was and not p and b.w:IsHovered() then
        local ok, err = pcall(click, b.v)
        if not ok then log(tostring(err)) end
        paint()
      end
      b.was = p
    end
  end
end

-- the game's top bar is on screen: not in menus, loading screens or photo mode
local function hudShown()
  local bar = valid(ui) and ui.TopStatusBarWidget or nil
  return valid(bar) and bar:IsVisible() and (bar:IsInViewport() or valid(bar:GetParent()))
end

------------------------------------------------------------------------------------------------------------ loops
local frame = 0
function M.input()                                -- every other frame is plenty: a click lasts ~0.1 s
  frame = frame + 1
  if frame % 2 == 0 and P.shown and valid(P.widget) then poll() end
end

local slow = 0
function M.background()                           -- 4 times a second
  slow = slow + 1
  if slow % 4 == 1 then                           -- FindFirstOf walks every object: at most once a second
    if not valid(ts) then ts = find("TimeSubsystem") end
    if not valid(ui) then ui = find("UIManagerComponent") end
  end
  local show = valid(ts) and hudShown()
  if show and not (valid(P.widget) and P.widget:IsInViewport()) then
    local pc = find("PlayerController")
    if pc then build(pc) end
  end
  if valid(P.widget) then
    if show ~= P.shown then
      P.widget:SetVisibility(show and 4 or 1)     -- 4: the buttons take clicks, the space round them doesn't
      P.shown = show
    end
    if show then paint() end
  end
end

if not M.started then
  M.started = true
  LoopInGameThreadAfterFrames(1, guarded("input", function() M.input() end))
  LoopInGameThreadAfterFrames(15, guarded("background", function() M.background() end))
  log("loaded - speed buttons under the game's own")
end

return M

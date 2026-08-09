// Tauri overlay control: positions the window on the vertical (portrait)
// secondary monitor and manages click-through. All Tauri calls are guarded so
// the HUD still renders under a plain `npm run dev` browser (no Tauri runtime).
//
// Click-through model (per spec): passthrough while dormant; interactive when
// summoned (so agent nodes are clickable); a global hotkey toggles on demand.
// The current interactive state is reflected back to the backend via the bridge.

import { getCurrentWindow, availableMonitors, primaryMonitor } from "@tauri-apps/api/window";
import { PhysicalPosition, PhysicalSize } from "@tauri-apps/api/dpi";
import { register } from "@tauri-apps/plugin-global-shortcut";
import { sendCommand } from "./ws.js";

const TOGGLE_HOTKEY = "CommandOrControl+Alt+O";
const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

let interactive = false;

async function placeOnPortraitMonitor() {
  const win = getCurrentWindow();
  const monitors = await availableMonitors();
  const primary = await primaryMonitor();
  // Prefer a portrait monitor; prefer one that isn't the primary.
  const portrait = monitors.filter((m) => m.size.height > m.size.width);
  const target =
    portrait.find((m) => !primary || m.position.x !== primary.position.x || m.position.y !== primary.position.y) ||
    portrait[0] ||
    primary ||
    monitors[0];
  if (!target) return;
  await win.setPosition(new PhysicalPosition(target.position.x, target.position.y));
  await win.setSize(new PhysicalSize(target.size.width, target.size.height));
}

async function applyInteractive(next) {
  interactive = next;
  if (isTauri()) {
    try {
      await getCurrentWindow().setIgnoreCursorEvents(!next);
    } catch {
      /* window API unavailable */
    }
  }
  sendCommand("set_interactive", next);
}

/** Called by the HUD when the composition changes (summoned <-> dormant). */
export function setOverlayInteractive(summoned) {
  applyInteractive(summoned);
}

export async function initOverlay() {
  if (!isTauri()) return; // browser dev: visuals only, no window control
  try {
    await placeOnPortraitMonitor();
    await applyInteractive(false); // start dormant => passthrough
    await register(TOGGLE_HOTKEY, (e) => {
      if (e.state === "Pressed") applyInteractive(!interactive);
    });
  } catch (err) {
    console.error("overlay init failed:", err);
  }
}

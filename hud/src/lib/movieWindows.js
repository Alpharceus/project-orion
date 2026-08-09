// Multi-monitor blackout for movie mode. The main HUD window owns this: when
// movie mode is on it opens one fullscreen black window per TARGET monitor
// (default: every monitor except the main/primary one) so those screens stop
// throwing light while you watch something on the main monitor. Each blackout
// window loads the app with ?blackout=1 and renders only the animation; it gets
// the active animation from its own WebSocket connection, so "animation 3"
// updates every screen at once.
//
// The HUD's OWN monitor is handled by the in-HUD MovieMode canvas (so the HUD
// stays above it); `selfBlackout` tells that canvas whether its monitor is a
// target. Only the main window runs this — blackout windows never do.

import { WebviewWindow } from "@tauri-apps/api/webviewWindow";
import { availableMonitors, primaryMonitor, currentMonitor } from "@tauri-apps/api/window";
import { PhysicalPosition, PhysicalSize } from "@tauri-apps/api/dpi";
import { writable } from "svelte/store";

const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

// Should the HUD's own monitor be blacked out (i.e. is it a target)?
export const selfBlackout = writable(false);

const wins = new Map(); // label -> WebviewWindow
let busy = false;
let pending = null;

const keyOf = (m) => `${m.position.x}_${m.position.y}`;
const samePos = (a, b) => a.position.x === b.position.x && a.position.y === b.position.y;

async function computeTargets(screens) {
  const monitors = await availableMonitors();
  if (screens === "all") return monitors.slice();
  const primary = await primaryMonitor();
  return monitors.filter((m) => !primary || !samePos(m, primary)); // all except main
}

async function createBlackout(m) {
  const label = `blackout-${keyOf(m)}`;
  if (wins.has(label)) return;
  const w = new WebviewWindow(label, {
    url: "/?blackout=1",
    transparent: false,    // opaque: a true blackout
    decorations: false,
    alwaysOnTop: true,
    skipTaskbar: true,
    shadow: false,
    focus: false,          // don't steal focus from the movie on the main screen
    resizable: false,
    title: "Orion Movie Mode",
  });
  wins.set(label, w);
  w.once("tauri://created", async () => {
    try {
      await w.setPosition(new PhysicalPosition(m.position.x, m.position.y));
      await w.setSize(new PhysicalSize(m.size.width, m.size.height));
      await w.setIgnoreCursorEvents(true); // click-through; it's just ambiance
      await w.setAlwaysOnTop(true);
    } catch (e) {
      console.error("[movie] blackout placement failed:", e);
    }
  });
  w.once("tauri://error", (e) => {
    console.error("[movie] blackout window error:", e);
    wins.delete(label);
  });
}

async function closeAll() {
  for (const [label, w] of [...wins]) {
    try { await w.close(); } catch { /* already gone */ }
    wins.delete(label);
  }
}

async function run({ on, screens }) {
  if (!on) {
    selfBlackout.set(false);
    await closeAll();
    return;
  }
  const targets = await computeTargets(screens);
  let self = null;
  try { self = await currentMonitor(); } catch { /* no current monitor */ }
  selfBlackout.set(!!self && targets.some((t) => samePos(t, self)));

  // Desired blackout windows = targets other than the HUD's own monitor.
  const desired = new Map();
  for (const t of targets) {
    if (self && samePos(t, self)) continue;
    desired.set(`blackout-${keyOf(t)}`, t);
  }
  // Close any that are no longer targets.
  for (const [label, w] of [...wins]) {
    if (!desired.has(label)) {
      try { await w.close(); } catch { /* ignore */ }
      wins.delete(label);
    }
  }
  // Open any missing.
  for (const [label, m] of desired) {
    if (!wins.has(label)) await createBlackout(m);
  }
}

/** Reconcile the blackout windows to the current movie state. Coalesces bursts. */
export function syncMovie(spec) {
  if (!isTauri()) return; // browser dev: only the in-page canvas matters
  pending = { on: !!spec.on, screens: spec.screens || "others" };
  if (busy) return;
  busy = true;
  (async () => {
    try {
      while (pending) {
        const next = pending;
        pending = null;
        await run(next);
      }
    } finally {
      busy = false;
    }
  })();
}

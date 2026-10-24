// WebSocket client for the Orion HUD: connects to the Phase 4 bridge
// (ws://127.0.0.1:8765), auto-reconnects with backoff, and fans incoming
// events into Svelte stores. The bridge sends a snapshot (current state + active
// agents) on connect, so the HUD renders correctly even if it starts mid-session.
//
// Transport: inside Tauri we use the Rust-side WebSocket plugin, because WebView2
// blocks the webview from opening ws://127.0.0.1 (private-network access). In a
// plain browser (npm run dev without Tauri) we fall back to the native WebSocket.

import { writable } from "svelte/store";

const URL = "ws://127.0.0.1:8765";
const isTauri = () => typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

export const connState = writable("connecting"); // connecting | live | down
export const orionState = writable("idle");       // idle | listening | thinking | speaking
export const amplitude = writable(0);             // 0..1 live TTS envelope
export const agents = writable({});               // id -> { status, meta, progress }
export const transcript = writable([]);           // [{ role, text }]
export const telemetry = writable({});            // { weather, cpu, gpu_gb, gpu_pct, ram }
export const ticker = writable([]);               // [title, ...]
export const remindersList = writable([]);        // [{ text, when }]
export const tasksList = writable([]);            // [{ title, priority, due }]
export const persona = writable("orion");         // orion | ultron (drives the HUD palette)
export const movie = writable({ on: false, index: 0, screens: "others" }); // movie-mode animation

let latestAmp = 0;
export const getAmplitude = () => latestAmp;

const MAX_TRANSCRIPT = 8;
let conn = null;       // plugin connection or native WebSocket
let backoff = 500;

function handle(msg) {
  switch (msg.type) {
    case "state": orionState.set(msg.value); break;
    case "amplitude": latestAmp = msg.value; amplitude.set(msg.value); break;
    case "agent":
      // Keep every agent as a persistent node; status sets its appearance.
      agents.update((a) => ({ ...a, [msg.id]: { status: msg.status, meta: msg.meta, progress: msg.progress } }));
      break;
    case "transcript":
      transcript.update((t) => [...t, { role: msg.role, text: msg.text }].slice(-MAX_TRANSCRIPT));
      break;
    case "telemetry": telemetry.set(msg); break;
    case "ticker": ticker.set(msg.titles || []); break;
    case "reminders_list": remindersList.set(msg.items || []); break;
    case "tasks_list": tasksList.set(msg.items || []); break;
    case "persona": persona.set(msg.name || "orion"); break;
    case "movie": movie.set({ on: !!msg.on, index: msg.index || 0, name: msg.name, screens: msg.screens || "others" }); break;
  }
}

function onText(text) {
  try { handle(JSON.parse(text)); } catch { /* ignore malformed frame */ }
}

function scheduleReconnect() {
  conn = null;
  setTimeout(connect, backoff);
  backoff = Math.min(backoff * 1.6, 5000);
}

async function connect() {
  connState.set("connecting");
  if (isTauri()) {
    try {
      const WS = (await import("@tauri-apps/plugin-websocket")).default;
      const socket = await WS.connect(URL);
      conn = socket;
      backoff = 500;
      connState.set("live");
      socket.addListener((msg) => {
        if (msg.type === "Text") onText(msg.data);
        else if (msg.type === "Close") { connState.set("down"); scheduleReconnect(); }
      });
    } catch {
      connState.set("down");
      scheduleReconnect();
    }
  } else {
    try {
      conn = new WebSocket(URL);
    } catch {
      return scheduleReconnect();
    }
    conn.onopen = () => { backoff = 500; connState.set("live"); };
    conn.onmessage = (e) => onText(e.data);
    conn.onclose = () => { connState.set("down"); scheduleReconnect(); };
    conn.onerror = () => conn && conn.close();
  }
}

export function sendCommand(name, value) {
  if (!conn) return;
  const payload = JSON.stringify(value === undefined ? { type: "command", name } : { type: "command", name, value });
  if (isTauri()) conn.send(payload).catch(() => {});
  else if (conn.readyState === WebSocket.OPEN) conn.send(payload);
}

export function startWs() {
  connect();
}

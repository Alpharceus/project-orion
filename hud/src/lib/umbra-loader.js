// Loads the ported Project Umbra render engines and exposes window.createUmbraTheme.
//
// The engine files reference each other through shared global lexical bindings
// (UmbraRenderer, ThemeBase, EngineBase) that only exist when they run as CLASSIC
// scripts in one global scope — they are NOT ES modules. Rather than fetch them
// at runtime (fragile under the Tauri asset protocol), we import their source as
// raw strings (bundled into the app) and run them as ONE inline <script>, so all
// their top-level declarations share that script's global scope. No network, no
// load-order races, no path resolution.
//
// The animations are a see-through ambient overlay ("movie mode"); see
// src/lib/umbra/renderer.js for the transparent-clear adaptation.

import renderer from "./umbra/renderer.js?raw";
import noise from "./umbra/engines/noise.js?raw";
import themeBase from "./umbra/theme-base.js?raw";
import engineBase from "./umbra/engines/engine-base.js?raw";
import e1 from "./umbra/engines/e1-point-field.js?raw";
import e2 from "./umbra/engines/e2-noise-field.js?raw";
import e3 from "./umbra/engines/e3-falling-column.js?raw";
import e4 from "./umbra/engines/e4-procedural-grid.js?raw";
import e5 from "./umbra/engines/e5-banded-field.js?raw";
import e6 from "./umbra/engines/e6-edge-mask.js?raw";
import registry from "./umbra/registry.js?raw";

// Concatenation order matters: bases before the engines that extend them.
const SOURCES = [renderer, noise, themeBase, engineBase, e1, e2, e3, e4, e5, e6, registry];

// Ordered list of the 10 themes -> "animation 1..10" the user selects by number.
export const ANIMATIONS = [
  { id: "cosmic-drift", name: "Cosmic Drift" },
  { id: "dust-motes", name: "Dust Motes" },
  { id: "abyssal-fluid", name: "Abyssal Fluid" },
  { id: "volumetric-smoke", name: "Volumetric Smoke" },
  { id: "glacial-nebula", name: "Glacial Nebula" },
  { id: "macro-rain", name: "Macro Rain" },
  { id: "digital-rainfall", name: "Digital Rainfall" },
  { id: "the-slow-matrix", name: "The Slow Matrix" },
  { id: "strata-shift", name: "Strata Shift" },
  { id: "solar-corona", name: "Solar Corona" },
];

let loaded = null;

/** Run the engine source once; returns window.createUmbraTheme. */
export function loadUmbra() {
  if (loaded) return loaded;
  loaded = new Promise((resolve, reject) => {
    try {
      if (typeof window.createUmbraTheme !== "function") {
        const el = document.createElement("script");
        el.textContent = SOURCES.join("\n;\n");
        document.head.appendChild(el);
      }
      if (typeof window.createUmbraTheme !== "function") {
        throw new Error("umbra engines ran but createUmbraTheme is missing");
      }
      resolve(window.createUmbraTheme);
    } catch (e) {
      loaded = null;
      reject(e);
    }
  });
  return loaded;
}

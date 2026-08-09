<!-- Movie mode: a blackout screensaver (ported from Project Umbra). It fills the
     portrait monitor with solid black and runs a slow ambient animation on top,
     so the screen stops throwing light / distraction while you watch something on
     the main monitor. It sits BELOW the Orion HUD and idle core (z-index) with
     pointer-events:none, so when the HUD is active it stays above the blackout.

     Driven by the `movie` store ({ on, index }) which the backend sets via the
     movie_mode tool ("hey orion, movie mode", "animation 3", "change to 1"). -->
<script>
  import { onMount } from "svelte";
  import { movie } from "./ws.js";
  import { loadUmbra, ANIMATIONS } from "./umbra-loader.js";

  // `enabled` decides whether THIS monitor shows the blackout. The main HUD
  // window passes (movie.on && its monitor is a target); a spawned blackout
  // window passes movie.on. The animation index always comes from the store.
  let { enabled = false } = $props();

  let canvas;
  let ctx = null;
  let create = null;        // window.createUmbraTheme once loaded
  let theme = null;         // active engine instance
  let curIndex = -1;        // which animation is instantiated
  let raf = 0;
  let last = 0;             // ms timestamp of previous frame
  let visualTime = 0;       // seconds of animation time (motion-scaled)
  const FPS = 24;           // ambient + cheap; throttle the loop
  const FRAME_MS = 1000 / FPS;
  const STATE = { density_scale: 1, contrast_scale: 1 }; // Umbra global controls

  const viewport = { width: 0, height: 0, aspect: 1, dpr: 1 };

  function resize() {
    if (!canvas) return;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const w = window.innerWidth, h = window.innerHeight;
    canvas.width = Math.round(w * dpr);
    canvas.height = Math.round(h * dpr);
    canvas.style.width = w + "px";
    canvas.style.height = h + "px";
    ctx?.setTransform(dpr, 0, 0, dpr, 0, 0);
    viewport.width = w;
    viewport.height = h;
    viewport.aspect = w / h;
    viewport.dpr = dpr;
  }

  function selectTheme(index) {
    if (!create) return;
    const anim = ANIMATIONS[index];
    if (!anim) return;
    theme?.destroy?.();
    theme = create(anim.id, { viewport, seed: 1337, state: STATE, params: {} });
    curIndex = index;
  }

  function frame(now) {
    raf = requestAnimationFrame(frame);
    if (now - last < FRAME_MS) return; // throttle to ~FPS
    const dt = last ? Math.min(0.1, (now - last) / 1000) : 0;
    last = now;
    visualTime += dt;
    if (!theme || !ctx) return;
    theme.update(visualTime, dt, STATE);
    ctx.clearRect(0, 0, viewport.width, viewport.height);
    theme.render(ctx, viewport, 1.0); // brightness 1.0 = no black dim veil
  }

  function startLoop() {
    if (!raf) { last = 0; raf = requestAnimationFrame(frame); }
  }
  function stopLoop() {
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
    if (ctx) ctx.clearRect(0, 0, viewport.width, viewport.height);
  }

  // React to enabled + animation index: load engines lazily on first enable.
  $effect(() => {
    const idx = $movie?.index ?? 0;
    if (!enabled) { stopLoop(); return; }
    if (!create) {
      loadUmbra()
        .then((fn) => { create = fn; selectTheme(idx); startLoop(); })
        .catch((e) => console.error("[movie] umbra load failed:", e));
      return;
    }
    if (idx !== curIndex) selectTheme(idx);
    startLoop();
  });

  onMount(() => {
    ctx = canvas.getContext("2d");
    resize();
    window.addEventListener("resize", resize);
    return () => { window.removeEventListener("resize", resize); stopLoop(); };
  });
</script>

<canvas bind:this={canvas} class="movie" class:on={enabled}></canvas>

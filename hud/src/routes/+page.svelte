<script>
  import { onMount } from "svelte";
  import { browser } from "$app/environment";
  import { orionState, connState, movie, persona, startWs } from "$lib/ws.js";
  import { initOverlay, setOverlayInteractive } from "$lib/overlay.js";
  import { syncMovie, selfBlackout } from "$lib/movieWindows.js";
  import MovieMode from "$lib/MovieMode.svelte";
  import Core from "$lib/Core.svelte";
  import Agents from "$lib/Agents.svelte";
  import Telemetry from "$lib/Telemetry.svelte";
  import Reminders from "$lib/Reminders.svelte";
  import Tasks from "$lib/Tasks.svelte";
  import Transcript from "$lib/Transcript.svelte";
  import Ticker from "$lib/Ticker.svelte";

  // Spawned blackout windows load this same page with ?blackout=1 — they render
  // ONLY the animation (no HUD, no overlay control), driven by their own ws feed.
  const isBlackout = browser && new URLSearchParams(window.location.search).has("blackout");

  const VERBS = { idle: "dormant", listening: "listening", thinking: "thinking", speaking: "speaking" };

  let summoned = $state(false);
  let waking = $state(false);
  let sweep = $state(0);
  let clock = $state("");

  let glow = $derived(summoned && $orionState === "listening");

  // Wake/dismiss orchestration driven by backend state transitions.
  let prev = "idle";
  $effect(() => {
    const s = $orionState;
    if (s !== "idle" && prev === "idle") {
      runWakeSweep(() => (summoned = true)); // edge sweep, then pull the HUD up
    } else if (s === "idle") {
      summoned = false;
      waking = false;
    }
    prev = s;
  });

  // Reflect composition to the overlay (passthrough when dormant, interactive when summoned).
  $effect(() => { if (!isBlackout) setOverlayInteractive(summoned); });

  // Main window only: open/close the per-monitor blackout windows as movie state changes.
  $effect(() => {
    if (isBlackout) return;
    syncMovie({ on: $movie?.on, screens: $movie?.screens || "others" });
  });

  function runWakeSweep(done) {
    waking = true;
    let s = 0;
    const spin = () => {
      s += 14;
      sweep = s;
      if (s < 360) requestAnimationFrame(spin);
      else { waking = false; done(); }
    };
    spin();
  }

  onMount(() => {
    startWs();
    if (isBlackout) return; // blackout windows: just the animation, no HUD/overlay
    initOverlay();
    const tick = () => {
      const d = new Date();
      clock = `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  });
</script>

{#if isBlackout}
  <!-- A spawned blackout window: fill its monitor black + run the animation. -->
  <div class="blackout"><MovieMode enabled={$movie?.on} /></div>
{:else}
<div class="hud-root" class:dormant={!summoned} class:summoned class:waking class:glow class:ultron={$persona === "ultron"} style="--sweep:{sweep}deg">
  <!-- Blackout for the HUD's OWN monitor: bottom layer, below the HUD + core orb.
       Only when this monitor is a target (selfBlackout). -->
  <MovieMode enabled={$movie?.on && $selfBlackout} />

  <div class="vignette"></div>
  <div class="edge"></div>
  <div class="frameglow"></div>

  <div class="corelayer"><Core state={$orionState} /></div>

  <div class="hud">
    <div class="topbar">
      <div class="brand">ORION</div>
      <div class="clock">{clock}</div>
    </div>
    <div class="status" class:active={summoned}>
      <span class="dot"></span><span>{VERBS[$orionState] ?? $orionState}</span>
      {#if $movie?.on}<span class="movie-tag">▦ {$movie.name ?? "movie"}</span>{/if}
      <span class="conn" class:live={$connState === "live"}>{$connState === "live" ? "linked" : "offline"}</span>
    </div>

    <Telemetry />

    <div class="panels">
      <Reminders />
      <Tasks />
    </div>

    <div class="spacer"></div>

    <Agents {summoned} />
    <Transcript />
    <Ticker />
  </div>
</div>
{/if}

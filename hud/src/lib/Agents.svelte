<!-- Agent nodes: a fixed, always-present row of the core tools (like the mockup
     hardcodes them) so they're guaranteed visible. The backend's `agent` events
     only set each node's status — active (blue, with meta/progress) vs idle
     (orange). On summon they boot-cascade in. Reminders + tasks have their own
     panels, so they're not in this row. -->
<script>
  import { agents } from "./ws.js";

  let { summoned = false } = $props();

  const AGENTS = [
    { id: "pomodoro", glyph: "◷", name: "Pomodoro" },
    { id: "eye_care", glyph: "◉", name: "Eye Care" },
    // Terminal node disabled until Orion runs sandboxed (config.ENABLE_TERMINAL).
    // { id: "terminal", glyph: "▸_", name: "Terminal" },
    { id: "arxiv_briefing", glyph: "✦", name: "Briefing" },
    { id: "memory", glyph: "◈", name: "Memory" },
    { id: "movie", glyph: "❖", name: "Movie" },
  ];

  // Merge each fixed node with its live status (default idle).
  let nodes = $derived(AGENTS.map((a) => ({ ...a, ...($agents[a.id] || { status: "idle" }) })));

  let booting = $state({});
  let prevSummoned = false;

  function scheduleBoot(id, delay) {
    setTimeout(() => {
      booting = { ...booting, [id]: true };
      setTimeout(() => {
        const next = { ...booting };
        delete next[id];
        booting = next;
      }, 700);
    }, delay);
  }

  $effect(() => {
    if (summoned && !prevSummoned) {
      AGENTS.forEach((a, i) => scheduleBoot(a.id, i * 130)); // cascade in on summon
    }
    prevSummoned = summoned;
  });
</script>

<div class="agents">
  {#each nodes as a (a.id)}
    <div class="agent" class:active={a.status === "active"} class:booting={booting[a.id]}>
      {#if typeof a.progress === "number"}
        <div class="arc" style="--p:{Math.round(a.progress * 100)}%"></div>
      {/if}
      <div class="ring"><span class="glyph">{a.glyph}</span></div>
      <div class="label">
        <span class="name">{a.name}</span>
        {#if a.meta}<span class="meta">{a.meta}</span>{/if}
      </div>
    </div>
  {/each}
</div>

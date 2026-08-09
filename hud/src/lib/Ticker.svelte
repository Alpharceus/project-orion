<!-- arXiv ticker: bottom marquee of the latest briefing's paper titles, mono and
     low-contrast with ember separators. Populated by `ticker` events in Phase 6;
     renders nothing until there's something to show. -->
<script>
  import { ticker } from "./ws.js";
  // duplicate the items so the marquee scrolls seamlessly
  let doubled = $derived([...$ticker, ...$ticker]);
</script>

{#if $ticker.length}
  <div class="ticker">
    <div class="track">
      {#each doubled as title}
        <b>{title}</b><span class="sep">◆</span>
      {/each}
    </div>
  </div>
{/if}

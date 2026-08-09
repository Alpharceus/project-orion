<!-- Upcoming reminders/events, soonest first. Sits just below the telemetry strip
     (the "stats"). Populated by `reminders_list` events; empty until something is
     scheduled. -->
<script>
  import { remindersList } from "./ws.js";
  const MAX = 5;
</script>

<div class="panel reminders">
  <div class="panel-head">
    <span class="panel-title">Schedule</span>
    <span class="panel-count">{$remindersList.length || ""}</span>
  </div>
  {#if $remindersList.length === 0}
    <div class="panel-empty">nothing scheduled</div>
  {:else}
    <div class="panel-list">
      {#each $remindersList.slice(0, MAX) as r}
        <div class="rem-item">
          <span class="rem-dot"></span>
          <span class="rem-text">{r.text}</span>
          <span class="rem-when">{r.when}</span>
        </div>
      {/each}
      {#if $remindersList.length > MAX}
        <div class="panel-more">+{$remindersList.length - MAX} more</div>
      {/if}
    </div>
  {/if}
</div>

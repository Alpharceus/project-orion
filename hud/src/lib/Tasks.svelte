<!-- Open tasks, priority-sorted (high → low). Sits opposite the schedule panel so
     the user can see what's on the list and how it's prioritized. Populated by
     `tasks_list` events. -->
<script>
  import { tasksList } from "./ws.js";
  const MAX = 5;
</script>

<div class="panel tasks">
  <div class="panel-head">
    <span class="panel-title">Tasks</span>
    <span class="panel-count">{$tasksList.length || ""}</span>
  </div>
  {#if $tasksList.length === 0}
    <div class="panel-empty">all clear</div>
  {:else}
    <div class="panel-list">
      {#each $tasksList.slice(0, MAX) as t}
        <div class="task-item">
          <span class="task-pri" class:high={t.priority === "high"} class:low={t.priority === "low"}></span>
          <span class="task-title">{t.title}</span>
          {#if t.due}<span class="task-due">{t.due}</span>{/if}
        </div>
      {/each}
      {#if $tasksList.length > MAX}
        <div class="panel-more">+{$tasksList.length - MAX} more</div>
      {/if}
    </div>
  {/if}
</div>

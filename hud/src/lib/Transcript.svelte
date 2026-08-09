<!-- Conversation transcript: scrolls upward, blue-white for Orion / slate for the
     user, legibility halo behind text so it reads over whatever's on the monitor. -->
<script>
  import { transcript } from "./ws.js";
</script>

<div class="transcript">
  {#each $transcript as line}
    <div class="line {line.role}">
      <span class="who">{line.role === "orion" ? "orion" : "you"}</span>{line.text}
    </div>
  {/each}
</div>

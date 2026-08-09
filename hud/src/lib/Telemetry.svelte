<!-- Telemetry strip: weather · cpu · gpu · ram. Hairline-separated cells, no box,
     mono digits. Data arrives via `telemetry` events in Phase 6; until then the
     cells render em-dashes. -->
<script>
  import { telemetry } from "./ws.js";
  const dash = "—";
</script>

<div class="telemetry">
  <div class="telcell">
    <div class="tellabel">weather</div>
    <div class="telval">{$telemetry.weather?.temp != null ? `${$telemetry.weather.temp}°` : dash}</div>
  </div>
  <div class="telcell">
    <div class="tellabel">cpu</div>
    <div class="telval">{$telemetry.cpu != null ? `${$telemetry.cpu}%` : dash}</div>
  </div>
  <div class="telcell">
    <div class="tellabel">gpu</div>
    <div class="telval">
      {#if $telemetry.gpu_gb != null}{$telemetry.gpu_gb}<span class="unit">GB</span>{:else}{dash}{/if}
    </div>
  </div>
  <div class="telcell">
    <div class="tellabel">ram</div>
    <div class="telval">{$telemetry.ram != null ? `${$telemetry.ram}%` : dash}</div>
  </div>
</div>

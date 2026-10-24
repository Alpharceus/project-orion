<!-- The core: concentric breathing rings + ember center, ported from
     orion_hud_mockup.html. Per-state behavior matches the mockup; the speaking
     state uses the "both" design (circumferential waveform on the outer rings +
     radial ember pulses on syllable onsets + an inner amplitude disc), now
     driven by the REAL amplitude envelope from the bridge instead of a fake one. -->
<script>
  import { get } from "svelte/store";
  import { getAmplitude, persona } from "./ws.js";

  // RGB triplets per persona: ring/text white, speaking blue, ember core, core highlight.
  // Orion's values are the original literals; Ultron's are the red equivalents.
  const PALETTES = {
    orion: { white: [201, 212, 232], blue: [110, 180, 255], ember: [70, 150, 255], hi: [150, 205, 255] },
    ultron: { white: [235, 205, 200], blue: [255, 90, 70], ember: [255, 40, 30], hi: [255, 150, 130] },
  };

  let { state = "idle" } = $props();

  let canvas;
  let curState = "idle";
  $effect(() => { curState = state; }); // mirror prop into a plain holder for the RAF loop

  $effect(() => {
    if (!canvas) return;
    const x = canvas.getContext("2d");
    const CX = 330, CY = 330, MAXR = 300;
    const baseRings = [60, 100, 140, 180, 215];
    // current palette, eased toward the persona's target each frame (~0.6 s)
    const pal = JSON.parse(JSON.stringify(PALETTES.orion));
    const ease = 1 - Math.pow(0.01, 1 / 36); // ~95% of the way in 36 frames (~0.6 s at 60 fps)
    function easePalette() {
      const target = PALETTES[get(persona)] || PALETTES.orion;
      for (const k in pal) for (let i = 0; i < 3; i++) pal[k][i] += (target[k][i] - pal[k][i]) * ease;
    }
    const rgb = (k, a) => `rgba(${pal[k][0] | 0},${pal[k][1] | 0},${pal[k][2] | 0},${a})`;
    let t = 0, sweep = 0, amp = 0, prevAmp = 0, pulses = [], raf;

    const cs = () => (curState === "speaking" ? "speaking3" : curState);
    const isSpeak = () => cs().indexOf("speaking") === 0;

    function updateAmp() {
      const target = isSpeak() ? getAmplitude() : 0;
      prevAmp = amp;
      amp += (target - amp) * 0.3; // ease toward the live value so it flows
    }
    const onset = () => amp > 0.42 && prevAmp <= 0.42;

    const breathSpeed = () => (cs() === "idle" ? 0.018 : cs() === "listening" ? 0.05 : cs() === "thinking" ? 0.05 : 0.04);
    const breathAmp = () => (cs() === "idle" ? 6 : cs() === "listening" ? 16 : cs() === "thinking" ? 16 : 8);
    const ringAlpha = () => (cs() === "idle" ? 0.4 : 0.62);
    const ringColor = (a) => (isSpeak() ? rgb("blue", a) : rgb("white", a));

    function speechDeform(angle) {
      const v = Math.sin(angle * 3 + t * 0.05) * 0.5 + Math.sin(angle * 5 - t * 0.035) * 0.3 + Math.sin(angle * 2 + t * 0.07) * 0.42;
      return v * amp * 30;
    }
    const deform = (angle, ringIndex) => (isSpeak() && ringIndex >= 3 ? speechDeform(angle) : 0);

    function drawRing(R, alpha, ringIndex) {
      x.beginPath();
      for (let a = 0; a <= Math.PI * 2 + 0.01; a += Math.PI / 90) {
        const r = R + deform(a, ringIndex);
        const px = CX + Math.cos(a) * r, py = CY + Math.sin(a) * r;
        a === 0 ? x.moveTo(px, py) : x.lineTo(px, py);
      }
      if (cs() === "thinking" && x.createConicGradient) {
        const grad = x.createConicGradient(sweep, CX, CY);
        grad.addColorStop(0, rgb("white", alpha * 1.6));
        grad.addColorStop(0.12, rgb("white", alpha * 0.25));
        grad.addColorStop(1, rgb("white", alpha * 0.25));
        x.strokeStyle = grad;
      } else x.strokeStyle = ringColor(alpha);
      x.lineWidth = 1.9;
      x.stroke();
    }

    function draw() {
      x.clearRect(0, 0, 660, 660);
      t++; sweep += 0.045; updateAmp(); easePalette();
      x.globalAlpha = cs() === "idle" ? 0.12 + 0.78 * (0.5 + 0.5 * Math.sin(t * 0.014)) : 1;

      if (isSpeak() && onset()) pulses.push({ r: 14, a: 0.55 + amp * 0.4 });
      pulses.forEach((p) => { p.r += 2.6; p.a *= 1 - p.r / MAXR > 0 ? 0.985 : 0; });
      pulses = pulses.filter((p) => p.r < MAXR && p.a > 0.02);
      pulses.forEach((p) => {
        x.lineWidth = 1.6;
        x.strokeStyle = rgb("blue", p.a * (1 - p.r / MAXR));
        x.beginPath(); x.arc(CX, CY, p.r, 0, Math.PI * 2); x.stroke();
      });

      const breath = Math.sin(t * breathSpeed()) * breathAmp();
      const aBase = ringAlpha();
      baseRings.forEach((R, i) => {
        const rr = R + breath * (0.5 + i * 0.16) + (isSpeak() ? amp * 6 : 0);
        drawRing(rr, aBase * (1 - i * 0.12), i);
      });

      if (isSpeak()) {
        const ir = 40 + amp * 55;
        const ig = x.createRadialGradient(CX, CY, 0, CX, CY, ir);
        ig.addColorStop(0, rgb("blue", 0.18 + amp * 0.22));
        ig.addColorStop(1, rgb("blue", 0));
        x.fillStyle = ig; x.beginPath(); x.arc(CX, CY, ir, 0, Math.PI * 2); x.fill();
      }

      const ea = cs() === "idle" ? 0.3 + 0.1 * Math.sin(t * 0.05) : isSpeak() ? 0.55 + amp * 0.45 : cs() === "thinking" ? 0.85 : 0.55;
      const er = isSpeak() ? 6 + amp * 12 : 6;
      const g = x.createRadialGradient(CX, CY, 0, CX, CY, er + 46);
      g.addColorStop(0, rgb("ember", ea));
      g.addColorStop(0.5, rgb("ember", ea * 0.4));
      g.addColorStop(1, rgb("ember", 0));
      x.fillStyle = g; x.beginPath(); x.arc(CX, CY, er + 46, 0, Math.PI * 2); x.fill();
      x.fillStyle = rgb("hi", Math.min(1, ea + 0.3));
      x.beginPath(); x.arc(CX, CY, er, 0, Math.PI * 2); x.fill();

      x.globalAlpha = 1;
      raf = requestAnimationFrame(draw);
    }
    draw();
    return () => cancelAnimationFrame(raf);
  });
</script>

<canvas bind:this={canvas} width="660" height="660"></canvas>

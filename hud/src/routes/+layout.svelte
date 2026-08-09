<script>
  import "../app.css";
  // Locally-bundled fonts (offline — no Google Fonts network call).
  import "@fontsource/space-grotesk/600.css";
  import "@fontsource/inter/400.css";
  import "@fontsource/inter/500.css";
  import "@fontsource/jetbrains-mono/400.css";
  import "@fontsource/jetbrains-mono/500.css";

  let { children } = $props();
</script>

{@render children()}

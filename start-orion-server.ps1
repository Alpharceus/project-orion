# Launch Orion's LLM server: Gemma 4 12B + audio/vision projector.
#
# Memory choices (RTX 5070 Ti 16GB + 32GB RAM, measured 2026-06-11):
#   --no-mmap        frees ~9GB of system RAM that the memory-mapped GGUF
#                    otherwise keeps resident after weights are on the GPU
#                    (commit charge stays ~10GB in Task Manager, but the pages
#                    are not physically resident - working set is <0.5GB)
#   -np 1            ONE server slot. Without it the auto-fitter created 4
#                    slots x 4096 ctx, quadrupling KV-cache VRAM for a
#                    single-user assistant.
#   -c 8192          context for the single slot (less total KV than 4x4096)
#   -fa on + q8_0 KV quantized KV cache, roughly halves KV VRAM at no
#                    noticeable quality cost

$root = $PSScriptRoot
& "$root\bin\llama\llama-server.exe" `
    -m "$root\models\gemma-4-12b-it-Q4_K_M.gguf" `
    --mmproj "$root\models\mmproj-F16.gguf" `
    --jinja `
    -ngl 99 `
    -np 1 `
    -c 8192 `
    --no-mmap `
    -fa on -ctk q8_0 -ctv q8_0 `
    --port 8080

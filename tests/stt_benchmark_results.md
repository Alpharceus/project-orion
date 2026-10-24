# STT benchmark results

Clips: 36 PocketTTS clips in the user's cloned voice (30 base + 6 with -25 dB pink noise).
CPU int8, beam 5, 6 threads. Latency is per clip, measured with Orion not running (no llama-server or orion.py contention), so live numbers may be somewhat higher. RSS is the benchmark process's resident size (includes earlier-loaded models and the TTS), not an isolated per-model peak.

| config | WER % | vocab acc % | mean s | p90 s | p90 s (<=5 s clips) | RSS MB |
|---|---|---|---|---|---|---|
| large-v3-turbo / none | 3.0 | 83.3 | 2.59 | 2.63 | 2.63 | 1722 |
| large-v3-turbo / hotwords | 1.3 | 90.0 | 2.62 | 2.67 | 2.67 | 1721 |
| large-v3-turbo / initial_prompt | 1.3 | 90.0 | 2.63 | 2.67 | 2.67 | 1721 |
| distil-large-v3 / none | 5.1 | 80.0 | 2.55 | 2.59 | 2.59 | 1673 |
| distil-large-v3 / hotwords | 4.7 | 80.0 | 2.58 | 2.60 | 2.60 | 1673 |
| distil-large-v3 / initial_prompt | 5.1 | 80.0 | 2.58 | 2.60 | 2.60 | 1673 |
| small.en / none | 4.2 | 80.0 | 0.64 | 0.67 | 0.67 | 1174 |
| small.en / hotwords | 0.0 | 100.0 | 0.72 | 0.78 | 0.78 | 1174 |
| small.en / initial_prompt | 0.0 | 100.0 | 0.73 | 0.77 | 0.77 | 1174 |

Chosen: **small.en / hotwords** (highest vocab accuracy among configs with p90 <= 1.2 s (clips <= 5 s), ties by WER).

## Misses

- Gemma skipped: llama-server did not answer /health.
- [large-v3-turbo / none] c04: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's Rxiv briefing."
- [large-v3-turbo / none] c10: ref='Search arXiv for Gaussian boson sampling.' hyp='Search Rxiv for Gaussian boson sampling.'
- [large-v3-turbo / none] c15: ref='Is there a Purcell enhancement paper today?' hyp='Is there a per-cell enhancement paper today?'
- [large-v3-turbo / none] c18: ref='Raman needs a twenty twenty twenty reminder.' hyp='Ramen needs a 20-20-20 reminder.'
- [large-v3-turbo / none] p10: ref='Cancel my appointment on the twenty second.' hyp='Cancel my appointment on the 22nd.'
- [large-v3-turbo / none] c04_noisy: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's Rxiv briefing."
- [large-v3-turbo / hotwords] c04: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's Rxiv briefing"
- [large-v3-turbo / hotwords] c10: ref='Search arXiv for Gaussian boson sampling.' hyp='Search Rxiv for Gaussian boson sampling'
- [large-v3-turbo / hotwords] c04_noisy: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's Rxiv Briefing"
- [large-v3-turbo / initial_prompt] c04: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's Rxiv briefing."
- [large-v3-turbo / initial_prompt] c10: ref='Search arXiv for Gaussian boson sampling.' hyp='Search Rxiv for Gaussian boson sampling.'
- [large-v3-turbo / initial_prompt] c04_noisy: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's Rxiv briefing."
- [distil-large-v3 / none] c02: ref='Bring back Jarvis.' hyp='bring back Java.'
- [distil-large-v3 / none] c04: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's RXIV briefing."
- [distil-large-v3 / none] c10: ref='Search arXiv for Gaussian boson sampling.' hyp='Search Rxiv for Gaussian boson sampling.'
- [distil-large-v3 / none] c12: ref='Remind me to email Osinski tomorrow at nine.' hyp='Remind me to email Ossinsky tomorrow, 9.'
- [distil-large-v3 / none] c18: ref='Raman needs a twenty twenty twenty reminder.' hyp='Raman needs a 2020 reminder.'
- [distil-large-v3 / none] p01: ref='Remind me to call mom at six fifteen.' hyp='Remind me to call Mom at 615.'
- [distil-large-v3 / none] p10: ref='Cancel my appointment on the twenty second.' hyp='cancel my appointment on the 22nd.'
- [distil-large-v3 / none] c04_noisy: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's RXIV briefing."
- [distil-large-v3 / none] p01_noisy: ref='Remind me to call mom at six fifteen.' hyp='Remind me to call Mom at 615.'
- [distil-large-v3 / hotwords] c02: ref='Bring back Jarvis.' hyp='bring back Javis.'
- [distil-large-v3 / hotwords] c04: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's RXIV briefing."
- [distil-large-v3 / hotwords] c10: ref='Search arXiv for Gaussian boson sampling.' hyp='Search RXiv for Gaussian boson sampling.'
- [distil-large-v3 / hotwords] c12: ref='Remind me to email Osinski tomorrow at nine.' hyp='remind me to email Ossinsky tomorrow, nine.'
- [distil-large-v3 / hotwords] c18: ref='Raman needs a twenty twenty twenty reminder.' hyp='Raman needs a 20-2020 reminder.'
- [distil-large-v3 / hotwords] p01: ref='Remind me to call mom at six fifteen.' hyp='Remind me to call Mom at 615.'
- [distil-large-v3 / hotwords] p10: ref='Cancel my appointment on the twenty second.' hyp='cancel my appointment on the 22nd.'
- [distil-large-v3 / hotwords] c04_noisy: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's RXIV briefing."
- [distil-large-v3 / hotwords] p01_noisy: ref='Remind me to call mom at six fifteen.' hyp='Remind me to call Mom at 615.'
- [distil-large-v3 / initial_prompt] c02: ref='Bring back Jarvis.' hyp='Bring back Javis.'
- [distil-large-v3 / initial_prompt] c04: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's RXIV briefing."
- [distil-large-v3 / initial_prompt] c10: ref='Search arXiv for Gaussian boson sampling.' hyp='Search RXiv for Gaussian boson sampling.'
- [distil-large-v3 / initial_prompt] c12: ref='Remind me to email Osinski tomorrow at nine.' hyp='Remind me to email Ossinsky tomorrow, 9.'
- [distil-large-v3 / initial_prompt] c18: ref='Raman needs a twenty twenty twenty reminder.' hyp='Raman needs a 2020 reminder.'
- [distil-large-v3 / initial_prompt] p01: ref='Remind me to call mom at six fifteen.' hyp='Remind me to call Mom at 615.'
- [distil-large-v3 / initial_prompt] p10: ref='Cancel my appointment on the twenty second.' hyp='cancel my appointment on the 22nd.'
- [distil-large-v3 / initial_prompt] c04_noisy: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's RXIV briefing."
- [distil-large-v3 / initial_prompt] p01_noisy: ref='Remind me to call mom at six fifteen.' hyp='Remind me to call Mom at 615.'
- [small.en / none] c02: ref='Bring back Jarvis.' hyp='Bring back Javis.'
- [small.en / none] c04: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's RX of Briefing."
- [small.en / none] c10: ref='Search arXiv for Gaussian boson sampling.' hyp='Search RXiv for Gaussian boson sampling.'
- [small.en / none] c12: ref='Remind me to email Osinski tomorrow at nine.' hyp='Remind me to email Ossinski tomorrow at 9.'
- [small.en / none] c18: ref='Raman needs a twenty twenty twenty reminder.' hyp='Rahman needs a 20-20-20 reminder.'
- [small.en / none] p10: ref='Cancel my appointment on the twenty second.' hyp='Cancel my appointment on the 22nd.'
- [small.en / none] c04_noisy: ref="Download the GKP paper from this morning's arXiv briefing." hyp="Download the GKP paper from this morning's RX of briefing."
- [small.en / none] p01_noisy: ref='Remind me to call mom at six fifteen.' hyp='Remind me to call mom at 615.'

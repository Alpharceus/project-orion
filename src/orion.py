"""Project Orion — voice assistant entry point.

Wires the pieces together: a wake word (wakeword.py) gates listening.py (mic +
VAD) -> llm.py (Gemma 4 via llama-server, tool dispatch) -> speech.py
(PocketTTS). A formal state machine (state.py) tracks idle/listening/thinking/
speaking and a local WebSocket bridge (hud_server.py) streams those events to
the HUD. Agent tools live in agents/. All tuning knobs are in config.py. See
ARCHITECTURE.md for the map.

Start the server first:  .\\start-orion-server.ps1  (project root)
"""

import re

import openai
from pysilero_vad import SileroVoiceActivityDetector

import config
import events
import hud_server
import memory
import persona
import state
import telemetry
from agents import movie, publish_agents_baseline, reminders, set_notifier, tasks
from agents.arxiv_briefing import schedule_default
from listening import record_voice
from llm import chat_turn, server_ready, transcribe, trim_history
from speech import SpeechPlayer, load_persona_voices, load_tts


# Whole-utterance dismissals that put Orion to sleep directly — a backstop so it
# never depends on the model remembering to call go_to_sleep. Matched only when
# the entire utterance is one of these (so "remind me to go to sleep at ten" is
# left to the model, not force-slept).
SLEEP_UTTERANCES = {
    "go to sleep", "go back to sleep", "go to sleep now", "go idle", "go to idle",
    "never mind", "nevermind", "that's all", "thats all", "that is all",
    "nothing else", "dismiss", "goodbye", "bye", "stop listening", "sleep",
    "go to bed", "power down", "stand down", "i'm done", "im done", "we're done",
    "were done", "that'll be all", "thatll be all", "rest now",
}

# Trailing clause to drop before matching, so "go to sleep BUT keep the movie on"
# (or "...and goodbye", "...just leave the animation") still reads as a dismissal.
_TRAILING_CLAUSE = re.compile(r"\s+\b(?:but|and|just|while|though|except)\b.*$")
# Leading / trailing filler around the core phrase.
_LEAD_FILLER = re.compile(r"^(?:ok(?:ay)?|alright(?:y)?|hey|orion|so|well|um+|uh+|and|you can|you may|please|just|now)\s+")
_TRAIL_FILLER = re.compile(r"\s+(?:please|now|orion|thanks|thank you|for now)$")


def _is_sleep_command(text: str) -> bool:
    """True if the whole utterance is a dismissal — robust to filler and to a
    trailing 'but keep the movie on' style clause (movie mode persists through
    sleep, so the user can ask to sleep without stopping the screensaver)."""
    t = re.sub(r"[,]", " ", text.lower())
    t = re.sub(r"\s+", " ", t).strip()
    t = _TRAILING_CLAUSE.sub("", t).strip(" .!?;").strip()
    prev = None
    while t != prev:  # peel filler until stable
        prev = t
        t = _LEAD_FILLER.sub("", t)
        t = _TRAIL_FILLER.sub("", t).strip(" .!?;").strip()
    return t in SLEEP_UTTERANCES


def _make_waker():
    """Return a zero-arg callable that blocks until it's time to talk.

    Wake word when enabled and available; press-Enter otherwise (so development
    isn't blocked if the wake engine can't load).
    """
    if config.WAKE_ENABLED:
        try:
            from wakeword import WakeWord
            waker = WakeWord()
            print(f"👂 [Orion] Wake word active — say \"{config.WAKE_WORD}\".")
            return lambda: (print(f"💤 [Orion] Dormant — say \"{config.WAKE_WORD}\"."),
                            waker.wait())
        except Exception as e:
            print(f"⚠️  [Orion] Wake word unavailable ({e}); using press-Enter.")
    return lambda: input("\nPress Enter to talk (Ctrl+C to quit): ")


def main():
    if not server_ready():
        print("🔌 [Orion] llama-server isn't running at "
              f"{config.LLM_BASE_URL} — start it first:  .\\start-orion-server.ps1")
        return

    print("🗣️ [Orion] Loading TTS and VAD...")
    tts, voice_state = load_tts()
    speaker = SpeechPlayer(tts, voice_state, load_persona_voices(tts, {"orion": voice_state}))
    vad = SileroVoiceActivityDetector()
    if config.STT_ENGINE == "whisper":
        print(f"📝 [Orion] Loading speech recognition ({config.STT_MODEL}, CPU)...")
        try:
            import stt
            stt.preload()
        except Exception as e:  # llm.transcribe falls back to Gemma per utterance
            print(f"⚠️  [Orion] Whisper unavailable ({e}); using Gemma transcription.")

    def announce(text: str):
        print(f"\n🔔 [Orion] {text}")
        speaker.say(text)

    set_notifier(announce)  # timer agents (pomodoro, eye care) speak through Orion
    schedule_default()      # daily arXiv briefing at config.BRIEFING_TIME

    # HUD clients can force Orion back to dormant; best-effort UI signal.
    events.subscribe(lambda e: state.set(state.IDLE)
                     if e.get("type") == "command" and e.get("name") == "dismiss" else None)

    hud_server.start()      # local WebSocket bridge (works fine with no client)
    publish_agents_baseline()  # populate the HUD's agent row (all dim)...
    memory.start()          # ...then memory/reminders/tasks light their nodes with counts
    reminders.start()
    tasks.start()
    movie.start()           # restore last movie-mode animation (if any)
    telemetry.start()       # system stats + weather for the HUD strip
    wait_to_talk = _make_waker()

    # System prompt + long-term memory; conversation history rolls across turns
    # and is trimmed/summarized (llm.trim_history) so the 8k window holds.
    messages = [{"role": "system", "content": persona.system_prompt() + memory.preamble()}]

    state.set(state.IDLE)
    print("🟢 [Orion] System Online.")

    try:
        while True:
            wait_to_talk()  # dormant: wake word (or press-Enter)

            # Conversation: accept follow-ups without the wake word until you go
            # quiet for FOLLOWUP_WINDOW_SECONDS (or ask to go idle), then sleep.
            # begin/end_conversation keeps the HUD summoned across turns (no
            # idle flash between speaking and the next listen).
            state.begin_conversation()
            while True:
                audio_b64 = record_voice(vad, no_speech_timeout=config.FOLLOWUP_WINDOW_SECONDS)
                if audio_b64 is None:
                    break  # quiet too long — back to sleep

                state.set(state.THINKING)  # transcribing, then answering
                try:
                    user_text = transcribe(audio_b64)
                    if not user_text:
                        continue  # nothing intelligible — keep listening
                    print(f"🗣️  You: {user_text}")
                    events.publish({"type": "transcript", "role": "user", "text": user_text})
                    if _is_sleep_command(user_text):
                        state.request_sleep()  # backstop in case the model doesn't call go_to_sleep
                    messages.append({"role": "user", "content": user_text})
                    messages = trim_history(messages)
                    print("🧠 [Orion] Thinking...")
                    chat_turn(messages, speaker)
                except openai.APIConnectionError:
                    if messages and messages[-1].get("role") == "user":
                        messages.pop()  # drop the unanswered turn so history stays consistent
                    print("🔌 [Orion] Lost contact with llama-server — is it still running? "
                          "Restart it with .\\start-orion-server.ps1 and try again.")
                    break
                speaker.wait_until_done()
                if state.sleep_requested():
                    state.clear_sleep()
                    print("😴 [Orion] Going idle.")
                    break

            state.end_conversation()
            state.set(state.IDLE)
    except KeyboardInterrupt:
        print("\n👋 [Orion] Shutting down.")


if __name__ == "__main__":
    main()

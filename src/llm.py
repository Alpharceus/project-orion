"""LLM client: streaming chat with sentence-level TTS handoff and tool dispatch."""

import json
import re
import urllib.request

import openai

import config
import events
import state
from agents import dispatch, tool_specs

client = openai.OpenAI(base_url=config.LLM_BASE_URL, api_key=config.LLM_API_KEY)

# Gemma 4 is a "thinking" model: left on, it spends time generating reasoning
# (slow — feels frozen on tool-heavy turns like scheduling) and the reasoning can
# leak into plain outputs (e.g. transcriptions showing up as a wall of "1. Listen
# 2. Transcribe ..."). Orion doesn't need visible reasoning, so disable it. Tool
# calls still work with thinking off.
_NO_THINK = {"chat_template_kwargs": {"enable_thinking": False}}


def server_ready() -> bool:
    """True if llama-server is answering on its health endpoint."""
    url = config.LLM_BASE_URL.removesuffix("/v1") + "/health"
    try:
        with urllib.request.urlopen(url, timeout=2):
            return True
    except OSError:
        return False

SENTENCE_END = re.compile(r"(?<=[.!?])\s+")


def stream_reply(messages: list, speaker) -> tuple[str, list]:
    """Stream one model response; return (text, tool_calls).

    Complete sentences are handed to the speaker as soon as they stream in.
    """
    state.set(state.THINKING)
    response = client.chat.completions.create(
        model=config.LLM_MODEL, messages=messages, tools=tool_specs(), stream=True,
        extra_body=_NO_THINK,
    )
    text = ""
    pending = ""  # text not yet sent to TTS
    tool_calls = {}  # index -> accumulated call
    for chunk in response:
        delta = chunk.choices[0].delta
        if delta.content:
            print(delta.content, end="", flush=True)
            text += delta.content
            pending += delta.content
            if speaker:
                *complete, pending = SENTENCE_END.split(pending)
                for sentence in complete:
                    speaker.say(sentence)
        for tc in delta.tool_calls or []:
            acc = tool_calls.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
            acc["id"] = tc.id or acc["id"]
            if tc.function:
                acc["name"] = tc.function.name or acc["name"]
                acc["arguments"] += tc.function.arguments or ""
    if speaker:
        speaker.say(pending)
    return text, [tool_calls[i] for i in sorted(tool_calls)]


def oneshot(system: str, user: str) -> str:
    """One non-streaming, tool-free completion (used by background agents)."""
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        extra_body=_NO_THINK,
    )
    return response.choices[0].message.content or ""


def transcribe(audio_b64: str) -> str:
    """Transcribe a user utterance to text, so conversation history stays text
    (not accumulating audio blobs) and the user's words can reach the HUD.

    Whisper (CPU) by default; Gemma is the selectable engine and the fallback."""
    if config.STT_ENGINE == "whisper":
        try:
            import stt
            return stt.transcribe(audio_b64)
        except Exception as e:
            print(f"⚠️  [Orion] Whisper failed ({e}); falling back to Gemma transcription.")
    return _gemma_transcribe(audio_b64)


def _gemma_transcribe(audio_b64: str) -> str:
    response = client.chat.completions.create(
        model=config.LLM_MODEL,
        messages=[{"role": "user", "content": [
            {"type": "text", "text": "Transcribe this audio to text exactly. Output only the spoken words, nothing else."},
            {"type": "input_audio", "input_audio": {"data": audio_b64, "format": "wav"}},
        ]}],
        extra_body=_NO_THINK,
    )
    return (response.choices[0].message.content or "").strip()


def trim_history(messages: list) -> list:
    """Keep the system message + the most recent turns, summarizing older ones
    into a compact note so context stays bounded as a conversation grows."""
    limit = config.CONVERSATION_MAX_MESSAGES
    if len(messages) <= limit + 1:
        return messages
    system, rest = messages[0], messages[1:]
    recent, older = rest[-limit:], rest[:-limit]
    older_text = "\n".join(f"{m['role']}: {m['content']}" for m in older
                           if isinstance(m.get("content"), str) and m["content"])
    try:
        summary = oneshot(
            "Summarize this conversation excerpt in two or three sentences, keeping any "
            "facts, decisions, and the user's intent. Output only the summary.",
            older_text,
        ).strip()
    except Exception:
        summary = ""
    head = [system]
    if summary:
        head.append({"role": "system", "content": f"Earlier in this conversation: {summary}"})
    return head + recent


def chat_turn(messages: list, speaker=None) -> str:
    """Run the model, dispatching tool calls until it gives a final answer."""
    while True:
        text, tool_calls = stream_reply(messages, speaker)
        if not tool_calls:
            messages.append({"role": "assistant", "content": text})
            if text.strip():
                events.publish({"type": "transcript", "role": "orion", "text": text.strip()})
            return text
        messages.append({
            "role": "assistant",
            "content": text or None,
            "tool_calls": [
                {"id": tc["id"], "type": "function",
                 "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                for tc in tool_calls
            ],
        })
        for tc in tool_calls:
            print(f"\n🔧 [Orion] Running tool: {tc['name']}({tc['arguments']})")
            try:
                args = json.loads(tc["arguments"] or "{}")
            except json.JSONDecodeError as e:
                output = f"Tool error: invalid arguments JSON ({e})"
            else:
                output = dispatch(tc["name"], args)
            messages.append({"role": "tool", "tool_call_id": tc["id"], "content": output})
        # A persona switch must take effect on the very next reply in this loop,
        # so rebuild the system message now rather than at the next turn.
        if (any(tc["name"] == "switch_persona" for tc in tool_calls)
                and messages[0]["role"] == "system"):
            import memory
            import persona
            messages[0]["content"] = persona.system_prompt() + memory.preamble()

r"""Unit tests for Phase 7 (memory, arXiv dedup, download, history trim) — no LLM.

Run from the project root:  orion_env\Scripts\python.exe tests\test_phase7.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

import config

_tmp = Path(tempfile.mkdtemp())
config.DATA_DIR = _tmp
config.PAPERS_DIR = _tmp / "papers"

import memory
import llm
from agents import arxiv_briefing as ab
from agents import dispatch, set_notifier

memory.STORE = _tmp / "memory.json"
memory._data.update({"facts": {}, "seen_arxiv": [], "last_briefing": []})

PASS, FAIL = 0, []


def check(name, condition, detail=""):
    global PASS
    if condition:
        PASS += 1
        print(f"  ok  {name}")
    else:
        FAIL.append(name)
        print(f"  FAIL {name}  {detail}")


# --- long-term memory ---------------------------------------------------------
print("memory facts:")
memory.remember("Raman works on single-photon sources")
memory.remember("Raman's advisor is Dr. Quantum")
check("facts stored", len(memory.all_facts()) == 2)
check("recall by keyword", [f["text"] for f in memory.recall("advisor")] == ["Raman's advisor is Dr. Quantum"])
check("preamble lists facts", "single-photon sources" in memory.preamble() and memory.preamble().startswith("\n"))
added = memory.remember_many(["Raman works on single-photon sources", "New fact about CV-QEC"])
check("remember_many skips dupes", added == 1 and len(memory.all_facts()) == 3)
check("forget by substring", memory.forget("advisor") == 1 and len(memory.all_facts()) == 2)

# persistence round-trip
memory._save()
memory._data.update({"facts": {}, "seen_arxiv": [], "last_briefing": []})
memory._load()
check("memory reloads from disk", len(memory.all_facts()) == 2)

# --- arXiv dedup ledger -------------------------------------------------------
print("arXiv dedup:")
check("unseen initially", not memory.is_seen("2506.00001"))
memory.mark_seen(["2506.00001", "2506.00002"])
check("seen after mark", memory.is_seen("2506.00001") and memory.is_seen("2506.00002"))
memory.mark_seen(["2506.00001"])
check("no duplicate ids", memory._data["seen_arxiv"].count("2506.00001") == 1)

# --- feed parsing (id + pdf) --------------------------------------------------
print("feed parsing:")
FEED = b"""<?xml version="1.0"?>
<feed xmlns="http://www.w3.org/2005/Atom">
  <entry>
    <id>http://arxiv.org/abs/2506.12345v2</id>
    <title>A Single Photon Paper</title>
    <summary>Abstract here.</summary>
    <author><name>A. Researcher</name></author>
    <category term="quant-ph"/>
    <link title="pdf" href="http://arxiv.org/pdf/2506.12345v2"/>
  </entry>
</feed>"""
papers = ab.parse_feed(FEED)
check("id version-stripped", papers[0]["id"] == "2506.12345", papers[0]["id"])
check("pdf link parsed", papers[0]["pdf"] == "http://arxiv.org/pdf/2506.12345v2")

# --- briefing dedup behavior --------------------------------------------------
print("briefing dedup:")
memory._data["seen_arxiv"] = []
PAPERS = [{"id": "2506.0001", "title": "GKP photonic codes", "summary": "x", "authors": ["A"], "category": "quant-ph", "pdf": "u1"},
          {"id": "2506.0002", "title": "SNSPD detectors", "summary": "y", "authors": ["B"], "category": "quant-ph", "pdf": "u2"}]
ab.fetch_papers = lambda *a, **k: PAPERS
llm.oneshot = lambda system, user: "Here is your briefing."
notes = []
set_notifier(notes.append)
ab.run_briefing()
check("first briefing speaks", any("briefing" in n.lower() for n in notes), str(notes))
check("papers marked seen", memory.is_seen("2506.0001") and memory.is_seen("2506.0002"))
check("last_briefing stored", len(memory.last_briefing()) == 2)
notes.clear()
ab.run_briefing()
check("second briefing says nothing new", any("nothing new" in n.lower() for n in notes), str(notes))

# --- download_paper -----------------------------------------------------------
print("download:")
class _FakeResp:
    def __init__(self, data): self.data = data
    def read(self): return self.data
    def __enter__(self): return self
    def __exit__(self, *a): return False
ab.urllib.request.urlopen = lambda req, timeout=30: _FakeResp(b"%PDF-1.7 fake")
check("no id/query -> asks", "couldn't tell" in dispatch("download_paper", {}).lower())
out = dispatch("download_paper", {"query": "GKP"})
check("query resolves from last briefing", "Downloaded 2506.0001" in out, out)
check("pdf written to papers dir", (config.PAPERS_DIR / "2506.0001.pdf").exists())
out = dispatch("download_paper", {"arxiv_id": "1234.5678"})
check("explicit id downloads", "Downloaded 1234.5678" in out, out)

# --- memory tools -------------------------------------------------------------
print("memory tools:")
check("store via tool", "Saved to memory" in dispatch("memory_store", {"text": "Raman likes British TTS voices"}))
check("recall via tool", "British" in dispatch("memory_recall", {"query": "voices"}))
check("forget via tool", "Forgot 1" in dispatch("memory_forget", {"query": "British"}))

# --- conversation history trim ------------------------------------------------
print("history trim:")
llm.oneshot = lambda system, user: "Summary of the earlier chat."
msgs = [{"role": "system", "content": "sys"}]
for i in range(20):
    msgs.append({"role": "user" if i % 2 == 0 else "assistant", "content": f"line {i}"})
trimmed = llm.trim_history(msgs)
check("trimmed to bound", len(trimmed) == config.CONVERSATION_MAX_MESSAGES + 2, str(len(trimmed)))
check("system kept first", trimmed[0]["content"] == "sys")
check("summary note inserted", "Summary of the earlier chat" in trimmed[1]["content"])
check("recent turns kept", trimmed[-1]["content"] == "line 19")
short = [{"role": "system", "content": "sys"}, {"role": "user", "content": "hi"}]
check("short history untouched", llm.trim_history(short) == short)

print(f"\n{PASS} passed, {len(FAIL)} failed" + (f": {FAIL}" if FAIL else ""))
sys.exit(1 if FAIL else 0)

"""arXiv briefing agent: fetch the newest papers, summarize via Gemma, speak.

Runs on a daily schedule (config.BRIEFING_TIME, wired up by orion.py at
startup) and on demand through the arxiv_briefing tool. The arXiv fetch is the
one place Orion touches the network at runtime; summarization and speech stay
local.
"""

import re
import threading
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

import config
import events
import scheduler

from . import notify, tool

ATOM = "{http://www.w3.org/2005/Atom}"
JOB_NAME = "arxiv_briefing"

BRIEFING_SYSTEM_PROMPT = (
    "You are Orion, a warm, sharp desktop assistant delivering a spoken morning "
    "research briefing. From the arXiv listings below, pick the 3 or 4 most "
    "interesting papers and present them conversationally. For EACH highlighted "
    "paper, say its title and its lead author by name (e.g. 'In \"Title here,\" "
    "Jane Smith and colleagues...'), then in one or two sentences what was done "
    "and why it matters. Then dispatch the rest in a single quick sentence, or "
    "skip them. Your reply is read aloud verbatim, so use plain sentences only — "
    "no markdown, lists, emoji, or LaTeX (say math in words)."
)


def parse_feed(xml_bytes: bytes) -> list[dict]:
    """Parse an arXiv Atom feed into [{id, title, summary, authors, category, pdf}].

    `id` is the version-stripped arXiv id (for dedup + downloads); `pdf` is the
    PDF url.
    """
    papers = []
    for entry in ET.fromstring(xml_bytes).findall(ATOM + "entry"):
        category = entry.find(ATOM + "category")
        raw = (entry.findtext(ATOM + "id") or "").split("/abs/")[-1]  # e.g. 2506.12345v1
        arxiv_id = re.sub(r"v\d+$", "", raw)                          # -> 2506.12345
        pdf = next((ln.get("href", "") for ln in entry.findall(ATOM + "link")
                    if ln.get("title") == "pdf"), "")
        if not pdf and arxiv_id:
            pdf = f"https://arxiv.org/pdf/{arxiv_id}"
        papers.append({
            "id": arxiv_id,
            "title": " ".join((entry.findtext(ATOM + "title") or "").split()),
            "summary": " ".join((entry.findtext(ATOM + "summary") or "").split()),
            "authors": [a.findtext(ATOM + "name") or "" for a in entry.findall(ATOM + "author")],
            "category": category.get("term", "") if category is not None else "",
            "pdf": pdf,
        })
    return papers


def _topic_to_query(line: str) -> str:
    """Turn a config topic into an arXiv query group.

    'all:quantum+dot+AND+all:single+photon' -> (all:"quantum dot" AND all:"single photon")
    """
    clauses = []
    for part in line.split("+AND+"):
        part = part.strip()
        if part.lower().startswith("all:"):
            clauses.append(f'all:"{part[4:].replace("+", " ").strip()}"')
        elif part:
            clauses.append(part.replace("+", " "))
    return "(" + " AND ".join(clauses) + ")"


def build_query(keywords=None, keyword_mode: str = "extend", scope: str = "niche") -> str:
    """Build the arXiv search_query.

    scope="all" -> the broad categories, no topic filter. scope="niche" (default)
    -> newest papers matching ANY standing topic (config.ARXIV_TOPICS), plus any
    ad-hoc keywords the model adds (extend) or only those (replace). With
    config.ARXIV_NICHE_ONLY set, the topic group is AND-constrained to the niche
    categories.
    """
    if scope == "all":
        return "(" + " OR ".join(f"cat:{c}" for c in config.ARXIV_CATEGORIES) + ")"
    topics = [_topic_to_query(t) for t in config.ARXIV_TOPICS]
    if keywords is not None:
        adhoc = [f'(all:"{k}")' for k in keywords]
        topics = topics + adhoc if keyword_mode == "extend" else adhoc
    if not topics:
        return "(" + " OR ".join(f"cat:{c}" for c in config.ARXIV_NICHE_CATEGORIES) + ")"
    group = "(" + " OR ".join(topics) + ")"
    if config.ARXIV_NICHE_ONLY and config.ARXIV_NICHE_CATEGORIES:
        cats = "(" + " OR ".join(f"cat:{c}" for c in config.ARXIV_NICHE_CATEGORIES) + ")"
        return f"{cats} AND {group}"
    return group


def fetch_papers(keywords=None, keyword_mode: str = "extend", scope: str = "niche") -> list[dict]:
    """Newest on-topic submissions, server-side filtered by category + keywords."""
    query = urllib.parse.urlencode({
        "search_query": build_query(keywords, keyword_mode, scope),
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "max_results": config.ARXIV_MAX_PAPERS,
    })
    url = "https://export.arxiv.org/api/query?" + query
    with urllib.request.urlopen(url, timeout=30) as response:
        return parse_feed(response.read())


def run_briefing(keywords=None, keyword_mode: str = "extend", scope: str = "niche") -> None:
    """Fetch, summarize, and speak the briefing. Blocking; run in a thread."""
    import memory  # deferred (memory has no agents dependency, but keep it lazy)

    fallback = False
    try:
        papers = fetch_papers(keywords, keyword_mode, scope)
        if not papers and scope == "niche":
            # Keyword filter matched nothing today — fall back to the niche
            # categories newest-N (no keyword filter) so a quiet day isn't silent.
            fallback = True
            papers = fetch_papers(keywords=[], keyword_mode="replace", scope="niche")
    except Exception as e:
        notify(f"I couldn't reach arXiv for the research briefing: {e}")
        return
    if not papers:
        notify("arXiv has nothing new in your categories today.")
        return

    # Dedup against the ledger so the same paper isn't read out twice. Keep the
    # full latest set for "download that paper" either way.
    memory.set_last_briefing(papers)
    fresh = [p for p in papers if not memory.is_seen(p["id"])]
    if not fresh:
        notify("Nothing new in your topics that I haven't already briefed you on.")
        return
    papers = fresh

    # Feed the HUD ticker the on-topic titles.
    events.publish({"type": "ticker", "titles": [p["title"] for p in papers]})

    listing = "\n\n".join(
        f"[{p['category']}] {p['title']}\nAuthors: {', '.join(p['authors'])}\n{p['summary']}"
        for p in papers
    )
    # Imported here, not at module top: llm.py imports the agents package, so a
    # top-level import would be circular.
    from llm import oneshot

    note = ("Note: today's keyword filter matched nothing, so these are the newest "
            "from the categories instead — mention that briefly. " if fallback else "")
    try:
        briefing = oneshot(
            BRIEFING_SYSTEM_PROMPT,
            f"{note}Here are the {len(papers)} newest arXiv papers:\n\n{listing}",
        )
    except Exception as e:
        notify(f"The briefing fetch worked but summarization failed: {e}")
        return
    memory.mark_seen([p["id"] for p in papers])  # only after a successful briefing
    notify(briefing.strip() or "The briefing came back empty. That's odd.")


def _start_briefing_thread(keywords=None, keyword_mode: str = "extend", scope: str = "niche") -> None:
    threading.Thread(target=run_briefing, args=(keywords, keyword_mode, scope), daemon=True).start()


def schedule_default() -> None:
    """Apply config.BRIEFING_TIME (called by orion.py at startup; "" disables)."""
    if config.BRIEFING_TIME:
        scheduler.schedule_daily(JOB_NAME, config.BRIEFING_TIME, run_briefing)


@tool(
    "arxiv_briefing",
    "Manage the spoken arXiv research briefing. Actions: 'now' fetches the "
    "latest papers and reads the briefing aloud shortly (do not repeat its "
    "contents yourself), 'schedule' sets the daily delivery time, 'cancel' turns "
    "the daily briefing off, 'status' reports the schedule and filters. By "
    "default the briefing is niche: it restricts to the user's research "
    "categories and standing keywords. For a 'now' run you can steer scope: pass "
    "scope='all' to brief across the broader categories with no keyword filter "
    "('brief me across all of physics'), or pass keywords to focus on a topic "
    "('anything on cat qubits today').",
    {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["now", "schedule", "cancel", "status"]},
            "time": {"type": "string", "description": "Delivery time as 24-hour HH:MM, for 'schedule'."},
            "keywords": {
                "type": "array", "items": {"type": "string"},
                "description": "Ad-hoc topic terms for a 'now' run.",
            },
            "keyword_mode": {
                "type": "string", "enum": ["extend", "replace"],
                "description": "Whether ad-hoc keywords extend the standing list (default) or replace it.",
            },
            "scope": {
                "type": "string", "enum": ["niche", "all"],
                "description": "'niche' (default) = research categories + keyword filter; 'all' = broad categories, no keyword filter.",
            },
        },
        "required": ["action"],
    },
)
def arxiv_briefing(action: str, time: str = "", keywords=None,
                   keyword_mode: str = "extend", scope: str = "niche") -> str:
    if action == "now":
        _start_briefing_thread(keywords, keyword_mode, scope)
        return ("Briefing started in the background; it will be read aloud in a "
                "moment. Tell the user it's coming, don't invent its contents.")
    if action == "schedule":
        spec = time or config.BRIEFING_TIME
        if not spec:
            return "No time given and no default configured. Ask for an HH:MM time."
        try:
            scheduler.schedule_daily(JOB_NAME, spec, run_briefing)
        except ValueError as e:
            return f"Tool error: {e}"
        return f"Daily arXiv briefing scheduled for {spec}."
    if action == "cancel":
        return ("Daily arXiv briefing cancelled." if scheduler.cancel(JOB_NAME)
                else "The daily briefing wasn't scheduled.")
    if action == "status":
        at = scheduler.scheduled_time(JOB_NAME)
        n = len(config.ARXIV_TOPICS)
        detail = (f"Filtering on {n} research topics (single-photon sources, GKP/CV "
                  f"error correction, integrated photonics, SNSPDs, ...).")
        return (f"Daily briefing runs at {at}. {detail}" if at
                else f"No daily briefing scheduled. {detail}")
    return f"Unknown action: {action}"


@tool(
    "download_paper",
    "Download an arXiv paper as a PDF to the user's papers folder. Provide an "
    "arxiv_id like '2506.12345', OR a query of a few words from the title to "
    "match a paper from the most recent briefing (when the user says e.g. "
    "'download the GKP one' or 'save that single-photon paper').",
    {
        "type": "object",
        "properties": {
            "arxiv_id": {"type": "string", "description": "An explicit arXiv id, e.g. 2506.12345."},
            "query": {"type": "string", "description": "Words from the title of a recently-briefed paper."},
        },
    },
)
def download_paper(arxiv_id=None, query=None) -> str:
    import memory

    if not arxiv_id and query:
        words = [w for w in query.lower().split() if len(w) > 2]
        for paper in memory.last_briefing():
            if any(w in paper["title"].lower() for w in words):
                arxiv_id = paper["id"]
                break
    if not arxiv_id:
        return "I couldn't tell which paper you mean. Give me the arXiv id, or a few words from its title."

    url = f"https://arxiv.org/pdf/{arxiv_id}"
    config.PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    dest = config.PAPERS_DIR / f"{arxiv_id.replace('/', '_')}.pdf"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Orion/1.0 (research assistant)"})
        with urllib.request.urlopen(req, timeout=30) as response:
            data = response.read()
        dest.write_bytes(data)
    except Exception as e:
        return f"Download failed: {e}"
    return f"Downloaded {arxiv_id} ({len(data) // 1024} KB) to the papers folder."


@tool(
    "open_papers_folder",
    "Open the folder of downloaded arXiv papers in the file explorer. Use when "
    "the user wants to see or open their downloaded papers — e.g. 'show them to "
    "me', 'open the papers folder', 'show me the papers I saved'.",
    {"type": "object", "properties": {}},
)
def open_papers_folder() -> str:
    import os
    config.PAPERS_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(config.PAPERS_DIR.glob("*.pdf"))
    try:
        os.startfile(str(config.PAPERS_DIR))  # Windows: open in Explorer
    except Exception as e:
        return f"I couldn't open the papers folder: {e}"
    if not pdfs:
        return "Opened the papers folder — it's empty so far."
    return f"Opened the papers folder ({len(pdfs)} paper{'s' if len(pdfs) != 1 else ''})."

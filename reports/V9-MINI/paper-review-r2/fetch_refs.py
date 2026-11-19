"""Open a primary or registry page for every reference in DRAFT.md.

This script does not import check_refs.py and does not read refs-evidence/.
It fetches live pages, keeps a bibliographic excerpt, and compares the page
with the draft line. Status values are 属实 / 不符 / 未核.
"""
from __future__ import annotations

import hashlib
import json
import re
import ssl
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path("/Users/mac/AinerWorkFlow/AinerZero")
DRAFT = ROOT / "reports/V9-MINI/paper/DRAFT.md"
OUT_DIR = ROOT / "reports/V9-MINI/paper-review-r2"
LIVE = OUT_DIR / "evidence" / "live"
try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")

UA = "Mozilla/5.0 (compatible; AinerZero-ref-review/1.0; bibliographic check)"
VENUE_OK = {
    "neurips": ["neurips", "nips", "neural information processing systems"],
    "cvpr": ["cvpr", "computer vision and pattern recognition"],
    "iclr": ["iclr", "international conference on learning representations"],
    "icml": ["icml", "international conference on machine learning"],
    "icra": ["icra", "international conference on robotics and automation"],
    "ijcai": ["ijcai", "international joint conference on artificial intelligence"],
    "tmlr": ["tmlr", "transactions on machine learning research"],
    "nature": ["nature"],
    "pnas": ["pnas", "proceedings of the national academy of sciences"],
    "neurocomputing": ["neurocomputing"],
    "mit press": ["mit press"],
    "cambridge university press": ["cambridge university press"],
    "github": ["github"],
    "openreview": ["openreview"],
    "arxiv": ["arxiv"],
    "ieee transactions on robotics": ["ieee transactions on robotics"],
}


def norm(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def fetch(url: str) -> bytes:
    last = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
            with urllib.request.urlopen(req, timeout=45, context=CTX) as resp:
                return resp.read()
        except Exception as exc:  # noqa: BLE001 — recorded per source
            last = exc
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(str(last))


def save_excerpt(key: str, idx: int, url: str, body: bytes, excerpt: str) -> dict:
    LIVE.mkdir(parents=True, exist_ok=True)
    path = LIVE / f"{key}-{idx}.txt"
    path.write_text(excerpt)
    digest = hashlib.sha256(body).hexdigest()
    return {"file": str(path.relative_to(OUT_DIR)), "sha256": digest, "bytes": len(body), "url": url}


def draft_lines() -> list[str]:
    text = DRAFT.read_text()
    block = text[text.index("## References"):text.index("## Appendix A")]
    return [line[2:] for line in block.splitlines() if line.startswith("- ")]


def parse_draft(line: str) -> dict:
    cleaned = re.sub(r"arXiv:\d{4}\.\d{4,5}", "", line)
    cleaned = re.sub(r"10\.\d{4,9}/\S+", "", cleaned)
    year = int(re.search(r"(?:19|20)\d{2}", cleaned).group(0))
    if " et al. " in line:
        authors = [line.split(",")[0]]
        full = False
        rest = line.split(" et al. ", 1)[1]
    else:
        person = r"[A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)*,\s*[A-Z]\.(?:\s*[A-Z]\.)*"
        match = re.match(rf"^((?:{person})(?:\s*(?:,|&)\s*(?:{person}))*)\s+(.*)$", line)
        if not match:
            raise RuntimeError(f"cannot split authors: {line}")
        author_blob = match.group(1)
        authors = re.findall(r"([A-Z][\w'’-]+(?:\s+[A-Z][\w'’-]+)*),", author_blob)
        full = True
        rest = match.group(2)
    title, venue = rest.split(". ", 1)
    title = re.sub(r"\s*\([^)]*\)\s*$", "", title).strip()
    return {"line": line, "authors": authors, "authors_complete": full, "year": year,
            "title": title, "venue": venue.rstrip(".")}


# key -> list of (kind, argument). Kinds: arxiv, crossref, html, openreview, openreview2, github, openlibrary, listing
SOURCES = {
    "andrychowicz2017": [("arxiv", "1707.01495"), ("html", "https://proceedings.neurips.cc/paper_files/paper/2017/hash/453fadbd8a1a3af50a9df4df899537b5-Abstract.html")],
    "assran2023": [("arxiv", "2301.08243"), ("html", "https://openaccess.thecvf.com/content/CVPR2023/html/Assran_Self-Supervised_Learning_From_Images_With_a_Joint-Embedding_Predictive_Architecture_CVPR_2023_paper.html")],
    "assran2025": [("arxiv", "2506.09985")],
    "balestriero2025": [("arxiv", "2511.08544")],
    "bardes2024": [("arxiv", "2404.08471"), ("openreview2", "Revisiting Feature Prediction for Learning Visual Representations from Video")],
    "chaplot2020a": [("arxiv", "2004.05155"), ("openreview", "Learning to Explore using Active Neural SLAM")],
    "chaplot2020b": [("html", "https://openaccess.thecvf.com/content_CVPR_2020/html/Chaplot_Neural_Topological_SLAM_for_Visual_Navigation_CVPR_2020_paper.html")],
    "chen2021": [("arxiv", "2106.01345"), ("html", "https://proceedings.neurips.cc/paper_files/paper/2021/hash/7f489f642a0ddb10272b5c31057f0663-Abstract.html")],
    "davison1997": [("crossref", "10.1017/CBO9780511802843")],
    "ha2018": [("arxiv", "1803.10122")],
    "hafner2020": [("arxiv", "1912.01603"), ("openreview", "Dream to Control: Learning Behaviors by Latent Imagination")],
    "hafner2025": [("crossref", "10.1038/s41586-025-08744-2")],
    "hannun2023": [("github", "https://raw.githubusercontent.com/ml-explore/mlx/main/README.md")],
    "johannink2019": [("arxiv", "1812.03201"), ("crossref", "10.1109/ICRA.2019.8794127")],
    "kaelbling1993": [("html", "https://www.ijcai.org/proceedings/1993/151")],
    "lecun2022": [("openreview", "A Path Towards Autonomous Machine Intelligence")],
    "maes2026": [("arxiv", "2603.19312")],
    "nosek2018": [("crossref", "10.1073/pnas.1708274114")],
    "parisotto2018": [("arxiv", "1702.08360"), ("openreview", "Neural Map: Structured Memory for Deep Reinforcement Learning"), ("listing", "https://iclr.cc/Conferences/2018/Schedule?type=Poster")],
    "parisotto2020": [("arxiv", "1910.06764"), ("html", "https://proceedings.mlr.press/v119/parisotto20a.html")],
    "savinov2018": [("arxiv", "1803.00653"), ("openreview", "Semi-parametric topological memory for navigation"), ("listing", "https://iclr.cc/Conferences/2018/Schedule?type=Poster")],
    "schaul2015": [("html", "https://proceedings.mlr.press/v37/schaul15.html")],
    "shah2021": [("arxiv", "2012.09812"), ("crossref", "10.1109/ICRA48506.2021.9561936")],
    "silver2018": [("arxiv", "1812.06298")],
    "su2024": [("crossref", "10.1016/j.neucom.2023.127063")],
    "thrun2005": [("openlibrary", "0262201623")],
    "wang2023": [("html", "https://proceedings.mlr.press/v202/wang23al.html")],
    "wayne2018": [("arxiv", "1803.10760")],
    "zeng2020": [("crossref", "10.1109/TRO.2020.2988642"), ("crossref", "10.15607/RSS.2019.XV.004")],
}


def meta_map(html: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for match in re.finditer(r"<meta\s+([^>]*)>", html, re.I):
        attrs = match.group(1)
        name = re.search(r'(?:name|property)\s*=\s*"([^"]+)"', attrs, re.I)
        content = re.search(r'content\s*=\s*"([^"]*)"', attrs, re.I)
        if name and content:
            out.setdefault(name.group(1).lower(), []).append(content.group(1))
    title = re.search(r"<title>(.*?)</title>", html, re.I | re.S)
    if title:
        out.setdefault("<title>", []).append(re.sub(r"\s+", " ", title.group(1)).strip())
    return out


def parse_arxiv_entry(entry, ns) -> dict:
    title = " ".join(entry.find("a:title", ns).text.split())
    authors = [a.find("a:name", ns).text for a in entry.findall("a:author", ns)]
    year = int(entry.find("a:published", ns).text[:4])
    journal = entry.find("{http://arxiv.org/schemas/atom}journal_ref")
    venue = "arXiv" + (f" ({journal.text})" if journal is not None and journal.text else "")
    return {"title": title, "authors": authors, "year": year, "venue": venue}


def batch_arxiv(ids: list[str]) -> dict[str, dict]:
    url = "http://export.arxiv.org/api/query?max_results=50&id_list=" + ",".join(ids)
    body = fetch(url)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    root = ET.fromstring(body)
    found = {}
    for entry in root.findall("a:entry", ns):
        ident = entry.find("a:id", ns).text
        aid = ident.rsplit("/", 1)[-1]
        aid = re.sub(r"v\d+$", "", aid)
        rec = parse_arxiv_entry(entry, ns)
        rec["body"] = body
        rec["entry_xml"] = ET.tostring(entry, encoding="unicode")
        found[aid] = rec
    found["_url"] = url
    found["_body"] = body
    return found


def parse_html(url: str, body: bytes) -> dict:
    text = body.decode("utf-8", "replace")
    meta = meta_map(text)
    title = (meta.get("citation_title") or meta.get("og:title") or meta.get("<title>") or [""])[0]
    authors = meta.get("citation_author", [])
    if not authors:
        authors = re.findall(r'href="[^"]*/authors/[^"]*"[^>]*>([^<]+)</a>', text)
    date = (meta.get("citation_publication_date") or meta.get("citation_date") or meta.get("citation_year") or [""])[0]
    year = int(date[:4]) if date[:4].isdigit() else None
    if year is None:
        match = re.search(r"(?:Proceedings|IJCAI)[^<]{0,240}?(19\d\d|20\d\d)", text)
        year = int(match.group(1)) if match else None
    venue = (meta.get("citation_conference_title") or meta.get("citation_journal_title") or meta.get("citation_inbook_title") or [""])[0]
    if not venue:
        match = re.search(r"Proceedings of the [^<|]{5,180}", text)
        venue = re.sub(r"\s+", " ", match.group(0)).strip() if match else ""
    keep = []
    for chunk in re.findall(r"<title>.*?</title>|<meta\s[^>]*>", text, re.S | re.I)[:40]:
        if "description" in chunk.lower():
            continue
        keep.append(re.sub(r"\s+", " ", chunk)[:300])
    return {"title": title, "authors": authors, "year": year, "venue": venue, "excerpt": "\n".join(keep[:25]), "text": text}


def parse_crossref(body: bytes) -> dict:
    message = json.loads(body)["message"]
    title = (message.get("title") or [""])[0]
    authors = []
    for author in message.get("author", message.get("editor", [])):
        authors.append(author.get("family") or author.get("name") or "")
    issued = (message.get("issued") or message.get("published") or {}).get("date-parts", [[None]])[0][0]
    venue = (message.get("container-title") or [None])[0] or (message.get("event") or {}).get("name") or message.get("publisher")
    excerpt = json.dumps({
        "title": message.get("title"),
        "author": message.get("author", message.get("editor")),
        "issued": message.get("issued"),
        "container-title": message.get("container-title"),
        "publisher": message.get("publisher"),
        "type": message.get("type"),
        "event": message.get("event"),
        "DOI": message.get("DOI"),
    }, ensure_ascii=False, indent=1)
    return {"title": title, "authors": authors, "year": issued, "venue": venue, "excerpt": excerpt}


def parse_openreview(body: bytes, query: str) -> dict:
    notes = json.loads(body).get("notes", [])
    value = lambda item: item.get("value") if isinstance(item, dict) else item
    hits = [note for note in notes if norm(str(value(note.get("content", {}).get("title", "")))) == norm(query)]
    if not hits:
        return {"title": "", "authors": [], "year": None, "venue": "", "excerpt": body[:500].decode("utf-8", "replace"), "error": "no note with this title"}
    def rank(note):
        venue = str(value(note.get("content", {}).get("venue")) or "")
        invitation = str(note.get("invitation") or note.get("invitations"))
        return ("dblp" not in invitation, venue == "", invitation)
    note = sorted(hits, key=rank)[0]
    content = note["content"]
    stamp = note.get("pdate") or note.get("odate") or note.get("cdate") or note.get("tcdate")
    year = time.gmtime(stamp / 1000).tm_year if stamp else None
    authors = value(content.get("authors", [])) or []
    venue = value(content.get("venue")) or ""
    invitation = note.get("invitation") or note.get("invitations")
    excerpt = json.dumps({
        "id": note.get("id"), "forum": note.get("forum"), "invitation": invitation,
        "title": value(content.get("title")), "authors": authors, "venue": venue,
        "pdate": note.get("pdate"), "cdate": note.get("cdate"),
    }, ensure_ascii=False, indent=1)
    return {"title": str(value(content.get("title"))), "authors": list(authors), "year": year,
            "venue": str(venue), "excerpt": excerpt, "forum": note.get("forum")}


def parse_github(body: bytes) -> dict:
    text = body.decode("utf-8", "replace")
    match = re.search(r"@software\{[^@]*?\n\}", text, re.S)
    if not match:
        return {"title": "", "authors": [], "year": None, "venue": "", "excerpt": "", "error": "no citation block"}
    block = match.group(0)
    title = re.search(r"title\s*=\s*\{(.*)\}", block).group(1).replace("{", "").replace("}", "")
    authors = [part.strip() for part in re.search(r"author\s*=\s*\{(.*)\}", block).group(1).split(" and ")]
    year = int(re.search(r"year\s*=\s*\{(\d{4})\}", block).group(1))
    return {"title": title, "authors": authors, "year": year, "venue": "GitHub", "excerpt": block}


def parse_openlibrary(isbn: str, body: bytes, fetch_fn) -> dict:
    data = json.loads(body)
    names = []
    excerpts = [json.dumps({k: data.get(k) for k in ("title", "authors", "publish_date", "publishers", "by_statement")}, ensure_ascii=False, indent=1)]
    by = data.get("by_statement", "")
    if by:
        names = [part.strip() for part in re.split(r",|\band\b", by.rstrip(".")) if part.strip()]
    else:
        for author in data.get("authors", []):
            raw = fetch_fn("https://openlibrary.org" + author["key"] + ".json")
            person = json.loads(raw)
            names.append(person.get("name", ""))
            excerpts.append(person.get("name", ""))
    year_m = re.search(r"(?:19|20)\d{2}", data.get("publish_date", ""))
    return {"title": data.get("title", ""), "authors": names, "year": int(year_m.group(0)) if year_m else None,
            "venue": "; ".join(data.get("publishers", [])), "excerpt": "\n".join(excerpts), "extra_bodies": []}


def parse_listing(url: str, title: str, body: bytes) -> dict:
    text = body.decode("utf-8", "replace")
    pos = text.lower().find(title.lower())
    if pos < 0:
        return {"title": "", "authors": [], "year": None, "venue": "", "excerpt": "", "error": "title not on listing page"}
    page_title = re.search(r"<title>(.*?)</title>", text, re.S)
    page_title = re.sub(r"\s+", " ", page_title.group(1)).strip() if page_title else ""
    year_m = re.search(r"(?:19|20)\d{2}", page_title)
    window = text[max(0, pos - 800):pos + 800]
    plain = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " | ", window))
    return {"title": title, "authors": [], "year": int(year_m.group(0)) if year_m else None,
            "venue": page_title, "excerpt": plain[:1500], "listed": True}


def author_tail(name: str) -> list[str]:
    name = name.strip()
    if "," in name:
        return norm(name.split(",")[0]).split()
    return norm(name).split()


def author_matches(expected: str, got: str) -> bool:
    exp = norm(expected).split()
    got_tokens = author_tail(got)
    return len(got_tokens) >= len(exp) and got_tokens[-len(exp):] == exp


def title_ok(got: str, expected: str) -> bool:
    return norm(expected) == norm(got) or norm(expected) in norm(got)


def authors_ok(got_authors: list[str], expected: list[str], complete: bool) -> tuple[bool, str]:
    if not got_authors:
        return False, "no authors on page"
    first_ok = author_matches(expected[0], got_authors[0])
    if not complete:
        return first_ok, "" if first_ok else f"first author page={got_authors[0]!r} draft={expected[0]!r}"
    if len(got_authors) != len(expected):
        return False, f"author count page={got_authors} draft={expected}"
    bad = [f"{e}!={g}" for e, g in zip(expected, got_authors) if not author_matches(e, g)]
    return not bad and first_ok, "; ".join(bad)


def venue_ok(draft_venue: str, page_venue: str, year_only_arxiv: bool) -> tuple[bool, str]:
    blob = norm(draft_venue + " " + (page_venue or ""))
    page = norm(page_venue or "")
    if year_only_arxiv:
        return "arxiv" in page or "arxiv" in norm(draft_venue), page_venue
    for label, keys in VENUE_OK.items():
        if any(k in norm(draft_venue) for k in keys):
            if any(k in page or k in blob for k in keys):
                return True, ""
            return False, f"draft venue {label!r} not in page venue {page_venue!r}"
    # arXiv id in the draft venue is enough when the page is arXiv
    if "arxiv" in norm(draft_venue) and "arxiv" in page:
        return True, ""
    return False, f"unmapped venue draft={draft_venue!r} page={page_venue!r}"


def main() -> int:
    lines = draft_lines()
    print(f"draft_reference_lines {len(lines)}")
    keys = list(SOURCES)
    print(f"source_keys {len(keys)}")
    if len(lines) != 29 or len(keys) != 29:
        print("REF_COUNT_ERROR")
    arxiv_ids = []
    for items in SOURCES.values():
        for kind, arg in items:
            if kind == "arxiv":
                arxiv_ids.append(arg)
    print(f"arxiv_batch_count {len(arxiv_ids)}")
    arxiv = batch_arxiv(arxiv_ids)
    print(f"arxiv_batch_got {len([k for k in arxiv if not k.startswith('_')])}")
    # one saved record for the batch
    LIVE.mkdir(parents=True, exist_ok=True)
    (LIVE / "arxiv-batch.src.txt").write_text(
        f"{arxiv['_url']}\nfull response: {len(arxiv['_body'])} bytes, sha256 {hashlib.sha256(arxiv['_body']).hexdigest()}\n"
    )
    listing_cache: dict[str, bytes] = {}
    last_call = 0.0
    results = {}
    parsed_lines = [parse_draft(line) for line in lines]
    TITLE_HINT = {
        "andrychowicz2017": "hindsight experience replay",
        "assran2023": "self-supervised learning from images",
        "assran2025": "v-jepa 2",
        "balestriero2025": "lejepa",
        "bardes2024": "revisiting feature prediction",
        "chaplot2020a": "active neural slam",
        "chaplot2020b": "neural topological slam",
        "chen2021": "decision transformer",
        "davison1997": "bootstrap methods and their application",
        "ha2018": "world models",
        "hafner2020": "dream to control",
        "hafner2025": "mastering diverse control tasks",
        "hannun2023": "mlx",
        "johannink2019": "residual reinforcement learning",
        "kaelbling1993": "learning to achieve goals",
        "lecun2022": "autonomous machine intelligence",
        "maes2026": "leworldmodel",
        "nosek2018": "preregistration revolution",
        "parisotto2018": "neural map",
        "parisotto2020": "stabilizing transformers",
        "savinov2018": "semi-parametric topological memory",
        "schaul2015": "universal value function approximators",
        "shah2021": "ving",
        "silver2018": "residual policy learning",
        "su2024": "roformer",
        "thrun2005": "probabilistic robotics",
        "wang2023": "quasimetric learning",
        "wayne2018": "unsupervised predictive memory",
        "zeng2020": "tossingbot",
    }
    line_by_key = {}
    used = set()
    for key, hint in TITLE_HINT.items():
        hits = [row for row in parsed_lines if hint in norm(row["title"])]
        if len(hits) > 1:
            hits = [row for row in hits if norm(row["title"]).startswith(hint)] or hits
        if len(hits) != 1:
            print(f"DRAFT_MATCH {key} hits {len(hits)}")
            line_by_key[key] = hits[0] if len(hits) == 1 else None
        else:
            line_by_key[key] = hits[0]
            used.add(hits[0]["line"])
    print(f"draft_lines_matched {len(used)} unmatched {len(lines) - len(used)}")

    for key, sources in SOURCES.items():
        draft = line_by_key[key]
        rec = {"draft_line": draft["line"] if draft else "", "expected_from_draft": draft, "sources": [], "problems": []}
        for idx, (kind, arg) in enumerate(sources):
            try:
                if kind == "arxiv":
                    got = arxiv.get(arg)
                    if not got:
                        raise RuntimeError("missing from arxiv batch")
                    body = got["entry_xml"].encode()
                    excerpt = got["entry_xml"][:2000]
                    url = f"https://arxiv.org/abs/{arg}"
                    parsed = {k: got[k] for k in ("title", "authors", "year", "venue")}
                elif kind == "crossref":
                    url = "https://api.crossref.org/works/" + urllib.parse.quote(arg)
                    now = time.time()
                    if now - last_call < 0.4:
                        time.sleep(0.4)
                    last_call = time.time()
                    body = fetch(url)
                    parsed = parse_crossref(body)
                    excerpt = parsed["excerpt"]
                elif kind == "html":
                    url = arg
                    body = fetch(url)
                    parsed = parse_html(url, body)
                    excerpt = parsed["excerpt"]
                elif kind in ("openreview", "openreview2"):
                    host = "api.openreview.net" if kind == "openreview" else "api2.openreview.net"
                    url = f"https://{host}/notes/search?term={urllib.parse.quote(arg)}&limit=10"
                    wait = 3.2 - (time.time() - last_call)
                    if wait > 0:
                        time.sleep(wait)
                    last_call = time.time()
                    body = fetch(url)
                    parsed = parse_openreview(body, arg)
                    excerpt = parsed["excerpt"]
                    if parsed.get("forum"):
                        url = f"https://openreview.net/forum?id={parsed['forum']}"
                elif kind == "github":
                    url = arg
                    body = fetch(url)
                    parsed = parse_github(body)
                    excerpt = parsed["excerpt"]
                elif kind == "openlibrary":
                    url = f"https://openlibrary.org/isbn/{arg}.json"
                    body = fetch(url)
                    parsed = parse_openlibrary(arg, body, fetch)
                    excerpt = parsed["excerpt"]
                elif kind == "listing":
                    url = arg
                    if url not in listing_cache:
                        listing_cache[url] = fetch(url)
                    body = listing_cache[url]
                    parsed = parse_listing(url, draft["title"] if draft else arg, body)
                    excerpt = parsed["excerpt"]
                else:
                    raise RuntimeError(kind)
            except Exception as exc:  # noqa: BLE001
                rec["sources"].append({"kind": kind, "arg": arg, "error": str(exc)})
                rec["problems"].append(f"{kind} {arg}: {exc}")
                print(f"FETCH_FAIL {key} {kind} {arg} {exc}")
                continue
            meta = save_excerpt(key, idx, url, body if isinstance(body, bytes) else str(body).encode(), excerpt if isinstance(excerpt, str) else str(excerpt))
            problems = []
            if parsed.get("error"):
                problems.append(parsed["error"])
            if draft and parsed.get("title") and not title_ok(parsed["title"], draft["title"]):
                problems.append(f"title page={parsed['title']!r}")
            if draft and parsed.get("authors"):
                ok, why = authors_ok(parsed["authors"], draft["authors"], draft["authors_complete"])
                if not ok:
                    problems.append("authors " + why)
            if draft and parsed.get("year") is not None and int(parsed["year"]) != draft["year"]:
                # arXiv of a venue paper can be a prior year; record it but only fail the venue page's year
                if kind == "arxiv" and any(k != "arxiv" for k, _ in sources):
                    problems.append(f"arxiv year {parsed['year']} (draft year {draft['year']}; venue source also checked)")
                else:
                    problems.append(f"year {parsed['year']}")
            year_only = kind == "arxiv" and all(k == "arxiv" for k, _ in sources)
            if draft and kind != "arxiv" and not parsed.get("error"):
                if not str(parsed.get("venue") or "").strip():
                    problems.append("venue missing")
                else:
                    ok, why = venue_ok(draft["venue"], str(parsed["venue"]), False)
                    if not ok:
                        problems.append("venue " + why)
            if year_only and draft:
                ok, why = venue_ok(draft["venue"], str(parsed.get("venue")), True)
                if not ok:
                    problems.append("venue " + why)
            source_rec = {"kind": kind, "arg": arg, "url": url, **{k: parsed.get(k) for k in ("title", "authors", "year", "venue")},
                          "evidence": meta, "problems": problems}
            rec["sources"].append(source_rec)
            rec["problems"].extend(f"{kind}: {p}" for p in problems)
            print(f"SOURCE {key} {kind} year={parsed.get('year')} venue={parsed.get('venue')!r} title={parsed.get('title')!r} authors={parsed.get('authors')}")
            if problems:
                print(f"PROBLEM {key} {problems}")
        # A reference is 属实 when at least one source has no problems and no source that was required failed closed.
        # Year notes on an arXiv twin of a venue paper do not by themselves make the entry 不符 if another source is clean
        # and the arXiv title and first author match.
        soft_prefixes = ("arxiv year", "venue missing", "title not", "no note", "no authors")
        hard = []
        for item in rec["problems"]:
            body = item.split(": ", 1)[-1]
            if body.startswith(soft_prefixes) or "venue source also checked" in item:
                continue
            if item.startswith(("html ", "arxiv ", "crossref ", "openreview", "github ", "openlibrary ", "listing ")):
                # fetch exception text, not a bibliographic contradiction
                if "title page=" not in item and not item.split(": ", 1)[-1].startswith(("authors ", "year ", "venue ")):
                    continue
            hard.append(item)
        clean = [s for s in rec["sources"] if not s.get("problems") and "error" not in s]
        if hard:
            rec["status"] = "不符"
        elif clean:
            rec["status"] = "属实"
        else:
            rec["status"] = "未核"
        rec["problems_hard"] = hard
        results[key] = rec
        print(f"STATUS {key} {rec['status']}")

    (OUT_DIR / "refs.json").write_text(json.dumps(results, ensure_ascii=False, indent=1))
    counts = __import__("collections").Counter(r["status"] for r in results.values())
    print(f"SUMMARY {dict(counts)} of {len(results)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

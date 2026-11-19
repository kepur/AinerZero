"""Check every reference of DRAFT.md against primary or registry sources, and keep the raw responses.

For each reference this script fetches one or more sources (arXiv API, Crossref DOI records, the proceedings page
with its citation_* metadata, OpenReview search, the MLX README, Open Library), saves every raw response under
refs-evidence/, extracts title, authors, year and venue, and compares them with the expected entry below.
It also checks that the reference line in DRAFT.md contains the expected title, first author and year.

  .venv/bin/python reports/V9-MINI/paper/check_refs.py            # fetch, save evidence, compare
  .venv/bin/python reports/V9-MINI/paper/check_refs.py --offline  # re-parse the saved evidence only

Output: refs-check.txt (readable) and refs-check.json (with the SHA-256 of every evidence file).
Only public bibliographic pages are requested; no user or project information is sent.
"""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import ssl
import sys
import time
import unicodedata
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

HERE = Path(__file__).resolve().parent
EV = HERE / "refs-evidence"
UA = "Mozilla/5.0 (compatible; ref-check/0.1)"
# Certificates are verified; python.org builds on macOS ship without a CA store, so use certifi or the system file.
try:
    import certifi
    CTX = ssl.create_default_context(cafile=certifi.where())
except ImportError:
    CTX = ssl.create_default_context(cafile="/etc/ssl/cert.pem")

NEURIPS = ["Neural Information Processing Systems", "NeurIPS", "NIPS"]
ICML = ["International Conference on Machine Learning", "ICML"]
CVPR = ["Computer Vision and Pattern Recognition", "CVPR"]
ICRA = ["International Conference on Robotics and Automation", "ICRA"]
ICLR18 = "https://iclr.cc/Conferences/2018/Schedule?type=Poster"

# key: (expected title, first-author surname, year, accepted venue strings or None, all surnames or None, sources)
# A source is (kind, argument, {"year": bool, "venue": bool}); arXiv preprints of venue papers check title and author only.
TITLE_ONLY = {"year": False, "venue": False}
REFS = {
    "andrychowicz2017": ("Hindsight experience replay", "Andrychowicz", 2017, NEURIPS, None, [
        ("html", "https://proceedings.neurips.cc/paper_files/paper/2017/hash/453fadbd8a1a3af50a9df4df899537b5-Abstract.html", {}),
        ("arxiv", "1707.01495", TITLE_ONLY)]),
    "assran2023": ("Self-supervised learning from images with a joint-embedding predictive architecture", "Assran", 2023, CVPR, None, [
        ("html", "https://openaccess.thecvf.com/content/CVPR2023/html/Assran_Self-Supervised_Learning_From_Images_With_a_Joint-Embedding_Predictive_Architecture_CVPR_2023_paper.html", {}),
        ("arxiv", "2301.08243", TITLE_ONLY)]),
    "assran2025": ("V-JEPA 2: self-supervised video models enable understanding, prediction and planning", "Assran", 2025, None, None, [
        ("arxiv", "2506.09985", {})]),
    "balestriero2025": ("LeJEPA: provable and scalable self-supervised learning without the heuristics", "Balestriero", 2025, None,
                        ["Balestriero", "LeCun"], [("arxiv", "2511.08544", {})]),
    "bardes2024": ("Revisiting feature prediction for learning visual representations from video", "Bardes", 2024,
                   ["TMLR", "Transactions on Machine Learning Research"], None, [
        ("openreview2", "Revisiting Feature Prediction for Learning Visual Representations from Video", {}),
        ("arxiv", "2404.08471", TITLE_ONLY)]),
    "chaplot2020a": ("Learning to explore using Active Neural SLAM", "Chaplot", 2020, ["ICLR 2020"], None, [
        ("openreview1", "Learning to Explore using Active Neural SLAM", {}),
        ("arxiv", "2004.05155", TITLE_ONLY)]),
    "chaplot2020b": ("Neural topological SLAM for visual navigation", "Chaplot", 2020, CVPR, None, [
        ("html", "https://openaccess.thecvf.com/content_CVPR_2020/html/Chaplot_Neural_Topological_SLAM_for_Visual_Navigation_CVPR_2020_paper.html", {})]),
    "chen2021": ("Decision Transformer: reinforcement learning via sequence modeling", "Chen", 2021, NEURIPS, None, [
        ("html", "https://proceedings.neurips.cc/paper_files/paper/2021/hash/7f489f642a0ddb10272b5c31057f0663-Abstract.html", {}),
        ("arxiv", "2106.01345", TITLE_ONLY)]),
    "davison1997": ("Bootstrap methods and their application", "Davison", 1997, ["Cambridge University Press"], ["Davison", "Hinkley"], [
        ("crossref", "10.1017/CBO9780511802843", {})]),
    "ha2018": ("World models", "Ha", 2018, None, ["Ha", "Schmidhuber"], [("arxiv", "1803.10122", {})]),
    "hafner2020": ("Dream to control: learning behaviors by latent imagination", "Hafner", 2020, ["ICLR 2020"], None, [
        ("openreview1", "Dream to Control: Learning Behaviors by Latent Imagination", {}),
        ("arxiv", "1912.01603", TITLE_ONLY)]),
    "hafner2025": ("Mastering diverse control tasks through world models", "Hafner", 2025, ["Science"], None, [
        ("crossref", "10.1038/s41586-025-08744-2", {})]),
    "hannun2023": ("MLX: efficient and flexible machine learning on Apple silicon", "Hannun", 2023, ["github"],
                   ["Hannun", "Digani", "Katharopoulos", "Collobert"], [
        ("github", "https://raw.githubusercontent.com/ml-explore/mlx/main/README.md", {})]),
    "johannink2019": ("Residual reinforcement learning for robot control", "Johannink", 2019, ICRA, None, [
        ("crossref", "10.1109/ICRA.2019.8794127", {}), ("arxiv", "1812.03201", TITLE_ONLY)]),
    "kaelbling1993": ("Learning to achieve goals", "Kaelbling", 1993, ["IJCAI", "International Joint Conference on Artificial Intelligence"], None, [
        ("html", "https://www.ijcai.org/proceedings/1993/151", {})]),
    "lecun2022": ("A path towards autonomous machine intelligence", "LeCun", 2022, ["OpenReview.net/Archive"], ["LeCun"], [
        ("openreview1", "A Path Towards Autonomous Machine Intelligence", {})]),
    "maes2026": ("LeWorldModel: stable end-to-end joint-embedding predictive architecture from pixels", "Maes", 2026, None,
                 ["Maes", "Le Lidec", "Scieur", "LeCun", "Balestriero"], [("arxiv", "2603.19312", {})]),
    "nosek2018": ("The preregistration revolution", "Nosek", 2018, ["Proceedings of the National Academy of Sciences"], None, [
        ("crossref", "10.1073/pnas.1708274114", {})]),
    "parisotto2018": ("Neural Map: structured memory for deep reinforcement learning", "Parisotto", 2018, ["ICLR 2018"],
                      ["Parisotto", "Salakhutdinov"], [
        ("openreview1", "Neural Map: Structured Memory for Deep Reinforcement Learning", {"venue": False}),
        ("listing", ICLR18, {}), ("arxiv", "1702.08360", TITLE_ONLY)]),
    "parisotto2020": ("Stabilizing transformers for reinforcement learning", "Parisotto", 2020, ICML, None, [
        ("html", "https://proceedings.mlr.press/v119/parisotto20a.html", {}), ("arxiv", "1910.06764", TITLE_ONLY)]),
    "savinov2018": ("Semi-parametric topological memory for navigation", "Savinov", 2018, ["ICLR 2018"],
                    ["Savinov", "Dosovitskiy", "Koltun"], [
        ("openreview1", "Semi-parametric topological memory for navigation", {"venue": False}),
        ("listing", ICLR18, {}), ("arxiv", "1803.00653", TITLE_ONLY)]),
    "schaul2015": ("Universal value function approximators", "Schaul", 2015, ICML, None, [
        ("html", "https://proceedings.mlr.press/v37/schaul15.html", {})]),
    "shah2021": ("ViNG: learning open-world navigation with visual goals", "Shah", 2021, ICRA, None, [
        ("crossref", "10.1109/ICRA48506.2021.9561936", {}), ("arxiv", "2012.09812", TITLE_ONLY)]),
    "silver2018": ("Residual policy learning", "Silver", 2018, None, None, [("arxiv", "1812.06298", {})]),
    "su2024": ("RoFormer: enhanced transformer with rotary position embedding", "Su", 2024, ["Neurocomputing"], None, [
        ("crossref", "10.1016/j.neucom.2023.127063", {})]),
    "thrun2005": ("Probabilistic robotics", "Thrun", 2005, ["MIT Press"], ["Thrun", "Burgard", "Fox"], [("openlibrary", "0262201623", {})]),
    "wang2023": ("Optimal goal-reaching reinforcement learning via quasimetric learning", "Wang", 2023, ICML, None, [
        ("html", "https://proceedings.mlr.press/v202/wang23al.html", {})]),
    "wayne2018": ("Unsupervised predictive memory in a goal-directed agent", "Wayne", 2018, None, None, [("arxiv", "1803.10760", {})]),
    "zeng2020": ("TossingBot: learning to throw arbitrary objects with residual physics", "Zeng", 2020, ["IEEE Transactions on Robotics"], None, [
        ("crossref", "10.1109/TRO.2020.2988642", {}),
        ("crossref", "10.15607/RSS.2019.XV.004", {"year": False, "venue": False})]),
}


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", html.unescape(t)).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()


_last_arxiv = [0.0]
_pages: dict[str, str] = {}


def trim(path: Path, body: bytes, extra: str = "") -> bytes:
    """Keep only the bibliographic part of a response (no abstracts or full pages from third parties).

    The SHA-256 and size of the full response are written next to it in <file>.src.txt.
    """
    kind = path.suffix
    if kind == ".xml":  # arXiv Atom: drop the abstract
        t = re.sub(rb"<summary>.*?</summary>", b"<summary>[removed]</summary>", body, flags=re.S)
    elif kind == ".html":  # proceedings pages: keep the title, the meta tags and author links
        s = body.decode("utf-8", "replace")
        keep = re.findall(r"<title>.*?</title>|<meta\s[^>]*>|<a[^>]*/authors/[^>]*>[^<]*</a>", s, re.S | re.I)
        keep = [k for k in keep if "description" not in k.lower() and "abstract\"" not in k.lower()]
        t = "\n".join(keep).encode()
    elif kind == ".json":
        d = json.loads(body)
        if isinstance(d.get("message"), dict):  # Crossref: drop abstract and reference list
            for k in ("abstract", "reference"):
                d["message"].pop(k, None)
        if isinstance(d.get("notes"), list):  # OpenReview search: keep notes with the queried title, bibliographic fields only
            v = lambda x: x.get("value") if isinstance(x, dict) else x
            d = {"notes": [{**{k: n.get(k) for k in ("id", "forum", "invitation", "invitations", "cdate", "pdate", "odate", "tcdate")},
                            "content": {k: n["content"].get(k) for k in ("title", "authors", "venue", "venueid") if k in n["content"]}}
                           for n in d["notes"] if norm(v(n["content"].get("title", ""))) == norm(extra)]}
        t = json.dumps(d, indent=1, ensure_ascii=False).encode()
    elif kind == ".md":  # MLX README: keep the citation block
        m = re.search(rb"@software\{[^@]*?\n\}", body, re.S)
        t = m.group(0) if m else b""
    else:
        t = body
    return t


def fetch(url: str, path: Path, offline: bool, extra: str = "") -> bytes:
    if offline:
        return path.read_bytes()
    if "export.arxiv.org" in url or "openreview.net" in url:
        wait = 3.5 - (time.time() - _last_arxiv[0])
        if wait > 0:
            time.sleep(wait)
        _last_arxiv[0] = time.time()
    err = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=40, context=CTX) as r:
                body = r.read()
            if path.suffix == ".tmp":
                return body
            t = trim(path, body, extra)
            path.write_bytes(t)
            Path(str(path) + ".src.txt").write_text(f"{url}\nfull response: {len(body)} bytes, sha256 {hashlib.sha256(body).hexdigest()}\n"
                                                   f"saved: {'trimmed to bibliographic fields' if t != body else 'unchanged'}\n")
            return t
        except Exception as e:  # network errors are reported per source
            err = e
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"fetch failed: {err}")


def meta_tags(s: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for m in re.finditer(r"<meta\s+([^>]*)>", s, re.I):
        a = m.group(1)
        n = re.search(r'(?:name|property)\s*=\s*"([^"]+)"', a, re.I)
        c = re.search(r'content\s*=\s*"([^"]*)"', a, re.I)
        if n and c:
            out.setdefault(n.group(1).lower(), []).append(html.unescape(c.group(1)))
    t = re.search(r"<title>(.*?)</title>", s, re.I | re.S)
    if t:
        out.setdefault("<title>", []).append(html.unescape(t.group(1)).strip())
    return out


def parse(kind: str, arg: str, key: str, i: int, offline: bool, title: str = "", venues=None) -> dict:
    if kind == "arxiv":
        url = f"http://export.arxiv.org/api/query?id_list={arg}"
        body = fetch(url, EV / f"{key}-{i}.xml", offline)
        ns = {"a": "http://www.w3.org/2005/Atom", "x": "http://arxiv.org/schemas/atom"}
        e = ET.fromstring(body).find("a:entry", ns)
        if e is None or e.find("a:title", ns) is None:
            raise RuntimeError("no arXiv entry")
        jr = e.find("x:journal_ref", ns)
        return {"url": f"https://arxiv.org/abs/{arg}", "title": " ".join(e.find("a:title", ns).text.split()),
                "authors": [a.find("a:name", ns).text for a in e.findall("a:author", ns)],
                "year": int(e.find("a:published", ns).text[:4]), "venue": "arXiv" + (f" ({jr.text})" if jr is not None else "")}
    if kind == "crossref":
        url = f"https://api.crossref.org/works/{urllib.parse.quote(arg)}"
        m = json.loads(fetch(url, EV / f"{key}-{i}.json", offline))["message"]
        venue = (m.get("container-title") or [None])[0] or (m.get("event") or {}).get("name") or m.get("publisher")
        y = (m.get("issued") or m.get("published") or {}).get("date-parts", [[None]])[0][0]
        auth = [a.get("family") or a.get("name") for a in m.get("author", m.get("editor", []))]
        return {"url": f"https://doi.org/{arg}", "title": (m.get("title") or [""])[0], "authors": auth, "year": y,
                "venue": venue, "note": f"publisher: {m.get('publisher')}; type: {m.get('type')}"}
    if kind == "html":
        s = fetch(arg, EV / f"{key}-{i}.html", offline).decode("utf-8", "replace")
        mt = meta_tags(s)
        title = (mt.get("citation_title") or mt.get("og:title") or mt.get("<title>") or [""])[0]
        authors = mt.get("citation_author", [])
        authors = [(a.split(",")[0] if "," in a else a.split()[-1]) for a in authors]
        if not authors:  # IJCAI pages: authors are links to /authors/
            authors = [html.unescape(x).split()[-1] for x in re.findall(r'href="[^"]*/authors/[^"]*/">([^<]+)</a>', s)]
        date = (mt.get("citation_publication_date") or mt.get("citation_date") or mt.get("citation_year") or [""])[0]
        y = int(date[:4]) if date[:4].isdigit() else None
        if y is None:
            m = re.search(r"(?:Proceedings|IJCAI)[^<]{0,200}?(19\d\d|20\d\d)", s)
            y = int(m.group(1)) if m else None
        venue = (mt.get("citation_conference_title") or mt.get("citation_journal_title") or mt.get("citation_inbook_title") or [""])[0]
        if not venue:
            m = re.search(r"Proceedings of the [^<|]{5,160}", s)
            venue = m.group(0).strip() if m else ""
        return {"url": arg, "title": title, "authors": authors, "year": y, "venue": venue}
    if kind in ("openreview1", "openreview2"):
        host = "api.openreview.net" if kind == "openreview1" else "api2.openreview.net"
        url = f"https://{host}/notes/search?term={urllib.parse.quote(arg)}&limit=10"
        notes = json.loads(fetch(url, EV / f"{key}-{i}.json", offline, arg))["notes"]
        val = lambda v: v.get("value") if isinstance(v, dict) else v
        hit = [n for n in notes if norm(val(n["content"].get("title", ""))) == norm(arg)]
        if not hit:
            raise RuntimeError("no OpenReview note with this title")
        # Prefer a record that states an expected venue (OpenReview's dblp mirror records do), then dblp records,
        # then the original submission. A record of someone else's report on the paper fails the author check.
        says = lambda n: bool(venues) and any(v.lower() in str(val(n["content"].get("venue")) or "").lower() for v in venues)
        n = sorted(hit, key=lambda n: (not says(n), "dblp" not in str(n.get("invitation")), str(n.get("invitation"))))[0]
        c = n["content"]
        t = n.get("pdate") or n.get("odate") or n.get("cdate") or n.get("tcdate")
        y = time.gmtime(t / 1000).tm_year if t else None
        inv = n.get("invitation") or n.get("invitations")
        # The venue is the record's own venue field; a record without one (an archive upload, or a submission
        # whose decision is not in the record) falls back to its invitation, which is shown as such.
        venue = val(c.get("venue")) or f"(no venue field) invitation {inv}"
        return {"url": f"https://openreview.net/forum?id={n['forum']}", "title": val(c["title"]),
                "authors": [a.split()[-1] for a in val(c.get("authors", []))],
                "year": y, "venue": venue, "note": f"invitation: {inv}"}
    if kind == "listing":
        exc = EV / f"{key}-{i}.excerpt.html"
        if offline:
            s = exc.read_text()
        else:
            if arg not in _pages:
                _pages[arg] = fetch(arg, EV / "_page.tmp", False).decode("utf-8", "replace")
            full = _pages[arg]
            j = full.lower().find(title.lower())
            if j < 0:
                raise RuntimeError("title not found on the listing page")
            t = re.search(r"<title>.*?</title>", full, re.S).group(0)
            s = (f"<!-- excerpt of {arg}; full page {len(full.encode())} bytes, sha256 "
                 f"{hashlib.sha256(full.encode()).hexdigest()} -->\n{t}\n{full[max(0, j - 1500):j + 1500]}\n")
            exc.write_text(s)
        text = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " | ", s)))
        j = text.lower().find(title.lower())
        if j < 0:
            raise RuntimeError("title not found in the excerpt")
        after = [x.strip() for x in text[j + len(title):].split("|") if x.strip()]
        names = next((x for x in after if "·" in x), "")
        page_title = re.search(r"<title>(.*?)</title>", s, re.S).group(1).strip()
        y = re.search(r"(19|20)\d\d", page_title)
        return {"url": arg, "title": text[j:j + len(title)], "authors": [a.strip().split()[-1] for a in names.split("·") if a.strip()],
                "year": int(y.group(0)) if y else None, "venue": f"{page_title} (poster listing)"}
    if kind == "github":
        s = fetch(arg, EV / f"{key}-{i}.md", offline).decode()
        b = re.search(r"@software\{[^@]*?\n\}", s, re.S)
        if not b:
            raise RuntimeError("no citation block in README")
        b = b.group(0)
        title = re.search(r"title\s*=\s*\{(.*)\},", b).group(1).replace("{", "").replace("}", "")
        auth = [a.strip().split()[-1] for a in re.search(r"author\s*=\s*\{(.*?)\},", b).group(1).split(" and ")]
        return {"url": "https://github.com/ml-explore/mlx", "title": title, "authors": auth,
                "year": int(re.search(r"year\s*=\s*\{(\d{4})\}", b).group(1)), "venue": "github (README citation block)"}
    if kind == "openlibrary":
        d = json.loads(fetch(f"https://openlibrary.org/isbn/{arg}.json", EV / f"{key}-{i}.json", offline))
        names = []
        for j, a in enumerate(d.get("authors", [])):
            ad = json.loads(fetch(f"https://openlibrary.org{a['key']}.json", EV / f"{key}-{i}-author{j}.json", offline))
            names.append(ad["name"].split()[-1])
        by = d.get("by_statement", "").rstrip(". ")
        if by:  # the record links only the first author; the statement of responsibility lists all of them
            names = [x.strip().split()[-1] for x in re.split(r",|\band\b", by) if x.strip()]
        y = re.search(r"(19|20)\d\d", d.get("publish_date", ""))
        return {"url": f"https://openlibrary.org/isbn/{arg}", "title": d.get("title", ""), "authors": names,
                "year": int(y.group(0)) if y else None, "venue": "; ".join(d.get("publishers", [])),
                "note": f"by_statement: {d.get('by_statement', '')}"}
    raise ValueError(kind)


def draft_refs() -> list[str]:
    s = (HERE / "DRAFT.md").read_text()
    sec = s[s.index("## References"):s.index("## Appendix A")]
    return [ln[2:] for ln in sec.splitlines() if ln.startswith("- ")]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true")
    args = ap.parse_args()
    EV.mkdir(exist_ok=True)
    lines = draft_refs()
    out, report, bad = {}, [], 0
    used_lines = set()
    for key, (title, first, year, venues, surnames, sources) in REFS.items():
        rec = {"expected": {"title": title, "first_author": first, "year": year, "venues": venues, "authors": surnames},
               "sources": [], "problems": []}
        dl = [ln for ln in lines if ln.startswith(first + ",") and norm(title) in norm(ln)]
        if len(dl) != 1:
            rec["problems"].append(f"draft: {len(dl)} reference lines with this first author and title")
        else:
            used_lines.add(dl[0])
            rec["draft_line"] = dl[0]
            if str(year) not in dl[0]:
                rec["problems"].append(f"draft: year {year} not in the reference line")
        for i, (kind, arg, chk) in enumerate(sources):
            try:
                got = parse(kind, arg, key, i, args.offline, title, venues)
            except Exception as e:
                rec["sources"].append({"kind": kind, "arg": arg, "error": str(e)})
                rec["problems"].append(f"{kind} {arg}: {e}")
                continue
            p = []
            if norm(got["title"]) != norm(title):
                p.append(f"title {got['title']!r}")
            if not got["authors"] or norm(first) not in norm(got["authors"][0]):
                p.append(f"first author {got['authors'][:1]}")
            # Full author list (only for references written with every author): same count, same order.
            if surnames and chk is not TITLE_ONLY:
                if len(got["authors"]) != len(surnames) or not all(norm(x) in norm(a) for x, a in zip(surnames, got["authors"])):
                    p.append(f"authors {got['authors']}")
            if chk.get("year", True) and got["year"] != year:
                p.append(f"year {got['year']}")
            if chk.get("venue", True) and venues and not any(v.lower() in str(got["venue"]).lower() for v in venues):
                p.append(f"venue {got['venue']!r}")
            files = sorted(EV.glob(f"{key}-{i}*"))
            got["evidence"] = [{"file": f.name, "sha256": hashlib.sha256(f.read_bytes()).hexdigest()} for f in files]
            rec["sources"].append({"kind": kind, "arg": arg, "checks": chk or "all", **got, "problems": p})
            rec["problems"] += [f"{kind} {arg}: {x}" for x in p]
        rec["status"] = "verified" if not rec["problems"] else "PROBLEM"
        bad += bool(rec["problems"])
        out[key] = rec
        report.append(f"[{rec['status']}] {key}: {title} ({first}, {year})")
        for s in rec["sources"]:
            if "error" in s:
                report.append(f"    {s['kind']:12s} {s['arg']}: ERROR {s['error']}")
            else:
                report.append(f"    {s['kind']:12s} {s['url']}\n      title: {s['title']}\n      authors: {', '.join(map(str, s['authors']))}"
                              f"\n      year: {s['year']}   venue: {s['venue']}" + (f"\n      {s['note']}" if s.get("note") else "")
                              + (f"\n      checks: {s['checks']}" if s["checks"] != "all" else "")
                              + (f"\n      PROBLEMS: {s['problems']}" if s["problems"] else ""))
        for x in rec["problems"]:
            if x.startswith("draft"):
                report.append(f"    {x}")
    extra = [ln for ln in lines if ln not in used_lines]
    report.append(f"\ndraft reference lines: {len(lines)}; matched to a checked entry: {len(used_lines)}; unmatched: {len(extra)}")
    for ln in extra:
        report.append(f"    UNMATCHED: {ln}")
    bad += len(extra)
    report.append(f"verified {sum(r['status'] == 'verified' for r in out.values())} of {len(out)}; "
                  + ("ALL OK" if bad == 0 else f"{bad} problem(s)"))
    (HERE / "refs-check.txt").write_text("\n".join(report) + "\n")
    (HERE / "refs-check.json").write_text(json.dumps(out, indent=1, ensure_ascii=False))
    print("\n".join(report))
    return 0 if bad == 0 else 1


if __name__ == "__main__":
    sys.exit(main())

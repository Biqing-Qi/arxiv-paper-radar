#!/usr/bin/env python3
"""Build a daily arXiv digest and optionally email it.

The script intentionally uses only Python's standard library so it runs on
GitHub Actions without dependency installation.
"""

from __future__ import annotations

import argparse
import datetime as dt
import email.mime.multipart
import email.mime.text
import html
import json
import os
import re
import smtplib
import sys
import textwrap
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ModuleNotFoundError:
    ZoneInfo = None


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.json"
DATA_DIR = ROOT / "data"
REPORTS_DIR = ROOT / "reports"
SEEN_PATH = DATA_DIR / "seen.json"
PAPERS_PATH = DATA_DIR / "papers.jsonl"
README_PATH = ROOT / "README.md"

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_API = "https://export.arxiv.org/api/query"


def load_config() -> dict:
    with CONFIG_PATH.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def load_seen() -> set[str]:
    if not SEEN_PATH.exists():
        return set()
    with SEEN_PATH.open("r", encoding="utf-8") as fh:
        data = json.load(fh)
    return set(data.get("arxiv_ids", []))


def save_seen(seen: set[str]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "arxiv_ids": sorted(seen),
    }
    with SEEN_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def arxiv_id_from_url(url: str) -> str:
    return url.rstrip("/").split("/")[-1]


def clean_text(value: str) -> str:
    return " ".join(value.split())


def parse_arxiv_datetime(value: str) -> dt.datetime:
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.astimezone(dt.timezone.utc)


def fetch_category(category: str, max_results: int, retries: int = 3) -> list[dict]:
    params = {
        "search_query": f"cat:{category}",
        "sortBy": "submittedDate",
        "sortOrder": "descending",
        "start": 0,
        "max_results": max_results,
    }
    url = f"{ARXIV_API}?{urllib.parse.urlencode(params)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "daily-arxiv-paper-radar/1.0 (personal research digest)"},
    )
    last_error: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
            break
        except (TimeoutError, urllib.error.URLError, OSError) as exc:
            last_error = exc
            if attempt < retries:
                time.sleep(5 * attempt)
    else:
        print(f"Warning: failed to fetch {category} after {retries} attempts: {last_error}")
        return []

    root = ET.fromstring(raw)
    papers: list[dict] = []
    for entry in root.findall("atom:entry", ATOM_NS):
        paper_url = entry.findtext("atom:id", default="", namespaces=ATOM_NS)
        title = clean_text(entry.findtext("atom:title", default="", namespaces=ATOM_NS))
        abstract = clean_text(entry.findtext("atom:summary", default="", namespaces=ATOM_NS))
        published = parse_arxiv_datetime(
            entry.findtext("atom:published", default="", namespaces=ATOM_NS)
        )
        updated = parse_arxiv_datetime(
            entry.findtext("atom:updated", default="", namespaces=ATOM_NS)
        )
        authors = [
            clean_text(author.findtext("atom:name", default="", namespaces=ATOM_NS))
            for author in entry.findall("atom:author", ATOM_NS)
        ]
        categories = [
            node.attrib.get("term", "")
            for node in entry.findall("atom:category", ATOM_NS)
            if node.attrib.get("term")
        ]
        pdf_url = ""
        for link in entry.findall("atom:link", ATOM_NS):
            if link.attrib.get("title") == "pdf":
                pdf_url = link.attrib.get("href", "")
                break
        papers.append(
            {
                "arxiv_id": arxiv_id_from_url(paper_url),
                "title": title,
                "abstract": abstract,
                "authors": authors,
                "published": published.isoformat(),
                "updated": updated.isoformat(),
                "url": paper_url,
                "pdf_url": pdf_url,
                "categories": categories,
            }
        )
    return papers


def fetch_recent_papers(config: dict) -> list[dict]:
    all_papers: dict[str, dict] = {}
    for index, category in enumerate(config["categories"]):
        if index:
            time.sleep(3.1)
        for paper in fetch_category(category, int(config["max_results_per_category"])):
            all_papers.setdefault(paper["arxiv_id"], paper)
    return list(all_papers.values())


def score_paper(paper: dict, config: dict) -> dict:
    text = f"{paper['title']} {paper['abstract']}".lower()
    topic_hits: list[dict] = []
    score = 0

    for topic_id, topic in config["topics"].items():
        hits = []
        topic_score = 0
        for keyword, weight in topic["keywords"].items():
            if keyword.lower() in text:
                hits.append(keyword)
                topic_score += int(weight)
        if hits:
            topic_hits.append(
                {
                    "id": topic_id,
                    "label": topic["label"],
                    "score": topic_score,
                    "keywords": hits,
                }
            )
            score += topic_score

    boost_hits = []
    for keyword, weight in config.get("boost_keywords", {}).items():
        if keyword.lower() in text:
            boost_hits.append(keyword)
            score += int(weight)

    topic_hits.sort(key=lambda item: item["score"], reverse=True)
    return {"score": score, "topics": topic_hits, "boost_hits": boost_hits}


def short_authors(authors: list[str], limit: int = 4) -> str:
    if not authors:
        return "Unknown authors"
    if len(authors) <= limit:
        return ", ".join(authors)
    return f"{', '.join(authors[:limit])}, et al."


def make_summary(paper: dict, scoring: dict) -> str:
    abstract = paper["abstract"]
    first_sentence = abstract.split(". ")[0].strip()
    if first_sentence and not first_sentence.endswith("."):
        first_sentence += "."
    if len(first_sentence) > 320:
        first_sentence = first_sentence[:317].rstrip() + "..."

    topic_labels = [topic["label"] for topic in scoring["topics"]]
    if topic_labels:
        prefix = f"Likely relevant to {', '.join(topic_labels)}."
    else:
        prefix = "Potentially relevant to the configured research interests."
    return f"{prefix} {first_sentence}"


def recommendation_label(score: int) -> str:
    if score >= 10:
        return "Read closely"
    if score >= 6:
        return "Worth scanning"
    return "Maybe relevant"


def filter_and_rank(papers: list[dict], config: dict, seen: set[str]) -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    lookback = dt.timedelta(days=int(config["lookback_days"]))
    min_score = int(config["min_score"])
    ranked = []

    for paper in papers:
        published = dt.datetime.fromisoformat(paper["published"])
        if now - published > lookback:
            continue
        if paper["arxiv_id"] in seen:
            continue

        scoring = score_paper(paper, config)
        if scoring["score"] < min_score or not scoring["topics"]:
            continue

        enriched = dict(paper)
        enriched["score"] = scoring["score"]
        enriched["topics"] = scoring["topics"]
        enriched["boost_hits"] = scoring["boost_hits"]
        enriched["recommendation"] = recommendation_label(scoring["score"])
        enriched["summary"] = make_summary(paper, scoring)
        ranked.append(enriched)

    ranked.sort(key=lambda item: (item["score"], item["published"]), reverse=True)
    return ranked[: int(config["max_papers_in_report"])]


def paper_to_markdown(paper: dict, tz: ZoneInfo) -> str:
    published = dt.datetime.fromisoformat(paper["published"]).astimezone(tz)
    topics = ", ".join(topic["label"] for topic in paper["topics"])
    keywords = sorted({kw for topic in paper["topics"] for kw in topic["keywords"]})
    keyword_text = ", ".join(keywords)
    lines = [
        f"### {paper['title']}",
        "",
        f"- Recommendation: **{paper['recommendation']}**",
        f"- Score: `{paper['score']}`",
        f"- Topics: {topics}",
        f"- Authors: {short_authors(paper['authors'])}",
        f"- Published: {published.strftime('%Y-%m-%d %H:%M %Z')}",
        f"- Links: [arXiv]({paper['url']})" + (f" / [PDF]({paper['pdf_url']})" if paper["pdf_url"] else ""),
        f"- Matched keywords: `{keyword_text}`",
        "",
        paper["summary"],
        "",
    ]
    return "\n".join(lines)


def build_report(papers: list[dict], config: dict) -> tuple[str, str]:
    tz = get_timezone(config["timezone"])
    today = dt.datetime.now(tz).date().isoformat()
    title = f"{config['site_title']} - {today}"

    lines = [
        f"# {title}",
        "",
        f"Generated at {dt.datetime.now(tz).strftime('%Y-%m-%d %H:%M %Z')}.",
        "",
    ]
    if not papers:
        lines.extend(
            [
                "No new papers matched the configured topics today.",
                "",
                "The workflow still ran successfully; try lowering `min_score` or adding more keywords in `config.json` if this happens often.",
                "",
            ]
        )
    else:
        lines.append(f"Found **{len(papers)}** new paper(s).")
        lines.append("")
        for paper in papers:
            lines.append(paper_to_markdown(paper, tz))

    return today, "\n".join(lines).rstrip() + "\n"


def get_timezone(name: str) -> dt.tzinfo:
    if ZoneInfo is not None:
        return ZoneInfo(name)
    if name == "Asia/Shanghai":
        return dt.timezone(dt.timedelta(hours=8), name)
    return dt.timezone.utc


def format_inline_markdown(text: str) -> str:
    parts = []
    cursor = 0
    link_pattern = re.compile(r"\[([^\]]+)\]\((https?://[^)]+)\)")
    for match in link_pattern.finditer(text):
        parts.append(html.escape(text[cursor : match.start()]))
        label = html.escape(match.group(1))
        url = html.escape(match.group(2), quote=True)
        parts.append(f'<a href="{url}">{label}</a>')
        cursor = match.end()
    parts.append(html.escape(text[cursor:]))
    rendered = "".join(parts)
    rendered = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", rendered)
    rendered = re.sub(r"`(.+?)`", r"<code>\1</code>", rendered)
    return rendered


def markdown_to_email_html(markdown_text: str) -> str:
    body = []
    for line in markdown_text.splitlines():
        if line.startswith("# "):
            body.append(f"<h1>{format_inline_markdown(line[2:])}</h1>")
        elif line.startswith("### "):
            body.append(f"<h3>{format_inline_markdown(line[4:])}</h3>")
        elif line.startswith("- "):
            body.append(f"<li>{format_inline_markdown(line[2:])}</li>")
        elif not line.strip():
            body.append("<br>")
        else:
            body.append(f"<p>{format_inline_markdown(line)}</p>")
    rendered = "\n".join(body)
    return f"""<!doctype html>
<html>
  <body style="font-family: -apple-system, BlinkMacSystemFont, Segoe UI, sans-serif; line-height: 1.5; color: #1f2937;">
    {rendered}
  </body>
</html>
"""


def send_email_if_configured(subject: str, markdown_text: str) -> bool:
    required = ["SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "MAIL_TO"]
    if not all(os.environ.get(key) for key in required):
        print("Email skipped: SMTP_HOST, SMTP_USER, SMTP_PASSWORD, or MAIL_TO is not configured.")
        return False

    smtp_host = os.environ["SMTP_HOST"]
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_user = os.environ["SMTP_USER"]
    smtp_password = os.environ["SMTP_PASSWORD"]
    mail_to = [addr.strip() for addr in os.environ["MAIL_TO"].split(",") if addr.strip()]

    message = email.mime.multipart.MIMEMultipart("alternative")
    message["Subject"] = subject
    message["From"] = smtp_user
    message["To"] = ", ".join(mail_to)
    message.attach(email.mime.text.MIMEText(markdown_text, "plain", "utf-8"))
    message.attach(email.mime.text.MIMEText(markdown_to_email_html(markdown_text), "html", "utf-8"))

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
        server.starttls()
        server.login(smtp_user, smtp_password)
        server.sendmail(smtp_user, mail_to, message.as_string())
    print(f"Email sent to {', '.join(mail_to)}.")
    return True


def append_papers_jsonl(papers: list[dict]) -> None:
    if not papers:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with PAPERS_PATH.open("a", encoding="utf-8") as fh:
        for paper in papers:
            fh.write(json.dumps(paper, ensure_ascii=False, sort_keys=True) + "\n")


def update_readme(today: str, report: str) -> None:
    readme = textwrap.dedent(
        f"""\
        # Daily arXiv Paper Radar

        This repository is maintained by a scheduled GitHub Actions workflow.
        It tracks arXiv papers related to diffusion language models and model architecture.

        Latest digest: [reports/latest.md](reports/latest.md)

        Latest run: {today}

        ## Preview

        {report.splitlines()[0]}

        See the full report in [reports/{today}.md](reports/{today}.md).
        """
    )
    README_PATH.write_text(readme, encoding="utf-8")


def write_outputs(today: str, report: str) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    (REPORTS_DIR / f"{today}.md").write_text(report, encoding="utf-8")
    (REPORTS_DIR / "latest.md").write_text(report, encoding="utf-8")
    update_readme(today, report)


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-email", action="store_true", help="Do not send email even if SMTP env vars exist.")
    parser.add_argument("--sample", action="store_true", help="Use built-in sample data instead of calling arXiv.")
    return parser.parse_args(argv)


def sample_papers() -> list[dict]:
    now = dt.datetime.now(dt.timezone.utc)
    return [
        {
            "arxiv_id": "2607.00001",
            "title": "Discrete Diffusion Language Models with Efficient Attention",
            "abstract": "We study diffusion language model training for text generation and introduce an efficient attention architecture for long context denoising.",
            "authors": ["Ada Researcher", "Bo Scientist"],
            "published": now.isoformat(),
            "updated": now.isoformat(),
            "url": "https://arxiv.org/abs/2607.00001",
            "pdf_url": "https://arxiv.org/pdf/2607.00001",
            "categories": ["cs.CL", "cs.LG"],
        }
    ]


def main(argv: list[str]) -> int:
    args = parse_args(argv)
    config = load_config()
    seen = load_seen()
    papers = sample_papers() if args.sample else fetch_recent_papers(config)
    selected = filter_and_rank(papers, config, seen)
    today, report = build_report(selected, config)
    write_outputs(today, report)
    append_papers_jsonl(selected)

    for paper in selected:
        seen.add(paper["arxiv_id"])
    save_seen(seen)

    subject = f"{config['site_title']} - {today}"
    if not args.no_email:
        send_email_if_configured(subject, report)

    print(f"Wrote digest for {today}: {len(selected)} paper(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

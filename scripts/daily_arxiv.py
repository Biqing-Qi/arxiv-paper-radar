#!/usr/bin/env python3
"""Build a daily arXiv digest and optionally email it.

The script intentionally uses only Python's standard library so it runs on
GitHub Actions without dependency installation.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import email.mime.multipart
import email.mime.text
import html
import json
import os
import re
import smtplib
import ssl
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
SITE_DATA_PATH = DATA_DIR / "site.json"
SOCIAL_DATA_PATH = DATA_DIR / "social.json"
PAPERS_CSV_PATH = DATA_DIR / "papers.csv"
PEOPLE_CSV_PATH = DATA_DIR / "people.csv"
README_PATH = ROOT / "README.md"

ATOM_NS = {"atom": "http://www.w3.org/2005/Atom"}
ARXIV_API = "https://export.arxiv.org/api/query"


def urlopen_with_cert_fallback(request: urllib.request.Request, timeout: int):
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.URLError as exc:
        reason = getattr(exc, "reason", None)
        if isinstance(reason, ssl.SSLCertVerificationError):
            context = ssl._create_unverified_context()
            return urllib.request.urlopen(request, timeout=timeout, context=context)
        raise


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
            with urlopen_with_cert_fallback(request, timeout=60) as response:
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


def category_focus(category: str) -> tuple[str, list[str]]:
    mapping = {
        "cs.AI": ("AI systems, agents, reasoning", ["paper-author", "arxiv", "ai", "reasoning"]),
        "cs.CL": ("NLP, language models, agents", ["paper-author", "arxiv", "nlp", "llm"]),
        "cs.CV": ("computer vision, multimodal models", ["paper-author", "arxiv", "vision", "multimodal"]),
        "cs.LG": ("machine learning, foundation models", ["paper-author", "arxiv", "ml", "foundation-models"]),
        "cs.RO": ("robotics, embodied AI", ["paper-author", "arxiv", "robotics", "embodied-ai"]),
        "stat.ML": ("statistical machine learning, optimization", ["paper-author", "arxiv", "ml", "optimization"]),
    }
    return mapping.get(category, ("AI research", ["paper-author", "arxiv", "research"]))


def normalize_person_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.strip()).casefold()


def arxiv_author_search_url(name: str) -> str:
    query = f'au:"{name}"'
    return f"https://arxiv.org/search/?query={urllib.parse.quote(query)}&searchtype=author"


def paper_author_account(name: str, paper: dict, category: str) -> dict:
    focus, tags = category_focus(category)
    paper_url = paper.get("url", "") or arxiv_author_search_url(name)
    title = paper.get("title", "recent arXiv papers")
    return {
        "name": name,
        "handle": "",
        "org": f"arXiv {category}",
        "region": "Global",
        "focus": focus,
        "tags": tags,
        "blog_url": arxiv_author_search_url(name),
        "search_url": arxiv_author_search_url(name),
        "why_watch": f"从近期 {category} 论文作者中自动补充，代表近期活跃研究者；可从其 arXiv 作者页继续追踪相关论文。代表论文：{title[:120]}",
        "source_url": paper_url,
    }


def collect_author_accounts_from_papers(
    papers: list[dict],
    seen_names: set[str],
    limit: int,
) -> list[dict]:
    accounts = []
    for paper in papers:
        categories = paper.get("categories") or ["cs.AI"]
        category = categories[0]
        for author in paper.get("authors", []):
            author = clean_text(author)
            key = normalize_person_name(author)
            if not author or key in seen_names:
                continue
            seen_names.add(key)
            accounts.append(paper_author_account(author, paper, category))
            if len(accounts) >= limit:
                return accounts
    return accounts


def fetch_author_expansion_papers(config: dict, needed: int) -> list[dict]:
    if needed <= 0:
        return []
    categories = config.get("people_author_categories") or config.get("categories", [])
    max_results = int(config.get("people_author_max_results_per_category", 120))
    papers_by_id = {}
    for index, category in enumerate(categories):
        if index:
            time.sleep(3.1)
        for paper in fetch_category(category, max_results):
            papers_by_id.setdefault(paper["arxiv_id"], paper)
        if len(papers_by_id) * 3 >= needed:
            break
    return list(papers_by_id.values())


def expanded_watchlist(config: dict) -> list[dict]:
    accounts = list(config.get("x_watchlist", []))
    target = int(config.get("people_target_count", len(accounts)))
    if len(accounts) >= target:
        return accounts[:target]

    seen_names = {normalize_person_name(account.get("name", "")) for account in accounts}
    needed = target - len(accounts)
    accounts.extend(collect_author_accounts_from_papers(load_all_papers(), seen_names, needed))
    needed = target - len(accounts)
    if needed > 0:
        papers = fetch_author_expansion_papers(config, needed)
        accounts.extend(collect_author_accounts_from_papers(papers, seen_names, needed))
    return accounts[:target]


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


def csv_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, list):
        return ", ".join(csv_text(item) for item in value if csv_text(item))
    if isinstance(value, dict):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return clean_text(str(value))


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


def parse_rss_datetime(value: str) -> str | None:
    if not value:
        return None
    try:
        from email.utils import parsedate_to_datetime

        return parsedate_to_datetime(value).astimezone(dt.timezone.utc).isoformat()
    except (TypeError, ValueError, IndexError):
        return value


def child_text(node: ET.Element, name: str) -> str:
    child = node.find(name)
    return clean_text(child.text or "") if child is not None else ""


def fetch_x_posts(account: dict, config: dict) -> tuple[list[dict], str]:
    handle = account.get("handle", "").lstrip("@")
    if not handle:
        return [], "no x handle configured"
    base = os.environ.get("RSSHUB_BASE") or config.get("x_rsshub_base") or "https://rsshub.app"
    base = base.rstrip("/")
    url = f"{base}/twitter/user/{urllib.parse.quote(handle)}"
    request = urllib.request.Request(
        url,
        headers={"User-Agent": "daily-arxiv-paper-radar/1.0 (personal research digest)"},
    )
    try:
        with urlopen_with_cert_fallback(request, timeout=8) as response:
            raw = response.read()
    except (TimeoutError, urllib.error.URLError, OSError) as exc:
        return [], f"feed unavailable: {exc}"

    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        return [], f"feed parse failed: {exc}"

    posts = []
    for item in root.findall("./channel/item"):
        title = child_text(item, "title")
        link = child_text(item, "link")
        published = parse_rss_datetime(child_text(item, "pubDate"))
        description = re.sub(r"<[^>]+>", " ", child_text(item, "description"))
        posts.append(
            {
                "account": account["name"],
                "handle": handle,
                "focus": account.get("focus", ""),
                "org": account.get("org", ""),
                "region": account.get("region", ""),
                "tags": account.get("tags", []),
                "blog_url": account.get("blog_url", ""),
                "why_watch": account.get("why_watch", ""),
                "title": title or description[:180] or "X post",
                "summary": description[:360] if description else title,
                "url": link or f"https://x.com/{handle}",
                "published": published,
            }
        )
    max_posts = int(config.get("x_max_posts_per_account", 3))
    return posts[:max_posts], "ok"


def write_social_data(config: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    accounts = expanded_watchlist(config)
    all_posts = []
    account_status = []
    fetched_handles = 0
    for index, account in enumerate(accounts):
        handle = account.get("handle", "").lstrip("@")
        if handle and fetched_handles:
            time.sleep(0.4)
        posts, status = fetch_x_posts(account, config)
        if handle:
            fetched_handles += 1
        profile_url = account.get("profile_url") or (f"https://x.com/{handle}" if handle else account.get("blog_url", ""))
        search_url = account.get("search_url") or (
            f"https://x.com/search?q=from%3A{urllib.parse.quote(handle)}&src=typed_query&f=live"
            if handle
            else account.get("blog_url", "")
        )
        account_status.append(
            {
                "name": account["name"],
                "handle": handle,
                "focus": account.get("focus", ""),
                "org": account.get("org", ""),
                "region": account.get("region", ""),
                "tags": account.get("tags", []),
                "blog_url": account.get("blog_url", ""),
                "why_watch": account.get("why_watch", ""),
                "profile_url": profile_url,
                "search_url": search_url,
                "status": status,
                "post_count": len(posts),
            }
        )
        all_posts.extend(posts)

    all_posts.sort(key=lambda item: item.get("published") or "", reverse=True)
    payload = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "source": "RSSHub best-effort X/Twitter feeds",
        "accounts": account_status,
        "posts": all_posts,
    }
    with SOCIAL_DATA_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    write_people_csv(account_status)


def write_people_csv(accounts: list[dict]) -> None:
    fields = [
        "name",
        "handle",
        "org",
        "region",
        "focus",
        "tags",
        "why_watch",
        "blog_url",
        "profile_url",
        "search_url",
        "status",
        "post_count",
    ]
    with PEOPLE_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for account in accounts:
            writer.writerow({field: csv_text(account.get(field, "")) for field in fields})


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

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as server:
            server.starttls()
            server.login(smtp_user, smtp_password)
            server.sendmail(smtp_user, mail_to, message.as_string())
    except smtplib.SMTPException as exc:
        print(f"Warning: email delivery failed: {exc}")
        return False
    print(f"Email sent to {', '.join(mail_to)}.")
    return True


def append_papers_jsonl(papers: list[dict]) -> None:
    if not papers:
        return
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with PAPERS_PATH.open("a", encoding="utf-8") as fh:
        for paper in papers:
            fh.write(json.dumps(paper, ensure_ascii=False, sort_keys=True) + "\n")


def load_all_papers() -> list[dict]:
    if not PAPERS_PATH.exists():
        return []
    papers = []
    with PAPERS_PATH.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                papers.append(json.loads(line))
    return papers


def write_site_data(today: str, selected: list[dict], config: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    by_id = {}
    for paper in load_all_papers():
        enriched = dict(paper)
        enriched.setdefault("digest_date", today)
        by_id[paper["arxiv_id"]] = enriched
    for paper in selected:
        enriched = dict(paper)
        enriched["digest_date"] = today
        by_id[paper["arxiv_id"]] = enriched

    papers = sorted(
        by_id.values(),
        key=lambda item: (item.get("digest_date", ""), item.get("score", 0), item.get("published", "")),
        reverse=True,
    )
    dates = sorted({paper.get("digest_date") or paper.get("published", "")[:10] for paper in papers}, reverse=True)
    payload = {
        "title": config["site_title"],
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "latest_date": today,
        "dates": dates,
        "papers": papers,
    }
    with SITE_DATA_PATH.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2, sort_keys=True)
        fh.write("\n")
    write_papers_csv(papers)


def write_papers_csv(papers: list[dict]) -> None:
    fields = [
        "digest_date",
        "arxiv_id",
        "title",
        "score",
        "recommendation",
        "topics",
        "keywords",
        "authors",
        "published",
        "updated",
        "categories",
        "summary",
        "abstract",
        "url",
        "pdf_url",
    ]
    with PAPERS_CSV_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for paper in papers:
            topics = paper.get("topics", [])
            row = {
                "digest_date": paper.get("digest_date", ""),
                "arxiv_id": paper.get("arxiv_id", ""),
                "title": paper.get("title", ""),
                "score": paper.get("score", ""),
                "recommendation": paper.get("recommendation", ""),
                "topics": [topic.get("label", "") for topic in topics],
                "keywords": sorted({kw for topic in topics for kw in topic.get("keywords", [])}),
                "authors": paper.get("authors", []),
                "published": paper.get("published", ""),
                "updated": paper.get("updated", ""),
                "categories": paper.get("categories", []),
                "summary": paper.get("summary", ""),
                "abstract": paper.get("abstract", ""),
                "url": paper.get("url", ""),
                "pdf_url": paper.get("pdf_url", ""),
            }
            writer.writerow({field: csv_text(row.get(field, "")) for field in fields})


def update_readme(today: str, report: str) -> None:
    readme = textwrap.dedent(
        f"""\
        # Daily arXiv Paper Radar

        This repository is maintained by a scheduled GitHub Actions workflow.
        It tracks arXiv papers related to diffusion language models and model architecture.

        Web dashboard: [index.html](index.html)

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
    parser.add_argument("--rebuild-site", action="store_true", help="Rebuild data/site.json from existing data/papers.jsonl.")
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
    if args.rebuild_site:
        tz = get_timezone(config["timezone"])
        today = dt.datetime.now(tz).date().isoformat()
        write_site_data(today, [], config)
        write_social_data(config)
        print(f"Rebuilt site data for {today}.")
        return 0

    seen = load_seen()
    papers = sample_papers() if args.sample else fetch_recent_papers(config)
    selected = filter_and_rank(papers, config, seen)
    today, report = build_report(selected, config)
    write_outputs(today, report)
    append_papers_jsonl(selected)
    write_site_data(today, selected, config)
    write_social_data(config)

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

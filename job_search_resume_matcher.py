#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import html
import json
import math
import re
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable
from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


DEFAULT_LOCATION = "Toronto"
USER_AGENT = "resume-job-matcher/1.0 (+local script)"
DEFAULT_FREEHIRE_URL = "https://freehire.me/api/v1/jobs"
DEFAULT_HIMALAYAS_URL = "https://himalayas.app/jobs/api"
GREENHOUSE_BOARD_URL = "https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true"
LEVER_POSTINGS_URL = "https://api.lever.co/v0/postings/{site}?mode=json&limit=100"
DEFAULT_JOBSPY_SITES = ["indeed"]
DEEPSEEK_CHAT_URL = "https://api.deepseek.com/chat/completions"
OLLAMA_CHAT_URL = "http://127.0.0.1:11434/v1/chat/completions"

STOPWORDS = {
    "a", "about", "after", "all", "also", "an", "and", "any", "are", "as", "at", "be",
    "been", "both", "but", "by", "can", "could", "did", "do", "does", "each", "for",
    "from", "had", "has", "have", "helped", "in", "into", "is", "it", "its", "led",
    "made", "more", "most", "of", "on", "or", "our", "over", "project", "projects",
    "responsible", "role", "roles", "skills", "team", "that", "the", "their", "them",
    "there", "these", "this", "through", "to", "using", "was", "were", "with", "you",
    "your",
}

ROLE_TERMS = {
    "analyst", "architect", "coordinator", "consultant", "designer", "developer",
    "engineer", "intern", "manager", "marketer", "product", "researcher",
    "scientist", "specialist", "strategist", "support", "technician",
}

ROLE_CONTEXT_TERMS = {
    "backend", "business", "cloud", "computer", "customer", "data", "devops", "electrical",
    "frontend", "fullstack", "machine", "ml", "operations", "platform", "product",
    "qa", "reliability", "security", "site", "software", "systems", "test",
}

TITLE_BLOCKLIST = {
    "ability", "bachelor", "course", "degree", "education", "experience", "including",
    "master", "objective", "observation", "persistent", "proficient", "project",
    "responsible", "storage", "summary",
}

TORONTO_ALIASES = {
    "toronto",
    "toronto, on",
    "toronto, ontario",
    "greater toronto area",
    "gta",
    "mississauga",
    "markham",
    "vaughan",
    "richmond hill",
    "scarborough",
    "north york",
    "etobicoke",
    "oakville",
    "brampton",
}

MONTH_NAMES = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
MONTH_PATTERN = "|".join(MONTH_NAMES)
EXPERIENCE_DATE_RANGE = re.compile(
    rf"\b(?P<start_month>{MONTH_PATTERN})\.?\s+(?P<start_year>\d{{4}})\s*"
    rf"(?:-|–|—|to)\s*(?:(?P<end_month>{MONTH_PATTERN})\.?\s+(?P<end_year>\d{{4}})|(?P<current>present|current))",
    re.I,
)
NUMBER_WORDS = {
    "one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0,
    "six": 6.0, "seven": 7.0, "eight": 8.0, "nine": 9.0, "ten": 10.0,
    "eleven": 11.0, "twelve": 12.0, "fifteen": 15.0, "twenty": 20.0,
}
YEAR_VALUE_PATTERN = r"(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|ten|eleven|twelve|fifteen|twenty)"

@dataclass
class ResumeProfile:
    raw_text: str
    title_hints: list[str]
    keywords: list[str]
    detected_keywords: list[str] = field(default_factory=list)
    experience_years: dict[str, float] = field(default_factory=dict)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Find jobs that match a resume, with Toronto-first filtering.")
    parser.add_argument("--resume", required=True, help="Path to resume (.txt, .md, .pdf, .docx)")
    parser.add_argument("--input", help="Local jobs file (.json or .csv)")
    parser.add_argument("--input-url", help="Remote JSON jobs endpoint")
    parser.add_argument(
        "--source",
        choices=("freehire", "himalayas"),
        help="Built-in public jobs source. Sets --input-url automatically.",
    )
    parser.add_argument(
        "--greenhouse-boards",
        nargs="*",
        default=[],
        help="One or more Greenhouse board tokens, for example stripe figma shopify.",
    )
    parser.add_argument(
        "--lever-sites",
        nargs="*",
        default=[],
        help="One or more Lever site names, for example netflix sourcegraph.",
    )
    parser.add_argument(
        "--companies-file",
        help="Path to a text file listing Greenhouse and Lever companies, one per line.",
    )
    parser.add_argument("--no-greenhouse", action="store_false", dest="use_greenhouse", default=True)
    parser.add_argument("--no-lever", action="store_false", dest="use_lever", default=True)
    parser.add_argument(
        "--jobspy-sites",
        nargs="*",
        default=[],
        help="Optional JobSpy sites such as indeed linkedin glassdoor google zip_recruiter.",
    )
    parser.add_argument(
        "--jobspy-search-terms",
        nargs="*",
        default=[],
        help="Optional search terms for JobSpy. Defaults to your titles or inferred resume titles.",
    )
    parser.add_argument(
        "--jobspy-results-wanted",
        type=int,
        default=40,
        help="Approximate number of jobs to fetch per JobSpy site per search term.",
    )
    parser.add_argument(
        "--jobspy-hours-old",
        type=int,
        help="Optional recency filter for JobSpy, in hours.",
    )
    parser.add_argument(
        "--jobspy-country-indeed",
        default="Canada",
        help="Indeed/Glassdoor country for JobSpy. Defaults to Canada.",
    )
    parser.add_argument(
        "--jobspy-linkedin-fetch-description",
        action="store_true",
        help="Fetch full LinkedIn descriptions in JobSpy. Slower and more rate-limit prone.",
    )
    parser.add_argument(
        "--captured-jds-file",
        help="Optional local JSON cache of full LinkedIn JDs copied from pages you opened.",
    )
    parser.add_argument(
        "--jobspy-linkedin-delay-seconds",
        type=float,
        default=4.0,
        help="Pause between LinkedIn JobSpy searches. Defaults to 4 seconds for lower request volume.",
    )
    parser.add_argument(
        "--jobspy-linkedin-max-terms",
        type=int,
        default=3,
        help="Maximum search terms sent to LinkedIn per run. Defaults to 3.",
    )
    parser.add_argument("--location", default=DEFAULT_LOCATION)
    parser.add_argument("--include-remote", action="store_true")
    parser.add_argument("--titles", nargs="*", default=[])
    parser.add_argument("--include-keywords", nargs="*", default=[])
    parser.add_argument(
        "--resume-keywords",
        nargs="*",
        help="Optional edited replacement for keywords extracted from the resume.",
    )
    parser.add_argument(
        "--experience-years-override",
        type=float,
        help="Optional manual override for professional experience years.",
    )
    parser.add_argument(
        "--no-resume-keywords",
        action="store_false",
        dest="use_resume_keywords",
        default=True,
        help="Do not use automatically detected resume keywords for matching.",
    )
    parser.add_argument("--exclude-keywords", nargs="*", default=[])
    parser.add_argument(
        "--json-path",
        help="Optional dot path to the job list inside JSON, for example data.jobs or results.items",
    )
    parser.add_argument(
        "--delimiter",
        default=",",
        help="CSV delimiter for local exports. Defaults to ','. Use '\\t' for TSV.",
    )
    parser.add_argument(
        "--encoding",
        default="utf-8-sig",
        help="File encoding for CSV/JSON input. Defaults to utf-8-sig.",
    )
    parser.add_argument(
        "--list-columns",
        action="store_true",
        help="Print detected columns/keys from the input file and exit.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=10,
        help="Maximum pages to fetch from paginated live JSON sources.",
    )
    parser.add_argument("--max-jobs", type=int, default=150)
    parser.add_argument("--min-score", type=float, default=3.5)
    parser.add_argument(
        "--min-candidate-results",
        type=int,
        default=25,
        help="Keep this many location-eligible candidates even when their score is below --min-score.",
    )
    parser.add_argument(
        "--ai-provider",
        choices=("off", "deepseek", "ollama", "openai-compatible"),
        default="off",
        help="Optional AI reranker. Off keeps matching fully local.",
    )
    parser.add_argument("--ai-api-key", help="API key for DeepSeek or an OpenAI-compatible provider. Never saved.")
    parser.add_argument("--ai-model", help="Model name for the selected AI provider.")
    parser.add_argument("--ai-base-url", help="Full /chat/completions URL for Ollama or an OpenAI-compatible provider.")
    parser.add_argument("--ai-rerank-limit", type=int, default=20, help="Maximum local matches sent to the AI provider.")
    parser.add_argument(
        "--verify-apply-pages",
        action="store_true",
        help="Open top application pages and rescore using their full job descriptions.",
    )
    parser.add_argument(
        "--verify-apply-limit",
        type=int,
        default=15,
        help="Maximum top-ranked application pages to check. Defaults to 15.",
    )
    parser.add_argument(
        "--no-source-balanced-verification",
        action="store_false",
        dest="source_balanced_verification",
        default=True,
        help="Verify strictly by global score instead of reserving one page per source first.",
    )
    parser.add_argument("--out", default="matched_jobs.csv")
    return parser.parse_args()


def read_resume(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".txt", ".md"}:
        return path.read_text(encoding="utf-8", errors="ignore")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("Install pypdf first: pip install pypdf") from exc
        reader = PdfReader(str(path))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("Install python-docx first: pip install python-docx") from exc
        document = Document(str(path))
        return "\n".join(paragraph.text for paragraph in document.paragraphs)
    raise ValueError(f"Unsupported resume format: {path.suffix}")


def normalize_space(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def strip_embedded_application_documents(text: str) -> str:
    """Ignore a cover letter or transcript appended after a resume in one PDF."""
    attachment = re.search(
        r"(?im)^\s*(?:dear\s+.+|registration\s+history|academic\s+history)\s*$",
        text,
    )
    return text[:attachment.start()] if attachment else text


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z][a-zA-Z0-9+#./-]{1,30}", text.lower())


def dedupe_preserve_order(items: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def infer_titles_from_resume(lines: list[str]) -> list[str]:
    candidates: list[str] = []
    for line in lines[:120]:
        text = normalize_space(line)
        lowered = text.lower()
        tokens = set(tokenize(lowered))
        if any(char.isdigit() for char in text):
            continue
        words = text.split()
        if not 2 <= len(words) <= 6:
            continue
        if text.endswith((".", ";", ":")):
            continue
        if tokens & TITLE_BLOCKLIST:
            continue
        if not (tokens & ROLE_TERMS):
            continue
        if not ((tokens & ROLE_CONTEXT_TERMS) or len(tokens & ROLE_TERMS) >= 2):
            continue
        if any(len(word) > 20 for word in words):
            continue
        candidates.append(text.title())

    defaults = [
        "Software Engineer",
        "Data Analyst",
        "Data Engineer",
        "QA Engineer",
        "DevOps Engineer",
        "Business Analyst",
    ]
    return dedupe_preserve_order(candidates + defaults)[:8]


def estimate_resume_experience_years(resume_text: str) -> dict[str, float]:
    """Estimate total professional experience from dated Professional Experience entries only."""
    resume_text = strip_embedded_application_documents(resume_text)
    professional_months = 0
    start = re.search(r"(?im)^\s*(?:professional|work)\s+experience\s*$", resume_text)
    if not start:
        return {"professional": 0.0, "professional_months": 0}
    end = re.search(
        r"(?im)^\s*(?:(?:selected|academic)\s+)?(?:research|academic|project|education|"
        r"certifications?|technical\s+skills|skills|projects?|publications?|teaching|volunteer|awards?)\b",
        resume_text[start.end() :],
    )
    section_end = start.end() + end.start() if end else len(resume_text)
    section = resume_text[start.end() : section_end]
    matches = list(EXPERIENCE_DATE_RANGE.finditer(section))
    for match in matches:
        start_month = MONTH_NAMES[match.group("start_month").lower().rstrip(".")]
        start_year = int(match.group("start_year"))
        if match.group("current"):
            end_year, end_month = date.today().year, date.today().month
        else:
            end_month = MONTH_NAMES[match.group("end_month").lower().rstrip(".")]
            end_year = int(match.group("end_year"))
        months = max(0, (end_year - start_year) * 12 + end_month - start_month)
        if not months:
            continue
        professional_months += months
    return {
        "professional": round(professional_months / 12, 1),
        "professional_months": professional_months,
    }


def build_resume_profile(
    resume_text: str,
    extra_titles: list[str],
    extra_keywords: list[str],
    use_resume_keywords: bool = True,
    resume_keywords_override: list[str] | None = None,
    experience_years_override: float | None = None,
) -> ResumeProfile:
    resume_text = strip_embedded_application_documents(resume_text)
    cleaned = normalize_space(resume_text)
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    tokens = [token for token in tokenize(cleaned) if token not in STOPWORDS and len(token) > 2]
    frequencies = Counter(tokens)
    title_hints = dedupe_preserve_order(infer_titles_from_resume(lines) + extra_titles)[:12]
    detected_keywords = [word for word, _ in frequencies.most_common(60)]
    detected_keywords = [keyword.lower() for keyword in detected_keywords if keyword.lower() not in STOPWORDS][:80]
    selected_resume_keywords = resume_keywords_override if resume_keywords_override is not None else detected_keywords
    keywords = dedupe_preserve_order((selected_resume_keywords if use_resume_keywords else []) + extra_keywords)
    keywords = [keyword.lower() for keyword in keywords if keyword.lower() not in STOPWORDS][:80]
    experience_years = estimate_resume_experience_years(resume_text)
    if experience_years_override is not None:
        professional_years = max(0.0, experience_years_override)
        experience_years = {
            "professional": round(professional_years, 1),
            "professional_months": round(professional_years * 12),
        }
    return ResumeProfile(
        raw_text=cleaned,
        title_hints=title_hints,
        keywords=keywords,
        detected_keywords=detected_keywords,
        experience_years=experience_years,
    )


def load_jobs(args: argparse.Namespace, profile: ResumeProfile) -> list[dict]:
    file_greenhouse_boards, file_lever_sites = load_company_targets(args.companies_file)
    greenhouse_boards = dedupe_preserve_order(args.greenhouse_boards + file_greenhouse_boards)
    lever_sites = dedupe_preserve_order(args.lever_sites + file_lever_sites)

    combined_jobs: list[dict] = []
    if getattr(args, "use_greenhouse", True) and greenhouse_boards:
        combined_jobs.extend(load_greenhouse_jobs(greenhouse_boards))
    if getattr(args, "use_lever", True) and lever_sites:
        combined_jobs.extend(load_lever_jobs(lever_sites))

    jobspy_sites = dedupe_preserve_order(args.jobspy_sites)
    if jobspy_sites:
        combined_jobs.extend(load_jobspy_jobs(args, profile, jobspy_sites))

    if args.input_url or args.source:
        combined_jobs.extend(
            load_jobs_from_url(
                args.input_url or built_in_source_url(args.source),
                args.json_path,
                args.max_pages,
            )
        )
    elif args.input:
        path = Path(args.input)
        if not path.exists():
            raise RuntimeError(f"Input file not found: {path}")
        if path.suffix.lower() == ".csv":
            combined_jobs.extend(load_jobs_from_csv(path, args.delimiter, args.encoding))
        elif path.suffix.lower() == ".json":
            combined_jobs.extend(load_jobs_from_json(path, args.encoding, args.json_path))
        else:
            raise RuntimeError("Input must be a .csv or .json file.")

    return dedupe_jobs(combined_jobs)


def load_company_targets(path_text: str | None) -> tuple[list[str], list[str]]:
    if not path_text:
        return [], []

    path = Path(path_text)
    if not path.exists():
        raise RuntimeError(f"Companies file not found: {path}")

    greenhouse_boards: list[str] = []
    lever_sites: list[str] = []

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        lowered = line.lower()
        if lowered.startswith("greenhouse:"):
            token = line.split(":", 1)[1].strip()
            if token:
                greenhouse_boards.append(token)
            continue

        if lowered.startswith("lever:"):
            site = line.split(":", 1)[1].strip()
            if site:
                lever_sites.append(site)
            continue

        if "," in line:
            prefix, value = [part.strip() for part in line.split(",", 1)]
            lowered_prefix = prefix.lower()
            if lowered_prefix == "greenhouse" and value:
                greenhouse_boards.append(value)
                continue
            if lowered_prefix == "lever" and value:
                lever_sites.append(value)
                continue

        raise RuntimeError(
            f"Unsupported companies file entry: {line}. "
            "Use 'greenhouse:token' or 'lever:site'."
        )

    return dedupe_preserve_order(greenhouse_boards), dedupe_preserve_order(lever_sites)


def built_in_source_url(source: str | None) -> str:
    if source == "freehire":
        return DEFAULT_FREEHIRE_URL
    if source == "himalayas":
        return DEFAULT_HIMALAYAS_URL
    raise RuntimeError("Provide --input, --input-url, or --source.")


def fetch_json_url(url: str) -> object:
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        with urlopen(request, timeout=60) as response:
            return json.load(response)
    except HTTPError as exc:
        raise RuntimeError(f"HTTP {exc.code} while loading {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach {url}") from exc


def load_jobspy_jobs(args: argparse.Namespace, profile: ResumeProfile, sites: list[str]) -> list[dict]:
    try:
        from jobspy import scrape_jobs
    except ImportError as exc:
        raise RuntimeError(
            "JobSpy is not installed. Install it with: "
            "pip install --no-deps python-jobspy && "
            "pip install pandas numpy beautifulsoup4 pydantic tls-client markdownify regex requests"
        ) from exc

    search_terms = dedupe_preserve_order(args.jobspy_search_terms + args.titles + profile.title_hints)[:6]
    if not search_terms:
        search_terms = ["software engineer", "data analyst"]

    jobs: list[dict] = []
    source_warnings = getattr(args, "source_warnings", [])
    non_linkedin_sites = [site for site in sites if site != "linkedin"]
    site_batches = [(non_linkedin_sites, search_terms, False)] if non_linkedin_sites else []
    if "linkedin" in sites:
        # Keep LinkedIn isolated so its pacing does not reduce results from other sources.
        linkedin_terms = search_terms[:max(1, args.jobspy_linkedin_max_terms)]
        site_batches.append((["linkedin"], linkedin_terms, True))

    for batch_sites, batch_terms, is_linkedin in site_batches:
        for term_index, search_term in enumerate(batch_terms):
            if is_linkedin and term_index:
                time.sleep(max(0.0, args.jobspy_linkedin_delay_seconds))
            try:
                kwargs = {
                    "site_name": batch_sites,
                    "search_term": search_term,
                    "location": args.location,
                    "results_wanted": args.jobspy_results_wanted,
                    "country_indeed": args.jobspy_country_indeed,
                    "linkedin_fetch_description": args.jobspy_linkedin_fetch_description,
                    "description_format": "markdown",
                    "verbose": 0,
                }
                if args.jobspy_hours_old is not None:
                    kwargs["hours_old"] = args.jobspy_hours_old
                if "google" in batch_sites:
                    kwargs["google_search_term"] = f"{search_term} jobs near {args.location}"
                dataframe = scrape_jobs(**kwargs)
            except Exception as exc:  # pragma: no cover - third-party behavior
                warning = f"JobSpy {', '.join(batch_sites)} failed for '{search_term}': {exc}"
                print(f"Warning: {warning}", file=sys.stderr)
                source_warnings.append(warning)
                continue

            try:
                records = dataframe.to_dict(orient="records")
            except Exception as exc:  # pragma: no cover - third-party behavior
                warning = f"Could not read JobSpy {', '.join(batch_sites)} results for '{search_term}': {exc}"
                print(f"Warning: {warning}", file=sys.stderr)
                source_warnings.append(warning)
                continue

            for record in records:
                if isinstance(record, dict):
                    jobs.append(normalize_jobspy_record(record))
    args.source_warnings = source_warnings
    return jobs


def load_greenhouse_jobs(board_tokens: list[str]) -> list[dict]:
    jobs: list[dict] = []
    for board_token in board_tokens:
        url = GREENHOUSE_BOARD_URL.format(board_token=board_token)
        try:
            data = fetch_json_url(url)
        except RuntimeError as exc:
            print(f"Warning: skipping Greenhouse board '{board_token}': {exc}", file=sys.stderr)
            continue
        board_jobs = data.get("jobs", []) if isinstance(data, dict) else []
        if not isinstance(board_jobs, list):
            continue
        for job in board_jobs:
            if isinstance(job, dict):
                jobs.append(normalize_greenhouse_job(job, board_token))
    return jobs


def normalize_greenhouse_job(job: dict, board_token: str) -> dict:
    offices = job.get("offices") or []
    office_locations = []
    if isinstance(offices, list):
        office_locations = [
            office.get("location", "")
            for office in offices
            if isinstance(office, dict) and office.get("location")
        ]
    departments = job.get("departments") or []
    department_names = []
    if isinstance(departments, list):
        department_names = [
            department.get("name", "")
            for department in departments
            if isinstance(department, dict) and department.get("name")
        ]
    location_value = ""
    raw_location = job.get("location")
    if isinstance(raw_location, dict):
        location_value = str(raw_location.get("name", "")).strip()
    elif raw_location:
        location_value = str(raw_location).strip()
    if not location_value:
        location_value = ", ".join(office_locations)

    return {
        "title": job.get("title", ""),
        "company": board_token,
        "location": location_value,
        "description": first_present(job, ("content",)),
        "url": job.get("absolute_url", ""),
        "platform": "greenhouse",
        "remote": "",
        "posted": job.get("updated_at", ""),
        "categories": ", ".join(department_names),
    }


def load_lever_jobs(site_names: list[str]) -> list[dict]:
    jobs: list[dict] = []
    for site_name in site_names:
        skip = 0
        while True:
            url = f"{LEVER_POSTINGS_URL.format(site=site_name)}&skip={skip}"
            try:
                data = fetch_json_url(url)
            except RuntimeError as exc:
                if skip == 0:
                    print(f"Warning: skipping Lever site '{site_name}': {exc}", file=sys.stderr)
                break
            if not isinstance(data, list) or not data:
                break
            for job in data:
                if isinstance(job, dict):
                    jobs.append(normalize_lever_job(job, site_name))
            if len(data) < 100:
                break
            skip += 100
    return jobs


def normalize_lever_job(job: dict, site_name: str) -> dict:
    categories = job.get("categories") if isinstance(job.get("categories"), dict) else {}
    category_values = []
    if isinstance(categories, dict):
        for key in ("team", "department", "commitment", "allLocations"):
            value = categories.get(key)
            if isinstance(value, list):
                category_values.extend(str(item) for item in value if item)
            elif value:
                category_values.append(str(value))

    return {
        "title": job.get("text", ""),
        "company": site_name,
        "location": first_present(categories, ("location", "allLocations")),
        "description": first_present(job, ("descriptionPlain", "description", "openingPlain")),
        "url": job.get("hostedUrl", "") or job.get("applyUrl", ""),
        "platform": "lever",
        "remote": "",
        "posted": first_present(job, ("createdAt", "updatedAt")),
        "categories": ", ".join(category_values),
    }


def normalize_jobspy_record(record: dict) -> dict:
    city = first_present(record, ("city", "CITY"))
    state = first_present(record, ("state", "STATE"))
    country = first_present(record, ("country", "COUNTRY"))
    location_parts = [part for part in (city, state, country) if part]
    location = first_present(record, ("location", "LOCATION"))
    if not location:
        location = ", ".join(location_parts)

    remote_value = first_present(record, ("is_remote", "IS_REMOTE"))
    remote_text = "remote" if str(remote_value).lower() in {"true", "1", "yes"} else ""
    platform = first_present(record, ("site", "SITE"))

    return {
        "title": first_present(record, ("title", "TITLE")),
        "company": first_present(record, ("company", "COMPANY")),
        "location": location,
        "description": first_present(record, ("description", "DESCRIPTION")),
        "description_origin": "LinkedIn full description" if platform.lower() == "linkedin" and len(first_present(record, ("description", "DESCRIPTION"))) >= 900 else "Job board listing",
        "url": first_present(record, ("job_url", "JOB_URL", "url", "URL")),
        "apply_url": first_present(record, ("job_url_direct", "JOB_URL_DIRECT", "apply_url", "APPLY_URL")),
        "platform": platform.lower(),
        "remote": remote_text,
        "posted": first_present(record, ("date_posted", "DATE_POSTED")),
        "categories": first_present(
            record,
            ("job_type", "JOB_TYPE", "job_level", "JOB_LEVEL", "job_function", "JOB_FUNCTION"),
        ),
    }


def load_jobs_from_url(url: str, json_path: str | None, max_pages: int) -> list[dict]:
    data = fetch_json_url(url)
    if json_path:
        data = resolve_json_path(data, json_path)
    records = find_job_list_in_json(data)
    paginated = collect_paginated_records(url, data, json_path, max_pages)
    if paginated:
        records = paginated
    if not records:
        raise RuntimeError(
            f"Could not find a list of job records in {url}. "
            "Try --json-path or use a local CSV/JSON file."
        )
    return records


def collect_paginated_records(url: str, data: object, json_path: str | None, max_pages: int) -> list[dict]:
    if not isinstance(data, dict):
        return []

    total = data.get("totalCount")
    limit = data.get("limit")
    offset = data.get("offset", 0)
    if not all(isinstance(value, int) for value in (total, limit, offset)):
        return []
    if limit <= 0 or total <= limit:
        return []

    all_records = find_job_list_in_json(data)
    current_offset = offset + limit
    pages_fetched = 1

    while current_offset < total and pages_fetched < max_pages:
        page_url = replace_query_params(url, {"offset": current_offset, "limit": limit})
        page_data = fetch_json_url(page_url)
        if json_path:
            page_data = resolve_json_path(page_data, json_path)
        page_records = find_job_list_in_json(page_data)
        if not page_records:
            break
        all_records.extend(page_records)
        current_offset += limit
        pages_fetched += 1

    return all_records


def replace_query_params(url: str, params: dict[str, int]) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    for key, value in params.items():
        query[key] = str(value)
    return urlunparse(parsed._replace(query=urlencode(query)))


def load_jobs_from_csv(path: Path, delimiter: str, encoding: str) -> list[dict]:
    actual_delimiter = "\t" if delimiter == "\\t" else delimiter
    with path.open("r", encoding=encoding, newline="") as handle:
        reader = csv.DictReader(handle, delimiter=actual_delimiter)
        rows = list(reader)
    if not rows:
        raise RuntimeError(f"No rows found in CSV: {path}")
    return rows


def load_jobs_from_json(path: Path, encoding: str, json_path: str | None) -> list[dict]:
    data = json.loads(path.read_text(encoding=encoding))
    if json_path:
        data = resolve_json_path(data, json_path)
    records = find_job_list_in_json(data)
    if not records:
        raise RuntimeError(
            "Could not find a list of job records in the JSON file. "
            "Try --json-path data.jobs or inspect the file with --list-columns."
        )
    return records


def resolve_json_path(data: object, path: str) -> object:
    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise RuntimeError(f"JSON path not found: {path}")
    return current


def find_job_list_in_json(data: object) -> list[dict]:
    if isinstance(data, list):
        if all(isinstance(item, dict) for item in data):
            return data
        for item in data:
            nested = find_job_list_in_json(item)
            if nested:
                return nested
        return []

    if isinstance(data, dict):
        priority_keys = ("jobs", "results", "items", "data", "postings", "records", "vacancies")
        for key in priority_keys:
            if key in data:
                nested = find_job_list_in_json(data[key])
                if nested:
                    return nested
        for value in data.values():
            nested = find_job_list_in_json(value)
            if nested:
                return nested
    return []


def first_present(job: dict, keys: Iterable[str], default: str = "") -> str:
    for key in keys:
        value = job.get(key)
        if value is None:
            continue
        if isinstance(value, list):
            joined = ", ".join(str(item) for item in value if item)
            if joined:
                return joined
        if isinstance(value, dict):
            nested = json.dumps(value, ensure_ascii=False)
            if nested:
                return nested
        text = str(value).strip()
        if text:
            return text
    return default


def collect_input_columns(jobs: list[dict]) -> list[str]:
    keys: set[str] = set()
    for job in jobs[:100]:
        keys.update(str(key) for key in job.keys())
    return sorted(keys)


def dedupe_jobs(jobs: list[dict]) -> list[dict]:
    seen: set[tuple[str, str, str]] = set()
    deduped: list[dict] = []
    for raw_job in jobs:
        if not isinstance(raw_job, dict):
            continue
        url = first_present(raw_job, ("url", "job_url", "JOB_URL")).casefold()
        title = first_present(raw_job, ("title", "TITLE", "job_title")).casefold()
        company = first_present(raw_job, ("company", "COMPANY", "company_name")).casefold()
        key = (url, title, company)
        if key in seen:
            continue
        if not any(key):
            continue
        seen.add(key)
        deduped.append(raw_job)
    return deduped


def normalize_job(job: dict) -> dict:
    return {
        "title": first_present(
            job,
            ("title", "job_title", "name", "position", "role", "jobTitle", "posting_title", "TITLE"),
        ),
        "company": first_present(
            job,
            ("company", "company_name", "organization", "org", "employer", "account", "companyName", "COMPANY"),
        ),
        "location": first_present(
            job,
            (
                "location",
                "locations",
                "city",
                "place",
                "job_location",
                "formattedLocation",
                "region",
                "locationRestrictions",
                "locationRequirement",
                "LOCATION",
            ),
        ),
        "description": first_present(
            job,
            ("description", "summary", "content", "text", "body", "snippet", "requirements", "excerpt", "DESCRIPTION"),
        ),
        "description_origin": first_present(job, ("description_origin", "jd_source")) or "Job board listing",
        "url": first_present(
            job,
            (
                "url",
                "absolute_url",
                "apply_url",
                "external_url",
                "job_url",
                "link",
                "posting_url",
                "applicationLink",
                "guid",
                "JOB_URL",
            ),
        ),
        "apply_url": first_present(job, ("apply_url", "job_url_direct", "JOB_URL_DIRECT", "application_url")),
        "platform": first_present(job, ("platform", "source", "ats", "job_board", "site", "SITE")),
        "remote": first_present(
            job,
            ("remote", "remote_type", "workplace_type", "workplace", "remoteStatus", "schedule", "is_remote", "IS_REMOTE"),
        ),
        "posted": first_present(
            job,
            ("posted_at", "created_at", "updated_at", "date", "posted", "publication_date", "listedAt", "DATE_POSTED"),
        ),
        "categories": first_present(job, ("categories", "parentCategories", "tags", "skills", "JOB_TYPE", "job_type")),
    }


def html_to_text(page_html: str) -> str:
    """Extract readable text from an application page without adding an HTML parser dependency."""
    text = re.sub(r"(?is)<(?:script|style|noscript|svg).*?>.*?</(?:script|style|noscript|svg)>", " ", page_html)
    text = re.sub(r"(?i)</?(?:p|div|section|article|li|h[1-6]|br|tr|td|main|ul|ol)[^>]*>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


def fetch_application_page_text(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return ""
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html,application/xhtml+xml"})
    try:
        with urlopen(request, timeout=20) as response:
            content_type = response.headers.get_content_type()
            if content_type not in {"text/html", "application/xhtml+xml"}:
                return ""
            body = response.read(1_500_000).decode("utf-8", errors="ignore")
    except (HTTPError, URLError, TimeoutError, ValueError) as exc:
        print(f"Warning: could not verify application page {url}: {exc}", file=sys.stderr)
        return ""
    return html_to_text(body)


def linkedin_job_key(url: str) -> str:
    """Return a stable LinkedIn job identifier while ignoring tracking parameters."""
    parsed = urlparse(url)
    if "linkedin.com" not in parsed.netloc.lower():
        return ""
    match = re.search(r"/jobs/(?:view|collections/recommended)/?(\d+)", parsed.path)
    return f"linkedin:{match.group(1)}" if match else ""


def load_captured_linkedin_descriptions(path_text: str) -> dict[str, dict]:
    if not path_text:
        return {}
    try:
        data = json.loads(Path(path_text).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def apply_captured_linkedin_descriptions(jobs: list[dict], path_text: str) -> int:
    """Use full JD text explicitly saved from a LinkedIn page opened by the user."""
    captured = load_captured_linkedin_descriptions(path_text)
    applied = 0
    for job in jobs:
        if not isinstance(job, dict):
            continue
        normalized = normalize_job(job)
        if normalized["platform"].lower() != "linkedin":
            continue
        entry = captured.get(linkedin_job_key(normalized["url"]))
        description = entry.get("description", "") if isinstance(entry, dict) else ""
        if len(normalize_space(description)) < 300:
            continue
        job["description"] = description
        job["description_origin"] = "Captured from opened LinkedIn page"
        applied += 1
    return applied


def is_location_match(location: str, target_location: str) -> bool:
    if not location:
        return False
    lowered_target = target_location.strip().lower()
    if lowered_target == "toronto":
        return is_toronto_match(location)
    location_text = location.lower()
    target_tokens = [token for token in re.split(r"[,/|]+", lowered_target) if token.strip()]
    return any(token.strip() in location_text for token in target_tokens)


def is_toronto_match(location: str) -> bool:
    text = location.lower()
    return any(alias in text for alias in TORONTO_ALIASES)


def is_remote_friendly(job: dict) -> bool:
    combined = " ".join([job.get("location", ""), job.get("remote", ""), job.get("description", "")[:300]]).lower()
    return any(keyword in combined for keyword in ("remote", "hybrid", "work from home"))


def title_similarity(title: str, title_hints: list[str]) -> float:
    lowered_title = title.lower()
    best = 0.0
    for hint in title_hints:
        hint_tokens = set(tokenize(hint))
        title_tokens = set(tokenize(lowered_title))
        if hint_tokens and title_tokens:
            overlap = len(hint_tokens & title_tokens) / len(hint_tokens | title_tokens)
            best = max(best, overlap)
    return best


def keyword_overlap(job_text: str, keywords: list[str], limit: int = 45) -> tuple[int, list[str]]:
    haystack = set(tokenize(job_text))
    matches = [keyword for keyword in keywords[:limit] if keyword in haystack]
    return len(matches), matches[:12]


def extract_year_requirements(job_text: str) -> list[float]:
    """Extract every explicit experience requirement without inferring its subject area."""
    years: list[float] = []

    def parse_year_value(value: str) -> float:
        lowered = value.lower()
        return NUMBER_WORDS[lowered] if lowered in NUMBER_WORDS else float(value)

    for line in re.split(r"[\n\u2022]+|(?<=[.!?])\s+", job_text):
        range_match = re.search(rf"\b({YEAR_VALUE_PATTERN})\s*(?:-|to)\s*({YEAR_VALUE_PATTERN})\s+years?\b", line, re.I)
        if range_match:
            years.append(parse_year_value(range_match.group(1)))
            continue
        for match in re.finditer(
            rf"\b(?:minimum|at\s+least|required|over|more\s+than)?\s*({YEAR_VALUE_PATTERN})\s*(?:\+|plus)?\s+years?\b",
            line,
            re.I,
        ):
            years.append(parse_year_value(match.group(1)))
    return sorted(set(years))


def experience_match_score(job_text: str, profile: ResumeProfile) -> tuple[float, float | None, list[str]]:
    """Score solely from total professional experience versus the highest stated requirement."""
    requirements = extract_year_requirements(job_text)
    if not requirements:
        return 0.0, None, []
    required = max(requirements)
    actual = profile.experience_years.get("professional", 0.0)
    if actual >= required:
        return 2.0, required, [f"experience: {actual:g}y meets {required:g}y required"]
    if actual >= required * 0.75:
        return 1.0, required, [f"experience: {actual:g}y close to {required:g}y required"]
    penalty = 4.0 + (required - actual) * 2.0
    return -penalty, required, [f"experience: {actual:g}y vs {required:g}y required"]


def score_job(job: dict, profile: ResumeProfile, args: argparse.Namespace) -> tuple[float, list[str]]:
    title = job["title"]
    location = job["location"]
    platform = (job.get("platform") or "").lower()
    text = " ".join([title, job["company"], location, job["description"], job.get("categories", "")]).lower()
    if args.exclude_keywords and any(word.lower() in text for word in args.exclude_keywords):
        return 0.0, ["excluded keyword"]

    keyword_count, keyword_matches = keyword_overlap(text, profile.keywords)
    context_count, context_matches = keyword_overlap(" ".join([title, job.get("categories", "")]), profile.keywords)
    boosted_titles = profile.title_hints + args.titles
    title_score = title_similarity(title, boosted_titles)
    keyword_score = min(8.0, keyword_count * 0.35)
    context_score = min(1.5, context_count * 0.15)
    location_score = 2.5 if is_location_match(location, args.location) else 0.0
    remote_score = 1.25 if args.include_remote and is_remote_friendly(job) else 0.0
    seniority_penalty = 1.5 if re.search(r"\b(staff|principal|director|vp|vice president)\b", title.lower()) else 0.0
    description_bonus = math.log1p(max(len(job["description"]), 1)) / 4.5
    experience_score, required_years, experience_reasons = experience_match_score(job["description"], profile)
    total = (title_score * 7.0) + keyword_score + context_score + location_score + remote_score + description_bonus + experience_score - seniority_penalty
    reasons = keyword_matches[:6]
    reasons.extend(f"title/category: {word}" for word in context_matches[:2] if word not in keyword_matches)
    reasons.extend(experience_reasons)
    job["required_experience_years"] = required_years if required_years is not None else ""
    job["experience_match_score"] = round(experience_score, 2)
    if is_location_match(location, args.location):
        reasons.append(f"{args.location} match")
    elif args.include_remote and is_remote_friendly(job):
        reasons.append("remote/hybrid")
    if title_score > 0.34:
        reasons.append("title overlap")
    if platform == "linkedin" and len(normalize_space(job["description"])) < 900:
        # A short LinkedIn card often omits hard requirements such as years of experience.
        total = min(total, args.min_score + 1.0)
        reasons.append("LinkedIn JD incomplete - score capped")
    return total, dedupe_preserve_order(reasons)


def filter_and_rank_jobs(jobs: list[dict], profile: ResumeProfile, args: argparse.Namespace) -> list[dict]:
    ranked: list[dict] = []

    for raw_job in jobs:
        job = normalize_job(raw_job)
        if not job["title"] or not job["url"]:
            continue
        if not args.include_remote and not is_location_match(job["location"], args.location):
            continue
        score, reasons = score_job(job, profile, args)
        job["match_score"] = round(score, 2)
        job["below_match_threshold"] = score < args.min_score
        if job["below_match_threshold"]:
            reasons.append("below preferred score - kept as a candidate")
        job["match_reasons"] = ", ".join(reasons)
        ranked.append(job)

    ranked.sort(key=lambda item: item["match_score"], reverse=True)
    selected = keep_ranked_candidates(ranked, args)
    args.ranking_diagnostics = {
        "scored": len(ranked),
        "above_threshold": sum(not job.get("below_match_threshold") for job in ranked),
        "below_threshold": sum(job.get("below_match_threshold") for job in ranked),
        "displayed": len(selected),
    }
    return selected


def keep_ranked_candidates(ranked: list[dict], args: argparse.Namespace) -> list[dict]:
    """Keep strong matches first, with a useful tail for review instead of hiding all near matches."""
    ranked.sort(key=lambda item: item["match_score"], reverse=True)
    strong = [job for job in ranked if not job.get("below_match_threshold")]
    remaining = [job for job in ranked if job.get("below_match_threshold")]
    minimum = max(0, getattr(args, "min_candidate_results", 25))
    selected = strong + remaining[:max(0, minimum - len(strong))]
    return selected[: args.max_jobs]


def verify_top_application_pages(matches: list[dict], profile: ResumeProfile, args: argparse.Namespace) -> list[dict]:
    """Fetch full text from only the best candidates, then rerun local scoring."""
    if not getattr(args, "verify_apply_pages", False) or not matches:
        return matches

    limit = max(1, min(getattr(args, "verify_apply_limit", 15), len(matches)))
    verification_candidates = matches[:limit]
    if getattr(args, "source_balanced_verification", True):
        # First give each source one verification slot, then fill slots by global score.
        verification_candidates = []
        selected_ids: set[int] = set()
        seen_sources: set[str] = set()
        for index, job in enumerate(matches):
            source = (job.get("platform") or "unknown").lower()
            if source not in seen_sources:
                verification_candidates.append(job)
                selected_ids.add(index)
                seen_sources.add(source)
            if len(verification_candidates) >= limit:
                break
        for index, job in enumerate(matches):
            if len(verification_candidates) >= limit:
                break
            if index not in selected_ids:
                verification_candidates.append(job)

    checked = 0
    enriched = 0
    checked_sources: Counter[str] = Counter()
    for job in verification_candidates:
        checked += 1
        checked_sources[(job.get("platform") or "unknown").lower()] += 1
        page_url = job.get("apply_url") or job.get("url", "")
        page_text = fetch_application_page_text(page_url)
        if len(page_text) < 300:
            job["application_page_checked"] = "unavailable"
            continue

        # Preserve board data, but allow full company-page requirements to affect scoring.
        job["description"] = f"{job['description']}\n\n## Verified application page\n{page_text}"
        job["description_origin"] = "Verified company application page"
        job["application_page_checked"] = "verified"
        score, reasons = score_job(job, profile, args)
        job["match_score"] = round(score, 2)
        job["match_reasons"] = ", ".join(reasons)
        enriched += 1

    args.application_page_verification = {
        "checked": checked,
        "enriched": enriched,
        "sources_checked": dict(checked_sources),
    }
    for job in matches:
        job["below_match_threshold"] = job["match_score"] < args.min_score
    return keep_ranked_candidates(matches, args)


def resolve_ai_provider(args: argparse.Namespace) -> tuple[str, str, str, str] | None:
    """Return the selected Chat Completions provider configuration."""
    if args.ai_provider == "off":
        return None
    if args.ai_provider == "deepseek":
        if not args.ai_api_key:
            raise RuntimeError("DeepSeek reranking is enabled, but no API key was provided.")
        return "DeepSeek", DEEPSEEK_CHAT_URL, args.ai_model or "deepseek-chat", args.ai_api_key
    if args.ai_provider == "ollama":
        if not args.ai_model:
            raise RuntimeError("Ollama reranking needs a locally installed model name.")
        return "Ollama", args.ai_base_url or OLLAMA_CHAT_URL, args.ai_model, ""
    if args.ai_provider == "openai-compatible":
        if not args.ai_api_key or not args.ai_model or not args.ai_base_url:
            raise RuntimeError("OpenAI-compatible reranking needs an API key, model, and full Chat Completions URL.")
        return "OpenAI-compatible", args.ai_base_url, args.ai_model, args.ai_api_key
    raise RuntimeError(f"Unsupported AI provider: {args.ai_provider}")


def parse_ai_json(content: str) -> dict:
    """Accept JSON embedded in code fences or reasoning text from compatible models."""
    clean_content = content.strip()
    if clean_content.startswith("```"):
        clean_content = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean_content, flags=re.I)
    try:
        parsed = json.loads(clean_content)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, character in enumerate(clean_content):
        if character != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(clean_content[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise json.JSONDecodeError("No JSON object found in AI response", clean_content, 0)


def test_ai_connection(args: argparse.Namespace) -> dict[str, str]:
    """Send a minimal request to confirm the selected AI provider is usable."""
    provider = resolve_ai_provider(args)
    if provider is None:
        raise RuntimeError("Select an AI provider before testing the connection.")
    provider_name, endpoint, model, api_key = provider
    is_ollama = args.ai_provider == "ollama"
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "Reply with OK."}],
        "temperature": 0,
        "max_tokens": 8,
        "stream": False,
    }
    if is_ollama:
        # Prefer a direct structured answer when the local model supports this option.
        payload["think"] = False
    request = Request(
        endpoint,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        # Local 7B models can take longer than a cloud API to load on first use.
        with urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"{provider_name} API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach {provider_name}: {exc.reason}") from exc

    choices = result.get("choices", [])
    if not choices or not isinstance(choices[0], dict) or not isinstance(choices[0].get("message"), dict):
        raise RuntimeError(f"{provider_name} responded without a valid chat completion.")
    return {"provider": provider_name, "model": model}


def ai_rerank_jobs(matches: list[dict], profile: ResumeProfile, args: argparse.Namespace) -> list[dict]:
    """Use one JSON-only request to improve ordering of the local top matches."""
    provider = resolve_ai_provider(args)
    if provider is None:
        return matches
    if not matches:
        return matches

    provider_name, endpoint, model, api_key = provider

    # Keep local Ollama requests well below common 4K context windows.
    is_ollama = args.ai_provider == "ollama"
    max_candidates = 8 if is_ollama else 50
    description_limit = 350 if is_ollama else 850
    response_token_limit = 650 if is_ollama else 1200
    keyword_limit = 20 if is_ollama else 35
    limit = max(1, min(args.ai_rerank_limit, max_candidates, len(matches)))
    candidates = [
        {
            "id": index,
            "title": job["title"],
            "company": job["company"],
            "location": job["location"],
            "description": re.sub(r"\s+", " ", job["description"])[:description_limit],
        }
        for index, job in enumerate(matches[:limit])
    ]
    prompt = {
        "candidate_profile": {
            "target_titles": dedupe_preserve_order(profile.title_hints + args.titles)[:10],
            "skills_and_keywords": profile.keywords[:keyword_limit],
            "target_location": args.location,
        },
        "jobs": candidates,
    }
    system_message = (
        "You are a precise job-fit ranker. Return JSON only in this exact shape: "
        '{"rankings":[{"id":0,"score":0,"reason":"short reason"}]}. '
        "Include every supplied id exactly once. score is an integer 0 through 100. "
        "Prioritize relevant skills, role scope, and location. Keep each reason under 12 words."
    )
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_message},
            {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0.1,
        "max_tokens": response_token_limit,
        "stream": False,
    }
    request = Request(
        endpoint,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            **({"Authorization": f"Bearer {api_key}"} if api_key else {}),
            "Content-Type": "application/json",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:400]
        raise RuntimeError(f"{provider_name} API returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"Could not reach {provider_name}: {exc.reason}") from exc

    message = result.get("choices", [{}])[0].get("message", {})
    content = (
        message.get("content", "")
        or message.get("reasoning_content", "")
        or message.get("reasoning", "")
    )
    try:
        rankings = parse_ai_json(content).get("rankings", [])
    except json.JSONDecodeError as exc:
        args.ai_usage = {
            "provider": provider_name,
            "model": model,
            "reranked_jobs": 0,
            "warning": "AI response was not valid JSON; local ranking was kept.",
        }
        return matches

    scores = {item.get("id"): item for item in rankings if isinstance(item, dict)}
    for index, job in enumerate(matches[:limit]):
        ranking = scores.get(index)
        if not ranking:
            continue
        semantic_score = max(0, min(100, int(ranking.get("score", 0))))
        job["semantic_score"] = semantic_score
        job["match_score"] = round(job["match_score"] + semantic_score * 0.12, 2)
        reason = str(ranking.get("reason", "")).strip()
        if reason:
            job["match_reasons"] = f"{job['match_reasons']}, AI: {reason}".strip(", ")

    usage = result.get("usage", {})
    args.ai_usage = {
        "provider": provider_name,
        "model": model,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "total_tokens": usage.get("total_tokens"),
        "reranked_jobs": limit,
    }
    matches.sort(key=lambda item: item["match_score"], reverse=True)
    return matches


def export_jobs(jobs: list[dict], output_path: Path) -> None:
    fieldnames = ["overall_rank", "source_rank", "match_score", "semantic_score", "experience_match_score", "required_experience_years", "title", "company", "location", "platform", "remote", "posted", "url", "apply_url", "application_page_checked", "match_reasons"]
    with output_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        source_ranks: Counter[str] = Counter()
        for overall_rank, job in enumerate(jobs, start=1):
            source = (job.get("platform") or "unknown").lower()
            source_ranks[source] += 1
            row = {field: job.get(field, "") for field in fieldnames}
            row["overall_rank"] = overall_rank
            row["source_rank"] = source_ranks[source]
            writer.writerow(row)


def print_summary(profile: ResumeProfile, jobs: list[dict], output_path: Path) -> None:
    print("Inferred titles:")
    for title in profile.title_hints[:8]:
        print(f"  - {title}")
    print("\nTop resume keywords:")
    print("  " + ", ".join(profile.keywords[:20]))
    print(f"\nMatched jobs: {len(jobs)}")
    print(f"Saved to: {output_path}")


def print_input_columns(jobs: list[dict]) -> None:
    columns = collect_input_columns(jobs)
    print("Detected input columns/keys:")
    for column in columns:
        print(f"  - {column}")


def run_matcher(args: argparse.Namespace) -> tuple[ResumeProfile, list[dict]]:
    args.source_warnings = getattr(args, "source_warnings", [])
    resume_text = read_resume(Path(args.resume))
    profile = build_resume_profile(
        resume_text,
        args.titles,
        args.include_keywords,
        args.use_resume_keywords,
        getattr(args, "resume_keywords", None),
        getattr(args, "experience_years_override", None),
    )
    jobs = load_jobs(args, profile)
    captured_count = apply_captured_linkedin_descriptions(jobs, getattr(args, "captured_jds_file", ""))
    if captured_count:
        args.source_warnings.append(f"Used {captured_count} full LinkedIn description(s) saved from opened job pages.")
    expected_sources = [str(site).lower() for site in getattr(args, "jobspy_sites", [])]
    if getattr(args, "use_greenhouse", True):
        expected_sources.append("greenhouse")
    if getattr(args, "use_lever", True):
        expected_sources.append("lever")
    source_fetch_counts = Counter({source: 0 for source in expected_sources})
    source_fetch_counts.update(Counter(
        (normalize_job(job).get("platform") or "unknown").lower()
        for job in jobs
        if isinstance(job, dict)
    ))
    args.source_fetch_counts = dict(source_fetch_counts)
    args.fetched_jobs_preview = [
        normalize_job(job)
        for job in jobs
        if isinstance(job, dict) and normalize_job(job)["title"] and normalize_job(job)["url"]
    ][:100]
    matches = filter_and_rank_jobs(jobs, profile, args)
    matches = verify_top_application_pages(matches, profile, args)
    matches = ai_rerank_jobs(matches, profile, args)
    args.source_match_counts = dict(Counter(
        (job.get("platform") or "unknown").lower()
        for job in matches
    ))
    return profile, matches


def main() -> int:
    args = parse_args()
    resume_path = Path(args.resume)
    if not resume_path.exists():
        print(f"Resume not found: {resume_path}", file=sys.stderr)
        return 1
    if (
        not args.input
        and not args.input_url
        and not args.source
        and not args.greenhouse_boards
        and not args.lever_sites
        and not args.companies_file
        and not args.jobspy_sites
    ):
        print(
            "Error: provide --input, --input-url, --source, --greenhouse-boards, --lever-sites, --companies-file, or --jobspy-sites",
            file=sys.stderr,
        )
        return 1
    try:
        if args.list_columns:
            resume_text = read_resume(resume_path)
            profile = build_resume_profile(
                resume_text,
                args.titles,
                args.include_keywords,
                args.use_resume_keywords,
                args.resume_keywords,
                args.experience_years_override,
            )
            jobs = load_jobs(args, profile)
            print_input_columns(jobs)
            return 0
        profile, matches = run_matcher(args)
        export_jobs(matches, Path(args.out))
        print_summary(profile, matches, Path(args.out))
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

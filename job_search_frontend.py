#!/usr/bin/env python3
from __future__ import annotations

import argparse
import cgi
import json
import tempfile
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from job_search_resume_matcher import build_resume_profile, export_jobs, read_resume, run_matcher, test_ai_connection


WORKSPACE_DIR = Path(__file__).resolve().parent
HTML_PATH = WORKSPACE_DIR / "job_search_frontend.html"
PRESET_COMPANIES = {
    "toronto_canada": WORKSPACE_DIR / "companies_toronto_canada.txt",
    "global_tech": WORKSPACE_DIR / "companies_global_tech.txt",
}
CAPTURED_LINKEDIN_JDS_PATH = WORKSPACE_DIR / "captured_linkedin_jds.json"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local web UI for the resume job matcher.")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind the local server to.")
    parser.add_argument("--port", type=int, default=8765, help="Port for the local server.")
    parser.add_argument("--no-browser", action="store_true", help="Do not open the browser automatically.")
    return parser.parse_args()


def parse_csv_list(text: str) -> list[str]:
    return [item.strip() for item in text.replace("\n", ",").split(",") if item.strip()]


def save_uploaded_file(field: cgi.FieldStorage, target_dir: Path) -> Path:
    filename = Path(field.filename or "upload.bin").name
    destination = target_dir / filename
    data = field.file.read()
    destination.write_bytes(data)
    return destination


def make_namespace(form: cgi.FieldStorage, temp_dir: Path) -> argparse.Namespace:
    resume_field = form["resume"]
    if not getattr(resume_field, "filename", ""):
        raise RuntimeError("Please upload a resume file.")
    resume_path = save_uploaded_file(resume_field, temp_dir)

    companies_file = ""
    preset_name = form.getfirst("companies_preset", "").strip()
    if preset_name in PRESET_COMPANIES:
        companies_file = str(PRESET_COMPANIES[preset_name])

    if "companies_upload" in form and getattr(form["companies_upload"], "filename", ""):
        companies_file = str(save_uploaded_file(form["companies_upload"], temp_dir))

    jobspy_sites = form.getlist("jobspy_sites")
    output_name = form.getfirst("output_name", "toronto_matches.csv").strip() or "toronto_matches.csv"
    output_path = WORKSPACE_DIR / Path(output_name).name
    resume_keywords_text = form.getfirst("resume_keywords", "").strip()
    experience_years_text = form.getfirst("experience_years_override", "").strip()

    return argparse.Namespace(
        resume=str(resume_path),
        input="",
        input_url="",
        source="",
        greenhouse_boards=[],
        lever_sites=[],
        companies_file=companies_file,
        use_greenhouse=bool(form.getfirst("use_greenhouse")),
        use_lever=bool(form.getfirst("use_lever")),
        jobspy_sites=jobspy_sites,
        jobspy_search_terms=parse_csv_list(form.getfirst("jobspy_search_terms", "")),
        jobspy_results_wanted=int(form.getfirst("jobspy_results_wanted", "40")),
        jobspy_hours_old=int(form.getfirst("jobspy_hours_old", "0")) or None,
        jobspy_country_indeed=form.getfirst("jobspy_country_indeed", "Canada").strip() or "Canada",
        jobspy_linkedin_fetch_description=bool(form.getfirst("jobspy_linkedin_fetch_description")),
        captured_jds_file=str(CAPTURED_LINKEDIN_JDS_PATH),
        jobspy_linkedin_delay_seconds=float(form.getfirst("jobspy_linkedin_delay_seconds", "4")),
        jobspy_linkedin_max_terms=int(form.getfirst("jobspy_linkedin_max_terms", "3")),
        location=form.getfirst("location", "Toronto").strip() or "Toronto",
        include_remote=bool(form.getfirst("include_remote")),
        titles=parse_csv_list(form.getfirst("titles", "")),
        include_keywords=parse_csv_list(form.getfirst("include_keywords", "")),
        use_resume_keywords=bool(form.getfirst("use_resume_keywords")),
        resume_keywords=parse_csv_list(resume_keywords_text) if resume_keywords_text else None,
        experience_years_override=float(experience_years_text) if experience_years_text else None,
        exclude_keywords=parse_csv_list(form.getfirst("exclude_keywords", "")),
        json_path="",
        delimiter=",",
        encoding="utf-8-sig",
        list_columns=False,
        max_pages=10,
        max_jobs=int(form.getfirst("max_jobs", "150")),
        min_score=float(form.getfirst("min_score", "3.5")),
        min_candidate_results=25,
        ai_provider=form.getfirst("ai_provider", "off").strip() or "off",
        ai_api_key=form.getfirst("ai_api_key", "").strip(),
        ai_model=form.getfirst("ai_model", "").strip(),
        ai_base_url=form.getfirst("ai_base_url", "").strip(),
        ai_rerank_limit=int(form.getfirst("ai_rerank_limit", "20")),
        ai_usage={},
        verify_apply_pages=bool(form.getfirst("verify_apply_pages")),
        verify_apply_limit=int(form.getfirst("verify_apply_limit", "15")),
        source_balanced_verification=bool(form.getfirst("source_balanced_verification")),
        application_page_verification={},
        source_fetch_counts={},
        source_match_counts={},
        source_warnings=[],
        fetched_jobs_preview=[],
        ranking_diagnostics={},
        out=str(output_path),
    )


def make_ai_namespace(form: cgi.FieldStorage) -> argparse.Namespace:
    return argparse.Namespace(
        ai_provider=form.getfirst("ai_provider", "off").strip() or "off",
        ai_api_key=form.getfirst("ai_api_key", "").strip(),
        ai_model=form.getfirst("ai_model", "").strip(),
        ai_base_url=form.getfirst("ai_base_url", "").strip(),
    )


def make_response_payload(profile: Any, matches: list[dict], args: argparse.Namespace) -> dict[str, Any]:
    source_ranks: dict[str, int] = {}
    ranked_rows = []
    for overall_rank, job in enumerate(matches, start=1):
        source = str(job.get("platform", "") or "unknown").lower()
        source_ranks[source] = source_ranks.get(source, 0) + 1
        ranked_rows.append(
            {
                "overall_rank": overall_rank,
                "source_rank": source_ranks[source],
                "match_score": job.get("match_score", ""),
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "platform": job.get("platform", ""),
                "url": job.get("url", ""),
                "apply_url": job.get("apply_url", "") or job.get("url", ""),
                "description_origin": job.get("description_origin", "Job board listing"),
                "reasons": f"JD: {job.get('description_origin', 'Job board listing')} | {job.get('match_reasons', '')}",
            }
        )

    return {
        "output_path": args.out,
        "matched_jobs": len(matches),
        "inferred_titles": profile.title_hints,
        "top_keywords": profile.detected_keywords[:20],
        "matching_keywords": profile.keywords[:20],
        "resume_experience_years": profile.experience_years,
        "ai_usage": args.ai_usage,
        "application_page_verification": args.application_page_verification,
        "source_fetch_counts": getattr(args, "source_fetch_counts", {}),
        "source_match_counts": getattr(args, "source_match_counts", {}),
        "source_warnings": getattr(args, "source_warnings", [])[:4],
        "ranking_diagnostics": getattr(args, "ranking_diagnostics", {}),
        "fetched_preview": [
            {
                "title": job.get("title", ""),
                "company": job.get("company", ""),
                "location": job.get("location", ""),
                "platform": job.get("platform", ""),
                "url": job.get("url", ""),
                "description_length": len(job.get("description", "")),
            }
            for job in getattr(args, "fetched_jobs_preview", [])
        ],
        "preview": ranked_rows[:25],
        "indeed_preview": [row for row in ranked_rows if row["platform"].lower() == "indeed"][:25],
        "linkedin_preview": [row for row in ranked_rows if row["platform"].lower() == "linkedin"][:25],
    }


class JobSearchHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path in {"/", "/index.html"}:
            self._serve_html()
            return
        self.send_error(HTTPStatus.NOT_FOUND, "Not found")

    def do_POST(self) -> None:
        if self.path == "/api/resume-preview":
            self._handle_resume_preview()
            return
        if self.path == "/api/test-ai":
            self._handle_test_ai()
            return
        if self.path == "/api/capture-linkedin-jd":
            self._handle_capture_linkedin_jd()
            return
        if self.path != "/api/run":
            self.send_error(HTTPStatus.NOT_FOUND, "Not found")
            return
        self._handle_run()

    def log_message(self, format: str, *args: object) -> None:
        return

    def _serve_html(self) -> None:
        html = HTML_PATH.read_text(encoding="utf-8")
        body = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_run(self) -> None:
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                },
            )
            with tempfile.TemporaryDirectory(prefix="job-search-ui-") as temp_name:
                temp_dir = Path(temp_name)
                args = make_namespace(form, temp_dir)
                profile, matches = run_matcher(args)
                export_jobs(matches, Path(args.out))
                payload = make_response_payload(profile, matches, args)
            self._send_json(HTTPStatus.OK, payload)
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_resume_preview(self) -> None:
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                },
            )
            resume_field = form["resume"]
            if not getattr(resume_field, "filename", ""):
                raise RuntimeError("Please select a resume file.")
            with tempfile.TemporaryDirectory(prefix="job-search-preview-") as temp_name:
                resume_path = save_uploaded_file(resume_field, Path(temp_name))
                profile = build_resume_profile(read_resume(resume_path), [], [])
            self._send_json(
                HTTPStatus.OK,
                {
                    "inferred_titles": profile.title_hints,
                    "top_keywords": profile.detected_keywords[:20],
                    "resume_experience_years": profile.experience_years,
                },
            )
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_test_ai(self) -> None:
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                },
            )
            self._send_json(HTTPStatus.OK, test_ai_connection(make_ai_namespace(form)))
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _handle_capture_linkedin_jd(self) -> None:
        try:
            form = cgi.FieldStorage(
                fp=self.rfile,
                headers=self.headers,
                environ={
                    "REQUEST_METHOD": "POST",
                    "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                },
            )
            job_url = form.getfirst("job_url", "").strip()
            description = form.getfirst("description", "").strip()
            from job_search_resume_matcher import linkedin_job_key

            key = linkedin_job_key(job_url)
            if not key:
                raise RuntimeError("Paste the LinkedIn job URL from the job page.")
            if len(description) < 300:
                raise RuntimeError("Paste the full job description (at least 300 characters).")
            try:
                existing = json.loads(CAPTURED_LINKEDIN_JDS_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                existing = {}
            if not isinstance(existing, dict):
                existing = {}
            existing[key] = {"url": job_url, "description": description}
            CAPTURED_LINKEDIN_JDS_PATH.write_text(json.dumps(existing, ensure_ascii=False, indent=2), encoding="utf-8")
            self._send_json(HTTPStatus.OK, {"saved": True, "key": key})
        except Exception as exc:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> int:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), JobSearchHandler)
    url = f"http://{args.host}:{args.port}/"
    print(f"Job search UI running at {url}")
    if not args.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

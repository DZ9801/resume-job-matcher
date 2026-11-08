# Resume Job Matcher

A local-first job search and resume matching tool with a browser interface. It
collects jobs from public company boards and optional job aggregators, scores
them against a resume, and exports ranked results to CSV.

The defaults are optimized for Toronto and Canada, but the target location,
titles, keywords, and sources are configurable.

## Features

- Reads resumes in PDF, DOCX, TXT, and Markdown formats.
- Infers likely job titles, skills, keywords, and professional experience.
- Collects public listings from Greenhouse and Lever.
- Optionally searches Indeed, LinkedIn, Glassdoor, Google, and ZipRecruiter
  through [python-jobspy](https://github.com/speedyapply/JobSpy).
- Ranks jobs locally using title, keyword, location, remote-work, seniority,
  description quality, and experience signals.
- Can verify top matches against their company application pages.
- Supports optional semantic reranking with DeepSeek, Ollama, or another
  OpenAI-compatible Chat Completions endpoint.
- Exports ranked results to CSV.

## Quick start

The current local web interface supports Python 3.10 through 3.12.

```powershell
git clone https://github.com/DZ9801/resume-job-matcher.git
cd resume-job-matcher
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-job-search.txt
python job_search_frontend.py
```

Open <http://127.0.0.1:8765/> if the browser does not open automatically. On
Windows, `start_job_search_ui.bat` starts the same interface.

### Optional JobSpy sources

```powershell
python -m pip install --no-deps python-jobspy
python -m pip install pandas numpy beautifulsoup4 pydantic tls-client markdownify regex requests
```

JobSpy-backed sources depend on third-party sites and may be incomplete or
rate-limited. Public Greenhouse and Lever feeds are generally more dependable.

## Using the browser interface

1. Upload a resume.
2. Review the inferred titles, keywords, and experience estimate.
3. Choose a company preset and optional JobSpy sources.
4. Adjust the target location, titles, keywords, and score threshold.
5. Run the search and review the ranked results.
6. Open the generated CSV for the complete export.

AI reranking is disabled by default. API keys entered in the interface are used
only for the current request and are not written to disk. Ollama runs locally
and does not require an API key.

## Command-line example

```powershell
python job_search_resume_matcher.py `
  --resume "C:\path\to\resume.pdf" `
  --companies-file "companies_toronto_canada.txt" `
  --jobspy-sites indeed `
  --jobspy-search-terms "Software Engineer" "Data Analyst" `
  --location "Toronto" `
  --include-remote `
  --out "toronto_matches.csv"
```

Run `python job_search_resume_matcher.py --help` for all options. More examples
are available in [README_job_search.md](README_job_search.md).

## Data and privacy

- Resume processing and rule-based scoring run locally.
- Resume uploads are held in a temporary directory during a search.
- AI reranking sends only a limited set of top-ranked job data and extracted
  profile signals to the selected provider.
- Manually captured LinkedIn job descriptions are stored locally in
  `captured_linkedin_jds.json`, which is excluded from Git.
- Generated match CSV files are excluded from Git by default.

Review the selected AI provider's privacy policy before enabling AI reranking.
The web server has no authentication and is intended for localhost use only;
do not bind it to a public or untrusted network interface.

## Project files

| File | Purpose |
| --- | --- |
| `job_search_frontend.py` | Local HTTP server and API endpoints |
| `job_search_frontend.html` | Browser interface |
| `job_search_resume_matcher.py` | Resume parsing, collection, scoring, reranking, and export |
| `companies_toronto_canada.txt` | Toronto/Canada company-board preset |
| `companies_global_tech.txt` | Global technology company-board preset |
| `companies.example.txt` | Example custom company list |

## Limitations

- Scraping-backed sources can change, block requests, or return partial job
  descriptions.
- Resume parsing and experience estimates are heuristic and should be reviewed.
- Match scores are prioritization aids, not hiring predictions.
- Verify job details on the employer's official application page before
  applying.

## License

No open-source license has been selected yet. The source is visible for review,
but reuse and redistribution are not granted until a license is added.

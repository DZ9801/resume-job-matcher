# Resume Job Matcher

This script can score jobs against your resume and now works especially well with public `Greenhouse` and `Lever` job feeds.

## Local web UI

If you want a simpler frontend, you can run the local browser UI:

```powershell
cd path\to\resume-job-matcher
python job_search_frontend.py
```

Or just double-click [start_job_search_ui.bat](start_job_search_ui.bat).

That starts a local server at `http://127.0.0.1:8765/`, opens a browser, and lets you:

- upload your resume
- immediately preview inferred titles, keywords, and the professional-experience estimate from the uploaded resume
- choose whether detected resume keywords are included in scoring, and add your own matching keywords
- create official LinkedIn searches for general entry-level terms such as `entry level`, `new grad`, and `graduate program`
- choose the Toronto / Canada or global company preset
- turn `Indeed` / `LinkedIn` / other JobSpy sources on or off
- set titles, keywords, score threshold, and output filename
- export results to CSV without typing long commands

### LinkedIn request pacing

LinkedIn results use JobSpy and are not guaranteed. When LinkedIn is selected, this tool runs search terms serially, defaults to three terms per run, and pauses four seconds between terms. These controls reduce bursty requests but cannot prevent rate limits or make LinkedIn scraping reliable. Prefer LinkedIn job alerts and direct company career pages for dependable coverage.

### Complete LinkedIn job descriptions

The local UI first asks JobSpy for full LinkedIn descriptions and then verifies top matches against a company application page when one is available. Neither route is guaranteed because LinkedIn pages are dynamic and rate-limited.

For a job you want to evaluate accurately, open it in your own LinkedIn session, copy the complete visible description, then use **Save a full LinkedIn job description** in the LinkedIn source section. The text is stored only in `captured_linkedin_jds.json` on your computer and is used to rescore that matching LinkedIn job on later searches. This avoids treating a short search-card summary as a complete JD.

### Professional experience estimate

The experience estimate only reads a `Professional Experience` or `Work Experience` section. It stops at research, academic, education, project, publication, teaching, volunteer, or skills sections, so those dates are not counted as professional employment.

### Optional AI semantic reranking

The UI defaults to local, zero-token matching. `AI Provider` can be set to `DeepSeek`, `Ollama Local`, or any `OpenAI-compatible API`. It only sends the locally ranked top jobs for final reranking (5-50, default 20), so job collection and most matching remain local. API keys are used only for the current request and are not written to disk. Ollama needs no key; start Ollama locally, choose an installed model, and the default local URL is filled in automatically.

## Install

```powershell
cd path\to\resume-job-matcher
python -m pip install -r requirements-job-search.txt
```

Optional JobSpy install:

```powershell
cd path\to\resume-job-matcher
python -m pip install --no-deps python-jobspy
python -m pip install pandas numpy beautifulsoup4 pydantic tls-client markdownify regex requests
```

This installs `python-jobspy` without pip getting stuck on its dependency metadata, then installs the runtime packages separately.

## Greenhouse

Greenhouse exposes public job listings at:

- `GET https://boards-api.greenhouse.io/v1/boards/{board_token}/jobs?content=true`

Run with one or more board tokens:

```powershell
cd path\to\resume-job-matcher
python job_search_resume_matcher.py `
  --resume "C:\path\to\resume.pdf" `
  --greenhouse-boards stripe figma shopify `
  --titles "Software Engineer" "Data Analyst" "Data Engineer" "QA Engineer" `
  --include-remote `
  --out "greenhouse_matches.csv"
```

## Lever

Lever exposes public job listings at:

- `GET https://api.lever.co/v0/postings/{site}?mode=json`

Run with one or more site names:

```powershell
cd path\to\resume-job-matcher
python job_search_resume_matcher.py `
  --resume "C:\path\to\resume.pdf" `
  --lever-sites netflix sourcegraph `
  --titles "Software Engineer" "Data Analyst" "Data Engineer" "QA Engineer" `
  --include-remote `
  --out "lever_matches.csv"
```

## Mix Greenhouse and Lever

```powershell
cd path\to\resume-job-matcher
python job_search_resume_matcher.py `
  --resume "C:\path\to\resume.pdf" `
  --greenhouse-boards stripe figma `
  --lever-sites sourcegraph `
  --titles "Software Engineer" "Data Analyst" "Data Engineer" "QA Engineer" `
  --location "Toronto" `
  --include-remote `
  --out "toronto_matches.csv"
```

## Recommended Toronto flow: Indeed + Greenhouse + Lever

This is the most practical combined setup for your use case:

```powershell
cd path\to\resume-job-matcher
python job_search_resume_matcher.py `
  --resume "C:\path\to\resume.pdf" `
  --companies-file "companies_toronto_canada.txt" `
  --jobspy-sites indeed `
  --jobspy-search-terms "Software Engineer" "Data Analyst" "Data Engineer" "QA Engineer" `
  --jobspy-country-indeed "Canada" `
  --jobspy-results-wanted 40 `
  --location "Toronto" `
  --include-remote `
  --out "toronto_matches.csv"
```

## Optional LinkedIn via JobSpy

LinkedIn is supported, but it is more rate-limit prone than Indeed.

```powershell
cd path\to\resume-job-matcher
python job_search_resume_matcher.py `
  --resume "C:\path\to\resume.pdf" `
  --companies-file "companies_toronto_canada.txt" `
  --jobspy-sites indeed linkedin `
  --jobspy-search-terms "Software Engineer" "Data Analyst" `
  --jobspy-country-indeed "Canada" `
  --jobspy-results-wanted 25 `
  --location "Toronto" `
  --include-remote `
  --out "toronto_matches.csv"
```

## Use a companies file

If you do not want to type a long list every time, use a text file like [companies.example.txt](companies.example.txt).

Supported format:

```text
greenhouse:stripe
greenhouse:figma
lever:spotify
```

Run with:

```powershell
cd path\to\resume-job-matcher
python job_search_resume_matcher.py `
  --resume "C:\path\to\resume.pdf" `
  --companies-file "companies.example.txt" `
  --titles "Software Engineer" "Data Analyst" "Data Engineer" "QA Engineer" `
  --location "Toronto" `
  --include-remote `
  --out "toronto_matches.csv"
```

## How to find the token or site name

- Greenhouse board token:
  Look at a company jobs page like `https://boards.greenhouse.io/stripe`
  The token is the last path segment, here `stripe`.

- Lever site name:
  Look at a company jobs page like `https://jobs.lever.co/sourcegraph`
  The site name is the last path segment, here `sourcegraph`.

## Still supported

The script also still supports:

- local `--input` CSV or JSON
- generic `--input-url`
- built-in `--source freehire` or `--source himalayas`
- `--jobspy-sites indeed linkedin glassdoor google zip_recruiter`

But for your use case, `Indeed + Greenhouse + Lever` is the recommended path, with LinkedIn optional.

# GitHub Trending Digest

Scrapes `github.com/trending/{language}`, summarizes new/changed repos
against your interest profile, and emails a digest once a day.

## Files

- `scraper.py` — fetches and parses the trending page, plus the structure-check guard
- `db.py` — single-table SQLite store (recurrence dedup, caching)
- `summarize.py` — Claude Haiku call: summary + use-cases per repo
- `render.py` — builds the HTML email body
- `send.py` — sends via Resend
- `main.py` — wires the above into one run; this is what the cron job calls
- `interests.txt` — your interest profile (edit this — it's the personalization anchor)
- `.github/workflows/digest.yml` — the daily cron job

## Setup

1. `pip install -r requirements.txt`
2. Edit `interests.txt` to describe what you actually work on.
3. On GitHub, verify a sending domain in Resend, then set these repo secrets
   (Settings → Secrets and variables → Actions):
   - `ANTHROPIC_API_KEY`
   - `RESEND_API_KEY`
   - `DIGEST_FROM_EMAIL` (must be on your verified Resend domain)
   - `DIGEST_TO_EMAIL`
4. Before relying on the scraper, check `github.com/robots.txt` yourself —
   this was flagged as an open question in the PRD and wasn't resolved here.
5. Push to GitHub. The workflow runs daily at 13:00 UTC, or trigger it by
   hand from the Actions tab (`workflow_dispatch`).

## Why the workflow commits the database back to the repo

GitHub Actions runners are ephemeral — nothing on disk survives between
runs unless you persist it explicitly. The last step in `digest.yml` commits
`data/repos.db` back to the repository after each run so recurrence dedup
(F4) actually works across days. First run will create `data/repos.db`.

## Changing the language

Set `DIGEST_LANGUAGE` in the workflow's `env:` block (e.g. `go`, `typescript`).
v1 supports one language at a time, per the PRD's non-goals.

## What was deliberately left out (YAGNI)

- No ORM — one table, raw SQL via stdlib `sqlite3`.
- No retry/backoff or dead-letter queue — a missed day is acceptable per the
  PRD's availability NFR, and re-runs are safe (dedup prevents double LLM spend).
- No separate logging framework — GitHub Actions' own run logs are the log.
- No config file/framework — everything is an environment variable.
- No multi-language, multi-user, or historical-backfill support.

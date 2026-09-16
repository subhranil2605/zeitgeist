# zeitgeist (GitHub Trending Digest)

Scrapes `github.com/trending/{language}`, summarizes new/changed repos against
a personal interest profile with an LLM, and emails a daily digest via Resend.
Runs unattended on a GitHub Actions cron. See `docs/PRD.md` for the full spec.

## Stack

- **Language / Runtime**: Python >=3.14
- **Key dependencies**: `requests` + `beautifulsoup4` (scraping), `langchain-google-genai`
  (Gemini LLM calls, structured output via `pydantic`), `resend` (email), stdlib `sqlite3`
  (single-table cache, no ORM)
- **Package manager**: `uv` (`uv.lock` present) for local dev; CI installs via
  `pip install -r requirements.txt` — keep both files in sync when adding a dependency

## Build approach

<TBD, set by /scope>

## Commands

```bash
# Install
uv sync            # or: pip install -r requirements.txt

# Run
python main.py
```

No test suite or lint config exists yet.

## Architecture

`main.py` wires the pipeline in order: `scraper.fetch_trending` -> `scraper.check_parse_quality`
(hard-stop guard) -> `db.needs_summary` (skip LLM if cached and unchanged) ->
`summarize.summarize_repo` -> `db.upsert` -> `render.render_digest` -> `send.send_digest`.

## Rules

- A parse-structure failure (`check_parse_quality`) aborts the *entire* run — never send a
  partial/garbage digest. Don't weaken this guard to "skip and continue."
- One repo's LLM summarization failure is logged and skipped; it must never kill the run
  for the other repos.
- Recurrence dedup (`db.needs_summary`, keyed on `full_name` + description hash) exists to
  avoid re-spending LLM calls on unchanged repos — preserve this when touching `db.py` or
  `main.py`.
- Deliberately no ORM, no retry/backoff, no logging framework, no config file: see the
  README's "What was deliberately left out" section before adding infrastructure.
- Env vars, not a config file: `DIGEST_LANGUAGE`, `DIGEST_PROFILE_PATH`, `GOOGLE_API_KEY`,
  `RESEND_API_KEY`, `DEFAULT_FROM_EMAIL`, `DIGEST_TO_EMAIL`.

## Gotchas

- The GitHub Actions workflow (`.github/workflows/digest.yml`) commits `data/repos.db` back
  to the repo after every run — runners are ephemeral, so this is how recurrence dedup
  persists across days. Don't remove that step without replacing the persistence mechanism.
- README.md describes the LLM as "Claude Haiku" in one place, but the actual code
  (`main.py`, `src/summarize.py`) calls Gemini via `langchain-google-genai` — treat the
  code as the source of truth and update the README if you touch that area.
- `main.py`'s HTML file-write is commented out; the only saved-HTML path is the
  `data/last_failed_digest.html` fallback when Resend send fails.

## Agent skills

- [resend](.claude/skills/resend/): `resend/resend-skills`, Resend email API conventions (used by `src/send.py`)
- [langchain-fundamentals](.claude/skills/langchain-fundamentals/): `langchain-ai/langchain-skills`, LangChain agent/tool conventions (used by `src/summarize.py`)
- [gemini-api-dev](.claude/skills/gemini-api-dev/): `google-gemini/gemini-skills`, Gemini API conventions (this project's LLM backend)
- [beautifulsoup-parsing](.claude/skills/beautifulsoup-parsing/): `mindrally/skills`, BeautifulSoup scraping conventions (used by `src/scraper.py`)
- [github-actions-templates](.claude/skills/github-actions-templates/): `wshobson/agents`, GitHub Actions workflow conventions (used by `.github/workflows/digest.yml`)

MCP servers: Resend MCP (recommended, resend.com/docs/mcp-server), web scraping MCP (recommended, community, e.g. Apify's BeautifulSoup Scraper)

## Context files

<!-- Nested AGENTS.md files are listed here as they are created -->

_Drafted by /audit from the repo, worth a quick human pass. Edit freely: once a line stops matching this draft, later runs treat it as curated and will flag rather than overwrite it._

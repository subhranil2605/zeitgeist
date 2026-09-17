# Scope: zeitgeist (GitHub Trending Digest)

A daily script that scrapes GitHub Trending, summarizes new or changed repos against a personal interest profile with an LLM, and emails a digest. Runs unattended on a GitHub Actions cron. This pass hardens the existing pipeline to production grade: logging, retry with backoff, and tighter exception handling.

**Build approach:** Tracer Bullet (thicken one reliability segment of the existing pipeline at a time, each real and working end to end).
**Workflow:** Beta (after `/develop`: `/check verify`, then `/test`). `/architect` is the recommended first stop for a feature with a real decision, but skippable when you already know the build. Any feature can carry its own tag (e.g. `· GA`) to do more or less.

_These are recommendations to keep your build orderly, not requirements. Skip anything that does not fit: if you already know how to build a feature, use `/develop` and skip `/architect`. You decide when a feature is `done`._

## At a glance

| # | Feature | Phase | Status |
|---|---------|-------|--------|
| A | Trending scraper & parse-quality guard | Existing | existing |
| B | Per-repo LLM summarization | Existing | existing |
| C | Recurrence dedup / cache DB | Existing | existing |
| D | Digest HTML rendering | Existing | existing |
| E | Email delivery (Resend) | Existing | existing |
| F | Pipeline orchestration | Existing | existing |
| G | Daily GitHub Actions cron | Existing | existing |
| 1 | Structured logging | Foundation | in-progress |
| 2 | Retry with backoff on I/O calls | Slice 1: Reliability hardening | done |
| 3 | Exception handling hardening | Slice 2: Reliability hardening | planned |

## Existing

### A. Trending scraper & parse-quality guard · existing
Fetches `github.com/trending/{language}` and parses each row; `check_parse_quality` hard-stops the whole run if too many required fields come back empty. code in `src/scraper.py`

### B. Per-repo LLM summarization · existing
Calls Gemini via `langchain-google-genai` with structured output to produce a summary and use-cases for one repo against the interest profile. code in `src/summarize.py`

### C. Recurrence dedup / cache DB · existing
Single-table SQLite cache keyed on `full_name`; skips re-summarizing unchanged repos and refreshes after 7 days. code in `src/db.py`

### D. Digest HTML rendering · existing
Renders the day's entries into the email HTML body. code in `src/render.py`

### E. Email delivery (Resend) · existing
Sends the rendered digest via the Resend API. code in `src/send.py`

### F. Pipeline orchestration · existing
Wires scrape -> parse-quality guard -> dedup check -> summarize -> upsert -> render -> send, with today's error handling (abort on scrape/guard failure, skip-and-continue on one repo's summarization failure, save-HTML-on-send-failure fallback). code in `main.py`

### G. Daily GitHub Actions cron · existing
Runs the pipeline daily and commits `data/repos.db` back to the repo so dedup persists across ephemeral runners. code in `.github/workflows/digest.yml`

## Foundations

### 1. Structured logging
Replace the `print(..., file=sys.stderr)` calls with Python's `logging` module, leveled (INFO for normal progress, WARNING for skipped repos, ERROR for aborts), still captured by GitHub Actions' own run log — no new destination. Every later feature's retry attempts and caught exceptions log through this.
**Done when:** every existing print/stderr call point emits through `logging` at an appropriate level, and the run log still reads at least as clearly as it does today.
- [x] `/develop structured logging` · code in `main.py`

## Slice 1: Reliability hardening

### 2. Retry with backoff on I/O calls
The scrape request, the per-repo LLM call, and the Resend send each get retry with backoff on transient failures before the pipeline's existing hard-stop/skip/fallback behavior kicks in.
**Done when:** a transient failure at any of the three call sites is retried with backoff before falling through to today's behavior (scrape failure still aborts the run after retries are exhausted, an LLM failure still only skips that one repo, a send failure still falls back to saved HTML) — permanent failures are not retried into a longer outage.
spec [0001](../specs/0001-retry-with-backoff-io-calls.md)
- [x] Design it (spec): `/architect retry with backoff on I/O calls`
- [x] Build it: `/develop retry with backoff on I/O calls` · code in `src/scraper.py`, `src/summarize.py`, `src/send.py`
  - [x] Add `tenacity` as a direct dependency, pinned to the version already resolved in `uv.lock`, satisfies AC-1, AC-2, AC-3
  - [x] Retry the scrape call on transient network/5xx/429 failures, satisfies AC-1, AC-4, AC-5, AC-6
  - [x] Retry the Gemini summarize call on transient rate-limit/server/transport failures, satisfies AC-2, AC-4, AC-5, AC-6
  - [x] Retry the Resend send call on transient rate-limit/server/transport failures, satisfies AC-3, AC-4, AC-5, AC-6
- [x] Verify it: `/check verify retry with backoff on I/O calls`
- [x] Test it: `/test retry with backoff on I/O calls`

## Slice 2: Reliability hardening

### 3. Exception handling hardening
Close the remaining unhandled failure paths: the profile file read, the DB connection/open, and an unexpected exception surfacing out of `main()` should all be caught, logged with context (which stage, which repo if applicable), and exit non-zero — never an unlogged crash. Preserves every existing guard (parse-quality hard-stop, per-repo skip-and-continue, send-failure fallback) exactly as documented in `AGENTS.md`.
**Done when:** every currently-unhandled failure path in `main.py` is caught and logged with context before the process exits non-zero, and none of today's three documented error-handling behaviors changed.
- [ ] `/develop exception handling hardening`

## Legend

**The decision box.** Every feature carries exactly one, the sub-task whose label ends with `(spec)`. Every other box is an execution box and `/architect` never ticks one.

**Feature lifecycle**: the scope updates as a feature moves; each row is what it shows and who sets it:

| State | Set by | The feature shows |
|---|---|---|
| `planned` · needs a decision | `/scope` | one box: `Design it (spec): /architect <feature>` |
| `in-progress` (designed) | **`/architect` at spec capture** | `Design it` ticked; spec linked; `Build it: /develop <feature>` + **2 to 5 milestones**; the tier's closing boxes (`Verify it`, `Test it`); any surfaced follow-up enrolled |
| `in-progress` (building) | `/develop` | milestone sub-boxes tick one by one; code pointer filled |
| `in-progress` (verified) | `/check verify` | `Build it` + milestones ticked; `Verify it` ticked |
| `done` | **you, when you decide it is** (any skill sets it when you say so); `/sync` reconciles | boxes you ran ticked, skipped ones marked skipped; Beta's last stage (`/test`) is the suggested point to call it done |

- **Next step** = the first unticked box (always a command or a tracked milestone).
- **needs a decision** = run `/architect` first; otherwise straight to `/develop`. The tag drops once the spec is captured.
- **Atomic build tasks live in the spec's `## Build plan`, not here**: the scope carries only the milestone rollup.
- **Status** `planned` -> `in-progress` -> `done`, plus `existing` (pre-workflow, this pass never touches these rows) and `dropped` (de-scoped, kept for history).
- **Workflow** (header line) is the project default: **Beta** = `/check verify` then `/test`.
- **Pointer line** (`spec <n> · code in <path>`): the spec link added by `/architect`, the code path by `/develop`.

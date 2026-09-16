# PRD: Daily GitHub Trending Digest

**Status:** Draft
**Owner:** [you]
**Last updated:** 2026-09-16
**Related:** Reuses architectural lessons from the arXiv Daily Digest PRD (personalization anchor, model tiering, solo-project failure handling). New elements specific to this project: scraping fragility guard, repo-recurrence dedup.

---

## 1. Problem Statement

GitHub's trending page (`github.com/trending/{language}`) surfaces ~25 repos/day for a given language, but has no digest/notification mechanism and no official API. Manually checking it daily doesn't happen. The goal is an automated pipeline that scrapes the daily trending list for a specific language, summarizes each repo with a use-case framed around your interests, and delivers it by email.

## 2. Goals / Non-Goals

**Goals**

- Fully automated daily scrape of `github.com/trending/{language}`
- Per-repo: summary + suggested use-cases specific to your stated interests (not generic boilerplate)
- Avoid re-summarizing repos that recur on the trending list unchanged
- Resilient to the page's HTML structure changing (fail loud, not silently send garbage)
- Minimal ongoing cost and minimal maintenance burden
**Non-Goals**
- Multi-language support in v1 (single language, per your request)
- Multi-user / multi-tenant support
- Exact replication of GitHub's internal trending algorithm — you're consuming what the page shows, not reverse-engineering their ranking
- Production-grade scraping infra (proxy rotation, headless browser, CAPTCHA handling) — at 1 request/day this is unnecessary
- Historical backfill if a run is missed

## 3. Users

Single user (you). No auth, no accounts.

## 4. Functional Requirements

| ID | Requirement |
| ---- | ------------- |
| F1 | System scrapes `github.com/trending/{language}?since=daily` once per day |
| F2 | System parses: repo full name, description, total stars, stars-today, primary language, repo URL |
| F3 | **System validates the parse before proceeding** — if expected fields are missing/null above a threshold, abort the run and log; do not send a partial/garbage report |
| F4 | System checks each repo against a local store; skips LLM summarization for repos already summarized with an unchanged description (hash comparison), reusing the cached summary/use-cases instead |
| F5 | System generates, for each new-or-changed repo: a summary, and suggested use-cases framed against a stored personal interest profile |
| F6 | System renders an HTML email listing all of today's trending repos for the language, with cached or freshly generated content per repo |
| F7 | System sends the report via Resend |
| F8 | System handles zero-repos/parse-failure days by skipping the send and logging, not by sending an empty or broken email |

## 5. Non-Functional Requirements

| Category | Requirement |
| ---------- | ------------- |
| Latency | Batch job, target <5 min per run (much smaller volume than the arXiv project — no scoring/ranking stage needed) |
| Availability | Best-effort, no SLA. A missed day is acceptable. |
| Cost | Near-zero — one page fetch/day, LLM calls only for new/changed repos (~5-15/day realistically, not the full ~25, once recurrence caching kicks in) |
| Resilience | Must degrade to "skip and log" rather than "send broken content" when the source page's structure changes |
| Maintainability | Prefer less code over defensive infrastructure — same principle as the arXiv project's solo-build revision |

## 6. System Architecture

```
[Scheduler: GitHub Actions cron]
        │
        ▼
[Scraper] — github.com/trending/{language}?since=daily
        │
        ▼
[Structure-check guard] — validates parsed field completeness; hard-stops run on failure
        │
        ▼
[Recurrence dedup] — flat table keyed on full_name + description_hash;
        │               skips LLM call for unchanged repurring repos, reuses cached summary
        ▼
[Deep-dive: LLM per new/changed repo] — summary + use-cases vs. personal interest profile
        │  (no pre-filter stage needed — daily volume is ~25 repos, not hundreds)
        ▼
[Renderer: HTML template]
        │
        ▼
[Sender: Resend API]
```

Explicitly excluded, same rationale as the arXiv project: message queues, load balancers, horizontal scaling, retry/dead-letter infrastructure, embedding-based pre-filtering (unnecessary — volume is already small).

## 7. Personalization Anchor

Same lesson as the arXiv project, reapplied: "use-cases specific to you" without an interest anchor produces generic output ("this could help developers interested in X"). Two options considered:

| Option | Description | Trade-off |
|--------|-------------|-----------|
| A — Hand-written profile | Short paragraph: languages you work in, project types (CLI, backend, dev tooling, etc.) | Explicit, cheap, needs occasional manual upkeep |
| B — Derived from your GitHub activity | Pull your starred repos / repo topics via GitHub API as an implicit signal | No upkeep, but noisier, and less useful when the digest is already scoped to one language |

**Decision:** Option A. Since the digest is already filtered to a single language, the differentiator that matters is *use-case type* (library vs. CLI tool vs. framework vs. learning resource vs. infra tool), which a short hand-written profile captures more precisely than inferred star history. Store as a single text file; embed/reference directly in the LLM prompt (no need for embedding-based similarity matching at this volume — direct prompt inclusion is simpler and sufficient).

## 8. Data Model

Single flat table, same simplification principle as the arXiv project — split out only if an actual query pattern demands it.

```
repos
  full_name        TEXT PRIMARY KEY   -- "owner/repo"
  language         TEXT
  description_hash TEXT               -- detects unchanged repos across days
  first_seen       DATE
  last_reported    DATE
  reported_count   INTEGER            -- tracks recurring trending repos
  stars_total      INTEGER
  stars_today      INTEGER
  summary          TEXT               -- cached, reused if description_hash unchanged
  use_cases        TEXT               -- cached, reused if description_hash unchanged
```

## 9. Scraper Design Notes

- No pagination on the trending page — one GET returns the full daily list for the language (~25 repos typically)
- Set a realistic User-Agent; keep to 1 request/day — no rotation/evasion infra needed at this volume
- Parse target fields defensively (missing star count, missing description are the most likely partial-failure modes based on how this page has historically shifted structure)
- [Guessing — verify independently] Check `github.com/robots.txt` before automating; a once-daily personal-use request is a materially different risk profile than bulk scraping, but confirm rather than assume

## 10. Failure Handling

| Failure | Handling |
| --------- | ---------- |
| Scraper returns unexpected HTML structure | Structure-check guard aborts the entire run (not per-repo) — a parse failure here likely means the whole page format changed, not one field |
| LLM call fails for one repo | Log and skip that repo's summary; continue with the rest |
| Resend send fails | Log to flat file; manual resend if needed |
| Job fails mid-run | Re-run is fine; recurrence dedup naturally prevents duplicate LLM spend, no special idempotency logic needed |

## 11. Success Metrics

- Pipeline completes without manual intervention on scheduled days
- Structure-check guard correctly catches and aborts on any future GitHub trending-page redesign (validated the first time it happens, not provable in advance)
- LLM call volume trends down over time as recurrence caching takes effect on repeat-trending repos
- You actually read and act on the digest after a month

## 12. Open Questions

1. Which language — confirm the exact `{language}` slug GitHub trending expects (e.g. `python`, `go`, `typescript`)
2. Interest profile content — needs to be written before M3 (see milestones)
3. Recurrence window: how many days should a repo be excluded from re-summarization after being reported, if description is unchanged? (Proposal: indefinite reuse of cached summary, refresh only on description change — but confirm this matches what "digest" should feel like to you, vs. wanting a fresh take periodically)
4. Should repos that fall off the trending list and later return be treated as "new" again, or retain history?

## 13. Milestones

| Milestone | Deliverable |
| ----------- | ------------- |
| M1 | Scraper + structure-check guard working locally against today's trending page |
| M2 | Recurrence dedup table working across 2+ consecutive daily runs |
| M3 | Interest profile written; LLM summary + use-case generation working for a sample day |
| M4 | Email rendering + Resend send, manual trigger end-to-end |
| M5 | GitHub Actions cron live, unattended for 1 week |
| M6 | First check on whether structure-check guard has needed to fire (validates resilience assumption)

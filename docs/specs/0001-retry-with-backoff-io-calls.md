# 0001. Retry with backoff on I/O calls

**Date**: 2026-09-17
**Status**: Accepted

## Summary

Each of the pipeline's three outside calls (fetching the trending page, asking Gemini to summarize a repo, sending the digest email) gets a small number of automatic retries with a growing wait between them, but only for failures that look temporary. A permanent failure (a bad request, a bad API key, a page GitHub genuinely restructured) still fails on the first try, exactly as it does today. This trades a little more code for fewer runs lost to a single bad network moment, without changing what happens once retries are used up.

## Context

> ⚠️ Premise note: this project's README and AGENTS.md record a deliberate decision against retry/backoff: "a missed day is acceptable per the PRD's availability NFR, and re-runs are safe (dedup prevents double LLM spend)." No incident has actually happened; the motivation given for this pass is tightening reliability before one does, not fixing a measured failure. That is the shape of a premature optimization: infrastructure added ahead of evidence. Two things make it reasonable to proceed anyway: the project's own `docs/scope/scope.md` already enrolls this as a planned "reliability hardening" pass with acceptance criteria seeded, so it is a considered part of the roadmap, not a reflex; and the change is small and fully reversible (three decorators, one new direct dependency, no schema or interface change). The engineer confirmed proceeding with this in mind. The tradeoff is recorded here and in Consequences, and the superseded assumption is flagged in Follow up so the project's own docs stay honest about why the old reasoning no longer holds.

Right now a single dropped connection, a slow response, or a momentary rate limit on any of the three outside calls has the same effect as a real, lasting problem: the scrape aborts the whole run, one repo's summary is skipped, or the email send falls back to a saved HTML file. Today's design accepts that on purpose, reasoning that a missed day costs nothing (the cron runs again tomorrow) and a re-run is cheap (the recurrence cache in `db.py` skips repos already summarized). That reasoning holds for a failure that clears up by tomorrow. It does not hold as well within a single run: GitHub's trending page, the Gemini API, and Resend's API can each return a genuinely transient error (a dropped connection, a `503`, a rate limit) that would very likely succeed a few seconds later, and today's pipeline treats that exactly like a permanent failure.

The run has a soft latency budget (under 5 minutes, per the PRD's non-functional requirements) and touches a modest number of repos per day (roughly 5 to 15 once the cache is warm), so there is room to absorb a few short waits without approaching that budget. The three call sites are not uniform: the scrape is a single request whose failure aborts the entire run; the Gemini call happens once per repo inside a loop, where the existing code already contains and logs a single repo's failure; and the Resend send is a single request whose failure already has a save-to-disk fallback. Whatever retry policy is added must slot in front of each of these three existing behaviors without changing what they do once retries are exhausted.

## Requirements

**User stories**:
- As the person relying on this digest to actually arrive, I want a short network blip during the run to be absorbed automatically, so that one bad moment does not cost a whole day's digest, one repo's summary, or an extra manual resend.
- As the maintainer reading the GitHub Actions run log, I want to see when a retry happened, so a run that took longer than usual is explained rather than mysterious.

**Acceptance criteria** (the contract, each criterion is independently checkable):
- **AC-1**: A transient failure on the trending page fetch (a connection error, a timeout, or an HTTP `429`/`500`/`502`/`503`/`504` response) is retried up to 3 total attempts, with a growing wait between attempts, before the run aborts exactly as it does today.
- **AC-2**: A transient failure on a single repo's Gemini summarization call (a rate limit, a server error, or a connection/timeout error) is retried up to 3 total attempts, with the same growing wait, before that one repo is skipped exactly as it does today.
- **AC-3**: A transient failure on the Resend send (a rate limit, a server error, or the SDK's wrapped connection/timeout error) is retried up to 3 total attempts, with the same growing wait, before the run falls back to saving the HTML exactly as it does today.
- **AC-4**: A permanent failure at any of the three call sites (e.g. a non-retryable HTTP `4xx` on the scrape, an invalid request/auth/model-not-found error from Gemini, or a Resend config/validation error) is never retried; it fails on the first attempt straight into today's existing abort, skip, or fallback behavior.
- **AC-5**: Every retry attempt logs one `WARNING` line through the existing `logging.getLogger("zeitgeist")` logger, naming which call site is retrying, the attempt number, and how long it is waiting, before it sleeps.
- **AC-6**: None of today's three documented error handling behaviors changes in what it does, only in when it triggers: a scrape failure still aborts the entire run, one repo's summarization failure still only skips that repo, and a send failure still falls back to the saved HTML.

## Options considered

### Option 1: tenacity decorators on each of the three functions

Add `tenacity` (already resolved as a transitive dependency of `langchain-google-genai` in `uv.lock`, just not declared directly) as a direct dependency, and decorate `scraper.fetch_trending`, `summarize.summarize_repo`, and `send.send_digest` each with their own `@retry(...)`, sharing the same attempt count and backoff shape but each naming its own retryable exceptions.

**Pros**:
- No new download; the exact version is already locked, so this only changes what is declared, not what is installed.
- Exponential backoff with jitter, attempt limits, and structured logging hooks are all built in and well tested, instead of hand written.
- Each decorator sits right on the function it protects, so a reader sees the resilience policy in the same place as the call it wraps.

**Cons**:
- The numeric policy (3 attempts, 2 second base, 30 second cap) is written three times, once per decorator, rather than defined once.
- One more direct dependency for a project whose stated principle is "prefer less code over defensive infrastructure."

### Option 2: a small hand written backoff loop

Write a short `for attempt in range(3): try/except/sleep` loop, duplicated (or factored into one tiny helper) at each of the three call sites, using `time.sleep` with a manually computed exponential delay.

**Pros**:
- No new direct dependency at all, closest to the project's existing "stdlib only" instinct.
- Every line is visible in the project's own code, nothing to look up in a third party library's behavior.

**Cons**:
- Backoff-with-jitter math, correct attempt counting, and "don't retry a permanent error" branching are each easy to get subtly wrong, and there is no test suite yet to catch it.
- Reinvents something `tenacity` already solved and that is already sitting in the dependency tree unused.

### Option 3: keep the current no-retry behavior

Leave all three call sites as they are; continue relying on tomorrow's cron run and the recurrence cache to absorb transient failures across days, as the original YAGNI decision reasoned.

**Pros**:
- Zero new code, zero new dependency, fully consistent with the project's documented "deliberately left out" list.
- Genuinely simplest; nothing new to maintain or misconfigure.

**Cons**:
- Does not address the actual gap this pass is meant to close: a short blip within a single run still costs a whole day, a whole repo, or an extra manual resend, even though the failure would very likely have cleared up seconds later.
- Leaves the reliability hardening pass recorded in `docs/scope/scope.md` undesigned.

## Decision

**Chosen option**: Option 1: tenacity decorators on each of the three functions

Add `tenacity` as a direct dependency and decorate `fetch_trending`, `summarize_repo`, and `send_digest` each with their own `@retry(...)`, sharing one attempt/backoff shape (3 total attempts, exponential backoff with jitter, base 2 seconds, cap 30 seconds) and a `before_sleep` hook that logs a `WARNING`, but each naming only the exceptions that are genuinely transient for that call site.

## Rationale

Option 3 was ruled out because it does not do the job this pass exists to do: the project's own scope already commits to hardening these three call sites, and a within-run blip is a real, different failure mode from the across-day case the original YAGNI reasoning covered. Between Option 1 and Option 2, the deciding force is that `tenacity` costs nothing new to install (it is already fully resolved in `uv.lock`, just undeclared) while removing exactly the kind of hand written backoff math that is easy to get wrong with no test suite in place yet to catch it. The project's "less code over defensive infrastructure" principle favors reusing a small, already-present library over writing and maintaining equivalent logic by hand, not writing it from scratch. The literal three-times-repeated numeric policy (Option 1's one real con) is an accepted tradeoff: at three call sites, a shared helper module would be the kind of abstraction the project's own conventions warn against building before it is needed twice over, let alone once.

## Feature design

**Data model sketch**: None. This decision changes control flow around existing I/O calls; it adds no new table, column, or persisted field.

**State transitions**: None. It does not introduce a state machine; it changes how many times an existing call is attempted before the pipeline's existing abort/skip/fallback states are reached.

**API surface**: None. This is an internal batch job with no request/response interface; nothing here is called by another system.

**Value sourcing** (every value each retry attempt needs to log or decide on names its source):

| Action | Value produced / displayed | Source |
|---|---|---|
| Any retry's `before_sleep` log line | Which call site is retrying | A literal string set in each decorator's logging hook, e.g. `"scrape"` / `"summarize"` / `"send"` |
| Any retry's `before_sleep` log line | Attempt number | `tenacity`'s `RetryCallState.attempt_number`, supplied by the library at each retry |
| Any retry's `before_sleep` log line | Wait duration before the next attempt | `tenacity`'s computed next-sleep value from the shared `wait_exponential_jitter` policy |
| `fetch_trending` retry predicate | Whether the caught exception is retryable | The exception's own type/status: `requests.exceptions.ConnectionError`, `requests.exceptions.Timeout`, or `requests.exceptions.HTTPError` whose `response.status_code` is in `{429, 500, 502, 503, 504}` |
| `summarize_repo` retry predicate | Whether the caught exception is retryable | The exception's own type: `langchain_google_genai.chat_models.GoogleRateLimitError` or `GoogleAPIError` (an HTTP response came back as a rate limit or server error), or `httpx.TimeoutException`/`httpx.ConnectError` (the request never got a response at all; these are the same two types the `google-genai` SDK itself names as `_HTTPX_TRANSIENT_EXC` in `google/genai/_api_client.py`). `GoogleInvalidRequestError`, `GoogleAuthenticationError`, `GooglePermissionDeniedError`, `GoogleModelNotFoundError`, and `GoogleContextOverflowError` are not retryable |
| `send_digest` retry predicate | Whether the caught exception is retryable | The exception's own type and `error_type` attribute, from `resend.exceptions`: `RateLimitError` or `ApplicationError` (a rate limit or server error response), or the base `ResendError` where `exc.error_type == "HttpClientError"` (the SDK's own catch all for the underlying `requests` call itself failing before any response, see `resend/request.py`'s `make_request`, which wraps that failure as `ResendError(error_type="HttpClientError")`, never a plain `RuntimeError`). `MissingApiKeyError`, `InvalidApiKeyError`, `ValidationError`, `MissingRequiredFieldsError`, and any other `ResendError` `error_type` are not retryable |

**Key invariants**:
- The total attempt count at each call site is exactly 3 (1 initial call plus 2 retries); it never grows silently.
- A retry never fires for an exception that is not explicitly named as transient for that call site; anything else propagates on the first attempt.
- Exhausting all 3 attempts at a call site produces exactly the exception that today's `main.py` already catches at that point, not `tenacity`'s own wrapping `RetryError`. Every `@retry(...)` decorator must set `reraise=True`, so the existing `try/except` blocks in `main()` (abort on scrape/guard failure, skip-and-continue on one repo's summarization failure, save-HTML-on-send-failure fallback) need no change to their own logic or their log messages, only to sit downstream of a call that may now take longer.

**Security model**: Unchanged. No new data is read, stored, or exposed; no new caller or permission boundary is introduced. The three call sites keep exactly the credentials (`GOOGLE_API_KEY`, `RESEND_API_KEY`) and scope they use today.

**Configuration required**: None. No new environment variable, secret, or credential. The attempt count, backoff base, and backoff cap are literal constants in code, not configuration, consistent with the project's "env vars, not a config file" rule for anything that does need to vary per environment (nothing here does).

**Critical test scenarios** (each maps to an acceptance criterion in Requirements):
- Happy path: the trending page fetch fails once with a connection error, then succeeds on the second attempt, and the run continues normally with one `WARNING` log line recorded, verifies **AC-1**, **AC-5**.
- Happy path: a single repo's Gemini call fails once with a rate limit error, then succeeds, and that repo's summary appears in the digest as normal, verifies **AC-2**, **AC-5**.
- Happy path: the Resend send fails once with a `500`, then succeeds, and no fallback HTML file is written, verifies **AC-3**, **AC-5**.
- Failure case: the trending page fetch fails with a connection error on all 3 attempts, and the run aborts exactly as it does today (same log line, same non-zero exit), verifies **AC-1**, **AC-6**.
- Failure case: a single repo's Gemini call fails with a rate limit error on all 3 attempts, and only that repo is skipped, the rest of the run completes, verifies **AC-2**, **AC-6**.
- Failure case: the Resend send fails with a `500` on all 3 attempts, and the HTML fallback file is written exactly as it does today, verifies **AC-3**, **AC-6**.
- Permanent failure: the trending page returns a `404`, or Gemini raises `GoogleInvalidRequestError`, or Resend raises `ValidationError`, and each fails on the first attempt with no retry and no extra wait, verifies **AC-4**.

## Build plan

1. [x] Add `tenacity` as a direct dependency in `pyproject.toml` and `requirements.txt`, pinned to the version already resolved in `uv.lock` (`9.1.4`), satisfies **AC-1**, **AC-2**, **AC-3** (foundation for all three call sites).
2. [x] Decorate `scraper.fetch_trending` with `@retry(stop=stop_after_attempt(3), wait=wait_exponential_jitter(initial=2, max=30), retry=retry_if_exception(...), before_sleep=..., reraise=True)`, retrying on `requests.exceptions.ConnectionError`, `requests.exceptions.Timeout`, and `requests.exceptions.HTTPError` with `response.status_code` in `{429, 500, 502, 503, 504}`; any other exception (including other `HTTPError` statuses) propagates unretried into `main.py`'s existing scrape-failure abort, satisfies **AC-1**, **AC-4**, **AC-5**, **AC-6**.
3. [x] Decorate `summarize.summarize_repo` with the same attempt/backoff shape and `reraise=True`, retrying on `langchain_google_genai.chat_models.GoogleRateLimitError`, `GoogleAPIError`, `httpx.TimeoutException`, and `httpx.ConnectError`; any other exception (`GoogleInvalidRequestError`, `GoogleAuthenticationError`, `GooglePermissionDeniedError`, `GoogleModelNotFoundError`, `GoogleContextOverflowError`, or anything else) propagates unretried into `main.py`'s existing per-repo skip-and-continue, satisfies **AC-2**, **AC-4**, **AC-5**, **AC-6**.
4. [x] Decorate `send.send_digest` with the same attempt/backoff shape and `reraise=True`, retrying on `resend.exceptions.RateLimitError`, `resend.exceptions.ApplicationError`, and `resend.exceptions.ResendError` where `error_type == "HttpClientError"`; any other exception (`MissingApiKeyError`, `InvalidApiKeyError`, `ValidationError`, `MissingRequiredFieldsError`, any other `ResendError` `error_type`, or anything else) propagates unretried into `main.py`'s existing save-HTML fallback, satisfies **AC-3**, **AC-4**, **AC-5**, **AC-6**.

## Consequences

**Positive**:
- A short network blip during a run (a dropped connection, a `503`, a momentary rate limit) no longer costs a whole aborted run, a whole skipped repo, or an extra manual resend; it costs a few seconds of waiting instead.
- The behavior a permanent failure produces today (abort, skip, or fallback) is unchanged, so nothing that relies on today's error handling needs to change alongside this.

**Negative / tradeoffs**:
- A new direct dependency (`tenacity`) is declared where none was before, even though it cost nothing new to install; it is one more thing to keep in `pyproject.toml`/`requirements.txt` in sync, per the project's own stated gotcha about the two files.
- Worst case latency grows more than a first glance suggests: the scrape's own 30 second request timeout applies to each of its 3 attempts, so a persistently slow scrape alone could add close to 2 minutes (3 timeouts plus up to 32 seconds of backoff waits) before aborting. The Gemini retry sits inside `main.py`'s per-repo loop, so it multiplies: if several of the day's 5 to 15 repos each need their full 3 attempts, the added time stacks across the run, not just once. This still fits under the sub-5-minute budget for the realistic case (most days, zero or one repo needs a retry at all), but a day where GitHub and Gemini are both degraded at once is the scenario to watch if run time is ever monitored.
- The numeric retry policy (3 attempts, 2 second base, 30 second cap) is duplicated across three decorators by design (see Rationale), so a future change to the policy means editing three places, not one.

**Neutral**:
- The original "no retry/backoff" reasoning in `README.md` and `AGENTS.md` no longer describes the code once this ships; those files need a matching edit (see Follow up).

## Follow-up

- [ ] Update `README.md`'s "What was deliberately left out (YAGNI)" section and `AGENTS.md`'s "Rules"/"Gotchas" sections to remove or rewrite the "no retry/backoff" line once this spec is built, so the project's own docs stop contradicting the shipped behavior.

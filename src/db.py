import hashlib
import os
import sqlite3
from datetime import UTC, date, datetime, timedelta

DB_PATH = "data/repos.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS repos (
    full_name           TEXT PRIMARY KEY,
    language            TEXT,
    description_hash    TEXT,
    first_seen          TEXT,
    last_reported       TEXT,
    reported_count      INTEGER DEFAULT 0,
    stars_total         INTEGER,
    stars_today         INTEGER,
    summary             TEXT,
    use_cases           TEXT
);
"""


# Refresh after N days, so a repo that sits on trending for weeks
# doesn't show identical text every day.
REFRESH_AFTER_DAYS = 7


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute(SCHEMA)
    return conn


def hash_description(description: str | None) -> str:
    return hashlib.sha256((description or "").encode("utf-8")).hexdigest()


def needs_summary(
    conn: sqlite3.Connection, full_name: str, description_hash: str
) -> bool:
    """True if this repo is new, its description changed, or its cached
    summary has aged past REFRESH_AFTER_DAYS
    """
    row = conn.execute(
        "SELECT description_hash, last_reported FROM repos WHERE full_name = ?",
        (full_name,),
    ).fetchone()

    if row is None:
        return True

    cached_hash, last_reported = row
    if cached_hash != description_hash:
        return True

    if last_reported and (
        datetime.now(tz=UTC).date() - date.fromisoformat(last_reported)
    ) > timedelta(days=REFRESH_AFTER_DAYS):
        return True

    return False


def get_cached(conn: sqlite3.Connection, full_name: str) -> tuple[str, str] | None:
    return conn.execute(
        "SELECT summary, use_cases FROM repos WHERE full_name = ?", (full_name,)
    ).fetchone()


def upsert(conn: sqlite3.Connection, repo: dict, summary: str, use_cases: str) -> None:
    today = date.today().isoformat()
    existing = conn.execute(
        "SELECT first_seen, reported_count FROM repos WHERE full_name = ?",
        (repo["full_name"],),
    ).fetchone()

    first_seen = existing[0] if existing else today
    reported_count = (existing[1] if existing else 0) + 1

    conn.execute(
        """
        INSERT INTO repos (full_name, language, description_hash, first_seen,
                            last_reported, reported_count, stars_total, stars_today,
                            summary, use_cases)
        VALUES (:full_name, :language, :description_hash, :first_seen,
                :last_reported, :reported_count, :stars_total, :stars_today,
                :summary, :use_cases)
        ON CONFLICT(full_name) DO UPDATE SET
            language = excluded.language,
            description_hash = excluded.description_hash,
            last_reported = excluded.last_reported,
            reported_count = excluded.reported_count,
            stars_total = excluded.stars_total,
            stars_today = excluded.stars_today,
            summary = excluded.summary,
            use_cases = excluded.use_cases
        """,
        {
            "full_name": repo["full_name"],
            "language": repo["language"],
            "description_hash": hash_description(repo["description"]),
            "first_seen": first_seen,
            "last_reported": today,
            "reported_count": reported_count,
            "stars_total": repo["stars_total"],
            "stars_today": repo["stars_today"],
            "summary": summary,
            "use_cases": use_cases,
        },
    )
    conn.commit()

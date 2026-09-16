import logging
import os
import sys

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from src import db, render, scraper, send, summarize

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("zeitgeist")

LANGUAGE = os.environ.get("DIGEST_LANGUAGE", "python")
PROFILE_PATH = os.environ.get("DIGEST_PROFILE_PATH", "interests.txt")
MODEL = "gemini-3.5-flash-lite"


def main():
    with open(PROFILE_PATH, encoding="utf-8") as f:
        profile = f.read().strip()

    try:
        repos = scraper.fetch_trending(LANGUAGE)
    except Exception as exc:
        logger.error("ABORT: scrape request failed: %s", exc)
        return 1

    if not scraper.check_parse_quality(repos):
        logger.error(
            "ABORT: structure-check guard failed on %d parsed rows "
            "-- github.com/trending's HTML structure may have changed.",
            len(repos),
        )
        return 1

    conn = db.connect()
    client = ChatGoogleGenerativeAI(
        model=MODEL,
        temperature=0.3,
        api_key=os.environ.get("GOOGLE_API_KEY")
    )
    entries = []

    for repo in repos:
        if not repo.get("full_name"):
            continue

        description_hash = db.hash_description(repo.get("description"))

        if db.needs_summary(conn, repo.get("full_name"), description_hash):
            try:
                summary, use_cases = summarize.summarize_repo(client, repo, profile)
            except Exception as exc:
                # One repo's LLM call failing shouldn't kill the whole run.
                logger.warning(
                    "summarization failed for %s: %s", repo["full_name"], exc
                )
                continue
        else:
            summary, use_cases = db.get_cached(conn, repo["full_name"])

        db.upsert(conn, repo, summary, use_cases)
        entries.append({**repo, "summary": summary, "use_cases": use_cases})

    conn.close()

    if not entries:
        logger.error("ABORT: no repos left to report after parsing/summarization.")
        return 1

    html = render.render_digest(LANGUAGE, entries)

    # with open("index.html", "w", encoding="utf-8") as f:
    #     f.write(html)

    try:
        send.send_digest(html, LANGUAGE)
    except Exception as exc:
        # Resend failure: log and stop. The DB write above already happened,
        # so nothing is lost -- save the HTML for a manual resend if needed.
        logger.error("ERROR: send failed: %s", exc)
        os.makedirs("data", exist_ok=True)
        with open("data/last_failed_digest.html", "w", encoding="utf-8") as f:
            f.write(html)
        return 1

    logger.info("OK: sent digest for %d repos.", len(entries))
    return 0


if __name__ == "__main__":
    sys.exit(main())

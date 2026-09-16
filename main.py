import os
import sys

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

from src import db, render, scraper, send, summarize

load_dotenv()

LANGUAGE = os.environ.get("DIGEST_LANGUAGE", "python")
PROFILE_PATH = os.environ.get("DIGEST_PROFILE_PATH", "interests.txt")
MODEL = "gemini-3.5-flash-lite"


def main():
    with open(PROFILE_PATH, encoding="utf-8") as f:
        profile = f.read().strip()

    try:
        repos = scraper.fetch_trending(LANGUAGE)
    except Exception as exc:
        print(f"ABORT: scrape request failed: {exc}", file=sys.stderr)
        return 1

    if not scraper.check_parse_quality(repos):
        print(
            f"ABORT: structure-check guard failed on {len(repos)} parsed rows "
            "-- github.com/trending's HTML structure may have changed.",
            file=sys.stderr,
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
                print(
                    f"WARN: summarization failed for {repo['full_name']}: {exc}",
                    file=sys.stderr,
                )
                continue
        else:
            summary, use_cases = db.get_cached(conn, repo["full_name"])

        db.upsert(conn, repo, summary, use_cases)
        entries.append({**repo, "summary": summary, "use_cases": use_cases})

    conn.close()

    if not entries:
        print(
            "ABORT: no repos left to report after parsing/summarization.",
            file=sys.stderr,
        )
        return 1

    html = render.render_digest(LANGUAGE, entries)

    # with open("index.html", "w", encoding="utf-8") as f:
    #     f.write(html)

    try:
        send.send_digest(html, LANGUAGE)
    except Exception as exc:
        # Resend failure: log and stop. The DB write above already happened,
        # so nothing is lost -- save the HTML for a manual resend if needed.
        print(f"ERROR: send failed: {exc}", file=sys.stderr)
        os.makedirs("data", exist_ok=True)
        with open("data/last_failed_digest.html", "w", encoding="utf-8") as f:
            f.write(html)
        return 1

    print(f"OK: sent digest for {len(entries)} repos.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

import os

import resend


def send_digest(html: str, language: str) -> None:
    resend.api_key = os.environ.get("RESEND_API_KEY")
    resend.Emails.send(
        {
            "from": os.environ["DEFAULT_FROM_EMAIL"],
            "to": os.environ["DIGEST_TO_EMAIL"],
            "subject": f"Github Trending Digest \u2014 {language}",
            "html": html,
        }
    )

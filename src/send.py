import logging
import os

import resend
from resend.exceptions import ApplicationError, RateLimitError, ResendError
from tenacity import (
    RetryCallState,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger("zeitgeist")


def _is_transient_send_error(exc: BaseException) -> bool:
    if isinstance(exc, (RateLimitError, ApplicationError)):
        return True
    if isinstance(exc, ResendError):
        return exc.error_type == "HttpClientError"
    return False


def _log_before_sleep(retry_state: RetryCallState) -> None:
    logger.warning(
        "send: attempt %d failed, retrying in %.1fs",
        retry_state.attempt_number,
        retry_state.next_action.sleep,
    )


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential_jitter(initial=2, max=30),
    retry=retry_if_exception(_is_transient_send_error),
    before_sleep=_log_before_sleep,
    reraise=True,
)
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

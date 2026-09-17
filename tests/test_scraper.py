import logging

import pytest
import requests

from src.scraper import (
    _is_transient_scrape_error,
    check_parse_quality,
    fetch_trending,
)

TRENDING_HTML = """
<html><body>
<article class="Box-row">
  <h3 class="h3 lh-condensed"><a class="Link" href="/octocat/hello-world"></a></h3>
  <p class="col-9 color-fg-muted my-1 tmp-pr-4">A friendly repo</p>
  <span itemprop="programmingLanguage">Python</span>
  <a class="tmp-mr-3 Link Link--muted d-inline-block" href="/octocat/hello-world/stargazers">1,234</a>
  <a class="tmp-mr-3 Link Link--muted d-inline-block" href="/octocat/hello-world/forks">10</a>
  <span class="float-sm-right">56 stars today</span>
</article>
</body></html>
"""


def _mock_response(mocker, status_code=200, text=TRENDING_HTML, raise_exc=None):
    response = mocker.Mock()
    response.status_code = status_code
    response.text = text
    if raise_exc is not None:
        response.raise_for_status.side_effect = raise_exc
    else:
        response.raise_for_status.return_value = None
    return response


def _http_error(status_code):
    response = requests.Response()
    response.status_code = status_code
    return requests.exceptions.HTTPError(response=response)


class TestIsTransientScrapeError:
    def test_connection_error_is_transient(self):
        assert _is_transient_scrape_error(requests.exceptions.ConnectionError()) is True

    def test_timeout_is_transient(self):
        assert _is_transient_scrape_error(requests.exceptions.Timeout()) is True

    @pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
    def test_retryable_http_status_is_transient(self, status_code):
        assert _is_transient_scrape_error(_http_error(status_code)) is True

    def test_non_retryable_http_status_is_not_transient(self):
        assert _is_transient_scrape_error(_http_error(404)) is False

    def test_http_error_without_response_is_not_transient(self):
        assert _is_transient_scrape_error(requests.exceptions.HTTPError()) is False

    def test_unrelated_exception_is_not_transient(self):
        assert _is_transient_scrape_error(ValueError("not a network error")) is False


class TestFetchTrending:
    def test_returns_parsed_rows_on_first_success(self, mocker):
        get = mocker.patch("src.scraper.requests.get")
        get.return_value = _mock_response(mocker)

        repos = fetch_trending("python")

        assert get.call_count == 1
        assert repos == [
            {
                "full_name": "octocat/hello-world",
                "description": "A friendly repo",
                "language": "Python",
                "stars_total": 1234,
                "stars_today": 56,
                "url": "https://github.com/octocat/hello-world",
            }
        ]

    def test_retries_transient_failure_then_succeeds(self, mocker, caplog):
        mocker.patch("time.sleep")
        get = mocker.patch("src.scraper.requests.get")
        get.side_effect = [
            requests.exceptions.ConnectionError("dropped"),
            _mock_response(mocker),
        ]

        with caplog.at_level(logging.WARNING, logger="zeitgeist"):
            repos = fetch_trending("python")

        assert get.call_count == 2
        assert len(repos) == 1
        assert any(
            "scrape: attempt 1 failed, retrying" in record.message
            for record in caplog.records
        )

    def test_exhausts_all_three_attempts_then_reraises_original_error(self, mocker):
        mocker.patch("time.sleep")
        get = mocker.patch("src.scraper.requests.get")
        get.side_effect = requests.exceptions.ConnectionError("still down")

        with pytest.raises(requests.exceptions.ConnectionError):
            fetch_trending("python")

        assert get.call_count == 3

    def test_permanent_error_fails_on_first_attempt_without_retry(self, mocker):
        mocker.patch("time.sleep")
        get = mocker.patch("src.scraper.requests.get")
        response = _mock_response(mocker, status_code=404, raise_exc=_http_error(404))
        get.return_value = response

        with pytest.raises(requests.exceptions.HTTPError):
            fetch_trending("python")

        assert get.call_count == 1


class TestCheckParseQuality:
    def test_empty_repo_list_fails(self):
        assert check_parse_quality([]) is False

    def test_all_fields_present_passes(self):
        repos = [
            {"full_name": "a/b", "description": "d", "stars_total": 1},
            {"full_name": "c/d", "description": "d", "stars_total": 2},
        ]
        assert check_parse_quality(repos) is True

    def test_too_many_missing_required_fields_fails(self):
        repos = [
            {"full_name": None, "description": None, "stars_total": None},
            {"full_name": None, "description": None, "stars_total": None},
        ]
        assert check_parse_quality(repos) is False

    def test_missing_ratio_at_threshold_passes(self):
        # 1 missing field out of 6 checks (1/6 ≈ 0.167) is under the default 0.2 ratio.
        repos = [
            {"full_name": "a/b", "description": None, "stars_total": 1},
            {"full_name": "c/d", "description": "d", "stars_total": 2},
        ]
        assert check_parse_quality(repos) is True

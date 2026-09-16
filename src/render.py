from datetime import date

ROW_TEMPLATE = """
<tr>
  <td style="padding:16px 0;border-bottom:1px solid #e1e4e8;">
    <a href="{url}" style="font-size:16px;font-weight:600;color:#0969da;text-decoration:none;">{full_name}</a>
    <span style="color:#57606a;font-size:13px;"> &middot; {language} &middot; \u2b50 {stars_total} total ({stars_today} today)</span>
    <p style="margin:8px 0 4px 0;color:#24292f;">{summary}</p>
    <p style="margin:0;color:#57606a;font-size:14px;"><strong>Use cases:</strong> {use_cases}</p>
  </td>
</tr>
"""

PAGE_TEMPLATE = """
<html>
<body style="font-family:-apple-system,Helvetica,Arial,sans-serif;max-width:680px;margin:0 auto;">
  <h1 style="font-size:20px;">GitHub Trending &mdash; {language} &mdash; {today}</h1>
  <table style="width:100%;border-collapse:collapse;">
    {rows}
  </table>
</body>
</html>
"""


def render_digest(language: str, entries: list[dict]) -> str:
    """entries: repo dicts merged with 'summary' and 'use_cases' keys."""

    rows = "".join(
        ROW_TEMPLATE.format(
            url=e["url"],
            full_name=e["full_name"],
            language=e["language"] or "\u2014",
            stars_total=e["stars_total"] if e["stars_total"] is not None else "\u2014",
            stars_today=f"+{e['stars_today']}"
            if e["stars_today"] is not None
            else "\u2014",
            summary=e["summary"],
            use_cases=e["use_cases"],
        )
        for e in entries
    )

    return PAGE_TEMPLATE.format(
        language=language, today=date.today().isoformat(), rows=rows
    )

from langchain_core.messages import HumanMessage
from langchain_google_genai import ChatGoogleGenerativeAI
from pydantic import BaseModel

PROMPT_TEMPLATE = """You are writing one entry in a daily GitHub trending email digest for a developer with this profile:
 
<profile>
{profile}
</profile>
 
Trending repo:
Name: {full_name}
Description: {description}
Language: {language}
 
Write:
1. A 1-2 sentence plain-language summary of what the repo does.
2. 1-2 concrete use-cases specific to the profile above — not generic "developers might find this useful" filler. If it genuinely doesn't fit the profile, say that plainly instead of forcing a connection.
 
Respond in exactly this format and nothing else:
SUMMARY: <text>
USE_CASES: <text>
"""


class SummaryResult(BaseModel):
    """The result of the LLM of the given repo"""

    summary: str
    use_cases: str


def summarize_repo(
    client: ChatGoogleGenerativeAI, repo: dict, profile: str
) -> tuple[str, str]:
    prompt = HumanMessage(
        content=PROMPT_TEMPLATE.format(
            profile=profile,
            full_name=repo["full_name"],
            description=repo["description"] or "(no description given)",
            language=repo["language"] or "unknown",
        )
    )

    structured_model = client.with_structured_output(SummaryResult)
    response = structured_model.invoke([prompt])
    return _parse_response(response.model_dump())


def _parse_response(text: dict) -> tuple[str, str]:
    summary = text.get("summary")
    use_cases = text.get("use_cases")
    return summary, use_cases

"""Structured reasoning: turn already-extracted system data into a prioritized action plan.

Unlike `home_inspection.py`, this never sees the report's raw text -- only the
age, condition, and findings already saved for each system (see
`service.py`'s `_build_action_plan_input`). That is a deliberate constraint,
not an incidental one: the whole point is a second, independent reasoning
pass over facts that are already fixed, not a re-read of the source document
that could quietly disagree with what was actually saved.
"""

from typing import Literal

import anthropic
from pydantic import BaseModel, Field

from app.core.config import settings
from app.extraction.home_inspection import ExtractionError, SystemName

MODEL = "claude-opus-5"

UrgencyTier = Literal["next_90_days", "next_2_years", "next_5_years"]

SYSTEM_PROMPT = """You are a home inspection reasoning assistant. You will be given \
structured data already extracted from a home inspection report -- one entry per system, \
each with an age (if known), a condition rating, and a list of specific findings, all \
already fixed and verified. Turn this into a prioritized, homeowner-facing action plan.

Reason only from the age, condition, and findings you are given. Never state or imply an \
age or condition other than what is given -- if age is unknown, do not guess one; if \
condition is "not_mentioned", do not describe the system as being in any particular state. \
Do not invent findings, defects, or details beyond what is listed. Treat a low-confidence \
value cautiously (hedge the recommendation) rather than as flatly certain.

For each system worth an action item, give:
- system: which system this is about.
- urgency: next_90_days for safety concerns or active defects needing prompt attention, \
next_2_years for systems nearing the end of their useful life or with maintenance items \
that will become urgent if ignored, next_5_years for systems in acceptable shape now but \
worth budgeting for eventually.
- recommendation: one or two plain-language sentences a homeowner can act on -- frame what \
to do and why it matters, grounded only in the given data, not a verbatim restatement of a \
finding.
- cost_low / cost_high: a rough US dollar range, in whole dollars, for addressing exactly the \
scope described in this item's findings -- not the cost of replacing the whole system. From \
general knowledge of typical US residential repair/replacement costs. This is an estimate, not \
a quote.
  - Match the range to the finding's actual severity and scope. A single localized repair \
(a leaking fixture, a section of damaged flashing, a loose connection) should get a narrow \
range priced as a repair; only price at full-system-replacement levels when the finding \
itself describes replacement-level damage (e.g. "no longer functional," "beyond repair," \
"end of useful life") or the system's condition and findings together clearly point that way.
  - Keep the range as narrow as the available information honestly supports. The high end \
should typically stay within roughly 2-3x the low end. Go wider only when the finding itself \
describes genuinely open-ended scope (e.g. it names a problem whose fix depends on what a \
contractor finds once the wall/roof/system is opened up, or explicitly says further \
inspection is needed to know the extent) -- and even then, do not pad the high end past what \
that described uncertainty actually supports.
  - Do not default to a wide range just to hedge uncertainty about the finding itself; a \
low-confidence finding should be hedged in the recommendation's wording (as above), not by \
inflating the cost spread.

Skip a system entirely if it is in good/excellent condition with no findings and nothing \
worth flagging -- not every system needs an action item. Also skip a system whose condition \
is "not_mentioned" and has no findings -- there is nothing in the data to act on, so do not \
invent a recommendation for it.

List items with the most urgent first."""


class ActionPlanItem(BaseModel):
    system: SystemName
    urgency: UrgencyTier
    recommendation: str = Field(description="Plain-language, homeowner-facing recommendation")
    cost_low: int = Field(ge=0, description="Low end of the estimated cost range, in US dollars")
    cost_high: int = Field(ge=0, description="High end of the estimated cost range, in US dollars")


class ActionPlan(BaseModel):
    items: list[ActionPlanItem]


def generate_action_plan(structured_input: str, *, model: str = MODEL) -> ActionPlan:
    """Ask Claude to prioritize already-extracted system data into an action plan.

    `structured_input` must be built from saved system/finding rows only (see
    `service.py`'s `_build_action_plan_input`) -- never the report's raw text.
    Raises ExtractionError for anything that goes wrong, the same failure
    modes as `extract_home_systems` (see home_inspection.py).
    """
    if not structured_input.strip():
        raise ExtractionError("No structured input to reason over -- structured_input is empty.")

    client = anthropic.Anthropic(api_key=settings.anthropic_api_key or None)

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=8000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": structured_input}],
            output_format=ActionPlan,
        )
    except TypeError as e:
        if "Could not resolve authentication method" not in str(e):
            raise
        raise ExtractionError(
            "No credentials found. Set ANTHROPIC_API_KEY, or run `ant auth login`."
        ) from e
    except anthropic.AuthenticationError as e:
        raise ExtractionError(
            "Credentials were rejected (401). The key is present but invalid or revoked."
        ) from e
    except anthropic.PermissionDeniedError as e:
        raise ExtractionError(
            f"Authenticated, but this key may not have access to {model} (403)."
        ) from e
    except anthropic.NotFoundError as e:
        raise ExtractionError(f"Model {model} not found (404).") from e
    except anthropic.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after", "60")
        raise ExtractionError(f"Rate limited (429). Retry after {retry_after}s.") from e
    except anthropic.APIStatusError as e:
        raise ExtractionError(f"API error {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise ExtractionError("Could not reach the API. Check your network or proxy.") from e

    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ExtractionError(f"The request was declined (category: {category}).")

    if response.parsed_output is None:
        raise ExtractionError("Claude's response did not parse against the expected schema.")

    return response.parsed_output

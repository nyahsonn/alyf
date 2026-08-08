"""Structured extraction: turn raw home-inspection report text into a typed report.

Unlike the rule-based extractor in `service.py`, this asks Claude to read the
whole document and place what it finds into a fixed shape -- one entry per
system, with its own confidence score on every field, so a caller can tell "the
report never mentioned this" apart from "this is a confident, verbatim reading."

Structured outputs (`output_format=`) constrain the response to the given
schema, so the result either matches `HomeInspectionReport` exactly or the call
raises -- never a mix of prose and JSON to parse around.
"""

from typing import Literal

import anthropic
from pydantic import BaseModel, Field

MODEL = "claude-opus-5"

# The six systems every residential inspection report is expected to cover.
# Fixed rather than left to the model to enumerate, so a caller always gets
# exactly these six back, in this order -- "the report never mentioned the
# water heater" becomes a low-confidence entry instead of a missing one.
SYSTEM_NAMES: tuple[str, ...] = (
    "roof", "hvac", "plumbing", "electrical", "water_heater", "foundation"
)

SystemName = Literal["roof", "hvac", "plumbing", "electrical", "water_heater", "foundation"]
Condition = Literal["excellent", "good", "fair", "poor", "not_mentioned"]

SYSTEM_PROMPT = f"""You are reading a home inspection report and pulling out what it says \
about six systems: {", ".join(SYSTEM_NAMES)}.

For each of the six systems, report:
- estimated_age: the age in years if the report states or clearly implies it (e.g. \
"installed in 2015" against a 2026 report date), otherwise null.
- condition: one of excellent, good, fair, poor, or not_mentioned if the report says \
nothing about this system's condition.
- findings: every specific issue, defect, or recommendation the report raises for this \
system, as short standalone strings. Empty list if none are raised.

Give every field its own confidence score from 0.0 to 1.0, reflecting how directly the \
report text supports that value -- not how confident you are that the system exists or \
that it was correctly left out of the report. A value read verbatim from the text, or \
directly computed from a fact the text states (e.g. an age computed from a stated \
install year against the report date), scores near 1.0. Do not guess to fill a value \
the report doesn't support -- use null / not_mentioned / an empty list instead.

If a system is not mentioned anywhere in the report, set confidence to exactly 0.0 for \
all three of its fields (estimated_age, condition, findings). 0.0 means "there is \
nothing here to go on -- this needs to be checked in person," not "we're confident it \
was correctly omitted." Never score an unmentioned system's fields above 0.0.

Report on all six systems even when a system is never mentioned in the text -- for an \
unmentioned system, use null / not_mentioned / an empty list, each with confidence 0.0, \
rather than omitting the system from the output."""


class ExtractionError(RuntimeError):
    """Claude could not be reached, refused the request, or its reply did not
    validate against the expected schema.

    The message is written to be printed as-is, so callers do not have to know
    Anthropic's exception types to say something useful.
    """


class AgeEstimate(BaseModel):
    years: int | None = Field(description="Estimated age of the system in years, or null")
    confidence: float = Field(ge=0.0, le=1.0)


class ConditionAssessment(BaseModel):
    rating: Condition
    confidence: float = Field(ge=0.0, le=1.0)


class Findings(BaseModel):
    items: list[str]
    confidence: float = Field(
        ge=0.0, le=1.0, description="Confidence in the findings list as a whole"
    )


class HomeSystem(BaseModel):
    name: SystemName
    estimated_age: AgeEstimate
    condition: ConditionAssessment
    findings: Findings


class HomeInspectionReport(BaseModel):
    systems: list[HomeSystem]


def extract_home_systems(raw_text: str, *, model: str = MODEL) -> HomeInspectionReport:
    """Ask Claude to read `raw_text` and place it into the HomeInspectionReport shape.

    `raw_text` is whatever an upstream OCR step returned for the document --
    prose and rendered tables both work, since the model reads either as plain
    text. Raises ExtractionError for anything that goes wrong, including a
    reply that comes back refused or fails to validate against the schema.
    """
    if not raw_text.strip():
        raise ExtractionError("No text to extract from -- raw_text is empty.")

    client = anthropic.Anthropic()

    try:
        response = client.messages.parse(
            model=model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": raw_text}],
            output_format=HomeInspectionReport,
        )
    except TypeError as e:
        # No credential at all: the SDK cannot build an auth header and raises
        # TypeError rather than AuthenticationError. Re-raise anything else.
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

    # Safety classifiers can decline a request: HTTP 200, empty content, no
    # parsed_output. Check stop_reason before trusting parsed_output.
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        raise ExtractionError(f"The request was declined (category: {category}).")

    if response.parsed_output is None:
        raise ExtractionError("Claude's response did not parse against the expected schema.")

    return response.parsed_output

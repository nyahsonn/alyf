"""Send one message to the Claude API and print the reply.

A connectivity check for your credentials — nothing in ALYF calls this. The
pipeline still runs fully offline; this only confirms that a key is in place
and working before you swap either of the offline seams for a real model.

    pip install anthropic
    python scripts/check_claude_api.py

Credentials resolve the way the SDK resolves them: ANTHROPIC_API_KEY, then
ANTHROPIC_AUTH_TOKEN, then an `ant auth login` profile. An unset env var does
not mean no credentials — run `ant auth status` to see which source is active.
"""

import sys

import anthropic

MODEL = "claude-opus-5"

# The reply is arbitrary model text, so it can contain characters the Windows
# console's default cp1252 codepage renders as "?". Ask for UTF-8 explicitly.
sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main() -> int:
    client = anthropic.Anthropic()

    try:
        response = client.messages.create(
            model=MODEL,
            # Thinking is on by default on this model, and max_tokens caps
            # thinking plus reply together — leave enough room for both or the
            # reply comes back truncated and the check looks like a failure.
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": "Reply with a single short sentence confirming you received this.",
                }
            ],
        )
    except TypeError as e:
        # No credential at all: the SDK cannot build an auth header and raises
        # TypeError rather than AuthenticationError. Re-raise anything else.
        if "Could not resolve authentication method" not in str(e):
            raise
        print("No credentials found. Set ANTHROPIC_API_KEY, or run `ant auth login`.")
        return 1
    except anthropic.AuthenticationError:
        print("Credentials were rejected (401). The key is present but invalid or revoked.")
        return 1
    except anthropic.PermissionDeniedError:
        print(f"Authenticated, but this key may not have access to {MODEL} (403).")
        return 1
    except anthropic.NotFoundError:
        print(f"Model {MODEL} not found (404) — the key works, the model id does not.")
        return 1
    except anthropic.RateLimitError as e:
        retry_after = e.response.headers.get("retry-after", "60")
        print(f"The key works, but you are rate limited (429). Retry after {retry_after}s.")
        return 1
    except anthropic.APIStatusError as e:
        print(f"API error {e.status_code}: {e.message}")
        return 1
    except anthropic.APIConnectionError:
        print("Could not reach the API. Check your network or proxy.")
        return 1

    # Safety classifiers can decline a request: HTTP 200, empty or partial
    # content. Check stop_reason before reading content.
    if response.stop_reason == "refusal":
        category = response.stop_details.category if response.stop_details else None
        print(f"The key works — the request itself was declined (category: {category}).")
        return 1

    reply = "".join(block.text for block in response.content if block.type == "text")
    print(f"OK — {response.model} replied: {reply.strip()}")
    print(
        f"   tokens: {response.usage.input_tokens} in / "
        f"{response.usage.output_tokens} out   (request {response._request_id})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

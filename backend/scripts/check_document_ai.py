"""Send one page to Document AI and print what came back.

A connectivity check for your credentials — nothing in ALYF calls this. The
pipeline still runs fully offline; this only confirms that a service account,
API, and processor are all wired together correctly before anything real
depends on them.

    pip install google-cloud-documentai
    python scripts/check_document_ai.py

Requires DOCAI_PROJECT_ID, DOCAI_LOCATION, and DOCAI_PROCESSOR_ID (see
backend/.env.example), plus GOOGLE_APPLICATION_CREDENTIALS pointing at a
service account key file — that last one is read directly by the Google auth
library, not from the .env file.
"""

import base64
import os
import sys

from google.api_core import exceptions as gax_exceptions
from google.auth import exceptions as auth_exceptions
from google.cloud import documentai

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# A minimal 1x1 PNG. Document AI's OCR processors take image/PDF bytes, not
# text, so the smallest valid input is a single pixel — the check cares about
# a successful response, not what text (if any) comes back.
TEST_IMAGE = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY"
    "42YAAAAASUVORK5CYII="
)


def main() -> int:
    project_id = os.environ.get("DOCAI_PROJECT_ID")
    location = os.environ.get("DOCAI_LOCATION", "us")
    processor_id = os.environ.get("DOCAI_PROCESSOR_ID")

    if not project_id or not processor_id:
        print("Set DOCAI_PROJECT_ID and DOCAI_PROCESSOR_ID (see backend/.env.example).")
        return 1

    try:
        client = documentai.DocumentProcessorServiceClient(
            client_options={"api_endpoint": f"{location}-documentai.googleapis.com"}
        )
        name = client.processor_path(project_id, location, processor_id)
        request = documentai.ProcessRequest(
            name=name,
            raw_document=documentai.RawDocument(content=TEST_IMAGE, mime_type="image/png"),
        )
        result = client.process_document(request=request)
    except auth_exceptions.DefaultCredentialsError:
        print("No credentials found. Set GOOGLE_APPLICATION_CREDENTIALS to a service account key file.")
        return 1
    except auth_exceptions.RefreshError:
        print("Credentials were rejected. The key file may be invalid or the service account key revoked.")
        return 1
    except gax_exceptions.PermissionDenied as e:
        print(f"Authenticated, but access was denied (403): {e.message}")
        return 1
    except gax_exceptions.NotFound:
        print(
            f"Processor not found (404). Check DOCAI_PROJECT_ID={project_id!r}, "
            f"DOCAI_LOCATION={location!r}, DOCAI_PROCESSOR_ID={processor_id!r}."
        )
        return 1
    except gax_exceptions.ResourceExhausted as e:
        print(f"The processor works, but you are rate limited or over quota (429): {e.message}")
        return 1
    except gax_exceptions.GoogleAPICallError as e:
        print(f"API error: {e.message}")
        return 1

    document = result.document
    print(f"OK — processor {processor_id} responded with {len(document.text)} character(s) of text.")
    print(f"   pages: {len(document.pages)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

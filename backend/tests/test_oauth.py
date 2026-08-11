"""Unit tests for the Google OAuth configuration guard. No database or
network needed -- see app/auth/oauth.py.

find_or_create_from_oauth (app/auth/service.py) isn't unit-tested the same
way nothing else that touches the DB in this codebase is (see README,
"Tests" -- deliberately pure-function-only); it gets the same treatment
extract_home_report/ingest_document etc. already get -- reviewed carefully,
verified live once real Google credentials are available.

Run with:  pytest
"""

from app.auth.oauth import provider_configured
from app.core.config import settings


def test_provider_configured_false_with_blank_credentials(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "")
    monkeypatch.setattr(settings, "google_client_secret", "")
    assert provider_configured("google") is False


def test_provider_configured_false_with_only_one_credential_set(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "some-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "")
    assert provider_configured("google") is False


def test_provider_configured_true_with_both_credentials_set(monkeypatch):
    monkeypatch.setattr(settings, "google_client_id", "some-client-id")
    monkeypatch.setattr(settings, "google_client_secret", "some-client-secret")
    assert provider_configured("google") is True


def test_provider_configured_false_for_an_unknown_provider():
    assert provider_configured("facebook") is False

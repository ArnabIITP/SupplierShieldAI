"""
Pytest configuration for SupplierShield backend tests.

Markers
-------
integration : Tests that require a live Supabase connection.
              These are skipped in CI unless SUPABASE_URL is set as an env var.
              Run locally with a real .env file.
"""
import pytest


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "integration: marks tests as integration tests requiring live Supabase (deselect with -m 'not integration')",
    )
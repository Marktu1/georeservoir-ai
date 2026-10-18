"""Shared test configuration: fixed, reproducible Hypothesis profile."""

from __future__ import annotations

from hypothesis import HealthCheck, settings

settings.register_profile(
    "georeservoir",
    derandomize=True,  # fixed seed derived from the test: reproducible runs
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow],
    print_blob=True,
)
settings.load_profile("georeservoir")

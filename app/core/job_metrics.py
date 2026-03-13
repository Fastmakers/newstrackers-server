"""Helpers for async job timing metrics.

These metrics are used to compare:
    - API + worker in one process
    - API-only process + separate worker process

All values are computed from existing timestamps so no schema change is required.
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.schemas.job_models import JobTimingMetrics


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _ms_between(start: datetime | None, end: datetime | None) -> int | None:
    if start is None or end is None:
        return None
    return max(0, int((end - start).total_seconds() * 1000))


def build_job_timing_metrics(
    created_at: datetime,
    started_at: datetime | None,
    completed_at: datetime | None,
    *,
    now: datetime | None = None,
) -> JobTimingMetrics:
    current = now or utc_now()
    processing_end = completed_at or current
    total_end = completed_at or current

    return JobTimingMetrics(
        age_ms=_ms_between(created_at, current),
        queue_wait_ms=_ms_between(created_at, started_at),
        processing_time_ms=_ms_between(started_at, processing_end),
        total_lead_time_ms=_ms_between(created_at, total_end),
    )

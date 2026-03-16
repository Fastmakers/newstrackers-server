"""Analysis Job / Report CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import AnalysisJobDB, AnalysisReportDB

_MAX_RETRIES = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


class JobRepository:
    def __init__(self, db: Session):
        self._db = db

    # ------------------------------------------------------------------
    # Job CRUD
    # ------------------------------------------------------------------

    def create_job(
        self,
        *,
        user_id: Optional[str],
        company: str,
        job_title: str,
        industry: str,
        career_level: str,
        resume_text: str,
    ) -> AnalysisJobDB:
        uid = uuid.UUID(user_id) if user_id else None
        job = AnalysisJobDB(
            id=uuid.uuid4(),
            user_id=uid,
            status="pending",
            company=company,
            job_title=job_title,
            industry=industry,
            career_level=career_level,
            resume_text=resume_text,
        )
        self._db.add(job)
        return job

    def get_job(self, job_id: uuid.UUID) -> Optional[AnalysisJobDB]:
        return self._db.get(AnalysisJobDB, job_id)

    def get_jobs_by_user(self, user_id: str) -> list[AnalysisJobDB]:
        uid = uuid.UUID(user_id)
        return (
            self._db.query(AnalysisJobDB)
            .filter(AnalysisJobDB.user_id == uid)
            .order_by(AnalysisJobDB.created_at.desc())
            .all()
        )

    def claim_pending_jobs(self, limit: int) -> list[AnalysisJobDB]:
        """pending job을 원자적으로 claim하여 running으로 전환.

        FOR UPDATE SKIP LOCKED로 동시에 여러 워커/인스턴스가 실행되어도
        같은 job을 중복 픽업하지 않도록 보장한다.
        호출 후 db.commit()으로 lock을 해제해야 한다.
        """
        jobs = (
            self._db.query(AnalysisJobDB)
            .filter(AnalysisJobDB.status == "pending")
            .order_by(AnalysisJobDB.created_at.asc())
            .limit(limit)
            .with_for_update(skip_locked=True)
            .all()
        )
        now = _now()
        for job in jobs:
            job.status = "running"
            job.started_at = now
            job.progress_pct = 10  # PDF 파싱은 job 생성 시 완료됨
        return jobs

    # ------------------------------------------------------------------
    # Job 상태 업데이트
    # ------------------------------------------------------------------

    def update_progress(self, job_id: uuid.UUID, pct: int) -> None:
        job = self._db.get(AnalysisJobDB, job_id)
        if job:
            job.progress_pct = pct

    def mark_completed(self, job_id: uuid.UUID) -> None:
        job = self._db.get(AnalysisJobDB, job_id)
        if job:
            job.status = "completed"
            job.completed_at = _now()
            job.progress_pct = 100

    def mark_failed_or_retry(self, job_id: uuid.UUID, error_msg: str) -> None:
        """실패 처리. retry_count < _MAX_RETRIES 면 pending으로 되돌려 재시도."""
        job = self._db.get(AnalysisJobDB, job_id)
        if not job:
            return
        job.retry_count += 1
        job.error_msg = error_msg
        if job.retry_count < _MAX_RETRIES:
            job.status = "pending"
            job.started_at = None
        else:
            job.status = "failed"
            job.completed_at = _now()

    # ------------------------------------------------------------------
    # Report CRUD
    # ------------------------------------------------------------------

    def save_report(
        self,
        job_id: uuid.UUID,
        user_id: Optional[uuid.UUID],
        report_data: dict,
    ) -> AnalysisReportDB:
        report = AnalysisReportDB(
            id=uuid.uuid4(),
            user_id=user_id,
            resume_profile=report_data.get("resume_profile"),
            matched_news=report_data.get("matched_news"),
            matched_news_count=report_data.get("matched_news_count"),
            relevance_analysis=report_data.get("relevance_analysis"),
            swot=report_data.get("swot"),
            final_report=report_data.get("final_report"),
        )
        self._db.add(report)
        self._db.flush()  # report.id 확보

        # job에 report_id 연결
        job = self._db.get(AnalysisJobDB, job_id)
        if job:
            job.report_id = report.id

        return report

    def get_report(self, report_id: uuid.UUID) -> Optional[AnalysisReportDB]:
        return self._db.get(AnalysisReportDB, report_id)

    def get_reports_by_user(self, user_id: str) -> list[tuple[AnalysisReportDB, AnalysisJobDB]]:
        uid = uuid.UUID(user_id)
        return (
            self._db.query(AnalysisReportDB, AnalysisJobDB)
            .join(AnalysisJobDB, AnalysisJobDB.report_id == AnalysisReportDB.id)
            .filter(AnalysisReportDB.user_id == uid)
            .order_by(AnalysisReportDB.created_at.desc())
            .all()
        )

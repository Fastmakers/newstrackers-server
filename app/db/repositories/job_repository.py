"""Analysis Job / Report CRUD."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.db.models import AnalysisJobDB, AnalysisReportDB


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

    def get_pending_jobs(self) -> list[AnalysisJobDB]:
        return (
            self._db.query(AnalysisJobDB)
            .filter(AnalysisJobDB.status == "pending")
            .order_by(AnalysisJobDB.created_at.asc())
            .limit(5)  # 동시 처리 상한
            .all()
        )

    # ------------------------------------------------------------------
    # Job 상태 업데이트
    # ------------------------------------------------------------------

    def mark_running(self, job_id: uuid.UUID) -> None:
        job = self._db.get(AnalysisJobDB, job_id)
        if job:
            job.status = "running"
            job.started_at = _now()

    def update_progress(
        self,
        job_id: uuid.UUID,
        step: int,
        label: str,
        detail: str,
        progress_pct: Optional[int],
    ) -> None:
        job = self._db.get(AnalysisJobDB, job_id)
        if job:
            job.current_step = step
            job.step_label = label
            if detail:
                job.step_detail = detail
            if progress_pct is not None:
                job.progress_pct = progress_pct

    def mark_completed(self, job_id: uuid.UUID) -> None:
        job = self._db.get(AnalysisJobDB, job_id)
        if job:
            job.status = "completed"
            job.completed_at = _now()
            job.progress_pct = 100

    def mark_failed(self, job_id: uuid.UUID, error_msg: str) -> None:
        job = self._db.get(AnalysisJobDB, job_id)
        if job:
            job.status = "failed"
            job.completed_at = _now()
            job.error_msg = error_msg

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
            job_id=job_id,
            user_id=user_id,
            resume_profile=report_data.get("resume_profile"),
            matched_news=report_data.get("matched_news"),
            matched_news_count=report_data.get("matched_news_count"),
            relevance_analysis=report_data.get("relevance_analysis"),
            swot=report_data.get("swot"),
            final_report=report_data.get("final_report"),
        )
        self._db.add(report)
        return report

    def get_report_by_job(self, job_id: uuid.UUID) -> Optional[AnalysisReportDB]:
        return (
            self._db.query(AnalysisReportDB)
            .filter(AnalysisReportDB.job_id == job_id)
            .first()
        )

    def get_report(self, report_id: uuid.UUID) -> Optional[AnalysisReportDB]:
        return self._db.get(AnalysisReportDB, report_id)

    def get_reports_by_user(self, user_id: str) -> list[AnalysisReportDB]:
        uid = uuid.UUID(user_id)
        return (
            self._db.query(AnalysisReportDB)
            .filter(AnalysisReportDB.user_id == uid)
            .order_by(AnalysisReportDB.created_at.desc())
            .all()
        )

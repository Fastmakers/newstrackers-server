"""비동기 분석 Worker.

DB의 pending job을 polling하여 ReportPipeline.run_with_progress()로 처리한다.
각 단계 완료 시 partial_result를 DB에 저장 → 클라이언트가 폴링으로 점진적 결과를 확인.
FastAPI lifespan에서 start/stop 한다.

Retry: 실패 시 최대 _MAX_RETRIES(3)회까지 자동 재시도.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Optional

from app.db.base import SessionLocal
from app.db.repositories.job_repository import JobRepository
from app.services.report_pipeline import ReportInput, ReportPipeline

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 3


class AnalysisWorker:
    """DB polling 기반 비동기 분析 워커."""

    def __init__(self) -> None:
        self._pipeline: Optional[ReportPipeline] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._active_jobs: set[uuid.UUID] = set()
        self._active_tasks: dict[uuid.UUID, asyncio.Task] = {}

    def set_pipeline(self, pipeline: ReportPipeline) -> None:
        self._pipeline = pipeline

    async def start(self) -> None:
        self._loop_task = asyncio.create_task(self._poll_loop(), name="analysis-worker")
        logger.info("AnalysisWorker started (polling interval=3s, max_retries=3)")

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("AnalysisWorker stopped")

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self._pick_and_dispatch()
            except Exception as exc:
                logger.error("Worker poll error: %s", exc)
            await asyncio.sleep(3)

    async def _pick_and_dispatch(self) -> None:
        if not self._pipeline:
            return
        slots = _MAX_CONCURRENT - len(self._active_jobs)
        if slots <= 0:
            return

        db = SessionLocal()
        try:
            repo = JobRepository(db)
            claimed = repo.claim_pending_jobs(slots)
            job_params = [
                (
                    job.id, job.user_id,
                    job.resume_text or "", job.company or "",
                    job.job_title or "", job.industry or "",
                    job.career_level or "신입",
                )
                for job in claimed
                if job.id not in self._active_jobs
            ]
            db.commit()
        finally:
            db.close()

        for job_id, user_id, resume_text, company, job_title, industry, career_level in job_params:
            self._active_jobs.add(job_id)
            task = asyncio.create_task(
                self._process_job(
                    job_id=job_id,
                    user_id=user_id,
                    resume_text=resume_text,
                    company=company,
                    job_title=job_title,
                    industry=industry,
                    career_level=career_level,
                ),
                name=f"job-{job_id}",
            )
            self._active_tasks[job_id] = task
            task.add_done_callback(lambda t, j_id=job_id: self._active_tasks.pop(j_id, None))

    async def _process_job(
        self,
        job_id: uuid.UUID,
        user_id: Optional[uuid.UUID],
        resume_text: str,
        company: str,
        job_title: str,
        industry: str,
        career_level: str,
    ) -> None:
        logger.info("Job %s started", job_id)
        inp = ReportInput(
            resume_text=resume_text,
            company=company,
            job_title=job_title,
            industry=industry,
            career_level=career_level,
        )

        async def on_step(step: int, pct: int, partial: dict) -> None:
            db = SessionLocal()
            try:
                repo = JobRepository(db)
                repo.update_partial_result(job_id, partial, pct)
                db.commit()
                logger.debug("Job %s step %d → %d%%", job_id, step, pct)
            except Exception as exc:
                logger.warning("Partial update failed for job %s step %d: %s", job_id, step, exc)
            finally:
                db.close()

        try:
            result = await self._pipeline.run_with_progress(inp, on_step=on_step)

            db = SessionLocal()
            try:
                repo = JobRepository(db)
                repo.save_report(job_id, user_id, result.model_dump(mode="json"))
                repo.mark_completed(job_id)
                db.commit()
            finally:
                db.close()

            logger.info("Job %s completed", job_id)

        except Exception as exc:
            logger.error("Job %s failed: %s", job_id, exc)
            db = SessionLocal()
            try:
                repo = JobRepository(db)
                repo.mark_failed_or_retry(job_id, str(exc))
                db.commit()
            finally:
                db.close()

        finally:
            self._active_jobs.discard(job_id)

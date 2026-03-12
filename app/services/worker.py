"""비동기 분석 Worker.

DB의 pending job을 polling하여 ReportPipeline.stream()으로 처리한다.
FastAPI lifespan에서 start/stop 한다.

Progress 매핑 (pipeline.stream 이벤트 → DB progress_pct):
    step=2 done (이력서 분석)  → 25%
    step=3 done (쿼리 최적화) → 30%   (2,3은 병렬이므로 둘 다 done이면 30%)
    step=4 done (뉴스 검색)   → 55%
    step=5 done (SWOT/분석)   → 80%
    step=6 done (최종 리포트) → 100%
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Optional

from app.db.base import SessionLocal
from app.db.repositories.job_repository import JobRepository
from app.services.report_pipeline import ReportInput, ReportPipeline

logger = logging.getLogger(__name__)

_STEP_PROGRESS: dict[tuple[int, str], int] = {
    (2, "done"): 25,
    (3, "done"): 30,
    (4, "done"): 55,
    (5, "done"): 80,
    (6, "done"): 100,
}

# 동시에 처리할 job 수 제한
_MAX_CONCURRENT = 3


class AnalysisWorker:
    """DB polling 기반 비동기 분석 워커."""

    def __init__(self) -> None:
        self._pipeline: Optional[ReportPipeline] = None
        self._loop_task: Optional[asyncio.Task] = None
        self._active_jobs: set[uuid.UUID] = set()

    def set_pipeline(self, pipeline: ReportPipeline) -> None:
        self._pipeline = pipeline

    async def start(self) -> None:
        self._loop_task = asyncio.create_task(self._poll_loop(), name="analysis-worker")
        logger.info("AnalysisWorker started (polling interval=3s)")

    async def stop(self) -> None:
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        logger.info("AnalysisWorker stopped")

    # ------------------------------------------------------------------
    # 내부 루프
    # ------------------------------------------------------------------

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
        if len(self._active_jobs) >= _MAX_CONCURRENT:
            return

        db = SessionLocal()
        try:
            repo = JobRepository(db)
            pending = repo.get_pending_jobs()
            for job in pending:
                if job.id in self._active_jobs:
                    continue
                if len(self._active_jobs) >= _MAX_CONCURRENT:
                    break
                # pending → running 선점 (중복 실행 방지)
                repo.mark_running(job.id)
                db.commit()
                self._active_jobs.add(job.id)
                asyncio.create_task(
                    self._process_job(
                        job_id=job.id,
                        user_id=job.user_id,
                        resume_text=job.resume_text or "",
                        company=job.company or "",
                        job_title=job.job_title or "",
                        industry=job.industry or "",
                        career_level=job.career_level or "신입",
                    ),
                    name=f"job-{job.id}",
                )
        finally:
            db.close()

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
        result_data: Optional[dict] = None

        try:
            async for raw_event in self._pipeline.stream(inp):
                line = raw_event.strip()
                if not line.startswith("data: "):
                    continue
                event = json.loads(line[6:])
                event_type = event.get("type")

                if event_type == "progress":
                    step = event.get("step", 0)
                    status = event.get("status", "")
                    label = event.get("label", "")
                    detail = event.get("detail", "")
                    pct = _STEP_PROGRESS.get((step, status))
                    self._update_progress(job_id, step, label, detail, pct)

                elif event_type == "result":
                    result_data = event.get("data")

                elif event_type == "error":
                    raise RuntimeError(event.get("message", "pipeline error"))

            # 완료
            db = SessionLocal()
            try:
                repo = JobRepository(db)
                if result_data:
                    repo.save_report(job_id, user_id, result_data)
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
                repo.mark_failed(job_id, str(exc))
                db.commit()
            finally:
                db.close()

        finally:
            self._active_jobs.discard(job_id)

    def _update_progress(
        self,
        job_id: uuid.UUID,
        step: int,
        label: str,
        detail: str,
        pct: Optional[int],
    ) -> None:
        db = SessionLocal()
        try:
            repo = JobRepository(db)
            repo.update_progress(job_id, step, label, detail, pct)
            db.commit()
        except Exception as exc:
            logger.warning("Progress update failed for job %s: %s", job_id, exc)
        finally:
            db.close()

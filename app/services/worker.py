"""비동기 분석 Worker.

DB의 pending job을 polling하여 ReportPipeline.stream()으로 처리한다.
FastAPI lifespan에서 start/stop 한다.

Progress 매핑 (pipeline.stream 이벤트 → progress_pct):
    step=2 done (이력서 분석)  → 25%
    step=3 done (쿼리 최적화) → 30%
    step=4 done (뉴스 검색)   → 55%
    step=5 done (SWOT/분석)   → 80%
    step=6 done (최종 리포트) → 100%

Retry: 실패 시 최대 _MAX_RETRIES(3)회까지 자동 재시도.
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
            # claim_pending_jobs: SELECT ... FOR UPDATE SKIP LOCKED + UPDATE running
            # 단일 트랜잭션으로 원자적 픽업 — 다중 워커/인스턴스에서 중복 실행 없음
            claimed = repo.claim_pending_jobs(slots)
            # commit 전에 필요한 필드 추출 (commit 후 ORM 객체 expire 방지)
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

        # 1. 초기화 단계에 추적용 딕셔너리 추가
        self._active_tasks: dict[uuid.UUID, asyncio.Task] = {}

        # 2. 작업 생성 시 참조 저장 및 완료 콜백 등록
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
    
        # 생성된 태스크 저장
        self._active_tasks[job_id] = task
        
        # 작업 완료(성공/실패 무관) 시 딕셔너리에서 안전하게 제거
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
                    pct = _STEP_PROGRESS.get((step, status))
                    if pct is not None:
                        self._update_progress(job_id, pct)

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
                repo.mark_failed_or_retry(job_id, str(exc))
                db.commit()
            finally:
                db.close()

        finally:
            self._active_jobs.discard(job_id)

    def _update_progress(self, job_id: uuid.UUID, pct: int) -> None:
        db = SessionLocal()
        try:
            repo = JobRepository(db)
            repo.update_progress(job_id, pct)
            db.commit()
        except Exception as exc:
            logger.warning("Progress update failed for job %s: %s", job_id, exc)
        finally:
            db.close()

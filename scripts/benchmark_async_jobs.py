#!/usr/bin/env python3
"""
scripts/benchmark_async_jobs.py

비동기 job 시스템 부하 실험 스크립트.

목적:
  - API + worker 동거 모드와
  - API-only + standalone worker 분리 모드를
  같은 입력과 같은 측정 기준으로 비교한다.

기능:
  1. POST /api/v1/jobs 로 N개 job 제출
  2. GET /api/v1/jobs/{job_id} 로 완료/실패까지 폴링
  3. API 응답의 timing 메트릭과 HTTP 지연시간을 집계
  4. 결과를 JSON으로 저장

예시:
  python scripts/benchmark_async_jobs.py \
    --base-url http://127.0.0.1:8000 \
    --pdf resume_kimjinju.pdf \
    --jobs 12 \
    --submit-concurrency 4 \
    --label inprocess

  python scripts/benchmark_async_jobs.py \
    --base-url http://127.0.0.1:8000 \
    --pdf resume_kimjinju.pdf \
    --jobs 12 \
    --submit-concurrency 4 \
    --label split
"""

from __future__ import annotations

import argparse
import json
import math
import mimetypes
import statistics
import sys
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parent.parent
RESULT_DIR = PROJECT_ROOT / "data" / "benchmarks"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def percentile(values: list[float], pct: float) -> float | None:
    if not values:
        return None
    if len(values) == 1:
        return values[0]
    sorted_values = sorted(values)
    rank = (len(sorted_values) - 1) * pct
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return sorted_values[lower]
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


def summarize(values: list[float | int]) -> dict[str, float | int | None]:
    numeric = [float(v) for v in values if v is not None]
    if not numeric:
        return {
            "count": 0,
            "mean": None,
            "p50": None,
            "p95": None,
            "min": None,
            "max": None,
        }
    return {
        "count": len(numeric),
        "mean": statistics.mean(numeric),
        "p50": percentile(numeric, 0.50),
        "p95": percentile(numeric, 0.95),
        "min": min(numeric),
        "max": max(numeric),
    }


def build_multipart_form_data(
    *,
    file_field: str,
    file_name: str,
    file_bytes: bytes,
    form_fields: dict[str, str],
) -> tuple[bytes, str]:
    boundary = f"----CodexBoundary{uuid.uuid4().hex}"
    content_type = f"multipart/form-data; boundary={boundary}"
    lines: list[bytes] = []

    for key, value in form_fields.items():
        lines.extend(
            [
                f"--{boundary}".encode(),
                f'Content-Disposition: form-data; name="{key}"'.encode(),
                b"",
                value.encode("utf-8"),
            ]
        )

    mime_type = mimetypes.guess_type(file_name)[0] or "application/octet-stream"
    lines.extend(
        [
            f"--{boundary}".encode(),
            (
                f'Content-Disposition: form-data; name="{file_field}"; '
                f'filename="{file_name}"'
            ).encode(),
            f"Content-Type: {mime_type}".encode(),
            b"",
            file_bytes,
            f"--{boundary}--".encode(),
            b"",
        ]
    )
    body = b"\r\n".join(lines)
    return body, content_type


def request_json(
    *,
    url: str,
    method: str,
    timeout_sec: float,
    body: bytes | None = None,
    headers: dict[str, str] | None = None,
) -> tuple[int, dict[str, Any], float]:
    request = Request(url=url, data=body, method=method)
    for key, value in (headers or {}).items():
        request.add_header(key, value)

    started = time.perf_counter()
    try:
        with urlopen(request, timeout=timeout_sec) as response:
            raw = response.read()
            latency_ms = (time.perf_counter() - started) * 1000
            payload = json.loads(raw.decode("utf-8"))
            return response.status, payload, latency_ms
    except HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        latency_ms = (time.perf_counter() - started) * 1000
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"detail": raw}
        return exc.code, payload, latency_ms
    except URLError as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        return 0, {"detail": str(exc)}, latency_ms


@dataclass
class SubmitResult:
    index: int
    job_id: str | None
    status_code: int
    latency_ms: float
    error: str | None


@dataclass
class JobRunResult:
    index: int
    job_id: str
    final_status: str
    submit_latency_ms: float
    poll_count: int
    final_poll_latency_ms: float
    poll_latency_ms_mean: float | None
    queue_wait_ms: int | None
    processing_time_ms: int | None
    total_lead_time_ms: int | None
    age_ms: int | None
    progress_pct: int | None
    retry_count: int | None
    report_id: str | None
    created_at: str | None
    started_at: str | None
    completed_at: str | None
    terminal_observed_at: str
    error_msg: str | None


def submit_job(
    *,
    index: int,
    base_url: str,
    pdf_name: str,
    pdf_bytes: bytes,
    form_fields: dict[str, str],
    auth_token: str | None,
    timeout_sec: float,
) -> SubmitResult:
    body, content_type = build_multipart_form_data(
        file_field="file",
        file_name=pdf_name,
        file_bytes=pdf_bytes,
        form_fields=form_fields,
    )
    headers = {"Content-Type": content_type}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    status_code, payload, latency_ms = request_json(
        url=urljoin(base_url, "/api/v1/jobs"),
        method="POST",
        timeout_sec=timeout_sec,
        body=body,
        headers=headers,
    )
    if status_code != 202:
        return SubmitResult(
            index=index,
            job_id=None,
            status_code=status_code,
            latency_ms=latency_ms,
            error=str(payload.get("detail")),
        )

    return SubmitResult(
        index=index,
        job_id=str(payload.get("job_id")),
        status_code=status_code,
        latency_ms=latency_ms,
        error=None,
    )


def poll_until_terminal(
    *,
    submit_result: SubmitResult,
    base_url: str,
    auth_token: str | None,
    poll_interval_sec: float,
    timeout_sec: float,
) -> JobRunResult:
    headers = {}
    if auth_token:
        headers["Authorization"] = f"Bearer {auth_token}"

    job_url = urljoin(base_url, f"/api/v1/jobs/{submit_result.job_id}")
    started = time.monotonic()
    poll_latencies: list[float] = []

    while True:
        status_code, payload, latency_ms = request_json(
            url=job_url,
            method="GET",
            timeout_sec=max(3.0, poll_interval_sec + 2.0),
            headers=headers,
        )
        poll_latencies.append(latency_ms)

        if status_code != 200:
            return JobRunResult(
                index=submit_result.index,
                job_id=submit_result.job_id or "",
                final_status="poll_error",
                submit_latency_ms=submit_result.latency_ms,
                poll_count=len(poll_latencies),
                final_poll_latency_ms=latency_ms,
                poll_latency_ms_mean=statistics.mean(poll_latencies),
                queue_wait_ms=None,
                processing_time_ms=None,
                total_lead_time_ms=None,
                age_ms=None,
                progress_pct=None,
                retry_count=None,
                report_id=None,
                created_at=None,
                started_at=None,
                completed_at=None,
                terminal_observed_at=utc_now_iso(),
                error_msg=str(payload.get("detail")),
            )

        status_value = str(payload.get("status"))
        timing = payload.get("timing") or {}
        if status_value in {"completed", "failed"}:
            return JobRunResult(
                index=submit_result.index,
                job_id=submit_result.job_id or "",
                final_status=status_value,
                submit_latency_ms=submit_result.latency_ms,
                poll_count=len(poll_latencies),
                final_poll_latency_ms=latency_ms,
                poll_latency_ms_mean=statistics.mean(poll_latencies),
                queue_wait_ms=timing.get("queue_wait_ms"),
                processing_time_ms=timing.get("processing_time_ms"),
                total_lead_time_ms=timing.get("total_lead_time_ms"),
                age_ms=timing.get("age_ms"),
                progress_pct=payload.get("progress_pct"),
                retry_count=payload.get("retry_count"),
                report_id=payload.get("report_id"),
                created_at=payload.get("created_at"),
                started_at=payload.get("started_at"),
                completed_at=payload.get("completed_at"),
                terminal_observed_at=utc_now_iso(),
                error_msg=payload.get("error_msg"),
            )

        if time.monotonic() - started > timeout_sec:
            return JobRunResult(
                index=submit_result.index,
                job_id=submit_result.job_id or "",
                final_status="timeout",
                submit_latency_ms=submit_result.latency_ms,
                poll_count=len(poll_latencies),
                final_poll_latency_ms=latency_ms,
                poll_latency_ms_mean=statistics.mean(poll_latencies),
                queue_wait_ms=timing.get("queue_wait_ms"),
                processing_time_ms=timing.get("processing_time_ms"),
                total_lead_time_ms=timing.get("total_lead_time_ms"),
                age_ms=timing.get("age_ms"),
                progress_pct=payload.get("progress_pct"),
                retry_count=payload.get("retry_count"),
                report_id=payload.get("report_id"),
                created_at=payload.get("created_at"),
                started_at=payload.get("started_at"),
                completed_at=payload.get("completed_at"),
                terminal_observed_at=utc_now_iso(),
                error_msg="poll timeout exceeded",
            )

        time.sleep(poll_interval_sec)


def print_summary(summary: dict[str, Any]) -> None:
    sep = "=" * 76
    print(f"\n{sep}")
    print("  비동기 Job Load Test Summary")
    print(sep)
    print(f"label                 : {summary['label']}")
    print(f"base_url              : {summary['base_url']}")
    print(f"jobs_requested        : {summary['jobs_requested']}")
    print(f"submit_concurrency    : {summary['submit_concurrency']}")
    print(f"wall_clock_sec        : {summary['wall_clock_sec']:.2f}")
    print(f"throughput_jobs_per_min: {summary['throughput_jobs_per_min']:.2f}")
    print("-" * 76)
    print("status_counts")
    for key, value in summary["status_counts"].items():
        print(f"  {key:<18} {value}")
    print("-" * 76)

    metric_names = [
        ("submit_request_ms", "submit_request_ms"),
        ("poll_request_ms", "poll_request_ms"),
        ("queue_wait_ms", "queue_wait_ms"),
        ("processing_time_ms", "processing_time_ms"),
        ("total_lead_time_ms", "total_lead_time_ms"),
    ]
    print(f"{'metric':<22} {'mean':>10} {'p50':>10} {'p95':>10} {'max':>10}")
    for display, key in metric_names:
        metric = summary["metrics"][key]
        def fmt(value: Any) -> str:
            if value is None:
                return "-"
            return f"{value:.1f}" if isinstance(value, float) else str(value)
        print(
            f"{display:<22} {fmt(metric['mean']):>10} {fmt(metric['p50']):>10} "
            f"{fmt(metric['p95']):>10} {fmt(metric['max']):>10}"
        )
    print(sep)
    if summary.get("result_path"):
        print(f"saved_result          : {summary['result_path']}")
        print(sep)


def main() -> int:
    parser = argparse.ArgumentParser(description="비동기 job 시스템 부하 실험")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000", help="FastAPI base URL")
    parser.add_argument("--pdf", required=True, help="업로드할 PDF 파일 경로")
    parser.add_argument("--jobs", type=int, default=12, help="생성할 총 job 수")
    parser.add_argument(
        "--submit-concurrency",
        type=int,
        default=4,
        help="job 제출 동시성",
    )
    parser.add_argument(
        "--poll-interval-sec",
        type=float,
        default=1.5,
        help="job 상태 폴링 간격",
    )
    parser.add_argument(
        "--job-timeout-sec",
        type=float,
        default=900.0,
        help="단일 job 최대 대기 시간",
    )
    parser.add_argument(
        "--request-timeout-sec",
        type=float,
        default=30.0,
        help="개별 HTTP 요청 타임아웃",
    )
    parser.add_argument("--label", default="unnamed", help="실험 결과 레이블")
    parser.add_argument("--company", default="삼성전자", help="form-data company")
    parser.add_argument("--job-title", default="백엔드 개발자", help="form-data job_title")
    parser.add_argument("--industry", default="반도체", help="form-data industry")
    parser.add_argument("--career-level", default="신입", help="form-data career_level")
    parser.add_argument("--auth-token", default=None, help="선택적 JWT bearer token")
    parser.add_argument("--save", action="store_true", help="data/benchmarks 에 JSON 저장")
    args = parser.parse_args()

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        print(f"PDF not found: {pdf_path}", file=sys.stderr)
        return 2

    pdf_bytes = pdf_path.read_bytes()
    form_fields = {
        "company": args.company,
        "job_title": args.job_title,
        "industry": args.industry,
        "career_level": args.career_level,
    }

    print("실험 시작")
    print(f"  label={args.label}")
    print(f"  base_url={args.base_url}")
    print(f"  jobs={args.jobs}")
    print(f"  submit_concurrency={args.submit_concurrency}")
    print(f"  poll_interval_sec={args.poll_interval_sec}")
    print(f"  pdf={pdf_path}")

    experiment_started_at = utc_now_iso()
    experiment_started = time.perf_counter()

    submit_results: list[SubmitResult] = []
    with ThreadPoolExecutor(max_workers=args.submit_concurrency) as executor:
        futures = [
            executor.submit(
                submit_job,
                index=i,
                base_url=args.base_url,
                pdf_name=pdf_path.name,
                pdf_bytes=pdf_bytes,
                form_fields=form_fields,
                auth_token=args.auth_token,
                timeout_sec=args.request_timeout_sec,
            )
            for i in range(args.jobs)
        ]
        for future in as_completed(futures):
            result = future.result()
            submit_results.append(result)
            state = "ok" if not result.error else f"error={result.error}"
            print(
                f"  submit[{result.index:03d}] "
                f"status={result.status_code} latency_ms={result.latency_ms:.1f} {state}"
            )

    submit_results.sort(key=lambda item: item.index)
    successful_submits = [item for item in submit_results if item.job_id]
    failed_submits = [item for item in submit_results if not item.job_id]

    if not successful_submits:
        print("생성된 job이 없어 실험을 종료합니다.", file=sys.stderr)
        return 1

    poll_workers = min(max(1, args.submit_concurrency), len(successful_submits))
    print(f"폴링 시작: {len(successful_submits)} jobs, workers={poll_workers}")
    job_results: list[JobRunResult] = []
    with ThreadPoolExecutor(max_workers=poll_workers) as executor:
        futures = [
            executor.submit(
                poll_until_terminal,
                submit_result=result,
                base_url=args.base_url,
                auth_token=args.auth_token,
                poll_interval_sec=args.poll_interval_sec,
                timeout_sec=args.job_timeout_sec,
            )
            for result in successful_submits
        ]
        for future in as_completed(futures):
            result = future.result()
            job_results.append(result)
            print(
                f"  job[{result.index:03d}] status={result.final_status} polls={result.poll_count} "
                f"queue_wait_ms={result.queue_wait_ms} processing_ms={result.processing_time_ms} "
                f"lead_ms={result.total_lead_time_ms}"
            )

    job_results.sort(key=lambda item: item.index)
    wall_clock_sec = time.perf_counter() - experiment_started

    status_counts: dict[str, int] = {}
    for result in job_results:
        status_counts[result.final_status] = status_counts.get(result.final_status, 0) + 1
    if failed_submits:
        status_counts["submit_failed"] = len(failed_submits)

    submit_latencies = [item.latency_ms for item in submit_results]
    poll_latencies = [item.final_poll_latency_ms for item in job_results]
    all_poll_means = [
        item.poll_latency_ms_mean for item in job_results if item.poll_latency_ms_mean is not None
    ]

    summary = {
        "label": args.label,
        "base_url": args.base_url,
        "jobs_requested": args.jobs,
        "jobs_submitted": len(successful_submits),
        "submit_concurrency": args.submit_concurrency,
        "poll_interval_sec": args.poll_interval_sec,
        "job_timeout_sec": args.job_timeout_sec,
        "started_at": experiment_started_at,
        "finished_at": utc_now_iso(),
        "wall_clock_sec": wall_clock_sec,
        "throughput_jobs_per_min": (
            (status_counts.get("completed", 0) / wall_clock_sec) * 60 if wall_clock_sec > 0 else 0.0
        ),
        "status_counts": status_counts,
        "metrics": {
            "submit_request_ms": summarize(submit_latencies),
            "poll_request_ms": summarize(all_poll_means or poll_latencies),
            "queue_wait_ms": summarize(
                [item.queue_wait_ms for item in job_results if item.queue_wait_ms is not None]
            ),
            "processing_time_ms": summarize(
                [
                    item.processing_time_ms
                    for item in job_results
                    if item.processing_time_ms is not None
                ]
            ),
            "total_lead_time_ms": summarize(
                [
                    item.total_lead_time_ms
                    for item in job_results
                    if item.total_lead_time_ms is not None
                ]
            ),
        },
    }

    result_payload = {
        "summary": summary,
        "submit_results": [asdict(item) for item in submit_results],
        "job_results": [asdict(item) for item in job_results],
    }

    result_path = None
    if args.save:
        RESULT_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        result_path = RESULT_DIR / f"async_jobs_{args.label}_{timestamp}.json"
        result_path.write_text(
            json.dumps(result_payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        summary["result_path"] = str(result_path)

    print_summary(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

# NewStrackers AI

자소서(Internal Context)와 뉴스(External Context)를 결합해 산업 분석과 기업 면접 준비를 지원하는 AI 서버입니다.

## 핵심 기능

- **산업 분석**: 뉴스 기반 트렌드, 키워드, 월별 감정 분석, 출처 통계
- **기업 분석**: 5대 지표 레이더, SWOT, 최신 뉴스 테마, 리스크 평가
- **자소서 분석**: PDF/DOCX 업로드 → 스킬·강점·키워드 추출
- **기업 면접 준비**: 자소서 + 기업 뉴스 기반 맞춤 면접 문항 생성
- **벡터 검색**: pgvector 코사인 유사도로 의미 기반 기사 검색

## 기술 스택

| 분류 | 기술 |
|------|------|
| 언어 / 프레임워크 | Python 3.12, FastAPI |
| LLM | Anthropic Claude (`claude-sonnet-4-6`) |
| 임베딩 | OpenAI `text-embedding-3-small` (1536차원) |
| DB | PostgreSQL (AWS RDS) + pgvector |
| AI 파이프라인 | LangGraph (병렬 노드 실행) |
| 테스트 | Pytest |

## 설치

```bash
git clone https://github.com/yourusername/newstrackers-server.git
cd newstrackers-server
uv sync
```

## 환경 변수

```bash
cp .env.example .env
```

| 변수 | 필수 | 설명 |
|------|------|------|
| `ANTHROPIC_API_KEY` | ✅ | Claude API 키 |
| `OPENAI_API_KEY` | ✅ | 임베딩용 OpenAI 키 |
| `DATABASE_URL` | ✅ | PostgreSQL 연결 문자열 |
| `LOG_LEVEL` | - | 로그 레벨 (기본: `INFO`) |

```
DATABASE_URL=postgresql://user:password@host:5432/dbname
```

## 실행

```bash
# FastAPI 서버
uvicorn app.main:app --reload

# Swagger UI
open http://localhost:8000/docs
```

### Worker 실행 모드

비동기 job worker는 두 가지 방식으로 실행할 수 있습니다.

```bash
# 1) API 프로세스 안에서 worker까지 함께 실행 (기본값)
RUN_WORKER_IN_API=true uvicorn app.main:app --reload

# 2) API와 worker 분리 실행
RUN_WORKER_IN_API=false uvicorn app.main:app --reload
python -m app.worker_main
```

추가 제어용 환경 변수:

- `RUN_WORKER_IN_API`: `true`면 FastAPI lifespan에서 worker 자동 시작
- `WORKER_POLL_INTERVAL_SEC`: pending job polling 주기
- `WORKER_MAX_CONCURRENT`: worker 동시 처리 job 수

## API 엔드포인트

### Health

| Method | Path | 설명 |
|--------|------|------|
| GET | `/health` | 루트 헬스체크 |
| GET | `/api/v1/health` | API v1 헬스체크 |

### 산업 분석

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/analysis/industry` | 산업 트렌드 분석 |
| GET | `/api/v1/analysis/graph/industry` | 분석 파이프라인 Mermaid 다이어그램 |

```bash
curl -X POST http://localhost:8000/api/v1/analysis/industry \
  -H "Content-Type: application/json" \
  -d '{"industry": "반도체", "days_back": 365}'
```

### 기업 분석

| Method | Path | Body | 설명 |
|--------|------|------|------|
| POST | `/api/v1/analysis/company` | JSON | 기업 분석 (자소서 텍스트) |
| POST | `/api/v1/analysis/company/upload` | form-data | 기업 분석 (자소서 파일) |
| GET | `/api/v1/analysis/graph/company` | - | 분석 파이프라인 Mermaid 다이어그램 |

```bash
# JSON 방식
curl -X POST http://localhost:8000/api/v1/analysis/company \
  -H "Content-Type: application/json" \
  -d '{"company": "삼성전자", "industry": "반도체", "resume": "자소서 내용...", "days_back": 365}'

# 파일 업로드 방식
curl -X POST http://localhost:8000/api/v1/analysis/company/upload \
  -F "company=삼성전자" \
  -F "industry=반도체" \
  -F "days_back=365" \
  -F "file=@자소서.pdf"
```

### 자소서

| Method | Path | 설명 |
|--------|------|------|
| POST | `/api/v1/resume/parse` | PDF/DOCX에서 텍스트 추출 |
| POST | `/api/v1/resume/analyze` | 텍스트 추출 + LLM 구조화 분석 |

```bash
curl -X POST http://localhost:8000/api/v1/resume/parse \
  -F "file=@자소서.pdf"
```

## LangGraph 파이프라인

### 산업 분석 그래프

```
fetch_articles
     │
     ├── extract_trends
     ├── extract_keywords
     ├── compute_monthly_sentiment
     └── compute_source_stats
              │
         assemble_result
```

### 기업 분석 그래프 (2단계 병렬)

```
Step 1 (병렬):  fetch_articles  ||  analyze_resume
                        └──── sync barrier ────┘
                                    │
Step 2 (병렬):  generate_swot  ||  generate_interview_questions
             ||  score_dimensions  ||  extract_themes
             ||  assess_risks      ||  extract_company_info
                        └──────────────────┘
                              assemble_result
```

GET `/api/v1/analysis/graph/industry` 또는 `/company` 로 현재 그래프 구조를 Mermaid 형식으로 실시간 확인 가능.

## 프로젝트 구조

```
app/
  agents/
    graphs/          # LangGraph 파이프라인 (industry_graph, company_graph)
    nodes/           # 그래프 노드 (fetch_nodes, llm_nodes, analysis_nodes)
    state.py         # LangGraph 상태 타입 정의
  analysis/
    industry_analyzer.py   # 산업 분석기 (그래프 실행)
    company_analyzer.py    # 기업 분석기 (그래프 실행)
  api/v1/
    endpoints/
      analysis.py    # 산업/기업 분석 엔드포인트
      resume.py      # 자소서 업로드/분석 엔드포인트
      health.py      # 헬스체크
    router.py
  core/
    config.py        # 환경 변수 (pydantic-settings)
    dependencies.py  # FastAPI DI 프로바이더
    constants.py     # 상수
  db/
    base.py          # SQLAlchemy 엔진/세션
    models.py        # news_article_embeddings 테이블 모델
  schemas/
    data_models.py   # Pydantic 응답 모델
  services/
    news_service.py  # DB 조회, 벡터 검색
    llm_service.py   # Claude API 호출
    data_loader.py   # AI Hub 데이터 로드 + OpenAI 임베딩 생성
  main.py            # FastAPI 앱 진입점
tests/
  unit/              # 단위 테스트
  integration/       # 통합 테스트
  api/               # API 엔드포인트 테스트
```

## 테스트

```bash
# 전체
pytest -v

# 단위만
pytest tests/unit/ -v

# 커버리지
pytest --cov=app tests/
```

## 데이터 로드

AI Hub 뉴스 데이터를 RDS에 적재할 때:

```bash
# 임베딩 포함 (OpenAI API 필요)
python -m app.services.data_loader --input data/news.jsonl

# 임베딩 제외 (빠른 적재)
python -m app.services.data_loader --input data/news.jsonl --no-embed
```

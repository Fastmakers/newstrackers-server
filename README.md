# News Tracker Server

LangGraph 기반 뉴스 트래킹 에이전트 서비스

## 요구사항

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) (패키지 관리자)

## 설치

```bash
# Python 버전 설치 및 의존성 설치
uv sync

# 개발 의존성 포함 설치
uv sync --dev
```

## 환경 설정

```bash
# .env 파일 생성
cp .env.example .env

# .env 파일 편집하여 API 키 설정
```

### 환경 변수

| 변수명 | 설명 | 필수 |
|--------|------|------|
| `OPENAI_API_KEY` | OpenAI API 키 | O |

## 실행

```bash
# 개발 서버 실행
uv run uvicorn app.main:app --reload

# 또는 가상환경 활성화 후 실행
source .venv/bin/activate
uvicorn app.main:app --reload
```

서버 실행 후 http://localhost:8000/docs 에서 API 문서 확인 가능

## 프로젝트 구조

```
app/
├── main.py              # FastAPI 앱 진입점
├── api/                 # API 라우터
│   └── v1/
│       ├── router.py
│       └── endpoints/
├── agents/              # LangGraph 에이전트
│   ├── state.py         # 에이전트 상태 정의
│   ├── graphs/          # 그래프 정의
│   └── nodes/           # 노드 함수
├── core/                # 핵심 설정
│   ├── config.py        # 환경 설정
│   └── dependencies.py  # 의존성 주입
├── schemas/             # Pydantic 스키마
├── services/            # 비즈니스 로직
├── tools/               # LangGraph 도구
└── prompts/             # 프롬프트 템플릿
tests/                   # 테스트
```

## 개발

```bash
# 린트 검사
uv run ruff check .

# 린트 자동 수정
uv run ruff check --fix .

# 포맷팅
uv run ruff format .

# 테스트 실행
uv run pytest
```

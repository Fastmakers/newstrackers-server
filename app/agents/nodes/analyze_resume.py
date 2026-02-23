import json

from app.agents.state import AnalysisState
from app.core.config import settings
from app.services.claude_llm import claude_llm_service


async def analyze_resume(state: AnalysisState) -> AnalysisState:
    """
    Node 1: 자소서 분석

    자소서 텍스트에서 지원 직무, 산업, 회사, 스킬, 경험을 추출합니다.
    """
    industries = ", ".join(settings.INDUSTRY_KEYWORDS)

    try:
        message = await claude_llm_service.client.messages.create(
            model="claude-sonnet-4-5-20250929",
            max_tokens=1000,
            messages=[
                {
                    "role": "user",
                    "content": (
                        "다음 자기소개서/이력서에서 정보를 추출하여 JSON으로만 응답하세요. "
                        "마크다운 코드 펜스나 다른 텍스트 없이 순수 JSON만 출력하세요.\n\n"
                        "응답 형식:\n"
                        '{"job_title": "지원 직무", "industry": "산업군", "company": "지원 회사", '
                        '"skills": ["스킬1", "스킬2"], "experiences": ["경험1", "경험2"]}\n\n'
                        f"industry 값은 반드시 다음 중 하나여야 합니다:\n{industries}\n\n"
                        "가장 잘 맞는 산업군을 위 목록에서 정확히 선택하세요. "
                        "company가 명시되지 않았다면 빈 문자열을 사용하세요.\n\n"
                        f"자기소개서:\n{state['resume_text']}"
                    ),
                }
            ],
        )

        raw = message.content[0].text.strip()

        # Claude가 ```json ... ``` 형식으로 감싸는 경우 처리
        if raw.startswith("```"):
            lines = raw.split("\n")
            raw = "\n".join(lines[1:-1])

        profile = json.loads(raw)

        # 필수 필드 기본값 보장
        profile.setdefault("job_title", "")
        profile.setdefault("industry", settings.INDUSTRY_KEYWORDS[0])
        profile.setdefault("company", "")
        profile.setdefault("skills", [])
        profile.setdefault("experiences", [])

        print(f"[Node 1] 자소서 분석 완료: {profile['job_title']} / {profile['industry']}")
        return {**state, "resume_profile": profile}

    except Exception as e:
        print(f"[Node 1] 자소서 분석 실패: {e}")
        return {**state, "error": f"자소서 분석 실패: {e}"}

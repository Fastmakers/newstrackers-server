"""리포트 생성 서비스 — Claude Sonnet 기반 취업 전략 리포트 생성."""

import logging
from typing import Dict, List, Tuple

from app.services.llm_client import LLMClient

logger = logging.getLogger(__name__)


class ReportGenerator(LLMClient):
    """SWOT 분석, 산업 연관성 분석, 최종 면접 리포트 생성 (Claude Sonnet 사용)."""

    def generate_swot_list(
        self,
        resume: str,
        company: str,
        job_title: str,
        chunks: list,
        industry: str = "",
        career_level: str = "신입",
    ) -> Dict[str, List[str]]:
        """지원자 관점 SWOT 분석 (자소서 + 뉴스 기반).

        Returns:
            {"strengths": [...], "weaknesses": [...], "opportunities": [...], "threats": [...]}
        """
        if not chunks and not resume.strip():
            return {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []}

        news_context = "\n".join(
            f"- {c.article.title if c.article else ''}: {c.chunk_text[:100]}"
            for c in chunks[:6]
        ) if chunks else "관련 뉴스 없음"

        industry_hint = f" ({industry})" if industry else ""
        career_context = (
            "지원자는 신입 지원자입니다. 실무 경험이 제한적임을 전제로, "
            "성장 가능성·학습 의지·잠재력·학업 성취를 강점으로 보고, 실무 경험 부재를 약점으로 평가하세요."
            if career_level == "신입" else
            "지원자는 경력직 지원자입니다. 즉시 전력 여부·전문성·성과·실무 역량을 중심으로 평가하고, "
            "이직 사유와 경력 활용도를 고려하세요."
        )

        system_prompt = f"""당신은 취업 전략 전문가입니다.
지원자의 자소서와 {company}{industry_hint} 관련 뉴스를 분석해,
지원자가 이 기업에 지원했을 때의 관점에서 SWOT 분석을 수행합니다.
{career_context}
반드시 유효한 JSON만 응답하세요. 마크다운 펜스, 설명 텍스트, trailing comma 없이 순수 JSON 객체만 출력하세요."""

        user_message = f"""다음 정보를 바탕으로 지원자의 SWOT 분석을 작성하세요.
분석 기준은 '{company}'의 '{job_title}' 직무 {career_level} 지원입니다.

[자소서 발췌]
{resume[:1200]}

[{company} 관련 뉴스 발췌]
{news_context}

각 항목당 2~3개 불릿을 작성하되, 각 불릿은 반드시 단 1문장 (50자 내외) 으로 작성하세요. 규칙:
- 지원자 역량과 {company}/직무를 연결하는 핵심만 1문장에 압축
- 키워드 나열 금지, 하지만 긴 복문도 금지 — 짧고 명확한 단문으로 작성
- {career_level} 기준에 맞는 평가 관점 적용
- 항목별 기준: Strengths=지원자 차별 강점, Weaknesses=보완 필요 약점, Opportunities=활용 가능한 기회, Threats=직면한 위협

응답 형식 (JSON):
{{
  "strengths": ["서술형 문장1", "서술형 문장2"],
  "weaknesses": ["서술형 문장1", "서술형 문장2"],
  "opportunities": ["서술형 문장1", "서술형 문장2"],
  "threats": ["서술형 문장1", "서술형 문장2"]
}}"""

        try:
            response = self._call_claude(system_prompt, user_message, temperature=0.5)
            try:
                data = self._extract_json(response)
            except Exception as json_err:
                logger.error("generate_swot_list JSON 파싱 실패: %s\nRAW:\n%s", json_err, response)
                return {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []}
            result: Dict[str, List[str]] = {
                "strengths": [], "weaknesses": [], "opportunities": [], "threats": [],
            }
            for key in result:
                val = data.get(key, [])
                if isinstance(val, list):
                    result[key] = [str(item) for item in val]
                elif isinstance(val, str) and val:
                    result[key] = [val]
            return result
        except Exception as e:
            logger.error("generate_swot_list 실패: %s", e)
            return {"strengths": [], "weaknesses": [], "opportunities": [], "threats": []}

    def generate_relevance_analysis(
        self,
        resume: str,
        chunks: list,
        company: str = "",
        industry: str = "",
        job_title: str = "",
        career_level: str = "신입",
    ) -> str:
        """자소서 + 뉴스 청크 기반 산업 연관성 분석 (마크다운 반환).

        Returns:
            마크다운 문자열 (### 섹션 3개 구조)
        """
        if not chunks:
            return ""

        context = "\n".join(
            f"- {c.article.title if c.article else ''}: {c.chunk_text[:150]}"
            for c in chunks[:6]
        )

        meta = ""
        if company:
            meta += f"지원 기업: {company}\n"
        if industry:
            meta += f"희망 산업: {industry}\n"
        if job_title:
            meta += f"희망 직무: {job_title}\n"

        career_note = (
            "신입 지원자 관점: 산업 트렌드를 처음 접하는 입문자 시각으로, 학습 기회와 성장 가능성을 중심으로 연결하세요."
            if career_level == "신입" else
            "경력직 지원자 관점: 산업 트렌드를 이미 경험한 전문가 시각으로, 실무 기여와 차별화 포인트를 중심으로 연결하세요."
        )

        system_prompt = f"""당신은 취업 전략 전문가입니다.
지원자의 자소서와 관련 뉴스 기사를 분석해 산업 연관성 리포트를 작성합니다.
{career_note}
반드시 지정된 마크다운 템플릿 구조를 정확히 따르세요. 섹션 외 서문이나 결론 문장을 추가하지 마세요."""

        user_message = f"""다음 정보를 바탕으로 산업 연관성 분석을 작성하세요.

{meta}
[자소서 핵심 발췌]
{resume[:600]}

[관련 뉴스 요약]
{context}

아래 템플릿을 정확히 따라 작성하세요. 헤딩 문자열을 그대로 유지하고, 각 섹션에 정확히 3개의 불릿을 작성하세요:

### 산업 트렌드 요약
- [뉴스 기사에서 확인된 트렌드 1 — 구체적 사실 기반 1~2문장]
- [뉴스 기사에서 확인된 트렌드 2 — 구체적 사실 기반 1~2문장]
- [뉴스 기사에서 확인된 트렌드 3 — 구체적 사실 기반 1~2문장]

### 역량-트렌드 연결 포인트
- **[지원자 역량명]** — [위 트렌드 중 하나와 지원자 경험이 어떻게 맞닿는지 1~2문장]
- **[지원자 역량명]** — [위 트렌드 중 하나와 지원자 경험이 어떻게 맞닿는지 1~2문장]
- **[지원자 역량명]** — [위 트렌드 중 하나와 지원자 경험이 어떻게 맞닿는지 1~2문장]

### 면접 활용 키워드
- **[키워드 1]**: [이 키워드를 면접에서 어떻게 활용하면 좋은지 1문장]
- **[키워드 2]**: [이 키워드를 면접에서 어떻게 활용하면 좋은지 1문장]
- **[키워드 3]**: [이 키워드를 면접에서 어떻게 활용하면 좋은지 1문장]"""

        try:
            return self._call_claude(system_prompt, user_message, temperature=0.4)
        except Exception as e:
            logger.error("generate_relevance_analysis 실패: %s", e)
            return ""

    def _build_final_report_prompt(
        self,
        resume: str,
        company: str,
        job_title: str,
        industry: str,
        swot: Dict[str, List[str]],
        relevance_analysis: str,
        career_level: str,
    ) -> Tuple[str, str]:
        """generate_final_report / stream_final_report 공통 프롬프트 빌더."""
        swot_summary = (
            f"강점: {'; '.join(swot.get('strengths', [])[:2])}\n"
            f"약점: {'; '.join(swot.get('weaknesses', [])[:2])}\n"
            f"기회: {'; '.join(swot.get('opportunities', [])[:2])}\n"
            f"위협: {'; '.join(swot.get('threats', [])[:2])}"
        )
        career_instruction = (
            "지원자는 신입입니다. 면접 질문과 권고사항은 실무 경험 대신 "
            "학습 의지·성장 가능성·잠재력·학업 성취를 부각하는 방향으로 작성하세요. "
            "경력직 수준의 역량을 요구하지 마세요."
            if career_level == "신입" else
            "지원자는 경력직입니다. 면접 질문과 권고사항은 즉시 전력 여부·기존 성과·전문성·이직 사유를 다루는 방향으로 작성하세요."
        )
        system_prompt = f"""당신은 취업 면접 코치입니다.
지원자 정보와 SWOT 분석, 산업 연관성 분석을 바탕으로 실전 면접 전략 리포트를 작성합니다.
{career_instruction}
반드시 지정된 마크다운 템플릿 구조를 정확히 따르세요."""

        user_message = f"""다음 정보를 바탕으로 면접 준비 리포트를 작성하세요.

지원 기업: {company}
희망 직무: {job_title}
희망 산업: {industry}
지원 유형: {career_level}

[SWOT 요약]
{swot_summary}

[산업 연관성 분석 참고]
{relevance_analysis[:500] if relevance_analysis else "없음"}

[자소서 발췌]
{resume[:800]}

아래 형식을 정확히 따라 마크다운으로 작성하세요. 헤딩 문자열(## 면접 준비 포인트, ## 최종 권고사항 등)을 정확히 유지하세요:

## 면접 준비 포인트

### Q1. [예상 질문 — 뉴스 트렌드 연관]
[이 질문이 나오는 배경과 최신 산업 이슈 1문장]
**핵심 답변 방향:** [지원자 경험을 어떻게 연결할지 구체적으로 2~3문장]

### Q2. [예상 질문 — 지원자 경험 연관]
[이 질문이 나오는 배경 1문장]
**핵심 답변 방향:** [2~3문장]

### Q3. [예상 질문 — 직무 적합성 연관]
[이 질문이 나오는 배경 1문장]
**핵심 답변 방향:** [2~3문장]

---

## 최종 권고사항

### 핵심 준비 사항
1. **[준비 항목명]** — [구체적 실행 방법과 목표 1~2문장]
2. **[준비 항목명]** — [구체적 실행 방법과 목표 1~2문장]
3. **[준비 항목명]** — [구체적 실행 방법과 목표 1~2문장]

### 차별화 전략
[지원자만의 차별점과 면접에서 집중 강조할 핵심 포인트 2~3문장]"""

        return system_prompt, user_message

    def generate_final_report(
        self,
        resume: str,
        company: str,
        job_title: str,
        industry: str,
        swot: Dict[str, List[str]],
        relevance_analysis: str = "",
        career_level: str = "신입",
    ) -> str:
        """면접 준비 포인트 + 최종 권고사항 리포트 (마크다운 반환).

        프론트엔드 FinalReportSummary 컴포넌트에서
        '면접 준비 포인트'와 '최종 권고사항' 섹션을 파싱해 사용.
        """
        system_prompt, user_message = self._build_final_report_prompt(
            resume, company, job_title, industry, swot, relevance_analysis, career_level
        )
        try:
            return self._call_claude(system_prompt, user_message, temperature=0.6, max_tokens=3500)
        except Exception as e:
            logger.error("generate_final_report 실패: %s", e)
            return ""

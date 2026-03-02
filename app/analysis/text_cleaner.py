"""
뉴스 기사 텍스트 정제기 — 바이라인·저작권·광고성 노이즈 제거.

매일경제 기사에서 반복적으로 등장하는 비내용성 텍스트를 Regex로 제거한다:
    - 기자 이름·이메일·바이라인
    - 저작권 고지 ("무단전재 및 재배포 금지")
    - 사진 출처 태그 ([사진=연합뉴스])
    - 통신사 태그 ([AP=연합뉴스])
    - URL
    - 중복 공백·개행
"""

from __future__ import annotations

import re

# ---------------------------------------------------------------------------
# 매경 전용 정제 패턴 (순서 중요 — 위에서부터 순차 적용)
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[re.Pattern, str]] = [
    # 이메일 주소
    (re.compile(r"[\w.+-]+@[\w-]+\.[a-zA-Z]{2,}"), ""),
    # URL
    (re.compile(r"https?://\S+"), ""),
    # 저작권 고지 (한 줄 전체)
    (re.compile(r"ⓒ\s*매일경제[^\n]*"), ""),
    (re.compile(r"©\s*매일경제[^\n]*"), ""),
    (re.compile(r"무단\s*전재\s*및\s*재배포\s*금지[^\n]*"), ""),
    (re.compile(r"무단전재[^\n]*재배포[^\n]*금지"), ""),
    # 사진 출처 태그: [사진 = 연합뉴스], [사진출처=게티이미지]
    (re.compile(r"\[사진\s*[=：]\s*[^\]]+\]"), ""),
    (re.compile(r"\[사진출처\s*[=：]\s*[^\]]+\]"), ""),
    # 통신사·언론사 태그: [AP=연합뉴스], [연합뉴스], [매경DB]
    (re.compile(r"\[[A-Za-z가-힣·\s]+=\s*[^\]]+뉴스\]"), ""),
    (re.compile(r"\[[가-힣A-Za-z\s]+뉴스\]"), ""),
    (re.compile(r"\[매경\s*DB\]"), ""),
    # 기자 바이라인: "홍길동 기자", "홍길동 특파원"
    # 이름 앞에 공백·줄바꿈이 있고 뒤에 이메일이 붙는 경우 포함
    (re.compile(r"[가-힣]{2,4}\s*(기자|특파원|논설위원|편집장)\s*[\w@.]*"), ""),
    # 각주형 번호 태그: [1], [2]
    (re.compile(r"\[\d+\]"), ""),
    # 3개 이상 연속 개행 → 2개로 정규화
    (re.compile(r"\n{3,}"), "\n\n"),
    # 2개 이상 연속 공백·탭 → 1개로
    (re.compile(r"[ \t]{2,}"), " "),
]


class TextCleaner:
    """
    뉴스 본문 텍스트에서 비내용성 노이즈를 제거한다.

    사용 예:
        cleaner = TextCleaner()
        clean_body = cleaner.clean(article.body)
    """

    def clean(self, text: str) -> str:
        """단건 텍스트 정제. 빈 문자열이면 그대로 반환."""
        if not text:
            return text
        for pattern, repl in _PATTERNS:
            text = pattern.sub(repl, text)
        return text.strip()

    def clean_batch(self, texts: list[str]) -> list[str]:
        """텍스트 목록 일괄 정제."""
        return [self.clean(t) for t in texts]

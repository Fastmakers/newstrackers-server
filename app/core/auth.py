"""Optional JWT 인증 의존성.

get_current_user (필수 인증, 401 반환) 는 dependencies.py 에 있다.
여기서는 Jobs 엔드포인트용 Optional 버전만 제공한다.
토큰이 없거나 유효하지 않으면 None을 반환한다.
"""

from __future__ import annotations

from typing import Optional

from fastapi import Request

from app.core.security import verify_access_token


def get_optional_user_id(request: Request) -> Optional[str]:
    """Authorization: Bearer <token> 헤더에서 user_id 추출.

    토큰 없거나 만료/유효하지 않으면 None 반환 (인증 강제 안 함).
    강제 인증이 필요하면 dependencies.py 의 get_current_user 를 사용할 것.
    """
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return None
    token = auth[7:].strip()
    user_uuid = verify_access_token(token)
    return str(user_uuid) if user_uuid else None

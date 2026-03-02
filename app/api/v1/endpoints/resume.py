"""Resume upload endpoint — accepts PDF or Word (.docx) files and returns extracted text."""

import io
import logging

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status

from app.schemas.data_models import ResumeAnalysis
from app.services.llm_service import LLMService
from app.core.dependencies import get_llm_service

logger = logging.getLogger(__name__)

router = APIRouter()

_ALLOWED_TYPES = {
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/msword",
}
_MAX_SIZE_BYTES = 5 * 1024 * 1024  # 5 MB


def _extract_text_from_pdf(data: bytes) -> str:
    try:
        from pypdf import PdfReader
        reader = PdfReader(io.BytesIO(data))
        return "\n".join(page.extract_text() or "" for page in reader.pages)
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="pypdf is not installed. Run: uv pip install pypdf",
        )


def _extract_text_from_docx(data: bytes) -> str:
    try:
        import docx
        doc = docx.Document(io.BytesIO(data))
        return "\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except ImportError:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail="python-docx is not installed. Run: uv pip install python-docx",
        )


@router.post("/parse")
async def parse_resume(file: UploadFile) -> dict:
    """Extract plain text from an uploaded PDF or Word resume.

    Returns:
        filename, content_type, char_count, text (first 5,000 chars)
    """
    if file.content_type not in _ALLOWED_TYPES and not (
        file.filename and (
            file.filename.endswith(".pdf")
            or file.filename.endswith(".docx")
            or file.filename.endswith(".doc")
        )
    ):
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"Unsupported file type: {file.content_type}. Use PDF or DOCX.",
        )

    data = await file.read()
    if len(data) > _MAX_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"File too large ({len(data) // 1024} KB). Max 5 MB.",
        )

    filename = file.filename or ""
    if filename.endswith(".pdf") or file.content_type == "application/pdf":
        text = _extract_text_from_pdf(data)
    else:
        text = _extract_text_from_docx(data)

    text = text.strip()
    if not text:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No text could be extracted from the file.",
        )

    logger.info(f"Parsed resume: {filename} ({len(text)} chars)")
    return {
        "filename": filename,
        "content_type": file.content_type,
        "char_count": len(text),
        "text": text[:5000],  # Return first 5,000 chars
    }


@router.post("/analyze", response_model=ResumeAnalysis)
async def analyze_resume(
    file: UploadFile,
    llm_service: LLMService = Depends(get_llm_service),
) -> ResumeAnalysis:
    """Upload a PDF or Word resume and return structured LLM analysis.

    Extracts: skills, experience_keywords, target_role, strengths, search_keywords.
    """
    # Reuse parse logic
    parse_result = await parse_resume(file)
    text = parse_result["text"]

    raw = llm_service.analyze_resume(text)
    return ResumeAnalysis(
        skills=raw.get("skills") or [],
        experience_keywords=raw.get("experience_keywords") or [],
        target_role=raw.get("target_role"),
        strengths=raw.get("strengths") or [],
        search_keywords=raw.get("search_keywords") or [],
    )

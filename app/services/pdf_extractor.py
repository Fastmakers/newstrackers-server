import fitz  # pymupdf


def extract_text_from_pdf(pdf_bytes: bytes) -> str:
    """
    PDF 바이트에서 텍스트를 추출합니다.

    Args:
        pdf_bytes: PDF 파일의 바이트 데이터

    Returns:
        추출된 텍스트

    Raises:
        ValueError: 암호화된 PDF이거나 텍스트 추출 불가 시
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")

    if doc.is_encrypted:
        raise ValueError("암호화된 PDF는 지원되지 않습니다.")

    pages_text = [page.get_text("text") for page in doc]
    full_text = "\n".join(pages_text).strip()

    if len(full_text) < 50:
        raise ValueError(
            "텍스트를 추출할 수 없습니다. 이미지 기반 PDF이거나 내용이 없는 파일입니다."
        )

    return full_text

from __future__ import annotations

import httpx


class DocumentParser:
    """Detects format and extracts clean text from documents."""

    @staticmethod
    def parse_markdown(content: str) -> str:
        return content.strip()

    @staticmethod
    def parse_html(content: str) -> str:
        try:
            import trafilatura
            text = trafilatura.extract(content, output_format="markdown")
            if text:
                return text.strip()
        except ImportError:
            pass

        from bs4 import BeautifulSoup
        soup = BeautifulSoup(content, "lxml")
        for tag in soup(["script", "style", "nav", "footer", "header", "aside"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)

    @staticmethod
    def parse_pdf(content: bytes) -> str:
        try:
            import fitz
            doc = fitz.open(stream=content, filetype="pdf")
            text = "\n".join(page.get_text() for page in doc)
            doc.close()
            return text.strip()
        except ImportError:
            return ""

    @staticmethod
    def _to_str(content: str | bytes) -> str:
        if isinstance(content, bytes):
            return content.decode("utf-8", errors="replace")
        return content

    @classmethod
    def parse(cls, content: str | bytes, source: str | None = None) -> str:
        content_type = ""
        if source:
            lower = source.lower()
            if lower.endswith(".md") or lower.endswith(".markdown"):
                return cls.parse_markdown(cls._to_str(content))
            if lower.endswith(".pdf"):
                return cls.parse_pdf(content if isinstance(content, bytes) else content.encode())
            if lower.endswith(".html") or lower.endswith(".htm"):
                return cls.parse_html(cls._to_str(content))
            if lower.endswith(".txt"):
                return cls._to_str(content).strip()
            if source.startswith("http://") or source.startswith("https://"):
                content_type = cls._detect_content_type(source)

        if content_type == "application/pdf":
            return cls.parse_pdf(content if isinstance(content, bytes) else content.encode())
        if content_type and "html" in content_type:
            return cls.parse_html(cls._to_str(content))

        return cls._to_str(content).strip()

    @staticmethod
    def _detect_content_type(url: str) -> str:
        try:
            response = httpx.head(url, timeout=10.0, follow_redirects=True)
            val: str = response.headers.get("content-type", "")
            return val.lower()
        except Exception:
            return ""

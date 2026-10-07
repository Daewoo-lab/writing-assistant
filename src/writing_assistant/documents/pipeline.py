"""Pipeline: brief bytes -> drafted document bytes. No external I/O."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from writing_assistant.documents.llm import LLMClient, WritingSample
from writing_assistant.documents.readers import read_any
from writing_assistant.documents.writers import DocMeta, write_docx, write_pptx

OutputFormat = Literal["docx", "pptx"]


@dataclass(frozen=True)
class Slide:
    title: str
    bullets: list[str]
    notes: str = ""


@dataclass(frozen=True)
class GeneratedDocument:
    content: bytes
    filename: str
    mime: str


_MIME = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pptx": "application/vnd.openxmlformats-officedocument.presentationml.presentation",
}


class DocumentPipeline:
    """Reads a brief, drafts with the LLM, renders an office file.

    The result is returned to the caller to hand to the author directly.
    Nothing here uploads, submits or logs in anywhere.
    """

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    async def generate(
        self,
        brief_file: bytes,
        brief_filename: str,
        hints: dict[str, str],
        writing_samples: list[WritingSample],
        output_format: OutputFormat,
    ) -> GeneratedDocument:
        brief_text = read_any(brief_file, brief_filename)
        meta = DocMeta(title=hints.get("title", ""), author=hints.get("author", ""))

        if output_format == "docx":
            text = await self._llm.generate_text(brief_text, hints, writing_samples)
            content = write_docx(text, meta)
            name = "draft.docx"
        elif output_format == "pptx":
            outline = await self._llm.generate_presentation_outline(
                brief_text, hints, writing_samples
            )
            content = write_pptx(outline, meta)
            name = "draft.pptx"
        else:  # pragma: no cover - guarded by Literal
            raise ValueError(f"unsupported output_format: {output_format!r}")

        return GeneratedDocument(content=content, filename=name, mime=_MIME[output_format])

"""LLM calls: draft prose and presentation outlines in a target tone of voice.

Uses the standard Anthropic SDK directly. Tone-of-voice samples are the
author's OWN writing, passed few-shot so the draft matches his register.
"""

from __future__ import annotations

from dataclasses import dataclass

from anthropic import AsyncAnthropic

DEFAULT_MODEL = "claude-opus-4-8"

_SYSTEM = (
    "You are a drafting assistant for an independent author. You produce a "
    "first draft from a brief. The author reviews and edits everything before "
    "it is used anywhere. Write clearly and stay on brief."
)


@dataclass(frozen=True)
class WritingSample:
    kind: str
    text: str


def _voice_block(samples: list[WritingSample]) -> str:
    if not samples:
        return "No voice samples provided. Write in a neutral, clean register."
    joined = "\n\n---\n\n".join(s.text for s in samples[:3])
    return (
        "Target voice reference. The author's own writing samples:\n\n"
        f"{joined}\n\n"
        "Match the vocabulary, rhythm and register of these samples."
    )


class LLMClient:
    def __init__(
        self,
        api_key: str,
        model: str = DEFAULT_MODEL,
        base_url: str | None = None,
    ) -> None:
        self._client = AsyncAnthropic(api_key=api_key, base_url=base_url)
        self._model = model

    async def generate_text(
        self,
        brief_text: str,
        hints: dict[str, str],
        samples: list[WritingSample],
    ) -> str:
        hint_lines = "\n".join(f"- {k}: {v}" for k, v in hints.items())
        prompt = (
            f"{_voice_block(samples)}\n\n"
            f"Brief:\n{brief_text}\n\n"
            f"Extra instructions:\n{hint_lines or '(none)'}\n\n"
            "Write the full draft now."
        )
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    async def generate_presentation_outline(
        self,
        brief_text: str,
        hints: dict[str, str],
        samples: list[WritingSample],
    ) -> list[dict[str, object]]:
        prompt = (
            f"{_voice_block(samples)}\n\n"
            f"Brief:\n{brief_text}\n\n"
            "Return a presentation outline as a JSON array of objects with "
            '"title" (str), "bullets" (list of str), "notes" (str). '
            "Return JSON only, no prose."
        )
        resp = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=_SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
        raw = "".join(b.text for b in resp.content if b.type == "text").strip()
        import json

        raw = raw.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
        data = json.loads(raw)
        if not isinstance(data, list):
            raise TypeError("outline must be a JSON array")
        return data

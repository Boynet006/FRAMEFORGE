"""The production plan: the editable, structured script that drives every later stage.

Produced by the planner (Phase 3) from one user prompt; consumed by TTS (Phase 4),
character/environment reference generation (Phase 5/6) and assembly (Phase 7).
Stored as JSON on the project (`Project.plan`) so advanced mode can edit it.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

WORDS_PER_SECOND = 2.4  # conversational TTS pace (~145 wpm); used for duration estimates


class Voice(BaseModel):
    engine: Literal["kokoro"] = "kokoro"
    voice: str = "af_heart"      # Kokoro voice id, e.g. af_heart, am_michael, bf_emma, bm_george
    speed: float = Field(default=1.0, ge=0.6, le=1.5)


class Character(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    role: str = ""
    personality: str = ""
    species: str = Field(default="", description="what the character is, e.g. 'cat', 'woman', 'golden retriever'")
    appearance: str = Field(default="", description="visual description used in image prompts")
    image_prompt: str = ""
    negative_prompt: str = "blurry, low quality, text, watermark, extra limbs, deformed"
    voice: Voice = Field(default_factory=Voice)
    reference_image: str | None = None  # path relative to the project data dir, set in Phase 5


class Environment(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    description: str = ""
    image_prompt: str = ""
    reference_image: str | None = None


class Line(BaseModel):
    id: str
    character_id: str
    text: str = Field(min_length=1)
    emotion: str = "neutral"
    pause_after_s: float = Field(default=0.4, ge=0, le=5)

    @property
    def word_count(self) -> int:
        return len(self.text.split())


class Scene(BaseModel):
    id: str
    environment_id: str
    summary: str = ""
    time_of_day: str = ""
    lines: list[Line] = Field(default_factory=list)

    @property
    def estimated_duration_s(self) -> float:
        return sum(l.word_count / WORDS_PER_SECOND + l.pause_after_s for l in self.lines)


class Music(BaseModel):
    enabled: bool = True
    mood: str = "light, playful"
    volume_db: float = -18.0


class ProductionPlan(BaseModel):
    version: int = 1
    title: str
    logline: str = ""
    style: str = "cinematic"
    aspect_ratio: str = "16:9"
    target_duration_s: int = Field(ge=5, le=1200)
    characters: list[Character] = Field(min_length=1)
    environments: list[Environment] = Field(min_length=1)
    scenes: list[Scene] = Field(min_length=1)
    music: Music = Field(default_factory=Music)
    subtitles: bool = True

    @property
    def estimated_duration_s(self) -> float:
        return round(sum(s.estimated_duration_s for s in self.scenes), 1)

    @property
    def line_count(self) -> int:
        return sum(len(s.lines) for s in self.scenes)

    @property
    def word_count(self) -> int:
        return sum(l.word_count for s in self.scenes for l in s.lines)

    @model_validator(mode="after")
    def _check_references(self) -> "ProductionPlan":
        char_ids = {c.id for c in self.characters}
        env_ids = {e.id for e in self.environments}
        seen_lines: set[str] = set()
        for s in self.scenes:
            if s.environment_id not in env_ids:
                raise ValueError(f"scene {s.id}: unknown environment_id {s.environment_id!r}")
            for l in s.lines:
                if l.character_id not in char_ids:
                    raise ValueError(f"line {l.id}: unknown character_id {l.character_id!r}")
                if l.id in seen_lines:
                    raise ValueError(f"duplicate line id {l.id}")
                seen_lines.add(l.id)
        return self

    def summary(self) -> dict:
        return {
            "title": self.title,
            "characters": len(self.characters),
            "environments": len(self.environments),
            "scenes": len(self.scenes),
            "lines": self.line_count,
            "words": self.word_count,
            "target_duration_s": self.target_duration_s,
            "estimated_duration_s": self.estimated_duration_s,
        }

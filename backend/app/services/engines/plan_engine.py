"""Phase 3 planner: user prompt -> ProductionPlan via a local LLM.

Two-pass generation keeps small models reliable and scales to long videos:
  1. outline: title, characters, environments, scene beats with word budgets
  2. per scene: dialogue lines for that scene within its word budget
Then a validation + duration check. Everything is constrained with JSON schemas.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

from pydantic import ValidationError

from ...plan import WORDS_PER_SECOND, Character, Environment, Line, Music, ProductionPlan, Scene, Voice
from ..llm_client import LLMError, OllamaClient

log = logging.getLogger(__name__)

ProgressCb = Callable[[float, str | None], Awaitable[None]]

# Kokoro voices grouped so distinct characters get distinct voices.
KOKORO_VOICES = {
    "female": ["af_heart", "af_bella", "af_sarah", "bf_emma", "af_nicole", "bf_isabella"],
    "male": ["am_michael", "am_adam", "bm_george", "am_fenrir", "bm_lewis", "am_puck"],
}

_OUTLINE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "logline": {"type": "string"},
        "characters": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "role": {"type": "string"},
                    "personality": {"type": "string"},
                    "appearance": {"type": "string"},
                    "voice_gender": {"type": "string", "enum": ["female", "male"]},
                },
                "required": ["name", "role", "personality", "appearance", "voice_gender"],
            },
        },
        "environments": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "description": {"type": "string"}},
                "required": ["name", "description"],
            },
        },
        "scenes": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "environment": {"type": "string"},
                    "summary": {"type": "string"},
                    "time_of_day": {"type": "string"},
                    "word_budget": {"type": "integer"},
                },
                "required": ["environment", "summary", "time_of_day", "word_budget"],
            },
        },
        "music_mood": {"type": "string"},
    },
    "required": ["title", "logline", "characters", "environments", "scenes", "music_mood"],
}

_SCENE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "minItems": 1,
            "items": {
                "type": "object",
                "properties": {
                    "character": {"type": "string"},
                    "text": {"type": "string"},
                    "emotion": {"type": "string"},
                },
                "required": ["character", "text", "emotion"],
            },
        }
    },
    "required": ["lines"],
}

_SYSTEM = (
    "You are a screenwriter for short animated films. You write natural, funny, character-driven "
    "dialogue. You answer ONLY with JSON that matches the requested schema. Never include stage "
    "directions, markdown or commentary inside dialogue text."
)


def slugify(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")
    return s or "x"


class PlanEngine:
    def __init__(self, llm: OllamaClient) -> None:
        self.llm = llm

    async def run(self, settings: dict[str, Any], prompt: str, *, progress: ProgressCb) -> ProductionPlan:
        duration = int(settings.get("duration_s") or 60)
        style = str(settings.get("style") or "cinematic")
        aspect = str(settings.get("aspect_ratio") or "16:9")
        total_words = int(duration * WORDS_PER_SECOND * 0.85)  # leave room for pauses
        n_scenes = max(1, min(12, round(duration / 60)))

        await progress(0.05, "outline")
        outline = await self._outline(prompt, style, duration, total_words, n_scenes)

        characters = self._characters(outline["characters"])
        environments = [
            Environment(id=slugify(e["name"]), name=e["name"], description=e["description"],
                        image_prompt=f"{e['description']}, {style} style, wide establishing shot, no people, no text")
            for e in outline["environments"]
        ]
        env_by_name = {e.name.lower(): e.id for e in environments}
        char_by_name = {c.name.lower(): c.id for c in characters}

        scenes: list[Scene] = []
        beats = outline["scenes"] or []
        for i, beat in enumerate(beats):
            await progress(0.15 + 0.75 * i / max(len(beats), 1), f"scene {i + 1}/{len(beats)}")
            env_id = env_by_name.get(str(beat.get("environment", "")).lower(), environments[0].id)
            budget = int(beat.get("word_budget") or total_words // max(len(beats), 1))
            raw_lines = await self._scene_lines(prompt, outline, beat, characters, budget)
            lines: list[Line] = []
            for j, rl in enumerate(raw_lines):
                cid = char_by_name.get(str(rl.get("character", "")).lower()) or self._closest(rl.get("character", ""), char_by_name)
                text = str(rl.get("text", "")).strip()
                if not cid or not text:
                    continue
                lines.append(Line(id=f"s{i + 1}l{j + 1}", character_id=cid, text=text,
                                  emotion=str(rl.get("emotion") or "neutral"),
                                  pause_after_s=0.35 if j < len(raw_lines) - 1 else 0.8))
            if lines:
                scenes.append(Scene(id=f"s{i + 1}", environment_id=env_id, summary=str(beat.get("summary", "")),
                                    time_of_day=str(beat.get("time_of_day", "")), lines=lines))

        try:
            plan = ProductionPlan(
                title=outline["title"], logline=outline.get("logline", ""), style=style, aspect_ratio=aspect,
                target_duration_s=duration, characters=characters, environments=environments, scenes=scenes,
                music=Music(mood=outline.get("music_mood") or "light, playful"),
            )
        except ValidationError as exc:
            raise LLMError(f"model produced an unusable plan: {exc.errors()[0].get('msg')}") from exc

        await progress(0.95, "validate")
        log.info("plan: %s", plan.summary())
        return plan

    # ---------- LLM calls ----------

    async def _outline(self, prompt: str, style: str, duration: int, total_words: int, n_scenes: int) -> dict[str, Any]:
        user = (
            f"Create the outline for a {duration}-second {style} dialogue video.\n"
            f"User request: {prompt}\n\n"
            f"Rules:\n"
            f"- Characters: as described by the request (default two). Give each a distinct personality, a vivid visual "
            f"appearance for an image generator (species, colours, clothing, defining features) and a voice_gender.\n"
            f"- Environments: 1 to {max(1, n_scenes)} named locations with concrete visual descriptions.\n"
            f"- Scenes: exactly {n_scenes} scene(s). Each names one environment, a short summary of what happens, "
            f"a time_of_day, and a word_budget. The word budgets must add up to about {total_words} words total.\n"
            f"- music_mood: a few words describing background music."
        )
        for attempt in range(3):
            data = await self.llm.chat_json(_SYSTEM, user, _OUTLINE_SCHEMA, temperature=0.8)
            if data.get("characters") and data.get("environments") and data.get("scenes"):
                return data
            log.warning("outline attempt %d incomplete: %s", attempt + 1, list(data))
        raise LLMError("model failed to produce a complete outline after 3 attempts")

    async def _scene_lines(self, prompt: str, outline: dict[str, Any], beat: dict[str, Any],
                           characters: list[Character], budget: int) -> list[dict[str, Any]]:
        cast = "\n".join(f"- {c.name}: {c.personality}" for c in characters)
        names = ", ".join(c.name for c in characters)
        user = (
            f"Film: {outline['title']} — {outline.get('logline', '')}\n"
            f"Original request: {prompt}\n"
            f"Characters:\n{cast}\n\n"
            f"Write the dialogue for this scene.\n"
            f"Scene: {beat.get('summary', '')} (location: {beat.get('environment', '')}, {beat.get('time_of_day', '')})\n"
            f"Rules:\n"
            f"- About {budget} words in total across all lines (this matters: not much more, not much less).\n"
            f"- Alternate speakers naturally; short punchy lines mixed with a few longer ones; include reactions, "
            f"interruptions and callbacks. Characters must be exactly one of: {names}.\n"
            f"- 'emotion' is one word (e.g. amused, annoyed, smug, curious, deadpan).\n"
            f"- No narration, no stage directions, no emojis."
        )
        for attempt in range(3):
            data = await self.llm.chat_json(_SYSTEM, user, _SCENE_SCHEMA, temperature=0.9)
            lines = data.get("lines") or []
            words = sum(len(str(l.get("text", "")).split()) for l in lines)
            if lines and words >= budget * 0.4:
                return lines
            log.warning("scene attempt %d too short (%d words for budget %d)", attempt + 1, words, budget)
        return lines

    # ---------- helpers ----------

    def _characters(self, raw: list[dict[str, Any]]) -> list[Character]:
        used: dict[str, int] = {"female": 0, "male": 0}
        out: list[Character] = []
        ids: set[str] = set()
        for c in raw:
            gender = "female" if str(c.get("voice_gender", "")).lower().startswith("f") else "male"
            pool = KOKORO_VOICES[gender]
            voice = pool[used[gender] % len(pool)]
            used[gender] += 1
            cid = slugify(c["name"])
            while cid in ids:
                cid += "_"
            ids.add(cid)
            appearance = str(c.get("appearance", ""))
            out.append(Character(
                id=cid, name=c["name"], role=str(c.get("role", "")), personality=str(c.get("personality", "")),
                appearance=appearance,
                image_prompt=f"character portrait of {c['name']}, {appearance}, facing camera, centered, "
                             f"neutral background, soft lighting, high detail",
                voice=Voice(voice=voice),
            ))
        return out

    @staticmethod
    def _closest(name: str, by_name: dict[str, str]) -> str | None:
        n = str(name).lower()
        for key, cid in by_name.items():
            if key in n or n in key:
                return cid
        return None

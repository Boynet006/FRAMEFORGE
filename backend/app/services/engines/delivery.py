"""How a line is performed: emotion -> voice settings, and the pause before the next line.

The planner tags every line with a one-word emotion ("smug", "annoyed", "curious", ...). Kokoro can only
change speed; Chatterbox also takes `exaggeration` (expressiveness; higher also speeds delivery up) and
`cfg_weight` (adherence to the reference voice's pacing; lower = looser, which keeps fast, excited
speech from rushing). Timing replaces the planner's uniform pause with conversational rhythm: quick
comebacks, a beat before a thoughtful answer, slight overlaps when someone is cut off.
"""

from __future__ import annotations

import re
import zlib
from dataclasses import dataclass

# emotion word -> family. Unknown words fall back to "neutral".
_FAMILIES: dict[str, tuple[str, ...]] = {
    "calm": ("calm", "matter-of-fact", "serious", "thoughtful", "deadpan", "dry", "flat", "pensive",
             "reflective", "sincere", "earnest", "patient"),
    "warm": ("warm", "kind", "gentle", "tender", "affectionate", "reassuring", "fond", "content", "happy", "relieved"),
    "playful": ("amused", "playful", "smug", "teasing", "sarcastic", "sly", "witty", "cheeky", "curious",
                "mischievous", "confident", "proud", "ironic", "skeptical", "sceptical", "wry"),
    "excited": ("excited", "enthusiastic", "eager", "thrilled", "delighted", "joyful", "gleeful", "triumphant",
                "surprised", "amazed", "astonished", "shocked", "incredulous"),
    "angry": ("angry", "annoyed", "irritated", "frustrated", "indignant", "outraged", "exasperated", "furious",
              "defensive", "offended", "grumpy", "huffy", "impatient"),
    "sad": ("sad", "disappointed", "wistful", "melancholy", "regretful", "tired", "weary", "resigned", "hurt"),
    "scared": ("nervous", "anxious", "scared", "worried", "afraid", "panicked", "uneasy", "embarrassed", "sheepish"),
}
_LOOKUP = {w: fam for fam, words in _FAMILIES.items() for w in words}


@dataclass(frozen=True)
class Delivery:
    family: str
    exaggeration: float   # Chatterbox expressiveness, 0.25 (flat) .. 2.0 (wild); 0.5 = default
    cfg_weight: float     # Chatterbox pacing adherence; default 0.5
    speed: float          # multiplier on the character's base speed (Kokoro, and timing estimates)


_STYLE: dict[str, Delivery] = {
    "calm":    Delivery("calm",    0.40, 0.55, 0.96),
    "neutral": Delivery("neutral", 0.50, 0.50, 1.00),
    "warm":    Delivery("warm",    0.55, 0.50, 0.98),
    "playful": Delivery("playful", 0.65, 0.45, 1.02),
    "excited": Delivery("excited", 0.85, 0.30, 1.08),
    "angry":   Delivery("angry",   0.80, 0.35, 1.06),
    "sad":     Delivery("sad",     0.45, 0.55, 0.90),
    "scared":  Delivery("scared",  0.70, 0.40, 1.05),
}


def family(emotion: str) -> str:
    e = (emotion or "").strip().lower()
    return _LOOKUP.get(e, _LOOKUP.get(e.removesuffix("ly"), "neutral"))  # "excitedly" -> "excited"


def delivery(emotion: str) -> Delivery:
    return _STYLE[family(emotion)]


_INTERJECTION = re.compile(r"^\s*(wait|what|no|nope|yes|yeah|oh|ooh|ah|hey|exactly|right|but|well|ha|hah|seriously|"
                           r"really|come on|okay|ok|please|ugh|hmm|whoa|wow)\b", re.I)


def gap_after(text: str, emotion: str, next_text: str, next_emotion: str, same_speaker: bool, line_id: str) -> float:
    """Seconds between the end of this line and the start of the next one (negative = overlap)."""
    nxt = family(next_emotion)
    t = text.rstrip()
    if same_speaker:
        gap = 0.30                                   # a breath within one speaker's turn
    elif t.endswith(("—", "--", "...", "…")):
        gap = -0.12                                  # cut off: the reply starts over the tail
    elif nxt == "sad":
        gap = 0.60                                   # a beat before a heavy reply, even "Oh. I'm sorry."
    elif nxt in ("excited", "angry") or _INTERJECTION.match(next_text or ""):
        gap = 0.10                                   # quick comeback ("Wait, really?" even when calm)
    elif nxt == "calm":
        gap = 0.50                                   # a beat before a thoughtful reply
    elif t.endswith("?"):
        gap = 0.22                                   # answers come quickly but not instantly
    else:
        gap = 0.28
    # small deterministic variation so the rhythm never sounds metronomic
    jitter = (zlib.crc32(line_id.encode()) % 1000) / 1000 * 0.10 - 0.05
    return round(gap + jitter, 3)


# ----- room acoustics for the dialogue mix -----

_OUTDOOR = ("outdoor", "outside", "park", "street", "garden", "beach", "forest", "field", "meadow", "mountain",
            "sky", "rooftop", "ice floe", "desert", "jungle", "yard", "balcony", "lake", "river", "ocean", "sea",
            "camp", "road", "square", "market")
_LARGE = ("hall", "church", "cathedral", "warehouse", "cave", "station", "gym", "arena", "theater", "theatre",
          "museum", "factory", "hangar", "palace", "temple", "auditorium", "lobby", "mall", "airport")


def room_preset(description: str) -> str:
    """'outdoor' | 'small' | 'large' from an environment description; indoor rooms default to small."""
    d = (description or "").lower()
    if any(w in d for w in _LARGE):
        return "large"
    if any(w in d for w in _OUTDOOR):
        return "outdoor"
    return "small"

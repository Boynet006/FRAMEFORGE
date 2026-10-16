from __future__ import annotations

from app.services.engines.delivery import delivery, family, gap_after, room_preset


def test_emotion_families_and_settings():
    assert family("smug") == "playful" and family("Annoyed") == "angry" and family("excitedly") == "excited"
    assert family("something-new") == "neutral" and family("") == "neutral"
    calm, excited = delivery("deadpan"), delivery("enthusiastic")
    assert excited.exaggeration > calm.exaggeration          # more expressive
    assert excited.cfg_weight < calm.cfg_weight              # looser pacing keeps fast speech from rushing
    assert excited.speed > 1.0 > delivery("sad").speed


def test_conversational_gaps():
    base = dict(same_speaker=False, line_id="x")
    quick = gap_after("You did what?", "neutral", "Exactly! Twice.", "excited", **base)
    beat = gap_after("I lost it.", "neutral", "Oh. I'm sorry.", "sad", **{**base, "line_id": "x"})
    cut = gap_after("I was going to say—", "neutral", "No you weren't.", "neutral", **base)
    normal = gap_after("It's fine.", "neutral", "Good to hear.", "neutral", **base)
    assert cut < 0 < quick < normal < beat               # sad reply gets a beat despite starting with "Oh"
    # interjections start quickly even when the emotion is calm
    assert gap_after("Look at this.", "neutral", "Wait, really?", "calm", **base) < normal
    # deterministic: same line id, same gap
    assert gap_after("a", "neutral", "b", "neutral", False, "s1l3") == gap_after("a", "neutral", "b", "neutral", False, "s1l3")


def test_sad_or_calm_reply_gets_a_beat():
    g = gap_after("It's gone.", "neutral", "Then we start again.", "calm", False, "x")
    assert g > 0.45


def test_room_presets():
    assert room_preset("A cosy café with wooden shelves") == "small"
    assert room_preset("A sunny park bench under trees") == "outdoor"
    assert room_preset("An echoing cathedral nave") == "large"
    assert room_preset("") == "small"

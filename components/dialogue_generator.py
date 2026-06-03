"""
Dialogue generation system.

Public API:
  generate(context_key, mood, facts, language) -> (text, next_contexts)
  generate_sentence(language, context_key, facts)  -> str
  ConversationNode().generate_dialogue(character, context) -> (text, next_contexts)

Adding new content: edit json/languages.json only — no Python changes needed.

JSON structure (per language block):
  contexts.<key>.<mood>  = ["line", ...] or {"compose": [[opts], [opts], ...]}
  parts.<key>            = ["fragment", ...]    (used as {key} in templates)
  next_context.<key>     = ["ContextKey", ...]  (conversation flow)

Template variables:
  {name}, {location}, etc.  — resolved from the `facts` dict
  {address}, {closer}, etc. — resolved from `parts` (random pick, can nest facts)
"""
from __future__ import annotations

import json
import random
import re
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from entity import Actor

_TEMPLATE_PATH = Path(__file__).resolve().parent.parent / "json" / "languages.json"
_DATA: dict | None = None


def _load() -> dict:
    global _DATA
    if _DATA is None:
        with _TEMPLATE_PATH.open("r", encoding="utf-8") as f:
            _DATA = json.load(f)
    return _DATA


def reload() -> None:
    """Force a reload of languages.json (useful in the debug console)."""
    global _DATA
    _DATA = None
    _load()


# ─── resolution helpers ───────────────────────────────────────────────────────

def _pick(options) -> str:
    if isinstance(options, str):
        return options
    if isinstance(options, list) and options:
        return random.choice(options)
    return ""


def _get_parts(language: str) -> dict:
    """Language parts merged over common parts (language wins on conflicts)."""
    data = _load()
    parts_block = data.get("parts", {})
    parts: dict = dict(parts_block.get("common", {}))
    if language != "common":
        parts.update(parts_block.get(language, {}))
    return parts


def _get_options(language: str, context_key: str, mood: str):
    """Return line options for context+mood.

    Lookup order:
      1. contexts[key][mood][language]
      2. contexts[key][neutral][language]
      3. contexts[key][mood][common]
      4. contexts[key][neutral][common]
    """
    data = _load()
    ctx = data.get("contexts", {}).get(context_key)
    if ctx is None:
        return None
    moods = ([mood, "neutral"] if mood != "neutral" else ["neutral"])
    langs  = ([language, "common"] if language != "common" else ["common"])
    for m in moods:
        mood_block = ctx.get(m)
        if not isinstance(mood_block, dict):
            continue
        for lang in langs:
            result = mood_block.get(lang)
            if result is not None:
                return result
    return None


def _resolve(text: str, facts: dict, parts: dict, _depth: int = 0) -> str:
    """Replace {key} with a randomly-picked part (recursive) or a fact value."""
    if _depth > 5:
        return text

    def replace(match: re.Match) -> str:
        key = match.group(1)
        if key in parts:
            raw = _pick(parts[key])
            return _resolve(raw, facts, parts, _depth + 1)
        val = facts.get(key)
        return str(val) if val is not None else ""

    return re.sub(r"\{(\w+)\}", replace, text)


# ─── primary public function ──────────────────────────────────────────────────

def generate(
    context_key: str,
    mood: str = "neutral",
    facts: dict | None = None,
    language: str = "common",
) -> tuple[str, list[str]]:
    """
    Generate one dialogue line.

    Args:
        context_key: Topic key matching a contexts.<key> entry in languages.json
                     (e.g. "Greeting", "Identity", "Location", "Knowledge").
        mood:        "neutral" | "friendly" | "hostile" | any custom mood in the JSON.
        facts:       Any NPC facts; every key is available as {key} in templates.
        language:    Language key (e.g. "common", "goblin"). Falls back to "common".

    Returns:
        (line_text, next_context_keys)
    """
    facts = facts or {}
    mood = mood.lower()

    data = _load()
    parts = _get_parts(language)
    options = _get_options(language, context_key, mood)

    if options is None:
        return ("...", ["Default"])

    # Expand: compose picks one string per segment list and joins; plain list picks one.
    if isinstance(options, dict) and "compose" in options:
        raw = "".join(_pick(seg) for seg in options["compose"])
    else:
        raw = _pick(options)

    text = _resolve(raw, facts, parts)
    text = " ".join(text.split())  # collapse whitespace from compose joins

    next_contexts: list[str] = (
        data.get("next_context", {}).get(context_key, ["Default"])
    )
    return (text, next_contexts)


def generate_sentence(
    language: str = "common",
    context_key: str = "Opening",
    facts: dict | None = None,
) -> str:
    """Convenience wrapper for callers that only need the text string."""
    text, _ = generate(context_key, mood="neutral", facts=facts or {}, language=language)
    return text


# ─── compatibility shim (keeps input_handlers.py unchanged) ──────────────────

_PRIMARY_CONTEXT_KEYS = (
    "RefuseTrade", "Greeting", "Identity", "Location",
    "Knowledge", "Goodbye", "Response", "guide_greet",
    "guide_combat", "guide_magic", "guide_items", "guide_world",
    "guide_opening"
)


def _opinion_to_mood(opinion: int) -> str:
    if opinion >= 67:
        return "friendly"
    if opinion <= 33:
        return "hostile"
    return "neutral"


class ConversationNode:
    """Thin wrapper that extracts context/mood/facts from an Actor and calls generate()."""

    def generate_dialogue(
        self,
        character: "Actor" = None,
        context=None,
        mood: str | None = None,
    ) -> tuple[str, list[str]]:
        if character is None or not getattr(character, "can_speak", False):
            return ("...", ["Default"])

        # ── build facts from knowledge ─────────────────────────────────────────
        raw: dict = dict(getattr(character, "knowledge", {}) or {})
        raw.setdefault("name", getattr(character, "name", "???"))
        raw.setdefault("location", "")
        raw.setdefault("location_empty", raw.get("location", ""))

        facts: dict = {}
        for key, val in raw.items():
            if val is None:
                # Omit None values — templates that reference them get an empty string.
                continue
            if isinstance(val, dict):
                # Flatten one level: pronouns.subject → pronouns_subject
                for subkey, subval in val.items():
                    if subval is not None:
                        facts[f"{key}_{subkey}"] = str(subval)
            else:
                facts[key] = str(val)

        # Restore location_empty even if it was empty string (not None).
        facts.setdefault("location_empty", raw.get("location", "") or "")

        # ── mood ──────────────────────────────────────────────────────────────
        if mood is None:
            opinion_raw = getattr(character, "opinion", None)
            opinion = int(opinion_raw if opinion_raw is not None else 50)
            mood = _opinion_to_mood(opinion)

        # ── language ──────────────────────────────────────────────────────────
        language = str(facts.get("language") or "common")

        # ── context_key ───────────────────────────────────────────────────────
        context_key = "Opening"
        if context:
            if isinstance(context, str):
                context = [context]
            ctx_str = " ".join(str(c) for c in context)
            for key in _PRIMARY_CONTEXT_KEYS:
                if key in ctx_str:
                    context_key = key
                    break

        return generate(context_key, mood=mood, facts=facts, language=language)

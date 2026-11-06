"""Keyword matching for SenseVoice text output.

The old MaixCAM-Pro KWS registered tone-labelled pinyin keywords
(chang1/chang2/chang4, chun1/chun2/chun3, ang1/ang2, chang2 chun1).
SenseVoice returns Chinese text without tone labels, so the same vocabulary is
represented by character families plus Chinese aliases.  The original pinyin
names remain in the config as metadata for logs and compatibility.
"""

from __future__ import annotations

import json
from pathlib import Path


def normalize_text(text: str) -> str:
    """Keep letters/digits/CJK characters and drop punctuation/space."""
    return "".join(ch.lower() for ch in text if ch.isalnum())


def load_config(path: str | Path) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def match_text(text: str, config: dict) -> dict:
    normalized = normalize_text(text)
    result = {
        "text": text,
        "normalized": normalized,
        "matches": [],
        "gate": False,
        "glyph_mask": 0,
        "reason": "no-match",
    }
    if not normalized:
        return result

    phrase = config.get("phrase", {})
    for alias in phrase.get("aliases", []):
        if normalize_text(alias) and normalize_text(alias) in normalized:
            result["matches"].append({
                "type": "phrase",
                "id": phrase.get("id", "phrase"),
                "display": phrase.get("display", ""),
                "matched": alias,
            })
            result["gate"] = bool(config.get("gate", {}).get("phrase_only", True))
            result["glyph_mask"] = int(phrase.get("glyph_mask", 3))
            result["reason"] = "phrase"
            return result

    families = config.get("char_families", {})
    present: list[str] = []
    for family, spec in families.items():
        for alias in spec.get("aliases", []):
            alias_norm = normalize_text(alias)
            if alias_norm and alias_norm in normalized:
                result["matches"].append({
                    "type": "char",
                    "family": family,
                    "display": spec.get("display", ""),
                    "matched": alias,
                    "registered_keywords": list(spec.get("registered_keywords", [])),
                })
                present.append(family)
                break

    if "chang" in present and "chun" in present:
        result["gate"] = True
        result["glyph_mask"] = int(config.get("phrase", {}).get("glyph_mask", 3))
        result["reason"] = "chang+chun"
    elif present:
        result["reason"] = "+".join(present)

    return result

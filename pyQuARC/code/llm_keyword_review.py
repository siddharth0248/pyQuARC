"""
Optional OpenAI-based review of deposit keywords against title + abstract.
Uses NASA SMD vocabulary (schemas/nasa_smd_keywords.json) for replacement suggestions.
Loads API key from environment (.env optional; see repo root).
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]
_SCHEMAS = Path(__file__).resolve().parents[1] / "schemas"
_NASA_SMD_VOCAB_PATH = _SCHEMAS / "nasa_smd_keywords.json"


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")
    load_dotenv()


def _load_nasa_smd_vocab() -> Tuple[List[str], Dict[str, str]]:
    """Returns (ordered_terms, lower_case -> canonical spelling)."""
    try:
        data = json.loads(_NASA_SMD_VOCAB_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("Could not load NASA SMD vocabulary: %s", exc)
        return [], {}
    raw = data.get("nasa_smd_keywords") or []
    ordered: List[str] = []
    lower_map: Dict[str, str] = {}
    for item in raw:
        if not isinstance(item, str):
            continue
        s = item.strip()
        if not s:
            continue
        ordered.append(s)
        lower_map[s.lower()] = s
    return ordered, lower_map


def _strip_html(text: Optional[str]) -> str:
    if text is None:
        return ""
    plain = re.sub(r"<[^>]+>", " ", str(text))
    return re.sub(r"\s+", " ", plain).strip()


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (list, tuple)) and value:
        return _as_text(value[0])
    return str(value).strip()


def _normalize_keywords(raw: Any) -> List[str]:
    if raw is None:
        return []
    if isinstance(raw, str):
        s = raw.strip()
        return [s] if s else []
    if isinstance(raw, list):
        out: List[str] = []
        for item in raw:
            if isinstance(item, str):
                if item.strip():
                    out.append(item.strip())
            elif isinstance(item, dict):
                v = item.get("subject") or item.get("name") or item.get("value")
                if v and str(v).strip():
                    out.append(str(v).strip())
        return out
    return []


def _filter_suggestions(raw: Any, lower_map: Dict[str, str], limit: int = 8) -> List[str]:
    out: List[str] = []
    if not lower_map or not isinstance(raw, list):
        return out
    for x in raw:
        if x is None:
            continue
        k = str(x).strip()
        canon = lower_map.get(k.lower())
        if canon and canon not in out:
            out.append(canon)
        if len(out) >= limit:
            break
    return out


def _parse_llm_json(content: str) -> dict:
    content = content.strip()
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            return json.loads(content[start : end + 1])
        raise


def review_keywords_against_record(
    title: Any, description: Any, keywords: Any
) -> dict:
    """
    Returns pyQuARC check shape, optionally with ``smd_suggestions`` (passed through
    by ``CustomChecker``) when ``valid`` is True.
    """
    _load_env()

    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        logger.info("keywords LLM check skipped: OPENAI_API_KEY not set")
        return {"valid": None, "value": None}

    title_s = _as_text(title)
    abstract_s = _strip_html(_as_text(description))
    kw_list = _normalize_keywords(keywords)
    vocab, lower_map = _load_nasa_smd_vocab()

    if not kw_list:
        return {"valid": True, "value": None}
    if not title_s and not abstract_s:
        return {"valid": True, "value": None}

    model = (os.environ.get("PYQUARC_LLM_MODEL") or "gpt-4o-mini").strip()

    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai package not installed; skipping keywords LLM check")
        return {"valid": None, "value": None}

    client = OpenAI(api_key=api_key, timeout=60.0)

    system = (
        "You validate metadata keywords for a repository record. "
        "You are given a controlled vocabulary list nasa_smd_keywords_allowed — "
        "every entry in suggested_keywords MUST be copied exactly from that list "
        "(same spelling and capitalization). Do not invent new phrases. "
        "Given TITLE, ABSTRACT (plain text), and the depositor KEYWORDS: "
        "(1) List unsupported_keywords that are NOT reasonably supported by the title "
        "and abstract (off-topic, too vague alone, contradictory, or jargon not reflected "
        "in the text). Be conservative. "
        "(2) suggested_keywords: 1–8 terms from nasa_smd_keywords_allowed only — "
        "prefer terms that replace or narrow weak keywords, or that add discoverability "
        "for this record. Omit terms the record already uses verbatim. "
        "Respond with JSON only, no markdown."
    )
    user_payload = {
        "title": title_s,
        "abstract": abstract_s,
        "keywords": kw_list,
        "nasa_smd_keywords_allowed": vocab,
        "schema": {
            "unsupported_keywords": ["string"],
            "brief_rationale": "string",
            "suggested_keywords": ["string (exactly from nasa_smd_keywords_allowed)"],
        },
    }

    try:
        completion = client.chat.completions.create(
            model=model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {
                    "role": "user",
                    "content": json.dumps(user_payload, ensure_ascii=False),
                },
            ],
        )
        raw = completion.choices[0].message.content or "{}"
        parsed = _parse_llm_json(raw)
    except Exception as exc:
        logger.warning("keywords LLM check failed: %s", exc)
        return {"valid": True, "value": None}

    bad: Sequence[Union[str, Any]] = parsed.get("unsupported_keywords") or []
    rationale = (parsed.get("brief_rationale") or "").strip()
    raw_suggestions = parsed.get("suggested_keywords") or []
    sug = _filter_suggestions(raw_suggestions, lower_map, limit=8)

    # Drop suggestions identical to existing user keywords (case-insensitive)
    kw_lower = {k.lower() for k in kw_list}
    sug = [s for s in sug if s.lower() not in kw_lower]

    cleaned: List[str] = []
    for k in bad:
        if k is None:
            continue
        s = str(k).strip()
        if s and s not in cleaned:
            cleaned.append(s)

    if not cleaned:
        out: dict = {"valid": True, "value": None}
        if sug:
            out["smd_suggestions"] = sug
        return out

    summary = (
        "Keywords that do not appear well supported by the title and abstract: "
        f"{', '.join(cleaned)}."
    )
    if rationale:
        summary += f" {rationale}"
    if sug:
        summary += f" Suggested from NASA SMD vocabulary: {', '.join(sug)}."

    return {
        "valid": False,
        "value": (summary,),
        "severity": "warning",
    }

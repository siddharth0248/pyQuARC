"""
Preview which Zenodo metadata fields could be filled from metadata.description
(LLM + optional baseline gap scan). Does not modify the record.
"""

from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[2]

ZENODO_EXTRACTION_TARGETS = """
Target paths (use these exact zenodo_path strings in output):

Top-level metadata:
- metadata/keywords — JSON array of NEW keyword strings not already in metadata.keywords
- metadata/version — string, only if description implies a version not already set
- metadata/language — ISO 639-3 (e.g. eng) if clearly inferable

Custom block (metadata/custom in record; use full path below):
- metadata/custom/nasa:platform — SINGLE object for host/satellite/platform, shape:
  {"id": "lowercase_id", "title": {"en": "Display name"}}
  Example: Terra → {"id": "terra", "title": {"en": "Terra"}}
- metadata/custom/nasa:instrument — ARRAY of objects with same id/title shape
- metadata/custom/nasa:mission — ARRAY of objects with same id/title shape
- metadata/custom/nasa:spatial_resolution — string (e.g. "1 km", "0.25 deg") from prose
- metadata/custom/nasa:temporal_resolution — object {"id": "daily", "title": {"en": "Daily"}} when cadence is stated
- metadata/custom/nasa:spatial_reference_type — object when CRS/geographic framing is clear
- metadata/custom/nasa:access_constraints — short string if policy language appears
- metadata/custom/nasa:use_constraints — string if usage restrictions appear
- metadata/custom/nasa:access_url — data-access URL if explicitly stated in prose
- metadata/custom/code:codeRepository — repo URL only if explicitly in prose

Rules:
- Prefer filling EMPTY or {} fields shown in current_metadata_subset before re-suggesting populated ones.
- Do not echo existing keyword strings into metadata/keywords; only add net-new terms grounded in description.
- For nested custom values, suggested_value MUST be JSON object/array matching the shapes above, not English prose.
""".strip()

FIELD_SHAPE_CHEATSHEET = """
Minimal valid examples (copy style, adapt ids from description):
  "nasa:platform": {"id": "terra", "title": {"en": "Terra"}}
  "nasa:instrument": [{"id": "modis", "title": {"en": "MODIS"}}]
  "nasa:mission": [{"id": "terra", "title": {"en": "Terra"}}]
""".strip()


def _refine_extractable(parsed: dict, metadata: Dict[str, Any]) -> dict:
    """Drop keyword rows that only duplicate existing metadata.keywords."""
    existing_kw = {
        str(k).lower().strip()
        for k in (metadata.get("keywords") or [])
        if isinstance(k, str) and k.strip()
    }
    ext = list(parsed.get("extractable_now") or [])
    new_ext: List[dict] = []
    for raw_item in ext:
        if not isinstance(raw_item, dict):
            continue
        item = dict(raw_item)
        path = (item.get("zenodo_path") or "").strip()
        val = item.get("suggested_value")
        if path == "metadata/keywords":
            if isinstance(val, list):
                filtered = [
                    str(x).strip()
                    for x in val
                    if x is not None
                    and str(x).strip()
                    and str(x).lower().strip() not in existing_kw
                ]
                if not filtered:
                    continue
                item["suggested_value"] = filtered
            elif isinstance(val, str):
                s = val.strip()
                if not s or s.lower() in existing_kw:
                    continue
            else:
                continue
        new_ext.append(item)
    out = dict(parsed)
    out["extractable_now"] = new_ext
    return out


def _format_suggested_value(val: Any) -> str:
    if isinstance(val, (dict, list)):
        return json.dumps(val, ensure_ascii=False, indent=2)
    return repr(val)


def _load_env() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    load_dotenv(ROOT / ".env")
    load_dotenv()


def strip_html(text: Optional[str]) -> str:
    if not text:
        return ""
    plain = re.sub(r"<[^>]+>", " ", str(text))
    return re.sub(r"\s+", " ", plain).strip()


def _baseline_empty_fields(metadata: Dict[str, Any]) -> List[Tuple[str, str]]:
    """Return (path, note) for fields that look empty and might be inferable from text."""
    out: List[Tuple[str, str]] = []
    checks: List[Tuple[str, Callable[[], Any]]] = [
        ("metadata/keywords", lambda: metadata.get("keywords")),
        ("metadata/version", lambda: metadata.get("version")),
        ("metadata/language", lambda: metadata.get("language")),
    ]
    custom = metadata.get("custom") or {}
    if isinstance(custom, dict):
        checks.extend(
            [
                (
                    "metadata/custom/nasa:access_constraints",
                    lambda: custom.get("nasa:access_constraints"),
                ),
                (
                    "metadata/custom/nasa:use_constraints",
                    lambda: custom.get("nasa:use_constraints"),
                ),
                ("metadata/custom/nasa:platform", lambda: custom.get("nasa:platform")),
                (
                    "metadata/custom/nasa:instrument",
                    lambda: custom.get("nasa:instrument"),
                ),
                (
                    "metadata/custom/nasa:spatial_resolution",
                    lambda: custom.get("nasa:spatial_resolution"),
                ),
                (
                    "metadata/custom/nasa:temporal_resolution",
                    lambda: custom.get("nasa:temporal_resolution"),
                ),
                (
                    "metadata/custom/nasa:spatial_reference_type",
                    lambda: custom.get("nasa:spatial_reference_type"),
                ),
                (
                    "metadata/custom/nasa:access_url",
                    lambda: custom.get("nasa:access_url"),
                ),
                (
                    "metadata/custom/code:codeRepository",
                    lambda: custom.get("code:codeRepository"),
                ),
            ]
        )

    def empty(v: Any) -> bool:
        if v is None:
            return True
        if isinstance(v, str) and not v.strip():
            return True
        if isinstance(v, (list, dict)) and len(v) == 0:
            return True
        return False

    for path, getter in checks:
        try:
            v = getter()
        except Exception:
            v = None
        if empty(v):
            out.append((path, "Currently empty or missing — may be inferable from a richer description."))
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


def _normalize_llm_preview_dict(parsed: Any) -> dict:
    if not isinstance(parsed, dict):
        return {}
    out = dict(parsed)
    # camelCase alternatives (some models)
    if "extractable_now" not in out and "extractableNow" in out:
        out["extractable_now"] = out.pop("extractableNow")
    if "needs_richer_description" not in out and "needsRicherDescription" in out:
        out["needs_richer_description"] = out.pop("needsRicherDescription")
    for key in ("extractable_now", "needs_richer_description", "general_tips"):
        v = out.get(key)
        if v is None:
            out[key] = []
        elif isinstance(v, dict):
            out[key] = [v]
        elif not isinstance(v, list):
            out[key] = [v]
    clean_extract: List[dict] = []
    for item in out.get("extractable_now") or []:
        if isinstance(item, dict) and item.get("zenodo_path"):
            clean_extract.append(item)
    out["extractable_now"] = clean_extract
    return out


def _fill_description_assessment(
    parsed: dict, description_plain: str
) -> None:
    n = len(description_plain.strip())
    if not parsed.get("description_quality") or str(parsed.get("description_quality")).lower() in (
        "unknown",
        "",
    ):
        if n < 80:
            parsed["description_quality"] = "thin"
        elif n < 300:
            parsed["description_quality"] = "adequate"
        else:
            parsed["description_quality"] = "rich"
    parsed["description_length_chars"] = n


def _heuristic_extractable_when_llm_empty(
    metadata: Dict[str, Any], description_plain: str
) -> List[dict]:
    """
    When the model returns no rows, propose obvious mappings from prose so the
    preview is still actionable (esp. empty nasa:platform {}).
    """
    desc_l = description_plain.lower()
    custom = metadata.get("custom") if isinstance(metadata.get("custom"), dict) else {}
    rows: List[dict] = []

    def plat_empty() -> bool:
        v = custom.get("nasa:platform")
        return v is None or v == {} or v == []

    if plat_empty():
        if "terra" in desc_l and "modis" in desc_l:
            rows.append(
                {
                    "zenodo_path": "metadata/custom/nasa:platform",
                    "suggested_value": {"id": "terra", "title": {"en": "Terra"}},
                    "confidence": "high",
                    "evidence": "Rule-based: description references MODIS on Terra.",
                }
            )
        elif "aqua" in desc_l and "modis" in desc_l:
            rows.append(
                {
                    "zenodo_path": "metadata/custom/nasa:platform",
                    "suggested_value": {"id": "aqua", "title": {"en": "Aqua"}},
                    "confidence": "high",
                    "evidence": "Rule-based: description references MODIS on Aqua.",
                }
            )
        elif "suomi" in desc_l or "snpp" in desc_l or "viirs" in desc_l:
            rows.append(
                {
                    "zenodo_path": "metadata/custom/nasa:platform",
                    "suggested_value": {
                        "id": "suomi_npp",
                        "title": {"en": "Suomi NPP"},
                    },
                    "confidence": "medium",
                    "evidence": "Rule-based: description references SNPP / VIIRS / Suomi.",
                }
            )

    existing_kw = {
        str(k).lower().strip()
        for k in (metadata.get("keywords") or [])
        if isinstance(k, str) and k.strip()
    }
    extra_kw: List[str] = []
    for term, label in (
        ("aerosol", "Aerosols"),
        ("optical depth", "Atmospheric Science"),
        ("level-3", "Earth Observation Data"),
        ("level 3", "Earth Observation Data"),
        ("radiative forcing", "Climate Change"),
        ("air quality", "Air Quality"),
        ("1km", "Geospatial Data"),
        ("1 km", "Geospatial Data"),
    ):
        if term in desc_l:
            if label.lower() not in existing_kw and label not in extra_kw:
                extra_kw.append(label)
    if extra_kw:
        rows.append(
            {
                "zenodo_path": "metadata/keywords",
                "suggested_value": extra_kw[:6],
                "confidence": "medium",
                "evidence": "Rule-based: terms inferred from description (not already in keywords).",
            }
        )

    spatial_ref_empty = custom.get("nasa:spatial_reference_type") in (None, {}, [])
    if spatial_ref_empty and (
        "global" in desc_l or "worldwide" in desc_l or "-180" in desc_l or "geographic" in desc_l
    ):
        rows.append(
            {
                "zenodo_path": "metadata/custom/nasa:spatial_reference_type",
                "suggested_value": {"id": "geographic", "title": {"en": "Geographic"}},
                "confidence": "medium",
                "evidence": "Rule-based: global / geographic coverage implied in description.",
            }
        )

    return rows


def run_llm_preview(
    title: str,
    description_plain: str,
    metadata_snapshot: Dict[str, Any],
    metadata: Dict[str, Any],
) -> Optional[dict]:
    _load_env()
    api_key = (os.environ.get("OPENAI_API_KEY") or "").strip()
    if not api_key:
        return None
    try:
        from openai import OpenAI
    except ImportError:
        logger.warning("openai not installed")
        return None

    model = (os.environ.get("PYQUARC_LLM_MODEL") or "gpt-4o-mini").strip()
    client = OpenAI(api_key=api_key, timeout=90.0)

    empty_or_weak = [path for path, _ in _baseline_empty_fields(metadata)]

    output_contract = (
        "Reply with one JSON object with these exact keys (use arrays; use [] if none): "
        '"description_quality" (thin|adequate|rich), '
        '"description_length_chars" (integer), '
        '"extractable_now" (array of {zenodo_path, suggested_value, confidence, evidence}), '
        '"needs_richer_description" (array of {zenodo_path, what_to_add}), '
        '"general_tips" (array of strings). '
        "If empty_or_weak_fields is non-empty and description has enough detail, extractable_now "
        "must include at least one grounded entry (e.g. fill metadata/custom/nasa:platform when "
        "Terra/MODIS appears and platform is empty in current_metadata_subset)."
    )

    system = (
        "You map dataset abstracts into Zenodo metadata updates. Reply with JSON only (no markdown).\n"
        + output_contract
        + "\n\nRules:\n"
        "1) For metadata/custom/nasa:* entries, suggested_value MUST be JSON (object or array of objects) "
        "with id (lowercase snake) and title.en.\n"
        "2) Prefer filling items listed in empty_or_weak_fields when the description supports them.\n"
        "3) metadata/keywords: only NEW keywords not already in current_metadata_subset.keywords.\n"
        "4) Do not invent URLs unless they appear verbatim in title or description.\n"
        "Example extractable_now item:\n"
        '{"zenodo_path":"metadata/custom/nasa:platform","suggested_value":{"id":"terra","title":{"en":"Terra"}},'
        '"confidence":"high","evidence":"MODIS Terra Level-3 dataset"}\n'
    )

    user_obj = {
        "instruction": output_contract,
        "title": title,
        "description_plain_text": description_plain,
        "current_metadata_subset": metadata_snapshot,
        "empty_or_weak_fields": empty_or_weak,
        "paths_and_shapes_reference": ZENODO_EXTRACTION_TARGETS,
        "json_shape_cheatsheet": FIELD_SHAPE_CHEATSHEET,
    }

    completion = client.chat.completions.create(
        model=model,
        temperature=0.2,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(user_obj, ensure_ascii=False)},
        ],
    )
    raw = completion.choices[0].message.content or "{}"
    parsed = _normalize_llm_preview_dict(_parse_llm_json(raw))
    _fill_description_assessment(parsed, description_plain)
    parsed = _refine_extractable(parsed, metadata)
    if not (parsed.get("extractable_now") or []) and len(description_plain.strip()) >= 80:
        fb = _heuristic_extractable_when_llm_empty(metadata, description_plain)
        if fb:
            parsed["extractable_now"] = fb
            tips = list(parsed.get("general_tips") or [])
            tips.insert(
                0,
                "Included rule-based extractions because the model returned none; verify before applying.",
            )
            parsed["general_tips"] = tips
    return parsed


def build_metadata_snapshot(record: Dict[str, Any]) -> Dict[str, Any]:
    """Small JSON for LLM context (not full record)."""
    md = record.get("metadata") or {}
    snap: Dict[str, Any] = {
        "title": md.get("title"),
        "keywords": md.get("keywords"),
        "version": md.get("version"),
        "language": md.get("language"),
    }
    custom = md.get("custom")
    if isinstance(custom, dict):
        snap["custom"] = {
            k: custom.get(k)
            for k in (
                "nasa:access_constraints",
                "nasa:use_constraints",
                "nasa:platform",
                "nasa:instrument",
                "nasa:mission",
                "nasa:processing_level",
                "nasa:science_topic",
                "nasa:spatial_resolution",
                "nasa:spatial_extents",
                "nasa:temporal_resolution",
                "nasa:temporal_start",
                "nasa:temporal_end",
                "nasa:spatial_reference_type",
                "nasa:access_url",
                "nasa:documentation_url",
                "code:codeRepository",
                "code:programmingLanguage",
            )
            if k in custom
        }
    return snap


def format_preview_report(
    record: Dict[str, Any],
    parsed: Optional[dict],
    baseline_gaps: List[Tuple[str, str]],
) -> str:
    md = record.get("metadata") or {}
    title = (md.get("title") or "").strip()
    raw_desc = md.get("description") or ""
    plain = strip_html(raw_desc)

    lines: List[str] = []
    lines.append("=" * 72)
    lines.append("DESCRIPTION → FIELD MAPPING PREVIEW (no changes applied)")
    lines.append("=" * 72)
    lines.append("")
    lines.append(f"Title (metadata.title): {title or '(empty)'}")
    lines.append(
        f"Description length: {len(plain)} chars (HTML stripped for analysis)."
    )
    if len(plain) < 50:
        lines.append(
            "Note: Very short descriptions rarely support automatic field extraction."
        )
    lines.append("")

    lines.append("-" * 72)
    lines.append("Baseline: empty / missing fields (may be fillable later)")
    lines.append("-" * 72)
    if baseline_gaps:
        for path, note in baseline_gaps:
            lines.append(f"  • {path}")
            lines.append(f"    {note}")
    else:
        lines.append("  (none detected among common NASA custom paths)")
    lines.append("")

    if parsed is None:
        lines.append("-" * 72)
        lines.append("LLM extraction map: skipped")
        lines.append("-" * 72)
        lines.append(
            "  Set OPENAI_API_KEY (e.g. in repo-root .env) and pip install openai "
            "for path-by-path extraction suggestions and richer-description hints."
        )
        lines.append("")
        return "\n".join(lines)

    dq = parsed.get("description_quality") or "unknown"
    dlen = parsed.get("description_length_chars")
    lines.append("-" * 72)
    lines.append("LLM assessment")
    lines.append("-" * 72)
    lines.append(f"  Description quality: {dq}")
    if dlen is not None:
        lines.append(f"  Reported length (chars): {dlen}")
    lines.append("")

    ext = parsed.get("extractable_now") or []
    lines.append("-" * 72)
    lines.append(f"Could map from current description ({len(ext)} suggestion(s))")
    lines.append("-" * 72)
    if not ext:
        lines.append("  (none — model found nothing it would map confidently)")
    else:
        for i, item in enumerate(ext, 1):
            path = item.get("zenodo_path") or "(no path)"
            val = item.get("suggested_value")
            conf = item.get("confidence") or "?"
            ev = item.get("evidence") or ""
            lines.append(f"  {i}. {path}")
            lines.append("     Suggested value:")
            val_fmt = _format_suggested_value(val)
            for ln in val_fmt.splitlines():
                lines.append(f"       {ln}")
            lines.append(f"     Confidence: {conf}")
            if ev:
                lines.append(f"     Evidence: {ev}")
    lines.append("")

    need = parsed.get("needs_richer_description") or []
    lines.append("-" * 72)
    lines.append(
        f"If description were richer, could consider ({len(need)} hint(s))"
    )
    lines.append("-" * 72)
    if not need:
        lines.append("  (no extra hints)")
    else:
        for i, item in enumerate(need, 1):
            path = item.get("zenodo_path") or "(no path)"
            what = item.get("what_to_add") or ""
            lines.append(f"  {i}. {path}")
            if what:
                lines.append(f"     Add to description: {what}")
    lines.append("")

    tips = parsed.get("general_tips") or []
    if tips:
        lines.append("-" * 72)
        lines.append("General tips")
        lines.append("-" * 72)
        for t in tips:
            lines.append(f"  • {t}")
        lines.append("")

    lines.append("=" * 72)
    lines.append("Next step: auto-fill is not enabled yet; use this report to edit JSON.")
    lines.append("=" * 72)
    return "\n".join(lines)


def preview_zenodo_record(record: Dict[str, Any]) -> str:
    md = record.get("metadata") or {}
    title = (md.get("title") or "").strip()
    plain = strip_html(md.get("description") or "")
    snap = build_metadata_snapshot(record)
    baseline = _baseline_empty_fields(md)
    llm = run_llm_preview(title, plain, snap, md)
    if llm is None and len(plain.strip()) >= 40:
        fb = _heuristic_extractable_when_llm_empty(md, plain)
        if fb:
            llm = _normalize_llm_preview_dict(
                {
                    "extractable_now": fb,
                    "needs_richer_description": [],
                    "general_tips": [
                        "Rule-based preview only; set OPENAI_API_KEY for full LLM-assisted mapping."
                    ],
                }
            )
            _fill_description_assessment(llm, plain)
            llm = _refine_extractable(llm, md)
    return format_preview_report(record, llm, baseline)

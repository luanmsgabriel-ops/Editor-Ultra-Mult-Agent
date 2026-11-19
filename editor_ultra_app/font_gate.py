"""Reusable font validation for independent Editor Ultra reconstructions."""
from hashlib import sha256
from io import BytesIO
import re
import unicodedata
from fontTools.ttLib import TTFont

ENGINE_FORMATS = {".ttf": b"\x00\x01\x00\x00", ".otf": b"OTTO"}
ASSET_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")
MAX_FONT_BYTES = 8 * 1024 * 1024


class FontGateError(ValueError):
    """Short failure code, with no paths or font bytes."""


def select_fonts(pack, selected_text, resolve_asset):
    """Validate hash, coverage, provenance and review. No fallback or path inputs.

    selected_text maps a typography role to text to be rendered. resolve_asset is
    an engine-owned asset-ID lookup, yielding bytes for the current project only.
    """
    if not isinstance(pack, dict) or pack.get("schema") != "editor-ultra-font-pack/1":
        raise FontGateError("font_manifest_invalid")
    refs = pack.get("styles")
    if not isinstance(refs, dict) or not isinstance(selected_text, dict) or not selected_text:
        raise FontGateError("font_styles_invalid")
    selected = {}
    for role, text in selected_text.items():
        item = refs.get(role)
        if not isinstance(item, dict) or not isinstance(text, str):
            raise FontGateError("font_style_missing")
        if (item.get("source_kind") not in ("licensed_original", "authorized_reconstruction", "original_approximation")
                or item.get("rights_status") != "reuse_verified" or not isinstance(item.get("provenance_note"), str) or not item["provenance_note"].strip()
                or item.get("visual_review") != "approved"):
            raise FontGateError("font_rights_or_review_pending")
        if item.get("source_kind") != "licensed_original" and item.get("claims_exact_original") is not False:
            raise FontGateError("font_identity_claim_invalid")
        asset_id = item.get("font_asset_id")
        name = item.get("format")
        fmt = ENGINE_FORMATS.get(name) if isinstance(name, str) else None
        if not isinstance(asset_id, str) or not ASSET_ID.fullmatch(asset_id) or not fmt:
            raise FontGateError("font_asset_invalid")
        payload = resolve_asset(asset_id)
        if not isinstance(payload, bytes) or len(payload) > MAX_FONT_BYTES or not payload.startswith(fmt):
            raise FontGateError("font_binary_invalid")
        if sha256(payload).hexdigest() != item.get("sha256"):
            raise FontGateError("font_hash_mismatch")
        try:
            with TTFont(BytesIO(payload), lazy=True) as font:
                if "fvar" in font:
                    raise FontGateError("font_requires_static_instance")
                cmap = font.getBestCmap() or {}
        except FontGateError:
            raise
        except Exception as exc:
            raise FontGateError("font_binary_unreadable") from exc
        normalized = unicodedata.normalize("NFC", text)
        needed = {ord(ch) for ch in normalized if ch not in "\r\n\t"}
        missing = sorted(x for x in needed if not cmap.get(x) or cmap[x] == ".notdef")
        if missing:
            raise FontGateError("font_glyph_missing:" + ",".join(f"U+{i:04X}" for i in missing))
        selected[role] = {"font_asset_id": asset_id, "sha256": item["sha256"], "text": normalized}
    return selected


def typography_texts(compiled):
    """Use only the text the renderer uses, grouped by actual renderer font role."""
    titles, subtitles = [], []
    for decision in compiled["decisions"]:
        effect = decision["effect_id"]
        if effect not in {"native.kinetic_type", "native.body_orbit"}:
            continue
        operation = decision.get("operation")
        if operation is None:
            continue
        params = operation["params"]
        titles.append(params["title"])
        if effect == "native.kinetic_type" and params.get("subtitle"):
            subtitles.append(params["subtitle"])
    texts = {}
    if titles:
        texts["font"] = "\n".join(titles)
    if subtitles:
        texts["script_font"] = "\n".join(subtitles)
    return texts

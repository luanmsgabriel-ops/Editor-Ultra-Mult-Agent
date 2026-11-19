from hashlib import sha256
from io import BytesIO
from unittest import TestCase
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from editor_ultra_app.font_gate import FontGateError, select_fonts, typography_texts


def fixture():
    b = FontBuilder(1000, isTTF=True)
    glyphs = [".notdef", "space", "A", "Aacute"]
    b.setupGlyphOrder(glyphs)
    b.setupCharacterMap({32: "space", 65: "A", 193: "Aacute"})
    b.setupGlyf({g: TTGlyphPen(None).glyph() for g in glyphs})
    b.setupHorizontalMetrics({g: (500, 0) for g in glyphs})
    b.setupHorizontalHeader(ascent=800, descent=-200)
    b.setupNameTable({"familyName": "Specimen Test", "styleName": "Regular"})
    b.setupOS2()
    b.setupPost()
    f = BytesIO()
    b.save(f)
    return f.getvalue()


class FontGateTest(TestCase):
    def setUp(self):
        self.data = fixture()
        self.item = dict(font_asset_id="fixture", format=".ttf", sha256=sha256(self.data).hexdigest(),
                         source_kind="original_approximation", provenance_note="synthetic test",
                         rights_status="reuse_verified", visual_review="approved", claims_exact_original=False)
        self.pack = dict(schema="editor-ultra-font-pack/1", styles={"headline": self.item})
    def run_gate(self, text="A Á"):
        return select_fonts(self.pack, {"headline": text}, lambda key: self.data)
    def test_nfc_and_matching_hash(self):
        self.assertEqual(self.run_gate("A A\u0301")["headline"]["text"], "A Á")
    def test_missing_az(self):
        with self.assertRaisesRegex(FontGateError, "font_glyph_missing:U\\+005A"):
            self.run_gate("AZ")
    def test_stale_font(self):
        self.item["sha256"] = "0" * 64
        with self.assertRaisesRegex(FontGateError, "font_hash_mismatch"):
            self.run_gate()
    def test_rights_pending(self):
        self.item["rights_status"] = "pending"
        with self.assertRaisesRegex(FontGateError, "font_rights_or_review_pending"):
            self.run_gate()
    def test_approximation_is_not_original(self):
        self.item["claims_exact_original"] = True
        with self.assertRaisesRegex(FontGateError, "font_identity_claim_invalid"):
            self.run_gate()

    def test_compiled_renderer_contract(self):
        plan = {"decisions": [
            {"effect_id": "native.kinetic_type", "operation": None},
            {"effect_id": "native.kinetic_type",
             "operation": {"params": {"title": "Á", "subtitle": "A"}}},
            {"effect_id": "native.body_orbit",
             "operation": {"params": {"title": "AA", "subtitle": "not rendered"}}},
            {"effect_id": "native.overlay", "operation": {"params": {"title": "not rendered"}}},
        ]}
        self.assertEqual(typography_texts(plan), {"font": "Á\nAA", "script_font": "A"})
        self.assertEqual(typography_texts({"decisions": []}), {})

    def test_malformed_format_fails_closed(self):
        self.item["format"] = []
        with self.assertRaisesRegex(FontGateError, "font_asset_invalid"):
            self.run_gate()

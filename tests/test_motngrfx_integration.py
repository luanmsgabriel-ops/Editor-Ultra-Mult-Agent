"""CPU render proofs for geometry, clock preservation and strict matte order.

Synthetic source/matte data only; no private media or bundled font assets.
"""
from copy import deepcopy
from fractions import Fraction
import json
from pathlib import Path
import shutil
import subprocess

import numpy as np
from PIL import Image
import pytest

from editorial_engine.contracts import ValidationError, file_sha256
from editorial_engine import motngrfx as motion


@pytest.fixture(scope="module")
def font_path():
    if not shutil.which("fc-match"):
        pytest.skip("Fontconfig is needed to locate a licensed system test font")
    path = subprocess.run(["fc-match", "-f", "%{file}", "DejaVu Sans"], capture_output=True, text=True, check=True).stdout
    if not Path(path).is_file():
        pytest.skip("No system font is available")
    return path


def spec(module="rotate", n=12):
    return {"schema": motion.SCHEMA, "text": "AÓ", "fps": "24/1", "frame_count": n,
            "width": 192, "height": 128, "font_size": 42, "extrusion_px": 9,
            "center": [0.5, 0.5], "color": [240, 220, 150], "side_color": [90, 40, 20],
            "animation": {"module": module, "keyframes": [
                {"frame": 0, "rotation_deg": [-25, 8, -3]},
                {"frame": n-1, "rotation_deg": [25, 8, 3]}]}}


@pytest.fixture(scope="module")
def rendered_sequence(tmp_path_factory, font_path):
    target = tmp_path_factory.mktemp("motngrfx-sequence")/"frames"
    return motion.render_sequence(spec(), target, font_path=font_path,
                                  font_license="DejaVu system font; license in the OS package; not redistributed")


def write_video(path, frames, fps="24/1"):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg/FFprobe are required for the encoded render proof")
    height, width = frames[0].shape[:2]
    p = subprocess.run(["ffmpeg", "-v", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
                        "-s", f"{width}x{height}", "-r", fps, "-i", "pipe:0", "-c:v", "ffv1",
                        "-level", "3", "-pix_fmt", "bgr0", str(path)],
                       input=b"".join(x.tobytes() for x in frames), capture_output=True)
    assert p.returncode == 0, p.stderr.decode()


def footage(tmp_path, n=12, fps="24/1"):
    y, x = np.mgrid[:128, :192]
    images = []
    for index in range(n):
        bg = np.stack([25+x//3, 35+y//2, np.full_like(x, 70 if index < n//2 else 120)], 2).astype(np.uint8)
        bg[:8, :16] = index*13
        bg[63:67] = [38, 110, 80]  # synthetic moving-picture subject region
        images.append(bg)
    source = tmp_path/"source.mkv"
    write_video(source, images, fps)
    mask = np.zeros((128, 192), np.uint8)
    mask[63:67] = 255
    masks = []
    for index in range(n):
        path = tmp_path/f"matte-{index:06d}.png"
        Image.fromarray(mask).save(path)
        masks.append({"index": index, "path": str(path), "sha256": file_sha256(path)})
    return source, images, {"source_sha256": file_sha256(source), "clock": "source", "fps": fps,
                            "frame_count": n, "width": 192, "height": 128, "frames": masks}


def test_real_extrusion_rotates_and_retains_straight_alpha(rendered_sequence):
    m = motion.validate_manifest(rendered_sequence)
    a = np.asarray(Image.open(m["frames"][0]["path"]))
    b = np.asarray(Image.open(m["frames"][-1]["path"]))
    assert not np.array_equal(a, b)
    assert a[..., 3].max() == 255 and np.any(a[..., 3] == 0)
    assert np.all(a[a[..., 3] == 0, :3] == 0)
    assert np.any((a[..., 0] < 120) & (a[..., 3] > 0))  # shaded extrusion walls
    assert "side walls" in m["geometry"]
    assert [g["char"] for g in m["glyphs"]] == ["A", "Ó"]
    assert m["perceptual_review"] == "unverified" and not m["user_approved"]


def test_hinge_uses_its_own_real_mechanic_and_seekable_frames(tmp_path, font_path):
    d = spec("hinge_unfold", 14)
    d["animation"]["hinge_frames"] = 8
    m = motion.render_sequence(d, tmp_path/"hinge", font_path=font_path, font_license="System DejaVu test font")
    normalized = motion.validate_spec(d)
    glyphs = motion._glyphs(normalized, font_path)
    # Seeking to a frame yields exactly the exported bytes, without state advance.
    expected, _, _ = motion._frame(normalized, glyphs, 5)
    actual = np.asarray(Image.open(m["frames"][5]["path"]))
    assert np.array_equal(expected, actual)
    assert not np.array_equal(actual, np.asarray(Image.open(m["frames"][-1]["path"])))
    assert m["spec"]["read_window"]["start_frame"] == 8


def test_compositor_preserves_source_and_behind_order(rendered_sequence):
    layer, ids = motion._load_layer(rendered_sequence["frames"][0])
    source = np.full((128, 192, 3), [20, 70, 120], np.uint8)
    matte = np.zeros((128, 192), np.uint8)
    matte[63:67] = 255
    result, report = motion.composite_frame(source, layer, mode="behind", matte=matte,
                                            glyph_ids=ids, min_glyph_visible=.2, min_visible=.5, min_occluded=.01)
    assert 0 < report["occluded"] < .5
    assert np.array_equal(result[matte == 255], source[matte == 255])
    assert np.array_equal(result[layer[..., 3] == 0], source[layer[..., 3] == 0])
    assert not report["order_changed"] and not report["effect_dropped"]


@pytest.mark.parametrize("matte,code", [(None, "matte_missing"),
                                      (np.ones((128, 192), np.float32), "type_legibility"),
                                      (np.zeros((128, 192), np.float32), "occlusion_missing")])
def test_impossible_behind_is_an_error_never_a_front_fallback(rendered_sequence, matte, code):
    layer, ids = motion._load_layer(rendered_sequence["frames"][0])
    with pytest.raises(ValidationError) as failure:
        motion.composite_frame(np.zeros((128, 192, 3), np.uint8), layer, mode="behind", matte=matte, min_occluded=.01, glyph_ids=ids)
    assert failure.value.issues[0]["code"] == code


def test_real_cpu_render_preserves_clock_picture_cut_and_mask(tmp_path, rendered_sequence):
    source, _, matte = footage(tmp_path)
    before = file_sha256(source)
    report = motion.render_on_video(source, tmp_path/"behind.mkv", rendered_sequence, mode="behind",
                                    matte=matte, cut_frames=[6], min_visible=.5, min_glyph_visible=.2)
    assert file_sha256(source) == before
    assert report["all_frames_compared"] == 12 and report["pixel_error_max"] == 0
    assert report["cut_frames"] == [6] and report["cut_frame_identity_verified"]
    assert any(x["occluded"] > 0 for x in report["occlusion"])
    assert (tmp_path/"behind.mkv.review.json").is_file()
    assert report["perceptual_motion"] == "unverified"


def test_wrong_cut_or_order_is_detected_on_actual_video(tmp_path, rendered_sequence):
    source, frames, _ = footage(tmp_path)
    correctly_composed = []
    for i, frame in enumerate(frames):
        layer, ids = motion._load_layer(rendered_sequence["frames"][i])
        correctly_composed.append(motion.composite_frame(frame, layer, glyph_ids=ids)[0])
    wrongly_ordered = correctly_composed[:]
    wrongly_ordered[5], wrongly_ordered[6] = wrongly_ordered[6], wrongly_ordered[5]
    write_video(tmp_path/"wrong.mkv", wrongly_ordered)
    with pytest.raises(ValidationError) as failure:
        motion.verify_render(source, tmp_path/"wrong.mkv", rendered_sequence, cut_frames=[6])
    assert failure.value.issues[0]["code"] == "render_mismatch"
    assert failure.value.issues[0]["path"] == "5"


@pytest.mark.parametrize("field,value,code", [("source_sha256", "0"*64, "matte_source"),
                                           ("fps", "25/1", "matte_clock"),
                                           ("clock", "timeline", "matte_clock")])
def test_matte_identity_and_clock_are_required_before_output(tmp_path, rendered_sequence, field, value, code):
    source, _, matte = footage(tmp_path)
    matte[field] = value
    target = tmp_path/"must-not-exist.mkv"
    with pytest.raises(ValidationError) as failure:
        motion.render_on_video(source, target, rendered_sequence, mode="behind", matte=matte)
    assert failure.value.issues[0]["code"] == code
    assert not target.exists()


def test_missing_glyph_or_unreadable_view_does_not_produce_export(tmp_path, font_path):
    d = spec()
    d["text"] = "\U0010ffff"
    with pytest.raises(ValidationError, match="font_coverage"):
        motion.render_sequence(d, tmp_path/"bad-font", font_path=font_path, font_license="System font")
    d = spec()
    d["animation"]["keyframes"] = [{"frame": 0, "rotation_deg": [90, 0, 0]}]
    with pytest.raises(ValidationError, match="type_edge_on"):
        motion.render_sequence(d, tmp_path/"edge", font_path=font_path, font_license="System font")
    assert not (tmp_path/"edge").exists()


def test_unknown_parameters_and_tampered_manifest_are_rejected(rendered_sequence):
    d = spec()
    d["choose_random_effect"] = True
    with pytest.raises(ValidationError, match="motion_parameter"):
        motion.validate_spec(d)
    changed = deepcopy(rendered_sequence)
    changed["frames"][0]["sha256"] = "0"*64
    with pytest.raises(ValidationError, match="motion_manifest_hash"):
        motion.validate_manifest(changed)


def test_probe_is_cpu_readiness_not_inference_or_render_claim():
    result = motion.probe_motngrfx()
    assert result["device"] == "cpu"
    assert result["modules"] == ["rotate", "hinge_unfold"]
    assert result["model_inference"] is False and result["render_tested"] is False


def test_per_glyph_requirement_cannot_be_claimed_without_ids(rendered_sequence):
    layer, _ = motion._load_layer(rendered_sequence["frames"][0])
    with pytest.raises(ValidationError, match="glyph_evidence_missing"):
        motion.composite_frame(np.zeros((128, 192, 3), np.uint8), layer, min_glyph_visible=.5)

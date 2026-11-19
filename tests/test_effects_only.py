from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil

import pytest

from editorial_engine.effects_only import (
    EffectsError, check_revision, load, render, render_frames, validate,
)

FIXTURE = Path(__file__).resolve().parent.parent / "fixtures/effects-only-synthetic.json"


@pytest.fixture
def plan():
    return load(FIXTURE)


def test_fixture_uses_a_real_analysis_document_digest(plan):
    b = (FIXTURE.parent / "effects-only-synthetic-analysis.txt").read_bytes()
    assert hashlib.sha256(b).hexdigest() == plan["reference"]["sha256"]


def test_render_order_caption_intervals_and_panel_movement(plan):
    frames = list(render_frames(plan))
    c = plan["canvas"]

    def pixel(f, x, y):
        index = (y * c["width"] + x) * 3
        return tuple(frames[f][index:index+3])

    # The teal panel overlaps the pulse and must sit in front of it.
    assert pixel(16, 200, 70) == (35, 146, 165)
    assert pixel(19, 200, 70) == (35, 146, 165)
    assert pixel(20, 200, 70) != (35, 146, 165)
    assert pixel(0, 8, 58) == (35, 146, 165)
    assert pixel(19, 8, 58) == (25, 36, 52)

    no_caption = deepcopy(plan)
    no_caption["effects"] = no_caption["effects"][:2]
    assert [i for i, (a,b) in enumerate(zip(frames, render_frames(no_caption))) if a != b] == list(range(17,43))

    backwards = deepcopy(plan)
    backwards["effects"].reverse()
    assert list(render_frames(backwards)) == frames


@pytest.mark.parametrize("break_it", [
    lambda p: p["reference"].update(path="source.mp4"),
    lambda p: p["reference"].update(usage="composite"),
    lambda p: p["audio"].update(mode="copy"),
    lambda p: p["effects"][0].update(provenance="reference_pixels"),
    lambda p: p["effects"][0].update(kind="unknown_optical_warp"),
    lambda p: p["effects"][0].update(end_frame=49),
    lambda p: p["effects"][0].update(start_frame=True),
    lambda p: p["effects"][0]["params"].update(x_end=300),
    lambda p: p["effects"].append(deepcopy(p["effects"][0])),
    lambda p: p["effects"][2]["params"].update(text="⚡"),
    lambda p: p["canvas"].update(width=1920,height=1920,duration_frames=1800),
])
def test_fail_closed(plan, break_it):
    break_it(plan)
    with pytest.raises(EffectsError):
        validate(plan)


def test_manifest_rejects_duplicate_fields(tmp_path, plan):
    p = tmp_path / "duplicated-key.json"
    p.write_text('{"schema":"wrong",' + json.dumps(plan)[1:])
    with pytest.raises(EffectsError, match="Duplicate JSON key"):
        load(p)


@pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="FFmpeg and FFprobe required")
def test_verified_master_frame_region_and_silent_revision(tmp_path, plan):
    a, same, b = [tmp_path / x for x in ["A", "same", "B"]]
    ra = render(plan, a)
    assert render(plan, same) == ra
    assert len(ra["timeline"]["pts"]) == 48
    plan["effects"][2]["params"]["text"] = "ANTES DE"
    rb = render(plan, b)
    assert ra["master_sha256"] != rb["master_sha256"]
    assert check_revision(a,b,17,18,[120,74,215,100]) == {
        "changed_frames":[17], "unchanged_outside_window":True, "authorized_window":[17,18],
        "verified_region":[120,74,215,100], "exact_pts":True, "unchanged_audio":True,
    }
    with pytest.raises(EffectsError, match="Unauthorized frame change"):
        check_revision(a,b,18,19)
    with pytest.raises(EffectsError, match="Unauthorized pixel change"):
        check_revision(a,b,17,18,[0,0,1,1])
    with pytest.raises(EffectsError, match="Use a new"):
        render(plan, b)
    with (b/"effects.mkv").open("ab") as f:
        f.write(b"tampered")
    with pytest.raises(EffectsError, match="Mismatched revision files"):
        check_revision(a,b,17,18)

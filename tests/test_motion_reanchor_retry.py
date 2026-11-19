"""Retry only inside the existing frame and geometric verification contract."""
import pytest

from visual_fidelity import motion_observation as motion


@pytest.mark.parametrize(
    "levels, accepted_at, invoked",
    [(4, 0, [0]), (4, 1, [0, 1]), (4, None, [0, 1]), (0, None, [0])],
)
def test_reanchor_retry_is_bounded_and_respects_tracker_budget(monkeypatch, levels, accepted_at, invoked):
    calls = []
    accepted = object()

    def attempt(seed, current, original, matrix, settings, flow, size, level):
        calls.append(level)
        return accepted if level == accepted_at else None

    monkeypatch.setattr(motion, "_reanchor_at_level", attempt)
    result = motion._reanchor(None, None, None, None, {}, {"maxLevel": levels}, (320, 240))
    assert calls == invoked
    assert result is (accepted if accepted_at in invoked else None)

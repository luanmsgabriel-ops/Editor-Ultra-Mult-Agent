"""The engine authors video prompts; the user generates and returns the media.

This is a project workflow rule, not a provider configuration. Local editing,
compositing, procedural rendering and text-only direction remain separate.
Do not infer permission to submit video jobs from a profile, avatar or asset.
"""

from .contracts import clone


_POLICY = {
    "schema": "video-generation-execution-policy/1",
    "mode": "prompt_export_only",
    "automatic_video_generation": False,
    "provider_selection": "user_external",
    "external_video_return": "user_supplied",
    "deliverables": ["per_shot_prompts", "settings", "reference_requirements",
                     "continuity", "assembly_instructions"],
}


def execution_policy():
    """Return a fresh declaration; request data cannot override this policy."""
    return clone(_POLICY)

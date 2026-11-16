"""Creative options for the director, not a keyword-to-effect rule engine."""

from .contracts import clone


_GUIDANCE = {
    "schema": "motion-guidance/1",
    "selection": "The director must cite source evidence, purpose, timing and technical requirements. These cards do not select an effect.",
    "authoring": "Author and render a recipe before binding its verified motion-layer/1 asset to a contextual plan. Do not invent an asset or claim a backend is ready from its name.",
    "rules": [
        "Use the reference's measured timing as evidence; do not impose a fixed high-energy template.",
        "Choose the visual role first: screen graphic, subject occlusion, measured planar placement or a solved world camera.",
        "A generated 3D scene is not proof of a solved camera in the source footage.",
        "A motion layer uses an explicit local-to-source frame map. No implicit repeats, holds or retiming.",
        "A behind-subject request stays behind. Failed legibility, tracking or masking requires an explicit revision.",
        "Movement-derived audio events are candidates. Curate a suitable sound, review its attack and audition the mix.",
        "Inspect the animated passage, not only the contact sheet. A technical render is not aesthetic or user approval.",
    ],
    "cards": [
        {"id": "reference_edit", "purpose": "Match measured pacing, transition shape and visual texture",
         "backend": "openkatana", "evidence": ["reference cut candidates", "cadence", "transition curves", "source content"],
         "requirements": ["explicit source/output clock map", "review false cuts and flashes"],
         "avoid": "Treating estimated pixel measurements as complete semantic or 3D reconstruction"},
        {"id": "authored_scene", "purpose": "Demonstrate a concept or product through an authored 2D or 3D scene",
         "backend": "motionlab", "evidence": ["brief", "reference composition", "assets and font provenance"],
         "requirements": ["recipe with absolute time", "independent camera/object tracks", "verified local renderer"],
         "avoid": "Replacing a requested moving 3D environment with a zoomed still"},
        {"id": "kinetic_volume", "purpose": "Emphasize a short, purposeful phrase using volume and controlled movement",
         "backend": "motngrfx", "evidence": ["exact phrase", "reading interval", "free screen area", "font choice"],
         "requirements": ["real chosen font", "entry/hold/exit plan", "letter visibility review"],
         "avoid": "Using the same animation for every word or treating an extruded title as body tracking"},
        {"id": "subject_layers", "purpose": "Use front/back relationships between the source subject and motion",
         "backend": "native.motion_behind", "evidence": ["subject matte over the whole interval", "protected face/hands"],
         "requirements": ["source-bound masks", "matching frame rate", "explicit occlusion and visibility target"],
         "avoid": "Automatically moving behind text in front or dropping unreadable frames"},
        {"id": "effect_accent", "purpose": "Use a transition, displacement, glow or temporal treatment for a justified moment",
         "backend": "openkatana", "evidence": ["narrative moment", "reference strength", "gesture or music timing"],
         "requirements": ["bounded parameter curves", "isolated effect preview", "review complete surrounding passage"],
         "avoid": "Applying an effect to every beat or every cut regardless of the scene"},
        {"id": "movement_sound", "purpose": "Suggest sound accents from measured movement in an authored scene",
         "backend": "motionlab", "evidence": ["actual animated trajectory", "speed/rotation", "event time"],
         "requirements": ["explicit audio choice", "sample-accurate spotting", "source mix and sound attack review"],
         "avoid": "Calling telemetry an understanding of the source audio, or selecting SFX at random"},
    ],
}


def motion_guidance() -> dict:
    return clone(_GUIDANCE)

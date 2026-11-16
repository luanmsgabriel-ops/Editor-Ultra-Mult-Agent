"""Evidence-grounded editorial planning, capability gates and render-bound QA.

JSON in / JSON out. Semantic proposals come from an explicit human/model
provider; no transcript keyword matcher is used as editorial understanding.
"""

from .catalog import validate_catalog
from .contracts import SCHEMA_VERSION, ValidationError, digest, file_sha256, validate_analysis
from .planner import DEFAULT_POLICY, apply_patch, build_plan, validate_plan
from .review import add_review, invalidate_review, new_review

__all__ = [
    "SCHEMA_VERSION", "ValidationError", "DEFAULT_POLICY", "digest", "file_sha256",
    "validate_analysis", "validate_catalog", "build_plan", "validate_plan",
    "new_review", "add_review", "invalidate_review", "apply_patch",
]

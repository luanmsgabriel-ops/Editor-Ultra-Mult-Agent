"""Typed resources for a reconstruction on an independent, source-aligned plate."""

from fractions import Fraction
from pathlib import Path
import re
import shutil
from typing import Annotated, Literal
from zipfile import ZipFile

from PIL import Image, ImageFont
from pydantic import BaseModel, ConfigDict, Field, model_validator

from editorial_engine.contracts import require

RESOURCE_TYPES = ("image/png", "application/json", "application/zip", "font/ttf", "font/otf")
AssetId = Annotated[str, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,95}$")]
MAX_RESOURCE_BYTES = 40 * 1024 * 1024
MAX_MATTE_EXPANSION = 128 * 1024 * 1024
IMAGE_OPERATIONS = {
    "screen": "overlay", "behind_subject": "behind_subject",
    "planar": "projected_asset", "planar_behind": "projected_behind",
}
IMAGE_POLICY = (
    "Inspecione a referência por cena e elemento. Reutilize um recurso equivalente quando existir. "
    "Modele em 3D os volumes cuja câmera revela faces ou profundidade. Quando ícone, ilustração, "
    "silhueta ou textura ganhar fidelidade com imagem, use editor_request_clone_images. "
    "Gere cada recurso pendente com a ferramenta de imagem do host, com fundo transparente, "
    "e importe o PNG real via editor_import_file com role clone_resource. Retome a preparação "
    "com base independente e associe o PNG ao id do pedido. Anime e componha no motor."
)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class ImageNeed(StrictModel):
    id: AssetId
    scene_id: AssetId
    frames: list[Annotated[int, Field(ge=0)]] = Field(min_length=2, max_length=2)
    reference_frame: int = Field(ge=0)
    placement: Literal["screen", "behind_subject", "planar", "planar_behind"]
    description: str = Field(min_length=5, max_length=1200)
    reason: str = Field(min_length=5, max_length=700)

    @model_validator(mode="after")
    def reference_in_range(self):
        first, last = self.frames
        if not first <= self.reference_frame < last:
            raise ValueError("The reference frame must lie in [first,last)")
        if not self.description.strip() or not self.reason.strip():
            raise ValueError("Describe the object and why a generated image improves this scene")
        return self


class MeasuredProjection(StrictModel):
    measurement_id: AssetId
    element_id: AssetId
    frames: list[Annotated[int, Field(ge=0, le=3600)]] = Field(min_length=2, max_length=2)


class CloneResources(StrictModel):
    base_asset_id: AssetId
    images: dict[AssetId, AssetId] = Field(default_factory=dict, max_length=12)
    motion_layers: dict[AssetId, AssetId] = Field(default_factory=dict, max_length=12)
    protection_asset_id: AssetId | None = None
    projection_asset_id: AssetId | None = None
    projection_assets: dict[AssetId, AssetId] = Field(default_factory=dict, max_length=12)
    measured_projection: MeasuredProjection | None = None
    pose_asset_id: AssetId | None = None
    matte_asset_id: AssetId | None = None
    font_asset_id: AssetId | None = None
    script_font_asset_id: AssetId | None = None


    @model_validator(mode="after")
    def one_projection(self):
        if sum(bool(option) for option in (self.projection_asset_id, self.projection_assets, self.measured_projection)) > 1:
            raise ValueError("Choose either authored quads or one measured trajectory")
        return self


def measured_quads(profile, element_id, frames, clock):
    from visual_fidelity.motion_profile import evaluate_kinematics, validate_profile
    from visual_fidelity.video_anchor import quad

    validate_profile(profile)
    source = profile["source"]
    width, height = clock["width"], clock["height"]
    first, last = frames
    rate = Fraction(clock["fps"])
    require((source["width"], source["height"], source["rotation_ccw_applied"]) == (width, height, 0)
            and Fraction(source["fps"]) == rate and 0 <= first < last <= clock["frame_count"],
            "clone_motion_clock", "The measured raster and frame interval must match the reconstruction clock")
    element = next((item for item in profile["elements"] if item["id"] == element_id), None)
    require(element is not None, "clone_motion_element", "Select a measured element in the profile")
    selected = set(range(first, last))
    require(all(any(selected <= set(segment["frames"]) for segment in channel["segments"])
                for channel in element["channels"].values()),
            "clone_motion_gap", "The trajectory cannot span a cut or unsupported frames")
    result = {}
    for frame in range(first, last):
        pose = evaluate_kinematics(profile, element_id, float(frame / rate))
        require(pose["corners"] is not None, "clone_motion_pose", "Motion requires a complete measured pose")
        points = [[(p["position_px"][0]+.5)/width, (p["position_px"][1]+.5)/height]
                  for p in pose["corners"]]
        result[str(frame)] = quad(points).tolist()
    return result


def read_signature(path):
    with path.open("rb") as binary:
        return binary.read(4)


def inspect_resource(path, mime_type):
    require(mime_type in RESOURCE_TYPES and path.stat().st_size <= MAX_RESOURCE_BYTES,
            "clone_resource_type", "Use a supported reconstruction resource under 40 MiB")
    if mime_type == "image/png":
        with Image.open(path) as image:
            require(image.format == "PNG" and image.width * image.height <= 8_388_608
                    and getattr(image, "n_frames", 1) == 1,
                    "clone_png", "Supply a single PNG with at most 8 megapixels")
            image.verify()
        with Image.open(path) as image:
            alpha = image.convert("RGBA").getchannel("A")
            low, high = alpha.getextrema()
            require(low == 0 and high > 0, "clone_png_alpha",
                    "The PNG needs both transparent background pixels and a visible foreground")
            return {"width": image.width, "height": image.height, "type": mime_type}
    if mime_type in ("font/ttf", "font/otf"):
        require(read_signature(path) in (b"OTTO", b"\x00\x01\x00\x00", b"true"),
                "clone_font", "Supply a static OpenType or TrueType font")
        ImageFont.truetype(str(path), 24)
    elif mime_type == "application/json":
        import json
        require(path.stat().st_size <= 4 * 1024 * 1024 and isinstance(
            json.loads(path.read_text(encoding="utf-8")), dict),
            "clone_json", "Supply one JSON object under 4 MiB")
    else:
        with ZipFile(path) as archive:
            matte_members(archive)
    return {"type": mime_type}


def matte_members(archive):
    members = archive.infolist()
    names = {info.filename for info in members}
    require(len(members) == len(names) and "alpha.json" in names and 2 <= len(names) <= 3601
            and all(re.fullmatch(r"(?:alpha\.json|[0-9]{6}\.png)", name) for name in names),
            "clone_matte_archive", "Use alpha.json and uniquely named 000000.png masks at ZIP root")
    require(sum(info.file_size for info in members) <= MAX_MATTE_EXPANSION
            and all(0 < info.file_size <= 4 * 1024 * 1024 and not info.flag_bits & 1 for info in members),
            "clone_matte_budget", "The expanded matte sequence exceeds the bounded resource budget")
    return members


def extract_mattes(path, destination: Path, count):
    with ZipFile(path) as archive:
        members = matte_members(archive)
        require({m.filename for m in members} == {"alpha.json", *(f"{n:06d}.png" for n in range(count))},
                "clone_matte_coverage", "Provide one matte for every frame of the reconstruction base")
        destination.mkdir()
        for info in members:
            with archive.open(info) as incoming, (destination / info.filename).open("xb") as output:
                shutil.copyfileobj(incoming, output)
            if info.filename.endswith(".png"):
                with Image.open(destination / info.filename) as image:
                    require(image.format == "PNG" and image.width * image.height <= 8_388_608,
                            "clone_matte_format", "Matte must be a PNG at a bounded resolution")
                    image.verify()
    return str(destination)


def requested_image_coverage(plan, needs, clock):
    """Check every requested interval against the operation selected by direction."""
    from editorial_engine.native import _frames
    rate = Fraction(clock["fps"])
    for need in needs:
        first, last = need["frames"]
        coverage = set()
        for decision in plan["decisions"]:
            operation = decision.get("operation")
            if (operation and operation["operation"] == IMAGE_OPERATIONS[need["placement"]]
                    and operation.get("bindings", {}).get("asset") == "asset:" + need["id"]):
                coverage.update(range(*_frames(decision["interval"], rate, clock["frame_count"])))
        require(coverage == set(range(first, last)), "clone_image_coverage",
                "Bind the image to the requested placement and exact source-frame interval", need["id"])

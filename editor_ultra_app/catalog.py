"""Private versioned template catalog, loaded from an owner-provided package."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import uuid
import zipfile

from .media import PreviewSigner


class Catalog:
    def __init__(self, data_dir: Path, signer: PreviewSigner):
        self.root = data_dir / "catalog"
        self.root.mkdir(parents=True, exist_ok=True)
        self.signer = signer

    def _directory(self):
        pointer = self.root / "current.json"
        if not pointer.exists():
            return None
        name = json.loads(pointer.read_text())["version"]
        directory = (self.root / name).resolve()
        if not directory.is_relative_to(self.root.resolve()):
            raise ValueError("Versão de catálogo inválida.")
        return directory

    def status(self):
        directory = self._directory()
        if not directory:
            return {"installed": False, "count": 0, "message": "O acervo privado ainda não foi importado."}
        info = json.loads((directory / "receipt.json").read_text())
        return {"installed": True, **info}

    def list_templates(self):
        directory = self._directory()
        if not directory:
            return {"templates": [], "catalog_status": self.status()}
        rows = json.loads((directory / "gallery.json").read_text())
        result = []
        for row in rows:
            item = {k: v for k, v in row.items() if k not in {"thumbnail_path", "videoLocal", "video_path"}}
            path = row.get("thumbnail_path")
            item["thumbnail"] = self.signer.url(directory / path) if path else None
            item["name"] = item.get("name", item.get("title", item["id"]))
            item["animated"] = item.get("previewMode") == "sample"
            result.append(item)
        return {"templates": result, "catalog_status": self.status()}

    def library_path(self):
        directory = self._directory()
        if directory:
            path = directory / "Clone-Templates-1.0.0" / "library.json"
            if path.is_file():
                return path
        return None

    def detail(self, template_id: str):
        from editorial_engine.templates import library_request
        library = self.library_path()
        if library is None:
            raise ValueError("Pacote privado de templates ainda não instalado.")
        return library_request(library, template_ids=[template_id], summary=False, verify_files=True)

    def install(self, archive: Path):
        """Extract bytes only. Template code is never executed by this operation."""
        with archive.open("rb") as stream:
            sha = hashlib.file_digest(stream, "sha256").hexdigest()
        name = "v-" + sha[:24]
        directory = self.root / name
        if not directory.exists():
            staging = self.root / ("incoming-" + uuid.uuid4().hex)
            staging.mkdir(mode=0o700)
            try:
                with zipfile.ZipFile(archive) as bundle:
                    members = bundle.infolist()
                    if len(members) > 6000 or sum(i.file_size for i in members) > 512 * 1024 * 1024:
                        raise ValueError("Pacote excede o limite de arquivos ou espaço.")
                    if "gallery.json" not in bundle.namelist():
                        raise ValueError("O pacote precisa conter gallery.json.")
                    gallery_info = bundle.getinfo("gallery.json")
                    if gallery_info.file_size > 10 * 1024 * 1024:
                        raise ValueError("Catálogo de prévias excede 10 MiB.")
                    # ZIP, previous catalog, extracted tree and decoded thumbnails coexist.
                    reserve = sum(i.file_size for i in members) + gallery_info.file_size
                    used = sum(p.stat().st_size for p in self.root.parent.rglob("*") if p.is_file())
                    limit = int(os.environ.get("EDITOR_ULTRA_MAX_STORAGE_MB", "850")) * 1024 * 1024
                    if used + reserve > limit or shutil.disk_usage(self.root).free < reserve + 64 * 1024 * 1024:
                        raise ValueError("Espaço insuficiente para extrair e conferir esta versão sem apagar a anterior.")
                    names = set()
                    for member in members:
                        path = PurePosixPath(member.filename)
                        mode = member.external_attr >> 16
                        if (path.is_absolute() or ".." in path.parts or "\\" in member.filename
                                or stat.S_ISLNK(mode) or str(path) in names
                                or (member.file_size > 100 * 1024 * 1024)):
                            raise ValueError("O pacote contém um caminho, link ou arquivo inválido.")
                        names.add(str(path))
                        target = staging.joinpath(*path.parts)
                        if member.is_dir():
                            target.mkdir(parents=True, exist_ok=True)
                        else:
                            target.parent.mkdir(parents=True, exist_ok=True)
                            with bundle.open(member) as source, target.open("xb") as out:
                                shutil.copyfileobj(source, out)
                gallery = json.loads((staging / "gallery.json").read_text())
                if not isinstance(gallery, list) or not 0 < len(gallery) <= 1000:
                    raise ValueError("gallery.json deve conter um catálogo válido.")
                seen = set()
                for i, item in enumerate(gallery):
                    if item["id"] in seen:
                        raise ValueError("ID de template repetido.")
                    seen.add(item["id"])
                    item.pop("videoLocal", None)
                    thumbnail = item.pop("thumbnail", None)
                    if thumbnail:
                        if not thumbnail.startswith("data:image/webp;base64,"):
                            raise ValueError("As amostras do catálogo devem ser WebP.")
                        raw = base64.b64decode(thumbnail.split(",", 1)[1], validate=True)
                        if len(raw) > 2 * 1024 * 1024 or raw[:4] != b"RIFF" or raw[8:12] != b"WEBP":
                            raise ValueError("Miniatura inválida.")
                        target = f"thumbs/{i:04d}.webp"
                        (staging / "thumbs").mkdir(exist_ok=True)
                        (staging / target).write_bytes(raw)
                        item["thumbnail_path"] = target
                library = staging / "Clone-Templates-1.0.0" / "library.json"
                if library.exists():
                    from editorial_engine.templates import validate_library
                    # Checks bytes/dependencies, not visual quality or runtime execution.
                    validate_library(json.loads(library.read_text()), root=library.parent, verify_files=True)
                receipt = {"archive_sha256": sha, "count": len(gallery),
                           "motion_samples": sum(bool(t.get("thumbnail_path")) for t in gallery),
                           "library_installed": library.exists(), "runtime_executed": False}
                (staging / "gallery.json").write_text(json.dumps(gallery, ensure_ascii=False))
                (staging / "receipt.json").write_text(json.dumps(receipt))
                staging.rename(directory)
            except BaseException:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        pointer = self.root / (uuid.uuid4().hex + ".json")
        pointer.write_text(json.dumps({"version": name}))
        pointer.replace(self.root / "current.json")
        return self.status()

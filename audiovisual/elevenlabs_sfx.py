"""Prepara os SFX exportados do ElevenLabs para ingestao auditavel no motor.

Este modulo NAO baixa midia do ElevenLabs, nao publica no Drive e nao
autoriza uso comercial automaticamente. A entrada sao MP3s exportados
com nomes padronizados conforme assets/sfx/elevenlabs/catalog.json.

Uso:
  python -m audiovisual.elevenlabs_sfx inspect --catalog assets/sfx/elevenlabs/catalog.json --exports /caminho/para/mp3
  python -m audiovisual.elevenlabs_sfx stage --catalog assets/sfx/elevenlabs/catalog.json --exports /caminho/para/mp3 --assets assets/elevenlabs --output out/elevenlabs-staged.json
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys


IDENTIFIER = re.compile(r"^SFX-[0-9]{3,}$")
FILENAME = re.compile(r"^SFX-[0-9]{3,}_[A-Za-z0-9_-]+\.mp3$")


def read_catalog(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("assets", [])
    if not isinstance(items, list) or not items:
        raise ValueError("Catalogo sem assets.")
    seen = set()
    for asset in items:
        ident, filename = asset["id"], asset["filename"]
        if not IDENTIFIER.fullmatch(ident) or ident in seen:
            raise ValueError(f"ID invalido ou duplicado: {ident!r}")
        if not FILENAME.fullmatch(filename) or not filename.startswith(ident + "_"):
            raise ValueError(f"Nome de arquivo invalido: {filename!r}")
        seen.add(ident)
    return data


def digest(path):
    with path.open("rb") as file:
        return hashlib.file_digest(file, "sha256").hexdigest()


def duration_ms(path):
    process = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        text=True, capture_output=True, check=True,
    )
    value = round(float(process.stdout.strip()) * 1000)
    if value <= 0:
        raise ValueError(f"Duracao invalida: {path}")
    return value


def scan(catalog, exports):
    rows = []
    for entry in catalog["assets"]:
        path = exports / entry["filename"]
        row = {
            "id": entry["id"], "category": entry["category"],
            "filename": entry["filename"], "exists": path.is_file(),
            "expected_duration_ms": entry["duration_ms"],
        }
        if path.is_file():
            row["duration_ms"] = duration_ms(path)
            row["sha256"] = digest(path)
            row["size_bytes"] = path.stat().st_size
        rows.append(row)
    return rows


def stage(catalog, exports, dest, output):
    rows = scan(catalog, exports)
    if any(not row["exists"] for row in rows):
        names = [row["filename"] for row in rows if not row["exists"]]
        raise ValueError("Faltam exports; nada foi staged: " + ", ".join(names))
    dest.mkdir(parents=True, exist_ok=True)
    assets = []
    entries = {entry["id"]: entry for entry in catalog["assets"]}
    for row in rows:
        entry = entries[row["id"]]
        src = exports / row["filename"]
        target = dest / (row["id"] + ".mp3")
        if target.exists():
            if digest(target) != row["sha256"]:
                raise ValueError(f"Conflito no destino: {target}")
        else:
            shutil.copy2(src, target)
        assets.append({
            "id": row["id"], "name": entry["filename"],
            "source": "elevenlabs", "provider_generation_id": entry["generation_id"],
            "mime_type": "audio/mpeg", "family": entry["category"],
            "tags": entry["tags"], "engines": ["ffmpeg"],
            "duration_ms": row["duration_ms"], "size_bytes": row["size_bytes"],
            "sha256": row["sha256"], "local_file": str(target),
            "root_id": None, "folder_ids": [], "drive_file_id": None,
            "can_download": False, "license_status": "unknown",
            "review_status": "pending", "editor_eligibility": False,
        })
    payload = {
        "schema_version": 1, "source_batch_flow_id": catalog["flow_id"],
        "status": "staged_locally_not_uploaded_to_drive_or_licensed",
        "assets": assets,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    return payload


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="action", required=True)
    for command in ("inspect", "stage"):
        child = subs.add_parser(command)
        child.add_argument("--catalog", required=True, type=Path)
        child.add_argument("--exports", required=True, type=Path)
        if command == "stage":
            child.add_argument("--assets", required=True, type=Path)
            child.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        catalog = read_catalog(args.catalog)
        if not args.exports.is_dir():
            raise ValueError("Pasta de exports nao encontrada.")
        if args.action == "inspect":
            rows = scan(catalog, args.exports)
            print(json.dumps({"total": len(rows),
                              "present": sum(row["exists"] for row in rows),
                              "items": rows}, ensure_ascii=False, indent=2))
        else:
            payload = stage(catalog, args.exports, args.assets, args.output)
            print(json.dumps({"staged": len(payload["assets"]),
                              "output": str(args.output)}, ensure_ascii=False))
        return 0
    except (ValueError, KeyError, OSError, subprocess.SubprocessError) as error:
        print(f"Erro: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

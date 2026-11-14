"""Inventário de mídia local e validação de timeline editorial."""
import argparse
import hashlib
import json
from fractions import Fraction
from pathlib import Path
import subprocess
import sys


MEDIA = {".mp4", ".mov", ".mxf", ".mkv", ".webm", ".avi", ".mts", ".wav", ".m4a",
         ".aiff", ".aif", ".mp3", ".flac", ".ogg", ".mpeg", ".mpg"}


def probe(path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json",
         str(path.resolve())], text=True, capture_output=True, check=False,
    )
    if result.returncode:
        raise ValueError(result.stderr.strip() or "ffprobe falhou.")
    metadata = json.loads(result.stdout)
    with path.open("rb") as source:
        digest = hashlib.file_digest(source, "sha256").hexdigest()
    return {
        "path": str(path),
        "sha256": digest,
        "bytes": path.stat().st_size,
        "streams": metadata.get("streams", []),
        "format": {key: value for key, value in metadata.get("format", {}).items()
                   if key != "filename"},
    }


def inventory(paths):
    files = set()
    for path in paths:
        if path.is_dir():
            files.update(file for file in path.rglob("*") if file.suffix.lower() in MEDIA
                         and file.is_file())
        elif path.is_file():
            files.add(path)
        else:
            raise ValueError(f"Entrada inexistente: {path}")
    if not files:
        raise ValueError("Nenhuma mídia encontrada.")
    entries, errors = [], []
    for file in sorted(files, key=str):
        try:
            entries.append(probe(file))
        except (OSError, ValueError) as err:
            errors.append({"path": str(file), "error": str(err)})
    return {"schema_version": 1, "assets": entries, "errors": errors}


def whole(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} deve ser inteiro ≥ {minimum}.")
    return value


def key(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} deve ser texto não vazio.")
    return value


def interval(value, label):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"{label} deve conter [início, fim].")
    start, end = (whole(item, label) for item in value)
    if start >= end:
        raise ValueError(f"{label} usa fim exclusivo maior que início.")
    return start, end


def overlap(a, b):
    return a[0] < b[1] and b[0] < a[1]


def rate(value, label):
    if not isinstance(value, str):
        raise ValueError(f"{label} deve ser taxa racional em texto.")
    result = Fraction(value)
    if result <= 0:
        raise ValueError(f"{label} deve ser positivo.")
    return result


def records(value, label):
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{label} deve ser lista de objetos.")
    return value


def validate(edit):
    if not isinstance(edit, dict):
        raise ValueError("A edição deve ser um objeto JSON.")
    if whole(edit.get("schema_version"), "schema_version") != 1:
        raise ValueError("Versão de edição incompatível.")
    fps = rate(edit["fps"], "fps da sequência")
    length = whole(edit["duration_frames"], "duration_frames", 1)
    sources = {}
    for asset in records(edit["assets"], "assets"):
        name = key(asset["id"], "id do ativo")
        if name in sources:
            raise ValueError(f"Ativo duplicado: {name}")
        count = whole(asset["frames"], f"{name}/frames", 1)
        fps_source = rate(asset["fps"], f"{name}/fps")
        blocked = []
        for entry in records(asset.get("forbidden", []), f"{name}/forbidden"):
            span = interval(entry["frames"], f"{name}/intervalo proibido")
            if span[1] > count:
                raise ValueError(f"Intervalo proibido fora do ativo {name}.")
            blocked.append((span, key(entry["reason"], "motivo da exclusão")))
        sources[name] = (count, fps_source, blocked)

    errors, segments = [], []
    for segment in records(edit["segments"], "segments"):
        name = key(segment["asset"], "referência de ativo")
        if name not in sources:
            errors.append(f"Ativo desconhecido: {name}")
            continue
        count, fps_source, blocked = sources[name]
        seq = interval(segment["sequence"], f"{name}/sequence")
        src = interval(segment["source"], f"{name}/source")
        used = interval(segment.get("read", segment["source"]), f"{name}/read")
        if seq[1] > length or src[1] > count or used[1] > count:
            errors.append(f"{name} excede os limites de mídia ou sequência.")
        if not used[0] <= src[0] < src[1] <= used[1]:
            errors.append(f"Leitura insuficiente para {name}: {used} → {src}.")
        if Fraction(seq[1] - seq[0], fps) != Fraction(src[1] - src[0], fps_source):
            errors.append(f"Duração a 1× incompatível em {name}, quadros {seq}.")
        for span, reason in blocked:
            if overlap(used, span) or overlap(src, span):
                errors.append(f"{name} inclui intervalo proibido {span}: {reason}.")
        segments.append(seq)

    cursor = 0
    for start, end in sorted(segments):
        if start != cursor:
            kind = "Lacuna" if start > cursor else "Sobreposição"
            errors.append(f"{kind} na faixa principal: {cursor} → {start}.")
        cursor = max(cursor, end)
    if cursor != length:
        errors.append(f"Faixa principal termina no quadro {cursor}. Esperado: {length}.")

    boundaries = {span[0] for span in segments}
    cue_checks = []
    for cue in records(edit.get("cues", []), "cues"):
        label = key(cue["label"], "rótulo da marca")
        cut = whole(cue["cut_frame"], f"{label}/cut_frame")
        tolerance = whole(cue["tolerance_frames"], f"{label}/tolerance_frames")
        sample = whole(cue["audio_sample"], f"{label}/audio_sample")
        sample_rate = whole(cue["sample_rate"], f"{label}/sample_rate", 1)
        if cut not in boundaries:
            errors.append(f"{label} aponta para um quadro sem corte: {cut}.")
        audio_time = Fraction(sample, sample_rate)
        distance = abs(cut - audio_time * fps)
        if distance > tolerance or audio_time * fps >= length:
            errors.append(f"{label} fora da janela: {float(distance):.3f} quadros.")
        cue_checks.append({"label": label, "cut_frame": cut,
                           "distance_frames": round(float(distance), 6)})
    return {"ok": not errors, "errors": errors, "cue_checks": cue_checks,
            "validated_segments": len(segments), "duration_frames": length}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subcommands = parser.add_subparsers(dest="command", required=True)
    read = subcommands.add_parser("inventory", help="Gerar inventário de arquivos locais")
    read.add_argument("paths", type=Path, nargs="+")
    check = subcommands.add_parser("validate", help="Validar uma edição em JSON")
    check.add_argument("path", type=Path)
    for command in (read, check):
        command.add_argument("--output", type=Path, help="Salvar resultado JSON")
    args = parser.parse_args(argv)
    try:
        if args.command == "inventory":
            result = inventory(args.paths)
        else:
            result = validate(json.loads(args.path.read_text(encoding="utf-8")))
        output = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(output, encoding="utf-8")
        else:
            print(output, end="")
    except (OSError, TypeError, ValueError, KeyError, ZeroDivisionError) as err:
        print(f"Erro: {err}", file=sys.stderr)
        return 2
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())

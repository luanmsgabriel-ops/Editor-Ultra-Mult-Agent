"""Curadoria de recursos e validação editorial sem dependências externas."""

from argparse import ArgumentParser
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import sys


def rational(value, label, *, allow_zero=False):
    if type(value) not in (int, str):
        raise ValueError(f"{label}: use um inteiro ou uma razão em texto.")
    result = Fraction(value)
    if result < 0 or (result == 0 and not allow_zero):
        raise ValueError(f"{label}: razão fora dos limites.")
    return result


def whole(value, label, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label}: esperado inteiro ≥ {minimum}.")
    return value


def text_set(values, label):
    if not isinstance(values, list) or any(not isinstance(x, str) or not x for x in values):
        raise ValueError(f"{label}: esperada lista de textos.")
    return set(values)


def bounds(values, label):
    if not isinstance(values, list) or len(values) != 2:
        raise ValueError(f"{label}: esperado intervalo [início, fim).")
    first, end = (whole(i, label) for i in values)
    if first >= end:
        raise ValueError(f"{label}: fim exclusivo deve ser maior que início.")
    return first, end


def load_assets(catalog):
    values = catalog["assets"] if isinstance(catalog, dict) else catalog
    if not isinstance(values, list):
        raise ValueError("O catálogo deve ter lista de ativos.")
    index = {}
    for item in values:
        name = item["id"]
        if not isinstance(name, str) or not name or name in index:
            raise ValueError(f"Identificador ausente ou duplicado: {name!r}.")
        index[name] = item
    return index


def eligibility(asset, scope, use):
    why, notes = [], []
    roots = text_set(scope["allowed_root_ids"], "allowed_root_ids")
    if asset.get("source") != "drive" or asset.get("root_id") not in roots:
        why.append("fora das raízes autorizadas")
    if asset.get("is_shortcut") is True or asset.get("mime_type") == "application/vnd.google-apps.shortcut":
        why.append("atalho: registre e verifique o próprio arquivo de destino")
    rights = asset.get("license_status")
    preview = (use == "private_preview" and scope.get("allow_unverified_private_preview") is True
               and asset.get("can_download") is True and rights == "unknown")
    if preview:
        notes.append("direitos não verificados; uso limitado à prévia privada")
    elif rights != "approved":
        why.append("direitos sem aprovação explícita")
    elif use and use not in text_set(asset.get("uses", []), "uses"):
        why.append("licença sem autorização para o destino")
    return why, notes


def rank(catalog, need, scope):
    """A elegibilidade precede o ranking. A omissão de metadados não dá pontos."""
    families = text_set(need["families"], "families")
    hosts = text_set(need.get("engines", []), "engines")
    mimes = text_set(need.get("mime_types", []), "mime_types")
    required = text_set(need.get("required_tags", []), "required_tags")
    preferred = text_set(need.get("preferred_tags", []), "preferred_tags")
    shots = text_set(need.get("shot_tags", []), "shot_tags")
    target_intensity = whole(need.get("intensity", 2), "need.intensity")
    min_duration_ms = whole(need.get("min_duration_ms", 0), "min_duration_ms")
    required_alpha = need.get("require_alpha", False)
    use = need.get("use")
    eligible, rejected = [], []
    for name, item in load_assets(catalog).items():
        why, notes = eligibility(item, scope, use)
        tags = text_set(item.get("tags", []), f"{name}/tags")
        if item.get("family") not in families:
            why.append("família incompatível")
        if hosts and not hosts.intersection(text_set(item.get("engines", []), f"{name}/engines")):
            why.append("motor incompatível ou desconhecido")
        if mimes and item.get("mime_type") not in mimes:
            why.append("formato incompatível ou desconhecido")
        if required_alpha and item.get("alpha") is not True:
            why.append("canal alfa necessário e não confirmado")
        duration = whole(item.get("duration_ms", 0), f"{name}/duration_ms")
        if duration < min_duration_ms:
            why.append("duração disponível insuficiente")
        if required - tags:
            why.append("faltam características: " + ", ".join(sorted(required - tags)))
        if why:
            rejected.append({"id": name, "reasons": why})
            continue
        tag_fit, shot_fit = sorted(preferred & tags), sorted(shots & tags)
        measured = item.get("intensity")
        delta = abs(whole(measured, f"{name}/intensity") - target_intensity) if measured is not None else 4
        weights = {"estilo": 6 * len(tag_fit), "plano": 9 * len(shot_fit),
                   "intensidade": max(0, 8 - 2 * delta)}
        eligible.append({"id": name, "score": sum(weights.values()), "components": weights,
                         "rationale": {"estilo": tag_fit, "plano": shot_fit, "desvio_intensidade": delta},
                         "restrictions": notes})
    eligible.sort(key=lambda e: (-e["score"], e["id"]))
    rejected.sort(key=lambda e: e["id"])
    return {"eligible": eligible, "rejected": rejected,
            "baseline": "corte limpo com trilha",
            "note": "A ordem orienta prévias. Aplique o recurso apenas se o teste A/B confirmar a decisão."}


def validate_plan(plan, catalog=None, scope=None):
    fps = rational(plan["fps"], "fps")
    end_frame = whole(plan["duration_frames"], "duration_frames", 1)
    errors, warnings, cue_checks, cuts = [], [], [], set()
    cursor = 0
    for index, item in enumerate(plan["segments"]):
        start, end = bounds(item["sequence"], f"plano {index}: sequência")
        src, out = bounds(item["source"], f"plano {index}: fonte")
        read_in, read_out = bounds(item.get("read", item["source"]), f"plano {index}: leitura")
        rate = rational(item["source_fps"], f"plano {index}: source_fps")
        length = whole(item["source_frames"], f"plano {index}: source_frames", 1)
        if start != cursor:
            errors.append(f"Plano {index}: esperado no quadro {cursor}, recebido {start}.")
        if (end - start) * rate != (out - src) * fps:
            errors.append(f"Plano {index}: duração do recorte a 1× incompatível.")
        if not read_in <= src < out <= read_out <= length:
            errors.append(f"Plano {index}: entrada ou saída excede os quadros disponíveis.")
        for unavailable in item.get("forbidden", []):
            lo, hi = bounds(unavailable, f"plano {index}: intervalo proibido")
            if hi > length:
                errors.append(f"Plano {index}: marcação proibida fora da fonte.")
            if lo < read_out and read_in < hi:
                errors.append(f"Plano {index}: leitura encontra trecho proibido [{lo}, {hi}).")
        cuts.add(start)
        cursor = end
    if cursor != end_frame:
        errors.append(f"Faixa principal termina em {cursor}, esperado {end_frame}.")

    if plan.get("effects"):
        if catalog is None or scope is None:
            raise ValueError("Para validar efeitos, informe catálogo e escopo.")
        assets = load_assets(catalog)
        for effect in plan["effects"]:
            start, end = bounds(effect["sequence"], "efeito: sequência")
            name = effect["asset_id"]
            if end > end_frame:
                errors.append(f"Efeito {name}: fora da sequência.")
            if name not in assets:
                errors.append(f"Efeito ausente do catálogo: {name}.")
                continue
            rejected, notices = eligibility(assets[name], scope, plan.get("use"))
            errors.extend(f"Efeito {name}: {why}." for why in rejected)
            warnings.extend(f"Efeito {name}: {note}." for note in notices)
    for cue in plan.get("cues", []):
        name = cue["label"]
        frame = whole(cue["frame"], f"{name}: frame")
        sample_rate = whole(cue["sample_rate"], f"{name}: sample_rate", 1)
        sample = whole(cue["audio_sample"], f"{name}: audio_sample")
        kind = cue.get("kind", "cut")
        if kind not in {"cut","gesture","effect","speech","title"}:
            raise ValueError(f"{name}: tipo de marcação desconhecido.")
        if kind == "cut" and frame not in cuts:
            errors.append(f"{name}: quadro {frame} sem corte.")
        if frame >= end_frame or Fraction(sample, sample_rate) * fps >= end_frame:
            errors.append(f"{name}: cue fora da duração da edição.")
        distance = abs(Fraction(frame) - Fraction(sample, sample_rate) * fps)
        tol = rational(cue.get("tolerance_frames", "1/2"), f"{name}: tolerância", allow_zero=True)
        if distance > tol:
            errors.append(f"{name}: desvio {float(distance):.3f} quadros supera {tol}.")
        offset = None
        if "sfx" in cue:
            sx = cue["sfx"]
            trim = whole(sx["trim_in"], f"{name}: trim_in")
            attack = whole(sx["source_attack_sample"], f"{name}: ponto de ataque")
            position = whole(sx["timeline_start_sample"], f"{name}: início do SFX")
            if attack < trim:
                errors.append(f"{name}: o efeito foi aparado depois do seu ataque.")
            intended = sx.get("intended_offset_samples", 0)
            if type(intended) is not int:
                raise ValueError(f"{name}: intended_offset_samples deve ser inteiro.")
            offset = position + attack - trim - (sample + intended)
            if abs(Fraction(offset, sample_rate) * fps) > tol:
                errors.append(f"{name}: ataque do SFX deslocado {offset} amostras.")
        cue_checks.append({"label": name, "deviation_frames": round(float(distance), 6),
                           "sfx_offset_samples": offset})
    return {"ok": not errors, "errors": errors, "warnings": warnings, "cue_checks": cue_checks}


def manifest(plan, files):
    """Fingerprint de insumos e saída. Não inclui relógio de execução para preservar reprodução."""
    entries = []
    for name, path in sorted(files.items()):
        with path.open("rb") as src:
            digest = hashlib.file_digest(src, "sha256").hexdigest()
        entries.append({"role": name, "file": path.name, "bytes": path.stat().st_size, "sha256": digest})
    encoded = json.dumps(plan, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return {"schema_version": 1, "timeline_sha256": hashlib.sha256(encoded).hexdigest(),
            "duration_frames": plan["duration_frames"], "fps": plan["fps"], "files": entries}


def read(path):
    return json.loads(Path(path).read_text(encoding="utf-8-sig")) if path else None


def main(argv=None):
    parser = ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    rank_cmd = subs.add_parser("rank", help="Ordenar recursos do acervo autorizado.")
    for arg in ("catalog", "need", "scope"):
        rank_cmd.add_argument(arg)
    plan_cmd = subs.add_parser("validate-plan", help="Validar cortes, exclusões, marcos e SFX.")
    plan_cmd.add_argument("plan")
    plan_cmd.add_argument("--catalog")
    plan_cmd.add_argument("--scope")
    man_cmd = subs.add_parser("manifest", help="Registrar revisão e SHA-256 de insumos e saídas.")
    man_cmd.add_argument("plan")
    man_cmd.add_argument("--file", action="append", default=[], metavar="PAPEL=CAMINHO")
    args = parser.parse_args(argv)
    try:
        if args.command == "rank":
            result = rank(read(args.catalog), read(args.need), read(args.scope))
        elif args.command == "validate-plan":
            result = validate_plan(read(args.plan), read(args.catalog), read(args.scope))
        else:
            roles = {}
            for entry in args.file:
                role, sep, path = entry.partition("=")
                if not sep or not role or not path or role in roles:
                    raise ValueError("Use --file papel=caminho com papéis exclusivos.")
                roles[role] = Path(path)
            result = manifest(read(args.plan), roles)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result.get("ok", True) else 1
    except (AttributeError, KeyError, TypeError, ValueError, ZeroDivisionError, OSError) as err:
        print(f"Erro: {err}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

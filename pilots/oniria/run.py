"""Valide os recursos, execute o piloto Oníria e verifique a exportação."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import subprocess
import sys

from .clean_picture import render
from extensions.editor_policy import manifest, rank, validate_plan

HERE = Path(__file__).resolve().parent
FPS, RATE, FRAMES = 24, 48000, 700


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")


def ff(*args):
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", *map(str,args)], check=True)


def check_result(path):
    text = subprocess.check_output(["ffprobe","-v","error","-show_streams","-of","json",str(path)])
    v, a = json.loads(text)["streams"]
    if (v["nb_frames"], v["avg_frame_rate"], v["width"], v["height"]) != ("700", "24/1", 1080, 1920):
        raise ValueError("A imagem exportada diverge do perfil do projeto.")
    if int(a["sample_rate"]) != RATE or abs(float(a["duration"]) - FRAMES/FPS) > 1/RATE + .001:
        raise ValueError("A duração de áudio exportada diverge da timeline.")
    ff("-xerror","-i",path,"-f","null","-")
    return {"frames":int(v["nb_frames"]), "fps":v["avg_frame_rate"], "audio_hz":int(a["sample_rate"])}


def run(args):
    timeline, catalog, scope, cues = (read(HERE/"Timeline.json"),read(args.catalog),
                                     read(args.scope),read(args.cues))
    allowed = scope["allowed_root_ids"]
    by_id = {asset["id"]: asset for asset in catalog["assets"]}
    args.out.mkdir(parents=True, exist_ok=True)
    selections, media = [], {}
    for cue in cues["cues"]:
        item = by_id[cue["id"]]
        if item["root_id"] != cue["root_id"]:
            raise ValueError("Escopo da seleção diverge do catálogo.")
        need = {
            "use":"private_preview","families":[item["family"]],
            "engines":["ffmpeg"],"mime_types":["audio/mpeg"],
            "min_duration_ms":round(1000*cue["source_range_s"][1]),
            "preferred_tags":[tag for tag in ("curto","fino","ouro","fogo") if tag in item["tags"]],
        }
        cand = rank(catalog, need, scope)
        if cue["id"] not in {option["id"] for option in cand["eligible"]}:
            raise ValueError(f"Recurso inelegível: {cue['id']}")
        p = args.assets / (cue["id"]+".mp3")
        with p.open("rb") as handle:
            digest = hashlib.file_digest(handle,"sha256").hexdigest()
        if digest != item.get("sha256"):
            raise ValueError(f"Arquivo do recurso diverge do catálogo: {cue['id']}")
        media[cue["id"]] = p
        selections.append({"chosen":cue["id"],"editorial_reason":cue["rationale"],"rank":cand["eligible"][:8]})
    write(args.out/"Curadoria.json", selections)
    write(args.out/"Cues-Autorizados.json", {"allowed_roots":allowed,"cues":cues["cues"]})
    picture = args.picture or args.out/"Picture.mp4"
    if args.picture is None:
        if not args.sources or not args.stage:
            raise ValueError("Forneça --sources e --stage para reconstruir a imagem.")
        render(args.sources.resolve(), args.stage.resolve(), picture)
    subprocess.run([sys.executable,"-m","pilots.oniria.mix_variant","--base",str(args.base),
                    "--assets",str(args.assets),"--cues",str(args.out/"Cues-Autorizados.json"),
                    "--out",str(args.out)],check=True)
    realized = read(args.out/"Cues-Realizados.json")
    plan = {"fps":"24/1","duration_frames":FRAMES,"use":"private_preview",
            "segments":[], "effects":[], "cues":[]}
    for row in timeline["shots"]:
        src_frames = int(subprocess.check_output(["ffprobe","-v","error","-select_streams","v:0","-show_entries","stream=nb_frames","-of","csv=p=0",str(args.sources/f"{row['id']}.mp4")])) if args.sources else row["out"]
        plan["segments"].append({"id":str(row["id"]),"sequence":[row["start"],row["end"]],
                                 "source":[row["in"], row["out"]],"source_fps":"24/1","source_frames":src_frames})
        if row["sync_cue"]:
            plan["cues"].append({"label":f"corte {row['id']}","kind":"cut","frame":row["start"],
                                 "sample_rate":RATE,"audio_sample":round(RATE*row["sync_cue"]["second"])})
    for fx in realized["cues"]:
        lo, hi = (Fraction(str(fx[key]))*FPS for key in ("rendered_in_s","rendered_out_s"))
        plan["effects"].append({"asset_id":fx["id"],"sequence":[int(lo),-(-hi.numerator//hi.denominator)]})
        plan["cues"].append({"label":fx["name"],"kind":"effect","frame":fx["sequence_frame"],
                             "sample_rate":RATE,"audio_sample":fx["sequence_anchor_sample"],
                             "sfx":{"trim_in":round(fx["source_range_s"][0]*RATE),
                                    "source_attack_sample":round(fx["source_anchor_s"]*RATE),
                                    "timeline_start_sample":round(fx["rendered_in_s"]*RATE)}})
    report = validate_plan(plan,catalog,scope)
    write(args.out/"Plano-Validado.json",plan)
    write(args.out/"Validacao.json",report)
    if not report["ok"]:
        raise ValueError("; ".join(report["errors"]))
    movie = args.out/"Oniria-Festival-Variante-Acervo-SFX.mp4"
    ff("-i",picture,"-i",args.out/"Mix-Variante.wav","-map","0:v:0","-map","1:a:0",
       "-c:v","copy","-c:a","aac","-b:a","256k","-movflags","+faststart",movie)
    write(args.out/"Exportacao.json",check_result(movie))
    write(args.out/"Manifesto.json",manifest(plan, {"export":movie,"imagem":picture,
                                                 "base":args.base,**media}))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    for field in ("sources","stage","picture"):
        p.add_argument("--"+field, type=Path)
    for field in ("catalog","scope","cues","assets","base","out"):
        p.add_argument("--"+field, type=Path, required=True)
    run(p.parse_args())

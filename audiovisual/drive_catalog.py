"""Catalogue o escopo autorizado do Drive e teste SFX locais com ffprobe."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import unicodedata
from urllib.parse import urlencode
from urllib.request import Request, urlopen

DRIVE = "https://www.googleapis.com/drive/v3/files"
FOLDER = "application/vnd.google-apps.folder"
SHORTCUT = "application/vnd.google-apps.shortcut"
ID = re.compile(r"[A-Za-z0-9_-]+")


def slug(value):
    plain = unicodedata.normalize("NFKD", value.lower())
    return "".join(letter for letter in plain if not unicodedata.combining(letter))


def file_id(value):
    if not isinstance(value, str) or not ID.fullmatch(value):
        raise ValueError("ID do Drive inválido.")
    return value


def family(name, mime):
    if mime == FOLDER:
        return "folder"
    if mime == SHORTCUT:
        return "shortcut"
    text = slug(name)
    if mime.startswith("audio/"):
        for key, words in {
            "fire": ("fogo", "chama", "rojao", "co2", "fire"),
            "riser": ("riser", "crescente"),
            "whoosh": ("whoosh", "swipe"),
            "impact": ("hit", "impacto", "explosao", "tambor"),
            "transition": ("transicao", "transition"),
            "music_candidate": ("trilha", "music"),
            "interface": ("interface", "hud", "shutter", "click"),
        }.items():
            if any(re.search(rf"\b{word}\w*\b", text) for word in words):
                return key
        return "audio_other"
    if text.endswith(".cube"):
        return "lut"
    return "video_candidate" if mime.startswith("video/") else "other"


def get_json(token, path="", **query):
    req = Request(DRIVE + path + "?" + urlencode(query),
                  headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
    with urlopen(req, timeout=30) as response:
        return json.load(response)


def scan(roots, fetch):
    """Traverse only actual descendants; omit target resolution for shortcuts."""
    found, counters = {}, []
    for root in dict.fromkeys(map(file_id, roots)):
        root_meta = fetch("/" + root, fields="id,name,mimeType,trashed",
                          supportsAllDrives="true")
        if root_meta.get("trashed") or root_meta.get("mimeType") != FOLDER:
            raise ValueError(f"A raiz {root} não é uma pasta acessível.")
        pending, seen, count = [root], set(), 0
        while pending:
            parent = pending.pop()
            if parent in seen:
                continue
            seen.add(parent)
            token = None
            while True:
                query = dict(q=f"'{parent}' in parents and trashed = false",
                             fields="nextPageToken,incompleteSearch,files(id,name,mimeType,size,parents,capabilities(canDownload),modifiedTime,md5Checksum)",
                             pageSize=100, supportsAllDrives="true", includeItemsFromAllDrives="true")
                if token:
                    query["pageToken"] = token
                page = fetch("", **query)
                if page.get("incompleteSearch"):
                    raise ValueError(f"A consulta do Drive está incompleta para {parent}.")
                for item in page.get("files", []):
                    id_ = file_id(item["id"])
                    if parent not in item.get("parents", []):
                        raise ValueError(f"Vínculo do ativo {id_} não confirmado.")
                    mime = item["mimeType"]
                    if mime == FOLDER:
                        pending.append(id_)
                        continue
                    count += 1
                    out = found.setdefault(id_, {
                        "id": id_, "root_id": root, "root_ids": [], "source": "drive",
                        "name": item["name"], "mime_type": mime, "license_status": "unknown",
                        "can_download": item.get("capabilities", {}).get("canDownload", False),
                        "size_bytes": int(item.get("size", 0)), "is_shortcut": mime == SHORTCUT,
                        "md5_checksum": item.get("md5Checksum"),
                        "modified_time": item.get("modifiedTime"), "folder_ids": [],
                    })
                    if root not in out["root_ids"]:
                        out["root_ids"].append(root)
                    if parent not in out["folder_ids"]:
                        out["folder_ids"].append(parent)
                token = page.get("nextPageToken")
                if not token:
                    break
        counters.append({"id": root, "name": root_meta["name"], "count": count})
    return {"roots": counters, "assets": list(found.values())}


def probe_seconds(path):
    output = subprocess.check_output([
        "ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
        str(path)], text=True)
    return round(float(output.strip())*1000)


def enrich(catalog, local):
    output = []
    for asset in catalog["assets"]:
        row = dict(asset)
        row["family"] = family(row["name"], row["mime_type"])
        row["tags"] = sorted(set(re.findall(r"[a-z]+", slug(row["name"]).split(".")[0]))
                             - {"byeditorpro", "editorpro"})
        row["engines"] = ["ffmpeg"] if row["mime_type"].startswith("audio/") else []
        if local:
            possible = list(local.glob(file_id(row["id"]) + ".*"))
            if len(possible) > 1:
                raise ValueError(f"Há várias cópias locais de {row['id']}.")
            if possible and possible[0].is_file():
                row["duration_ms"] = probe_seconds(possible[0])
                with possible[0].open("rb") as handle:
                    row["sha256"] = hashlib.file_digest(handle, "sha256").hexdigest()
        output.append(row)
    return {**catalog, "assets": output}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    inp = p.add_mutually_exclusive_group(required=True)
    inp.add_argument("--root", action="append", help="ID de pasta autorizada, repetível")
    inp.add_argument("--snapshot", type=Path, help="Catálogo de metadados obtido via conector")
    p.add_argument("--local", type=Path, help="Cópias baixadas e nomeadas ID.ext")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    if a.root:
        token = os.environ.get("EDITOR_DRIVE_ACCESS_TOKEN")
        if not token:
            p.error("EDITOR_DRIVE_ACCESS_TOKEN ausente para consulta direta.")
        catalog = scan(a.root, lambda path, **query: get_json(token, path, **query))
    else:
        catalog = json.loads(a.snapshot.read_text(encoding="utf-8"))
    a.output.write_text(json.dumps(enrich(catalog, a.local), ensure_ascii=False, indent=2)+"\n",
                        encoding="utf-8")


if __name__ == "__main__":
    main()

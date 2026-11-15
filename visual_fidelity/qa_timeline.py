"""Compare two rendered timelines on their shared CFR video clock."""
import argparse
import csv
import json
from pathlib import Path
import subprocess

import cv2
import numpy as np


def get_series(video):
    """Return adjacent-frame luma change and thumbnails for aligned comparisons."""
    progress=[]
    thumbs=[]
    cap=cv2.VideoCapture(str(video))
    fps=cap.get(cv2.CAP_PROP_FPS)
    if not cap.isOpened() or fps<=0:
        cap.release()
        raise ValueError(f"Vídeo ilegível: {video}")
    try:
        last=None
        while True:
            ok, bgr=cap.read()
            if not ok:
                break
            image=cv2.resize(bgr,(90,160),interpolation=cv2.INTER_AREA)
            y=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY).astype(np.float32)
            thumbs.append(image)
            progress.append(0 if last is None else float(np.abs(y-last).mean()))
            last=y
    finally:
        cap.release()
    if not progress:
        raise ValueError(f"Sem quadros decodificados: {video}")
    return fps,np.asarray(progress),np.asarray(thumbs)


def local_peak(series, center, radius):
    a,b=max(1,center-radius),min(len(series),center+radius+1)
    return a+int(np.argmax(series[a:b])) if a<b else None


def summarize(reference, sample, timeline, csv_path):
    cursor=0
    for shot in timeline["shots"]:
        if shot["start"]!=cursor or shot["end"]<=cursor:
            raise ValueError("A timeline contém lacunas, sobreposições ou cenas vazias.")
        cursor=shot["end"]
    if cursor!=timeline["frames"]:
        raise ValueError("As cenas não cobrem o total de quadros da timeline.")
    fps, original, source_pixels=get_series(reference)
    out_fps, rendered, rendered_pixels=get_series(sample)
    frames=timeline["frames"]
    if not (abs(fps-timeline["fps"])<.001 and abs(out_fps-fps)<.001
            and len(original)==len(rendered)==frames):
        raise ValueError(
            f"Timelines incompatíveis. Ref {len(original)} × {fps:g} fps, "
            f"render {len(rendered)} × {out_fps:g} fps, esperados {frames} × {timeline['fps']} fps."
        )
    with csv_path.open("w",encoding="utf-8",newline="") as stream:
        writer=csv.writer(stream)
        writer.writerow(("quadro","segundos","delta_luma_referencia","delta_luma_render","erro_rgb"))
        difference=(np.abs(source_pixels.astype(np.int16)-rendered_pixels.astype(np.int16))).mean(axis=(1,2,3))
        writer.writerows((i,round(i/fps,5),round(x,3),round(y,3),round(difference[i],3))
                         for i,(x,y) in enumerate(zip(original,rendered)))
    rows=[]
    for shot in timeline["shots"]:
        a,b=shot["start"],shot["end"]
        x,y=original[a:b],rendered[a:b]
        pa,pb=local_peak(original,a,3),local_peak(rendered,a,3)
        is_change=pa is not None and min(original[pa],rendered[pb])>=7.5
        data={
            "id":shot["id"],"start":a,"end":b,"start_s":round(a/fps,5),
            "motion_ref_p90":round(float(np.quantile(x,.9)),2),"motion_render_p90":round(float(np.quantile(y,.9)),2),
            "mean_rgb_error":round(float(difference[a:b].mean()),2),
            "peak_ref":pa if a>0 else None,"peak_render":pb if a>0 else None,
            "peak_shift_frames":(pb-pa) if a>0 and is_change else None,
        }
        rows.append(data)
    return {
        "frames":frames,"fps":fps,"duration_s":round(frames/fps,6),"same_clock":True,
        "motion_metric":"Diferença média de luminância entre quadros contíguos em miniatura 90 × 160, escala 0–255.",
        "peak_metric":"Maior diferença de quadro na janela de ±3; desvio comparado quando ambos os picos são de pelo menos 7,5.",
        "visual_metric":"Diferença RGB média, escala 0–255. Inclui pessoa, iluminação, elementos substitutos e ausência de originais.",
        "shots":rows,
    }


def contact_video(reference, sample, output, compare_audio, frames, fps):
    head=82
    typography="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    labels=[
        (24,"REFERÊNCIA"),(744,"RECONSTRUÇÃO"),
        (1120,f"%{{pts\\:hms}}  |  {fps:g} fps")
    ]
    titles="".join(f",drawtext=fontfile={typography}:text='{t}':x={x}:y=24:fontsize=25:fontcolor=white" for x,t in labels)
    graph=("[0:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[a];"
           "[1:v]scale=720:1280:force_original_aspect_ratio=decrease,pad=720:1280:(ow-iw)/2:(oh-ih)/2,setsar=1[b];"
           f"[a][b]hstack=shortest=1,pad=1440:{1280+head}:0:{head}:color=0x131619{titles}[v]")
    command=["ffmpeg","-v","error","-y","-filter_complex_threads","2","-i",str(reference),"-i",str(sample),
             "-filter_complex",graph,"-map","[v]"]
    audio={"referencia":"0:a:0?","render":"1:a:0?"}.get(compare_audio)
    if audio:
        command += ["-map",audio,"-c:a","aac","-b:a","160k"]
    else:
        command+=["-an"]
    command += ["-t",str(frames/fps),"-c:v","libx264","-preset","fast","-crf","20",
                "-threads","4","-pix_fmt","yuv420p","-movflags","+faststart",str(output)]
    subprocess.run(command,check=True)


def main():
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("reference",type=Path)
    cli.add_argument("render",type=Path)
    cli.add_argument("timeline",type=Path)
    cli.add_argument("output",type=Path)
    cli.add_argument("--compare",type=Path)
    cli.add_argument("--audio",choices=("referencia","render","nenhum"),default="referencia")
    args=cli.parse_args()
    if args.output.suffix.lower() != ".json":
        cli.error("O caminho do relatório deve terminar em .json.")
    cv2.setNumThreads(2)
    timeline=json.loads(args.timeline.read_text(encoding="utf-8"))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    report=summarize(args.reference,args.render,timeline,args.output.with_suffix(".csv"))
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    if args.compare:
        contact_video(args.reference,args.render,args.compare,args.audio,report["frames"],report["fps"])


if __name__=="__main__":
    main()

"""Export a foreground pass from a local SAM 2 checkpoint and a box prompt."""

import argparse
from pathlib import Path

import cv2
import numpy as np


def write_foreground(frame, logits, destination):
    mask = np.asarray(logits, dtype=np.float32).squeeze()
    if mask.shape != frame.shape[:2] or not np.isfinite(mask).all():
        raise ValueError("A saída da máscara precisa corresponder ao quadro original.")
    alpha = cv2.GaussianBlur(np.uint8(mask > 0) * 255, (3, 3), .65)
    rgba = np.dstack((frame, alpha))
    if not cv2.imwrite(str(destination), rgba):
        raise OSError(f"Não consegui gravar o recorte {destination}.")


def run(args):
    try:
        from sam2.build_sam import build_sam2_video_predictor
        import torch
    except ImportError as error:
        raise RuntimeError("Instale SAM 2 e PyTorch no ambiente que fará a rotoscopia.") from error
    files = sorted(
        (file for file in args.frames.iterdir() if file.suffix.lower() in {".jpg", ".jpeg"}),
        key=lambda file: int(file.stem),
    )
    if not files or not args.checkpoint.is_file():
        raise ValueError("Forneça a sequência JPEG numerada e o checkpoint local do SAM 2.")
    x1, y1, x2, y2 = args.box
    sample = cv2.imread(str(files[0]))
    if (x2 <= x1 or y2 <= y1 or min(x1, y1) < 0 or sample is None
            or x2 > sample.shape[1] or y2 > sample.shape[0]):
        raise ValueError("A caixa do primeiro quadro precisa ficar dentro da imagem.")
    args.out.mkdir(parents=True, exist_ok=True)
    predictor = build_sam2_video_predictor(args.model_cfg, str(args.checkpoint), device=args.device)
    with torch.inference_mode():
        state = predictor.init_state(video_path=str(args.frames))
        predictor.add_new_points_or_box(
            inference_state=state,
            frame_idx=0,
            obj_id=1,
            box=np.float32(args.box),
        )
        written = set()
        for index, objects, logits in predictor.propagate_in_video(state):
            position = list(objects).index(1)
            frame = cv2.imread(str(files[index]))
            if frame is None:
                raise ValueError(f"Falha de leitura no quadro {index}.")
            write_foreground(frame, logits[position].cpu().numpy(), args.out / f"{index + 1:06}.png")
            written.add(index)
    if written != set(range(len(files))):
        raise RuntimeError("O SAM 2 retornou apenas parte da sequência solicitada.")
    print(f"{len(written)} quadros RGBA em {args.out}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--frames", type=Path, required=True)
    ap.add_argument("--checkpoint", type=Path, required=True)
    ap.add_argument("--model-cfg", default="configs/sam2.1/sam2.1_hiera_s.yaml")
    ap.add_argument("--device", choices=("cuda", "cpu", "mps"), default="cuda")
    ap.add_argument("--box", type=int, nargs=4, metavar=("X1", "Y1", "X2", "Y2"), required=True)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    try:
        run(args)
    except (RuntimeError, OSError, ValueError) as error:
        ap.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()

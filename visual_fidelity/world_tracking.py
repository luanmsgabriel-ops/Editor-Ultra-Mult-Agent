"""Resolve a bounded, continuous shot and attach a graphic in its 3D space."""

from __future__ import annotations

import cv2
import numpy as np


def _camera(matrix, rvec, tvec, error, count):
    rotation = cv2.Rodrigues(rvec)[0]
    return {"K": matrix.tolist(), "R": rotation.tolist(), "t": tvec.ravel().tolist(),
            "reprojection_px": float(error), "inliers": int(count)}


def _track(grays, pixels):
    points = np.asarray(pixels, np.float32).reshape(-1, 1, 2)
    positions = [points.reshape(-1, 2).copy()]
    visible = [np.ones(len(points), dtype=bool)]
    for previous, current in zip(grays, grays[1:]):
        next_points, forward, _ = cv2.calcOpticalFlowPyrLK(previous, current, points, None)
        if next_points is None:
            raise ValueError("O tracking perdeu os pontos da tomada.")
        back, backward, _ = cv2.calcOpticalFlowPyrLK(current, previous, next_points, None)
        if back is None:
            raise ValueError("O tracking perdeu os pontos da tomada.")
        new = next_points.reshape(-1, 2)
        size = current.shape[::-1]
        valid = (forward.ravel() > 0) & (backward.ravel() > 0)
        valid &= np.linalg.norm(back.reshape(-1, 2) - points.reshape(-1, 2), axis=1) <= 1.5
        valid &= np.isfinite(new).all(axis=1) & (new >= 0).all(axis=1) & (new < size).all(axis=1)
        visible.append(visible[-1] & valid)
        positions.append(new.copy())
        points = np.where(visible[-1][:, None, None], next_points, points)
    return np.asarray(positions), np.asarray(visible)


def _solve(matrix, points, image_points):
    points = np.ascontiguousarray(points, dtype=np.float64)
    image_points = np.ascontiguousarray(image_points, dtype=np.float64)
    if len(points) < 8:
        raise ValueError("São necessários oito pontos estáveis para resolver a câmera.")
    ok, rvec, tvec, inliers = cv2.solvePnPRansac(
        points, image_points, matrix, None, iterationsCount=200,
        reprojectionError=2.5, confidence=.995, flags=cv2.SOLVEPNP_EPNP,
    )
    if not ok or inliers is None or len(inliers) < max(8, int(len(points) * .55)):
        raise ValueError("Pontos insuficientes ou inconsistentes na solução de câmera.")
    indices = inliers.ravel()
    points, image_points = points[indices], image_points[indices]
    rvec, tvec = cv2.solvePnPRefineLM(points, image_points, matrix, None, rvec, tvec)
    projected = cv2.projectPoints(points, rvec, tvec, matrix, None)[0].reshape(-1, 2)
    rms = np.sqrt(np.mean(np.square(np.linalg.norm(projected - image_points, axis=1))))
    if not np.isfinite(rms) or rms > 2.5:
        raise ValueError("O erro de reprojeção da câmera excede 2,5 pixels.")
    return _camera(matrix, rvec, tvec, rms, len(points))


def _reconstruct(matrix, positions, visible):
    best = None
    inverse = np.linalg.inv(matrix)
    projection = matrix @ np.column_stack((np.eye(3), np.zeros(3)))
    for view in np.unique(np.linspace(1, len(positions) - 1, min(10, len(positions) - 1), dtype=int)):
        indices = np.flatnonzero(visible[view])
        if len(indices) < 16:
            continue
        first, second = positions[0, indices], positions[view, indices]
        if np.median(np.linalg.norm(first - second, axis=1)) < 4:
            continue
        essential, mask = cv2.findEssentialMat(first, second, matrix, cv2.RANSAC, .999, 1.)
        if essential is None or essential.shape != (3, 3):
            continue
        count, rotation, translation, mask = cv2.recoverPose(essential, first, second, matrix, mask=mask)
        if count < 16:
            continue
        # Reject weak parallax and pure rotation before treating image tracks as 3D.
        inliers = mask.ravel() != 0
        rays_a = np.column_stack((first[inliers], np.ones(count))) @ inverse.T
        rays_b = np.column_stack((second[inliers], np.ones(count))) @ inverse.T @ rotation
        cosines = (rays_a * rays_b).sum(axis=1) / (np.linalg.norm(rays_a, axis=1) * np.linalg.norm(rays_b, axis=1))
        angle = np.degrees(np.arccos(np.clip(cosines, -1, 1)))
        if np.median(angle) < .65:
            continue
        target = matrix @ np.column_stack((rotation, translation))
        homogeneous = cv2.triangulatePoints(projection, target, first[inliers].T, second[inliers].T).T
        nonzero = np.abs(homogeneous[:, 3]) > 1e-8
        homogeneous = homogeneous[nonzero]
        xyz = homogeneous[:, :3] / homogeneous[:, 3:4]
        good = (xyz[:, 2] > 0) & (xyz[:, 2] < 150) & np.isfinite(xyz).all(axis=1)
        if int(good.sum()) < 16:
            continue
        xyz = xyz[good]
        spread = np.linalg.svd(xyz - np.median(xyz, axis=0), compute_uv=False)
        if spread[-1] < .015 * spread[0]:
            continue
        selected = indices[inliers][nonzero][good]
        score = min(int(good.sum()), 120) * min(float(np.median(angle)), 6)
        if best is None or score > best[0]:
            best = score, xyz, selected
    if best is None:
        raise ValueError("Sem paralaxe ou pontos suficientes. Indique pontos 3D conhecidos nesta tomada.")
    return best[1:]


def solve_world_track(grays, *, calibration=None, anchor=None, size_fraction=.24, exclude=None):
    """Track calibrated scene points, or solve a relative two-view reconstruction."""
    if not 2 <= len(grays) <= 300:
        raise ValueError("A tomada 3D precisa ter de 2 a 300 quadros.")
    height, width = grays[0].shape
    if calibration:
        matrix = np.array(calibration["intrinsics"], dtype=np.float64)
        xyz = np.array(calibration["world_points"], dtype=np.float64)
        pixels = np.array(calibration["image_points"], dtype=np.float32) * [width, height]
        if (len(xyz) != len(pixels) or matrix[0, 0] <= 0 or matrix[1, 1] <= 0
                or not np.allclose(matrix[2], [0, 0, 1]) or matrix[0, 1] or matrix[1, 0]):
            raise ValueError("Intrínsecos pinhole e correspondências da tomada são obrigatórios.")
        if np.linalg.matrix_rank(xyz - xyz.mean(axis=0)) < 3:
            raise ValueError("Os pontos de calibração precisam ocupar profundidades distintas.")
        positions, visible = _track(grays, pixels)
        indices = np.arange(len(xyz))
        mode = "calibrated_pnp"
    else:
        focal = max(width, height) * 1.15
        matrix = np.array([[focal, 0., width / 2], [0., focal, height / 2], [0., 0., 1.]])
        mask = None if exclude is None else np.where(exclude, 0, 255).astype(np.uint8)
        corners = cv2.goodFeaturesToTrack(grays[0], 360, .008, 5, mask=mask)
        if corners is None or len(corners) < 16:
            raise ValueError("O plano tem poucos pontos de fundo para resolver a câmera.")
        positions, visible = _track(grays, corners)
        xyz, indices = _reconstruct(matrix, positions, visible)
        mode = "relative_two_view_pnp_assumed_intrinsics"

    cameras = []
    for frame, (pixels, valid) in enumerate(zip(positions[:, indices], visible[:, indices])):
        try:
            cameras.append(_solve(matrix, xyz[valid], pixels[valid]))
        except ValueError as exc:
            raise ValueError(f"Tracking 3D sem cobertura no quadro {frame} da aplicação. {exc}") from exc
    rotation, translation = np.asarray(cameras[0]["R"]), np.asarray(cameras[0]["t"])
    camera_points = xyz @ rotation.T + translation
    positive = camera_points[:, 2] > 0
    if not np.any(positive):
        raise ValueError("A tomada não tem geometria à frente da câmera.")
    pixel = np.array(anchor or [.54, .42]) * [width, height]
    neighbors = np.argsort(np.linalg.norm(positions[0, indices][positive] - pixel, axis=1))[:7]
    distance = float(np.median(camera_points[positive][neighbors, 2]))
    center = (np.linalg.solve(matrix, [*pixel, 1.]) * (distance * .85) - translation) @ rotation
    horizontal, vertical, forward = rotation
    card_width = distance * .85 * size_fraction * width / matrix[0, 0]
    return {"method": mode, "raster": [width, height], "cameras": cameras,
            "center": center.tolist(), "axes": [horizontal.tolist(), vertical.tolist(), forward.tolist()],
            "card_width": card_width}

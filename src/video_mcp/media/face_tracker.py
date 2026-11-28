"""OpenCV-based speaker/face horizontal center estimator for smart 9:16 reframing."""

from __future__ import annotations

import asyncio
import statistics
from pathlib import Path


def estimate_face_center_x_sync(video_path: Path, max_samples: int = 12) -> float:
    """Return normalized horizontal center [0.0, 1.0] of detected faces, or 0.5 fallback."""
    if not video_path.is_file():
        return 0.5
    try:
        import cv2  # type: ignore[import-not-found]
    except ImportError:
        return 0.5

    if not hasattr(cv2, "CascadeClassifier") or not hasattr(cv2, "data"):
        return 0.5

    cascade_path = str(Path(cv2.data.haarcascades) / "haarcascade_frontalface_default.xml")
    detector = cv2.CascadeClassifier(cascade_path)
    if detector.empty():
        return 0.5

    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        return 0.5

    try:
        frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
        if frame_count <= 0 or width <= 0:
            return 0.5

        step = max(1, frame_count // max_samples)
        centers: list[float] = []
        for idx in range(0, frame_count, step):
            cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
            ok, frame = cap.read()
            if not ok or frame is None:
                continue
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            faces = detector.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=5, minSize=(40, 40))
            if len(faces) > 0:
                # Pick largest face in frame
                x, _y, w, _h = max(faces, key=lambda f: int(f[2]) * int(f[3]))
                centers.append(min(1.0, max(0.0, (x + w / 2.0) / width)))

        if not centers:
            return 0.5
        return round(float(statistics.median(centers)), 4)
    finally:
        cap.release()


async def estimate_face_center_x(video_path: Path, max_samples: int = 12) -> float:
    """Async wrapper for `estimate_face_center_x_sync`."""
    return await asyncio.to_thread(estimate_face_center_x_sync, video_path, max_samples)

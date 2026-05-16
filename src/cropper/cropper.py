"""
Etapa 4 - Orquestrador do reenquadramento vertical COM TRACKING DINAMICO.

O que esse modulo faz:
    Pega um clip viral (start/end no video original) e produz um arquivo
    .mp4 vertical 1080x1920. O crop ACOMPANHA o rosto da pessoa durante
    o clip todo (tracking dinamico frame-a-frame), nao e estatico.

Pipeline interno:
    1. detect_face_trajectory()  -> trajetoria bruta (samples a 5 fps)
    2. smooth_trajectory()       -> suaviza pra evitar tremida
    3. save_crop_plan()          -> salva .crop.json (editavel pelo usuario)
    4. apply_crop_with_ffmpeg()  -> pipeline OpenCV + FFmpeg pipe:
        - OpenCV le cada frame do video
        - Calcula x_center interpolado pra esse instante
        - Faz crop dinamico no frame
        - Manda frame cropado via stdin pro FFmpeg
        - FFmpeg encoda H.264 + adiciona o audio original
"""
from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path

from src.analyzer.schemas import ViralAnalysis, ViralClip
from src.common.paths import OUTPUTS_DIR, TEMP_DIR, ensure_dirs, get_video_output_dir
from src.cropper.face_tracker import detect_face_trajectory
from src.cropper.schemas import CropKeyframe, CropPlan
from src.cropper.smoothing import interpolate_x_at_time, smooth_trajectory
from src.cropper.face_tracker import FaceTrajectory, FaceSample

logger = logging.getLogger(__name__)


def build_crop_plan(
    video_path: Path | str,
    clip: ViralClip,
    *,
    sample_fps: float = 5.0,
    smoothing_window: int = 5,
    target_width: int = 1080,
    target_height: int = 1920,
) -> CropPlan:
    """
    Detecta rosto, suaviza, e monta o plano de crop pra um clip.

    Args:
        video_path:       Video original.
        clip:             ViralClip com start/end.
        sample_fps:       Amostras de deteccao por segundo. Default 5.
        smoothing_window: Janela da media movel. Default 5.
        target_width:     Largura do output. Default 1080.
        target_height:    Altura do output. Default 1920.

    Returns:
        CropPlan com keyframes em tempo RELATIVO ao clip (comecando em 0).
    """
    trajectory = detect_face_trajectory(
        video_path,
        start_s=clip.start,
        end_s=clip.end,
        sample_fps=sample_fps,
    )

    smoothed = smooth_trajectory(trajectory, window_size=smoothing_window)

    keyframes = [
        CropKeyframe(
            time=s.time - clip.start,
            x_center=s.x_center,
            detected=s.detected,
            manual=False,
        )
        for s in smoothed.samples
    ]

    return CropPlan(
        clip_title=clip.title,
        clip_start=clip.start,
        clip_end=clip.end,
        source_width=trajectory.source_width,
        source_height=trajectory.source_height,
        target_width=target_width,
        target_height=target_height,
        keyframes=keyframes,
    )


def save_crop_plan(plan: CropPlan, cache_key: str) -> Path:
    """Salva o plano em data/temp/<cache_key>.crop.json (editavel)."""
    ensure_dirs()
    path = TEMP_DIR / f"{cache_key}.crop.json"
    path.write_text(plan.model_dump_json(indent=2), encoding="utf-8")
    logger.info("Plano de crop salvo: %s (editavel manualmente)", path.name)
    return path


def load_crop_plan(cache_key: str) -> CropPlan:
    """Carrega plano salvo (potencialmente editado)."""
    path = TEMP_DIR / f"{cache_key}.crop.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return CropPlan.model_validate(data)


def _plan_to_trajectory(plan: CropPlan) -> FaceTrajectory:
    """
    Converte CropPlan (formato persistido) de volta pra FaceTrajectory
    pra usar com interpolate_x_at_time().

    Helper interno - reaproveita a funcao de interpolacao do smoothing.py.
    """
    samples = [
        FaceSample(time=k.time, x_center=k.x_center,
                   detected=k.detected, confidence=0.0)
        for k in plan.keyframes
    ]
    return FaceTrajectory(
        video_path="", source_width=plan.source_width,
        source_height=plan.source_height, fps=30.0,
        samples=samples, backend="loaded",
    )


def apply_crop_with_ffmpeg(
    video_path: Path | str,
    plan: CropPlan,
    output_path: Path | str,
) -> Path:
    """
    Aplica o plano de crop DINAMICAMENTE frame-a-frame.

    Estrategia tecnica:
        OpenCV nao consegue produzir mp4 H.264 de qualidade boa sozinho.
        FFmpeg sozinho nao consegue fazer crop com trajetoria arbitraria
        (a expressao FFmpeg pra interpolar N keyframes fica enorme).

        Solucao hibrida = melhor dos 2 mundos:
            1. OpenCV: le cada frame, calcula x_center pra aquele instante,
               faz o crop com numpy slicing, e resize pro target final.
            2. FFmpeg via pipe stdin: recebe os frames cropados como raw
               BGR, e encoda H.264 com qualidade alta + mux do audio
               original (com -ss/-to pra alinhar com o clip).

    Args:
        video_path:  Video original.
        plan:        CropPlan ja calculado (keyframes em tempo relativo).
        output_path: Onde salvar o .mp4 vertical resultante.

    Returns:
        Path do arquivo gerado.

    Raises:
        RuntimeError: Se OpenCV nao abrir o video, ou FFmpeg falhar.

    Performance:
        ~25-40 fps de processamento em CPU (i5/Ryzen 5). Um clip de 60s
        leva ~45-90s. FFmpeg encode roda em paralelo via pipe.
    """
    import cv2
    import numpy as np

    if not plan.keyframes:
        raise RuntimeError("CropPlan sem keyframes - rode build_crop_plan primeiro")

    video = Path(video_path).resolve()
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    # ----- Abre video e descobre metadados reais -----
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV nao conseguiu abrir: {video}")

    src_fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    src_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    src_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

    # Calcula dimensoes do crop em pixels da fonte (aspect 9:16)
    crop_w = plan.crop_width_in_source
    crop_h = src_h
    # Garante par (necessario pra H.264)
    if crop_w % 2 != 0:
        crop_w -= 1

    target_w = plan.target_width
    target_h = plan.target_height

    # Trajetoria pra interpolar x_center em qualquer instante
    trajectory = _plan_to_trajectory(plan)

    # Pula pro inicio do clip
    cap.set(cv2.CAP_PROP_POS_MSEC, plan.clip_start * 1000)

    # ----- Inicia FFmpeg como subprocess esperando frames via stdin -----
    # Estrategia: 2 inputs no FFmpeg
    #   Input 0 (stdin) : frames cropados/redimensionados em raw BGR
    #   Input 1 (video) : usa SOMENTE o audio, ja trimado com -ss/-to
    ffmpeg_cmd = [
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
        # Input 0: video frames via stdin
        "-f", "rawvideo",
        "-pix_fmt", "bgr24",
        "-s", f"{target_w}x{target_h}",
        "-r", f"{src_fps}",
        "-i", "-",
        # Input 1: audio do video original (trimado pro clip)
        "-ss", str(plan.clip_start),
        "-to", str(plan.clip_end),
        "-i", str(video),
        # Mapeamento: video do input 0, audio do input 1
        "-map", "0:v",
        "-map", "1:a?",  # ? = opcional (caso video nao tenha audio)
        # Encode
        "-c:v", "libx264", "-preset", "medium", "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "128k",
        "-shortest",          # corta se audio for mais longo que video
        "-movflags", "+faststart",
        str(output),
    ]

    logger.info("Tracking dinamico: %d frames @ %.1ffps (crop %dx%d -> %dx%d)",
                int((plan.clip_end - plan.clip_start) * src_fps),
                src_fps, crop_w, crop_h, target_w, target_h)

    process = subprocess.Popen(
        ffmpeg_cmd,
        stdin=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    frames_written = 0
    try:
        current_t = plan.clip_start
        while current_t < plan.clip_end:
            ok, frame = cap.read()
            if not ok:
                break

            # Tempo RELATIVO ao clip (que e o que o plan usa)
            relative_t = current_t - plan.clip_start

            # x_center interpolado pra esse instante (0.0 a 1.0)
            x_norm = interpolate_x_at_time(trajectory, relative_t)

            # Converte pra pixels: centro do crop no video original
            x_center_px = int(x_norm * src_w)
            x_left = x_center_px - crop_w // 2
            # Clamp pra nao sair do video
            x_left = max(0, min(src_w - crop_w, x_left))

            # Faz crop com numpy slicing (rapido, in-place)
            cropped = frame[:, x_left:x_left + crop_w]

            # Resize pro target final (1080x1920)
            resized = cv2.resize(cropped, (target_w, target_h), interpolation=cv2.INTER_AREA)

            # Envia raw bytes pro FFmpeg via stdin
            try:
                process.stdin.write(resized.tobytes())
            except BrokenPipeError:
                # FFmpeg fechou stdin - provavelmente erro no encode
                break

            frames_written += 1
            current_t += 1.0 / src_fps

    finally:
        cap.release()
        if process.stdin:
            process.stdin.close()
        stderr_output = process.stderr.read().decode("utf-8", errors="replace") if process.stderr else ""
        return_code = process.wait()

    if return_code != 0:
        raise RuntimeError(
            f"FFmpeg falhou (code {return_code}):\n{stderr_output[-1500:]}"
        )

    logger.info("Clip vertical salvo: %s (%d frames escritos)",
                output.name, frames_written)
    return output


def crop_all_clips(
    video_path: Path | str,
    analysis: ViralAnalysis,
    *,
    cache_key_base: str,
    use_cache_plan: bool = False,
    on_clip_progress: "logging.Callable[[int, int], None] | None" = None,
) -> list[Path]:
    """
    Processa TODOS os clips de uma analise e exporta em data/outputs/.

    Args:
        video_path:     Video original.
        analysis:       ViralAnalysis da Etapa 3.
        cache_key_base: Prefixo dos arquivos. Cada clip vira
                        '<base>_clip_1', '<base>_clip_2', etc.
        use_cache_plan: True = carrega .crop.json existente (preserva
                        edicoes manuais). False = regenera.

    Returns:
        Lista de Paths dos MP4s gerados.
    """
    ensure_dirs()
    outputs: list[Path] = []
    total = len(analysis.clips)

    for idx, clip in enumerate(analysis.clips, 1):
        # Notifica progresso sub-etapa antes de processar cada clip.
        # Permite ETA mais preciso no frontend mesmo quando o crop demora.
        if on_clip_progress:
            try:
                on_clip_progress(idx, total)
            except Exception:
                pass

        cache_key = f"{cache_key_base}_clip_{idx}"

        cache_file = TEMP_DIR / f"{cache_key}.crop.json"
        if use_cache_plan and cache_file.exists():
            logger.info("Usando crop_plan existente: %s", cache_file.name)
            plan = load_crop_plan(cache_key)
        else:
            plan = build_crop_plan(video_path, clip)
            save_crop_plan(plan, cache_key)

        # Cada video tem sua propria subpasta em data/outputs/<nome_video>/
        # pra organizacao - shorts de videos diferentes nao se misturam.
        video_dir = get_video_output_dir(cache_key_base)
        out_path = video_dir / f"{cache_key}.mp4"
        apply_crop_with_ffmpeg(video_path, plan, out_path)
        outputs.append(out_path)

    return outputs

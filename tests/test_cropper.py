"""
Testes do cropper que NAO dependem de mediapipe/opencv/ffmpeg instalados.
Pra teste end-to-end, use o CLI: python -m src.cropper.cli ...
"""
import json
from pathlib import Path

import pytest

from src.cropper.face_tracker import FaceSample, FaceTrajectory
from src.cropper.schemas import CropKeyframe, CropPlan
from src.cropper.smoothing import interpolate_x_at_time, smooth_trajectory


def _sample_trajectory(samples):
    """Helper: cria FaceTrajectory de teste."""
    return FaceTrajectory(
        video_path="fake.mp4",
        source_width=1920,
        source_height=1080,
        fps=30.0,
        samples=samples,
    )


def test_smooth_reduz_variancia_dos_x_centers():
    """Tremida virando suavidade: variancia DEVE diminuir."""
    samples = [
        FaceSample(time=0.0, x_center=0.5, detected=True),
        FaceSample(time=0.2, x_center=0.7, detected=True),  # pulo
        FaceSample(time=0.4, x_center=0.4, detected=True),  # volta
        FaceSample(time=0.6, x_center=0.6, detected=True),
        FaceSample(time=0.8, x_center=0.5, detected=True),
    ]
    t = _sample_trajectory(samples)
    smoothed = smooth_trajectory(t, window_size=3)

    # Variancia original vs suavizada
    def variance(xs):
        m = sum(xs) / len(xs)
        return sum((x - m) ** 2 for x in xs) / len(xs)

    orig_var = variance([s.x_center for s in t.samples])
    smooth_var = variance([s.x_center for s in smoothed.samples])
    assert smooth_var < orig_var, "Suavizacao deveria diminuir variancia"


def test_smooth_preserva_metadados():
    """Tempo, detected e confidence NAO devem mudar - so x_center."""
    samples = [
        FaceSample(time=0.0, x_center=0.5, detected=False, confidence=0.0),
        FaceSample(time=0.2, x_center=0.8, detected=True, confidence=0.95),
    ]
    smoothed = smooth_trajectory(_sample_trajectory(samples), window_size=3)
    assert smoothed.samples[0].time == 0.0
    assert smoothed.samples[0].detected is False
    assert smoothed.samples[1].detected is True
    assert smoothed.samples[1].confidence == 0.95


def test_interpolate_dentro_do_intervalo():
    """Interpola linearmente entre 2 keyframes."""
    samples = [
        FaceSample(time=0.0, x_center=0.4, detected=True),
        FaceSample(time=1.0, x_center=0.6, detected=True),
    ]
    t = _sample_trajectory(samples)
    # Meio do caminho = media
    assert abs(interpolate_x_at_time(t, 0.5) - 0.5) < 1e-9
    # 1/4 do caminho
    assert abs(interpolate_x_at_time(t, 0.25) - 0.45) < 1e-9


def test_interpolate_fora_do_intervalo_usa_borda():
    samples = [
        FaceSample(time=1.0, x_center=0.3, detected=True),
        FaceSample(time=2.0, x_center=0.7, detected=True),
    ]
    t = _sample_trajectory(samples)
    assert interpolate_x_at_time(t, 0.0) == 0.3  # antes do primeiro
    assert interpolate_x_at_time(t, 3.0) == 0.7  # depois do ultimo


def test_crop_plan_calcula_largura_correta():
    """Aspect ratio 9:16: crop_width = source_height * 9/16."""
    plan = CropPlan(
        clip_title="teste", clip_start=0, clip_end=10,
        source_width=1920, source_height=1080,
        target_width=1080, target_height=1920,
        keyframes=[],
    )
    # 1080 * 1080/1920 = 607.5 -> 607
    assert plan.crop_width_in_source == 607


def test_crop_keyframe_valida_x_center_fora_de_range():
    """Pydantic deve recusar x_center > 1.0 (validacao automatica do schema)."""
    with pytest.raises(Exception):
        CropKeyframe(time=0.0, x_center=1.5)
    with pytest.raises(Exception):
        CropKeyframe(time=0.0, x_center=-0.1)


def test_crop_plan_round_trip_json(tmp_path: Path):
    """Salvar e carregar JSON preserva todos os campos."""
    original = CropPlan(
        clip_title="Pregacao top",
        clip_start=120.0,
        clip_end=180.0,
        source_width=1920, source_height=1080,
        keyframes=[
            CropKeyframe(time=0.0, x_center=0.5, detected=True, manual=False),
            CropKeyframe(time=5.0, x_center=0.7, detected=False, manual=True),
        ],
    )
    path = tmp_path / "test.crop.json"
    path.write_text(original.model_dump_json(indent=2), encoding="utf-8")

    loaded = CropPlan.model_validate(json.loads(path.read_text(encoding="utf-8")))
    assert loaded.clip_title == "Pregacao top"
    assert len(loaded.keyframes) == 2
    assert loaded.keyframes[1].manual is True

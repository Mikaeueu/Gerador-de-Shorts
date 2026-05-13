"""
Etapa 4b - Suavizacao da trajetoria do crop.

O problema que esse modulo resolve:
    Detecao de rosto frame a frame produz uma trajetoria "trementetremida":
    o x_center pula 50 pixels pra um lado e pro outro entre frames vizinhos,
    mesmo que a pessoa esteja parada. Isso ficaria HORRIVEL no video final
    (o crop ficaria vibrando).

A solucao: SUAVIZAR.
    Aplicamos uma media movel sobre os samples, calculando o x_center
    "verdadeiro" como a media dos vizinhos. Resultado: movimento suave,
    natural, igual ao do Opus Clip.

Por que media movel e nao filtro de Kalman (que e "mais correto"):
    - Media movel e simples de implementar e debugar.
    - Pra rosto humano falando, o resultado e indistinguivel pro usuario.
    - Kalman precisa de tuning fino (covariance matrix) que e overkill.
    - Se um dia precisarmos de algo mais sofisticado, e facil trocar.
"""
from __future__ import annotations

import logging
from dataclasses import replace

from src.cropper.face_tracker import FaceSample, FaceTrajectory

logger = logging.getLogger(__name__)


def smooth_trajectory(
    trajectory: FaceTrajectory,
    window_size: int = 5,
) -> FaceTrajectory:
    """
    Aplica media movel sobre o x_center dos samples.

    Args:
        trajectory: FaceTrajectory original (com possivel "tremida" frame-a-frame).
        window_size: Quantos samples vizinhos considerar na media.
                     Tamanho IMPAR e recomendado (centralizado).
                     Default 5 = considera o atual + 2 antes + 2 depois.
                     - Janela pequena (3): suaviza pouco, mantem movimento rapido.
                     - Janela media (5-7): bom equilibrio (default).
                     - Janela grande (15+): bem suave mas pode "atrasar" o rosto.

    Returns:
        Nova FaceTrajectory com samples suavizados.
        NAO modifica a original (imutabilidade ajuda debugging).

    Detalhes:
        - Samples nas bordas (sem vizinhos suficientes) usam janela menor.
        - Samples com detected=False MANTEM esse flag (pra rastreabilidade),
          mas o x_center ainda e suavizado normalmente.
        - O time de cada sample fica intocado.

    Exemplo:
        Trajetoria original:  [0.5, 0.7, 0.4, 0.6, 0.5]
        Apos smooth (w=3):    [0.6, 0.53, 0.57, 0.5, 0.55]
                                ^     ^
                                |     media dos vizinhos
                                media (so 2 disponiveis nas bordas)
    """
    if not trajectory.samples:
        return trajectory

    half = window_size // 2
    smoothed_samples: list[FaceSample] = []

    for i, sample in enumerate(trajectory.samples):
        # Pega os vizinhos dentro da janela (lidando com bordas)
        start = max(0, i - half)
        end = min(len(trajectory.samples), i + half + 1)
        window = trajectory.samples[start:end]

        # Media dos x_center na janela
        avg_x = sum(s.x_center for s in window) / len(window)

        # `replace` cria uma copia do dataclass com campos alterados.
        # Mantemos time/detected/confidence; soh trocamos x_center.
        smoothed_samples.append(replace(sample, x_center=avg_x))

    logger.debug("Suavizado %d samples com janela %d", len(smoothed_samples), window_size)

    return FaceTrajectory(
        video_path=trajectory.video_path,
        source_width=trajectory.source_width,
        source_height=trajectory.source_height,
        fps=trajectory.fps,
        samples=smoothed_samples,
    )


def interpolate_x_at_time(trajectory: FaceTrajectory, t: float) -> float:
    """
    Calcula x_center em um instante qualquer t, interpolando entre samples.

    Pra que serve:
        A trajetoria tem amostras a cada 0.2s (5 fps), mas o video tem
        30 fps. Pra cada frame do video, precisamos saber x_center exato
        naquele instante - interpolamos linearmente entre samples adjacentes.

    Args:
        trajectory: FaceTrajectory ja suavizada.
        t:          Tempo em segundos.

    Returns:
        x_center interpolado (0.0-1.0). Se t estiver fora do range
        dos samples, retorna o sample mais proximo (extrapolacao "flat").

    Exemplo:
        Samples: [(0.0, 0.5), (0.2, 0.6), (0.4, 0.55)]
        interpolate_x_at_time(0.1) = 0.55 (meio entre 0.5 e 0.6)
        interpolate_x_at_time(0.5) = 0.55 (extrapola = mesmo do ultimo)
    """
    if not trajectory.samples:
        return 0.5  # centro fallback

    # Antes do primeiro sample: usa o primeiro
    if t <= trajectory.samples[0].time:
        return trajectory.samples[0].x_center

    # Depois do ultimo sample: usa o ultimo
    if t >= trajectory.samples[-1].time:
        return trajectory.samples[-1].x_center

    # Acha os dois samples que cercam o tempo t
    for i in range(len(trajectory.samples) - 1):
        s1 = trajectory.samples[i]
        s2 = trajectory.samples[i + 1]
        if s1.time <= t <= s2.time:
            # Interpolacao linear: peso pela distancia temporal
            ratio = (t - s1.time) / (s2.time - s1.time) if s2.time > s1.time else 0.0
            return s1.x_center + (s2.x_center - s1.x_center) * ratio

    # Nao deve chegar aqui, mas fallback de seguranca
    return 0.5

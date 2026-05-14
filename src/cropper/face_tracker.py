"""
Etapa 4a - Deteccao de rosto frame a frame.

Backends de deteccao (escolhidos automaticamente em runtime):
    1. OpenCV YuNet (PRIMARIO)
       - Detector CNN leve, otimizado pra CPU
       - Muito mais preciso que Haar (especialmente em angulos)
       - Vem com OpenCV 4.5.4+ - sem deps extras
       - Modelo ONNX baixado automaticamente (~340KB)

    2. OpenCV Haar Cascade (FALLBACK)
       - Funciona em qualquer versao do OpenCV
       - Usado se YuNet falhar (sem internet pra baixar modelo, etc.)

Por que removemos o MediaPipe:
    Versoes 0.10.30+ no Windows quebraram TODAS as rotas de import legacy.
    YuNet substitui com vantagens: melhor precisao, sem inferno de versoes.

Como o x_center funciona:
    Retornamos x_center NORMALIZADO entre 0.0 e 1.0:
        0.0 = canto ESQUERDO, 0.5 = CENTRO, 1.0 = canto DIREITO.
"""
from __future__ import annotations

import logging
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from src.common.paths import DATA_DIR

logger = logging.getLogger(__name__)


# ============================================================
# Modelo YuNet - download automatico
# ============================================================

YUNET_MODEL_URL = (
    "https://github.com/opencv/opencv_zoo/raw/main/models/"
    "face_detection_yunet/face_detection_yunet_2023mar.onnx"
)
YUNET_MODEL_DIR = DATA_DIR / "models"
YUNET_MODEL_PATH = YUNET_MODEL_DIR / "face_detection_yunet_2023mar.onnx"


def _ensure_yunet_model() -> Path | None:
    """Garante que o modelo YuNet esta no disco. Baixa se necessario."""
    if YUNET_MODEL_PATH.exists():
        return YUNET_MODEL_PATH

    YUNET_MODEL_DIR.mkdir(parents=True, exist_ok=True)
    logger.info("Baixando modelo YuNet (~340KB) de %s...", YUNET_MODEL_URL)
    try:
        urllib.request.urlretrieve(YUNET_MODEL_URL, YUNET_MODEL_PATH)
        logger.info("Modelo YuNet salvo em %s", YUNET_MODEL_PATH)
        return YUNET_MODEL_PATH
    except Exception as e:
        logger.warning("Falha ao baixar modelo YuNet (%s: %s). Usando fallback Haar.",
                       type(e).__name__, e)
        if YUNET_MODEL_PATH.exists():
            try:
                YUNET_MODEL_PATH.unlink()
            except Exception:
                pass
        return None


# ============================================================
# Detector abstrato + 2 implementacoes
# ============================================================

class _YuNetDetector:
    """
    Detector usando OpenCV YuNet (cv2.FaceDetectorYN).

    Modelo CNN leve (~340KB) otimizado pra CPU. Disponivel desde
    OpenCV 4.5.4. Vantagens sobre Haar:
        - Detecta em angulos diversos (nao so frontal puro)
        - Score de confianca real (0-1)
        - Mais preciso, menos falsos positivos
        - Quase tao rapido quanto Haar
    """
    def __init__(self, model_path: Path):
        import cv2
        self._cv2 = cv2
        # input_size sera ajustado por frame via setInputSize()
        self._detector = cv2.FaceDetectorYN.create(
            model=str(model_path),
            config="",
            input_size=(320, 320),
            score_threshold=0.7,    # alta confianca = menos falsos positivos
            nms_threshold=0.3,
            top_k=5000,
        )
        self._last_size = (0, 0)

    def detect(self, frame_bgr):
        """
        Detecta rosto em um frame BGR.

        Returns:
            (x_center_normalizado, confidence) ou None.
        """
        h, w = frame_bgr.shape[:2]
        # YuNet exige setInputSize quando a resolucao muda.
        if (w, h) != self._last_size:
            self._detector.setInputSize((w, h))
            self._last_size = (w, h)

        # detect() -> (retval, faces). faces e None se nada achado,
        # ou ndarray (N x 15): [x, y, w, h, lmk0_x, ..., lmk4_y, score]
        retval, faces = self._detector.detect(frame_bgr)
        if faces is None or len(faces) == 0:
            return None

        scores = faces[:, -1]
        best_idx = int(scores.argmax())
        best = faces[best_idx]
        x, y, fw, fh = best[0], best[1], best[2], best[3]
        score = float(best[-1])

        x_center = (x + fw / 2.0) / w
        x_center = max(0.0, min(1.0, x_center))
        return float(x_center), score

    def close(self):
        pass  # YuNet nao tem recursos pra liberar


class _HaarCascadeDetector:
    """
    Detector fallback usando OpenCV Haar Cascade frontal face.

    Vantagens:
        - Vem dentro do opencv-python, sem instalar nada extra.
        - Funciona com qualquer versao do OpenCV.
    Desvantagens:
        - Menos preciso que YuNet em angulos/iluminacao ruim.
        - Funciona muito bem pra rosto frontal (caso de pregacao).
    """
    def __init__(self):
        import cv2
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(cascade_path)
        if self._cascade.empty():
            raise RuntimeError(f"Haar cascade nao encontrado em: {cascade_path}")

    def detect(self, frame_bgr):
        """
        Detecta rosto via Haar.

        Returns:
            (x_center_normalizado, confidence_proxy) ou None.
            Como Haar nao tem score, usamos area do rosto / area do frame
            como proxy de confidence.
        """
        import cv2
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        faces = self._cascade.detectMultiScale(
            gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60)
        )
        if len(faces) == 0:
            return None
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        frame_h, frame_w = frame_bgr.shape[:2]
        x_center = (x + w / 2) / frame_w
        confidence = (w * h) / (frame_w * frame_h)
        return float(x_center), float(min(confidence * 10, 1.0))

    def close(self):
        pass


def _create_face_detector():
    """
    Cria o melhor detector disponivel: YuNet se possivel, senao Haar.

    Ordem:
        1. YuNet (CNN moderno, melhor precisao)
        2. Haar Cascade (fallback sempre disponivel)

    Returns:
        Tupla (detector, backend_name).
    """
    # Tentativa 1: YuNet
    model_path = _ensure_yunet_model()
    if model_path is not None:
        try:
            detector = _YuNetDetector(model_path)
            logger.info("Face detector: YuNet (preferido)")
            return detector, "yunet"
        except Exception as e:
            logger.warning(
                "YuNet falhou ao inicializar (%s: %s). Caindo pra Haar.",
                type(e).__name__, e,
            )

    # Tentativa 2: Haar Cascade
    detector = _HaarCascadeDetector()
    logger.info("Face detector: Haar Cascade (fallback)")
    return detector, "haar_cascade"


# ============================================================
# Dataclasses do output
# ============================================================

@dataclass
class FaceSample:
    """
    Uma amostra de deteccao de rosto em um instante do video.

    Attributes:
        time:       Tempo em segundos desde o inicio do video.
        x_center:   Posicao horizontal NORMALIZADA do centro (0.0-1.0).
        detected:   True se algum detector achou. False = fallback.
        confidence: Score do detector (0-1). 0 quando nao detectado.
    """
    time: float
    x_center: float
    detected: bool
    confidence: float = 0.0


@dataclass
class FaceTrajectory:
    """
    Trajetoria completa de deteccao de rosto durante um clip.
    """
    video_path: str
    source_width: int
    source_height: int
    fps: float
    samples: list[FaceSample] = field(default_factory=list)
    backend: str = "unknown"

    def detected_ratio(self) -> float:
        """Porcentagem de samples onde um rosto foi detectado."""
        if not self.samples:
            return 0.0
        detected = sum(1 for s in self.samples if s.detected)
        return detected / len(self.samples)


# ============================================================
# API principal
# ============================================================

def detect_face_trajectory(
    video_path: Path | str,
    start_s: float = 0.0,
    end_s: float | None = None,
    sample_fps: float = 5.0,
    min_confidence: float = 0.5,
) -> FaceTrajectory:
    """
    Detecta a trajetoria horizontal do rosto durante um trecho do video.

    Args:
        video_path:     Caminho do arquivo de video.
        start_s:        Tempo de inicio. Default: 0.
        end_s:          Tempo de fim. None = ate o fim.
        sample_fps:     Amostras por segundo. Default 5.
        min_confidence: Limiar (so usado por detectores que tem score real).

    Returns:
        FaceTrajectory cobrindo [start_s, end_s].

    Raises:
        FileNotFoundError: Video nao existe.
        RuntimeError: OpenCV nao conseguiu abrir o video.

    Estrategia "sticky": quando deteccao falha em algum frame,
    mantemos a ULTIMA posicao detectada conhecida em vez de cair
    pra centro. Evita o "balanco" do crop quando a pessoa fica
    parada e a deteccao oscila.
    """
    import cv2

    path = Path(video_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Video nao encontrado: {path}")

    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"OpenCV nao conseguiu abrir: {path}")

    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    video_duration = total_frames / fps if fps > 0 else 0.0
    end_s = end_s if end_s is not None else video_duration

    detector, backend = _create_face_detector()
    logger.info("Tracking %s [%.1fs-%.1fs] (backend=%s)",
                path.name, start_s, end_s, backend)

    cap.set(cv2.CAP_PROP_POS_MSEC, start_s * 1000)
    sample_interval = 1.0 / sample_fps

    trajectory = FaceTrajectory(
        video_path=str(path),
        source_width=width,
        source_height=height,
        fps=fps,
        backend=backend,
    )

    # Sticky fallback - ver docstring acima
    last_known_x: float = 0.5
    has_ever_detected = False

    try:
        current_t = start_s
        while current_t < end_s:
            cap.set(cv2.CAP_PROP_POS_MSEC, current_t * 1000)
            ok, frame = cap.read()
            if not ok:
                break

            result = detector.detect(frame)
            if result is not None:
                x_center, confidence = result
                last_known_x = x_center
                has_ever_detected = True
                trajectory.samples.append(FaceSample(
                    time=current_t, x_center=x_center,
                    detected=True, confidence=confidence,
                ))
            else:
                # Sem deteccao: usa ultima posicao conhecida
                trajectory.samples.append(FaceSample(
                    time=current_t, x_center=last_known_x, detected=False,
                ))

            current_t += sample_interval
    finally:
        detector.close()
        cap.release()

    # Passada retroativa: samples no INICIO antes da primeira deteccao
    # recebem o x da primeira deteccao real (evita comecar em centro).
    if has_ever_detected:
        first_detected_x = next(
            (s.x_center for s in trajectory.samples if s.detected), 0.5
        )
        for s in trajectory.samples:
            if s.detected:
                break
            s.x_center = first_detected_x

    logger.info("Tracking concluido: %d samples, %.0f%% detectados",
                len(trajectory.samples), trajectory.detected_ratio() * 100)
    return trajectory

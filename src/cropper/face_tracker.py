"""
Etapa 4a - Deteccao de rosto frame a frame.

O que esse modulo faz:
    Le um video com OpenCV, detecta a posicao do rosto em cada frame,
    e devolve a "trajetoria" do crop: lista de (timestamp, x_center_normalizado).

Backends de deteccao (escolhidos automaticamente em runtime):
    1. MediaPipe Face Detection (preferido)
       - Mais preciso, score de confianca nativo
       - Sofre com diferentes versoes do pip no Windows (API muda muito)

    2. OpenCV Haar Cascade (fallback automatico)
       - Funciona em QUALQUER versao do OpenCV (vem incluido)
       - Sem dependencia extra
       - Suficiente pra pregador frontal e bem iluminado (caso comum)
       - Detecta menos confiavel em angulos extremos

Como o x_center funciona:
    Retornamos x_center NORMALIZADO entre 0.0 e 1.0:
        0.0 = canto ESQUERDO, 0.5 = CENTRO, 1.0 = canto DIREITO.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


# ============================================================
# Detector abstrato + 2 implementacoes (MediaPipe / Haar Cascade)
# ============================================================

class _MediaPipeDetector:
    """
    Detector usando MediaPipe Face Detection (API legacy 'solutions').

    Tentamos varias rotas de import porque a API mudou entre versoes
    do mediapipe e algumas distribuicoes pip nao expoem o submodulo
    'solutions' da forma esperada.
    """
    def __init__(self):
        face_detection = self._import_face_detection()
        # model_selection=1 = bom pra video (alcance 5m), 0 = selfie close-up
        self._detector = face_detection.FaceDetection(
            model_selection=1, min_detection_confidence=0.5
        )

    @staticmethod
    def _import_face_detection():
        """Tenta importar mediapipe.solutions.face_detection via varias rotas."""
        try:
            from mediapipe.solutions import face_detection
            return face_detection
        except Exception:
            pass
        try:
            from mediapipe.python.solutions import face_detection  # type: ignore
            return face_detection
        except Exception:
            pass
        import mediapipe as mp
        return mp.solutions.face_detection  # pode lancar AttributeError

    def detect(self, frame_bgr):
        """
        Detecta rosto em um frame BGR (OpenCV).

        Returns:
            tuple (x_center_normalizado, confidence) se achar,
            ou None se nao detectar.
        """
        import cv2
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        result = self._detector.process(rgb)
        if not result.detections:
            return None
        best = max(result.detections, key=lambda d: d.score[0])
        bbox = best.location_data.relative_bounding_box
        x_center = bbox.xmin + bbox.width / 2.0
        x_center = max(0.0, min(1.0, x_center))
        return x_center, float(best.score[0])

    def close(self):
        self._detector.close()


class _HaarCascadeDetector:
    """
    Detector fallback usando OpenCV Haar Cascade frontal face.

    Vantagens:
        - Vem dentro do opencv-python, sem instalar nada extra.
        - Funciona com qualquer versao do OpenCV.
    Desvantagens:
        - Menos preciso que MediaPipe em angulos/iluminacao ruim.
        - Funciona MUITO bem pra rosto frontal (caso de pregacao).
    """
    def __init__(self):
        import cv2
        # cv2.data.haarcascades aponta pra pasta dos XMLs incluidos no opencv-python.
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        self._cascade = cv2.CascadeClassifier(cascade_path)
        if self._cascade.empty():
            raise RuntimeError(f"Haar cascade nao encontrado em: {cascade_path}")

    def detect(self, frame_bgr):
        """
        Detecta rosto via Haar.

        Returns:
            (x_center_normalizado, confidence_proxy) ou None.
            Como Haar nao tem score, usamos AREA do rosto / area do frame
            como proxy de confidence (rosto maior = mais provavel real).
        """
        import cv2
        gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
        # detectMultiScale parametros:
        #   scaleFactor=1.2 -> reduz imagem em 20% a cada passe (mais rapido que 1.1)
        #   minNeighbors=5  -> 5 deteccoes vizinhas confirmam (filtra falsos positivos)
        #   minSize=(60,60) -> ignora rostos menores que 60px (lixo)
        faces = self._cascade.detectMultiScale(
            gray, scaleFactor=1.2, minNeighbors=5, minSize=(60, 60)
        )
        if len(faces) == 0:
            return None
        # Pega o maior rosto (geralmente o principal)
        x, y, w, h = max(faces, key=lambda f: f[2] * f[3])
        frame_h, frame_w = frame_bgr.shape[:2]
        x_center = (x + w / 2) / frame_w
        # confidence proxy: area do rosto / area do frame
        confidence = (w * h) / (frame_w * frame_h)
        return float(x_center), float(min(confidence * 10, 1.0))

    def close(self):
        pass  # nada pra fechar


def _create_face_detector():
    """
    Cria o melhor detector disponivel: MediaPipe se possivel, senao Haar Cascade.

    Returns:
        Tupla (detector, backend_name) onde backend_name e 'mediapipe' ou 'haar_cascade'.
    """
    try:
        detector = _MediaPipeDetector()
        logger.info("Face detector: MediaPipe (preferido)")
        return detector, "mediapipe"
    except Exception as e:
        logger.warning(
            "MediaPipe indisponivel (%s: %s). Usando OpenCV Haar Cascade como fallback.",
            type(e).__name__, e,
        )
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
        x_center:   Posicao horizontal NORMALIZADA do centro do rosto (0.0-1.0).
        detected:   True se algum detector achou um rosto. False = fallback (centro).
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

    Attributes:
        video_path:    Caminho do video de origem.
        source_width:  Largura original em pixels.
        source_height: Altura original em pixels.
        fps:           Frames per second do video.
        samples:       Lista de FaceSample em ordem cronologica.
        backend:       Qual detector foi usado ('mediapipe' ou 'haar_cascade').
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
        start_s:        Tempo de inicio (segundos). Default: 0.
        end_s:          Tempo de fim. None = ate o fim do video.
        sample_fps:     Amostras por segundo. Default 5 (5 fps).
        min_confidence: Limiar de confianca pro detector que suporta score.
                        Pro Haar (sem score real), e ignorado.

    Returns:
        FaceTrajectory cobrindo [start_s, end_s]. Quando nenhum detector
        acha rosto, x_center=0.5 e detected=False.

    Raises:
        FileNotFoundError: Video nao existe.
        RuntimeError: OpenCV nao conseguiu abrir o video.
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

    # Estrategia "sticky": quando o detector falha em algum frame,
    # mantemos a ULTIMA posicao detectada conhecida. Isso evita o
    # comportamento amador de "balanco" - antes, frames sem deteccao
    # caiam pra x_center=0.5 (centro), e quando a pessoa esta parada
    # mas nao no centro, o crop ficava pulando entre o real e o centro.
    #
    # Inicializamos com 0.5 (centro) como fallback se NUNCA detectarmos
    # nada no clip todo (raro, mas precisamos de um valor inicial).
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
                last_known_x = x_center  # atualiza memoria
                has_ever_detected = True
                trajectory.samples.append(FaceSample(
                    time=current_t, x_center=x_center,
                    detected=True, confidence=confidence,
                ))
            else:
                # Sem deteccao: usa ultima posicao conhecida.
                # Se nunca detectamos antes, last_known_x=0.5 (centro).
                trajectory.samples.append(FaceSample(
                    time=current_t, x_center=last_known_x, detected=False,
                ))

            current_t += sample_interval
    finally:
        detector.close()
        cap.release()

    # Se conseguimos detectar em algum momento, fazemos uma "passada
    # retroativa": samples NO INICIO do clip que cairam no fallback
    # (antes de qualquer deteccao real) recebem o x da PRIMEIRA deteccao.
    # Isso evita que o clip comece em x=0.5 antes de ir pra posicao certa.
    if has_ever_detected:
        first_detected_x = next(
            (s.x_center for s in trajectory.samples if s.detected), 0.5
        )
        for s in trajectory.samples:
            if s.detected:
                break  # primeiro detectado - parar aqui
            s.x_center = first_detected_x

    logger.info("Tracking concluido: %d samples, %.0f%% detectados",
                len(trajectory.samples), trajectory.detected_ratio() * 100)
    return trajectory

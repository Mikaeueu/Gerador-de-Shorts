"""
Schemas Pydantic da Etapa 4.

Esses schemas tem 2 papeis:
    1. Representar a trajetoria do crop em memoria.
    2. Persistir em data/temp/<nome>.crop.json para o usuario poder
       EDITAR MANUALMENTE depois (se o tracking automatico errou).

Formato do crop.json:
    Eh propositalmente simples e editavel a mao em qualquer editor de texto.
    Cada keyframe tem 'time' (segundos) e 'x_center' (0.0 a 1.0).
    Entre keyframes interpolamos linearmente.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CropKeyframe(BaseModel):
    """
    Um ponto-chave da trajetoria do crop.

    Attributes:
        time:     Tempo em segundos (relativo ao inicio do CLIP, nao do video).
        x_center: Posicao horizontal normalizada (0.0 = esquerda, 1.0 = direita).
        detected: True se MediaPipe detectou rosto; False = fallback central.
                  Util pra UI futura mostrar quais keyframes foram "chutados".
        manual:   True se o usuario editou esse keyframe manualmente no JSON.
                  Indica pra nao sobrescrever em rerruns.
    """
    time: float = Field(..., description="Tempo em segundos relativo ao clip")
    x_center: float = Field(..., ge=0.0, le=1.0, description="Posicao horizontal 0-1")
    detected: bool = Field(default=True, description="Se MediaPipe detectou rosto aqui")
    manual: bool = Field(default=False, description="Se editado manualmente pelo usuario")


class CropPlan(BaseModel):
    """
    Plano completo de crop pra UM clip viral.

    Esse e o objeto que vai e volta pro disco (.crop.json), permitindo
    que o usuario edite manualmente se o tracking errou.

    Attributes:
        clip_title:     Titulo do clip vindo da Etapa 3 (pra identificacao).
        clip_start:     Inicio do clip no video original (segundos).
        clip_end:       Fim do clip no video original.
        source_width:   Largura original em pixels.
        source_height:  Altura original em pixels.
        target_width:   Largura do output vertical. Default 1080.
        target_height:  Altura do output. Default 1920.
        keyframes:      Lista de CropKeyframe em ordem cronologica.
                        Tempos em SEGUNDOS RELATIVOS ao clip (nao ao video).
    """
    clip_title: str
    clip_start: float
    clip_end: float
    source_width: int
    source_height: int
    target_width: int = 1080
    target_height: int = 1920
    keyframes: list[CropKeyframe] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        """Duracao do clip em segundos."""
        return self.clip_end - self.clip_start

    @property
    def crop_width_in_source(self) -> int:
        """
        Largura do crop em pixels do video ORIGINAL.

        Por que esse calculo:
            Pra manter aspect ratio 9:16, a largura do crop e calculada
            a partir da altura ORIGINAL do video:
                crop_w = source_height * (9/16)
            Ex: video 1920x1080 -> crop_w = 1080 * 9/16 = 607 pixels.
        """
        return int(self.source_height * (self.target_width / self.target_height))

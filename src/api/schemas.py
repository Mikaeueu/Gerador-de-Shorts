"""
Schemas Pydantic da API - representam jobs e mensagens via HTTP/WebSocket.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


# ============================================================
# Enums
# ============================================================

class JobStatus(str, Enum):
    """Estados possiveis de um job."""
    queued = "queued"        # criado mas ainda nao comecou
    running = "running"      # processando agora
    done = "done"            # concluido com sucesso
    failed = "failed"        # erro durante processamento
    cancelled = "cancelled"  # cancelado pelo usuario via DELETE/cancel


# ============================================================
# Job
# ============================================================

class JobParams(BaseModel):
    """
    Parametros pro pipeline (espelha args do run_pipeline).

    Os 4 parametros dependentes de template (min/max_clip_seconds,
    max_clips, min_score) sao Optional - quando None, o analyzer usa
    os smart defaults do template escolhido (ex: gameplay_humor usa
    15-60s/8 clips, evangelical_preaching usa 45-90s/5 clips).
    """
    whisper_model: str = "base"
    language: Optional[str] = None
    refine: bool = True
    refine_context: str = "pregacao evangelica em portugues do Brasil"
    template: str = "evangelical_preaching"
    # Optional: None = usa default do template
    min_clip_seconds: Optional[float] = None
    max_clip_seconds: Optional[float] = None
    max_clips: Optional[int] = None
    min_score: Optional[float] = None
    font_size: int = 90
    words_per_chunk: int = 3
    fade_out_seconds: float = 3.0


class Job(BaseModel):
    """
    Estado completo de um job de processamento.

    Persistido em data/jobs/{id}.json.
    """
    id: str = Field(..., description="UUID unico do job")
    status: JobStatus = JobStatus.queued
    source: str = Field(..., description="URL ou caminho do arquivo de origem")
    source_kind: str = Field(..., description="'url' ou 'upload'")
    params: JobParams = Field(default_factory=JobParams)

    # Progresso
    stage: Optional[str] = Field(None, description="Etapa atual")
    message: Optional[str] = Field(None, description="Mensagem humana do estado")
    percent: int = Field(0, ge=0, le=100, description="Progresso 0-100")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # Resultado
    clips: list[str] = Field(default_factory=list,
                              description="Nomes dos MP4s finais (relativos a data/outputs/)")
    error: Optional[str] = Field(None, description="Stack trace / mensagem de erro")
    cache_key: Optional[str] = Field(None,
                                     description="Stem do video original (pra cleanup em data/temp/ e data/outputs/)")


# ============================================================
# Requests
# ============================================================

class JobCreateRequestUrl(BaseModel):
    """Body pra POST /jobs com URL (JSON)."""
    source: str = Field(..., description="URL do YouTube ou caminho local")
    params: Optional[JobParams] = None


# ============================================================
# Mensagem WebSocket de progresso
# ============================================================

class ProgressMessage(BaseModel):
    """
    Mensagem enviada via WebSocket durante o processamento.

    O frontend deve esperar esse formato em cada mensagem JSON.
    """
    job_id: str
    status: JobStatus
    stage: str = Field(..., description="Etapa atual (download/transcribe/refine/analyze/crop/caption)")
    message: str = Field(..., description="Mensagem humana")
    percent: int = Field(..., ge=0, le=100)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

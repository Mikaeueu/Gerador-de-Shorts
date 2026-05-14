"""
Schemas Pydantic da API - representam jobs e mensagens via HTTP/WebSocket.

Esses models sao serializados pra JSON automaticamente pelo FastAPI nas
respostas HTTP e nas mensagens WebSocket.
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
    """
    Estados possiveis de um job.

    Fluxo normal: queued -> running -> done.
    Fluxo de erro: queued -> running -> failed.
    """
    queued = "queued"      # criado mas ainda nao comecou
    running = "running"    # processando agora
    done = "done"          # concluido com sucesso
    failed = "failed"      # erro durante processamento


# ============================================================
# Job
# ============================================================

class JobParams(BaseModel):
    """Parametros pro pipeline (espelha args do run_pipeline)."""
    whisper_model: str = "base"
    language: Optional[str] = None
    refine: bool = True
    refine_context: str = "pregacao evangelica em portugues do Brasil"
    template: str = "evangelical_preaching"
    min_clip_seconds: float = 45
    max_clip_seconds: float = 90
    max_clips: int = 5
    min_score: float = 7.0
    font_size: int = 90
    words_per_chunk: int = 3
    fade_out_seconds: float = 3.0


class Job(BaseModel):
    """
    Estado completo de um job de processamento.

    Persistido em data/jobs/{id}.json. Cada update sobrescreve o arquivo.
    """
    id: str = Field(..., description="UUID unico do job")
    status: JobStatus = JobStatus.queued
    source: str = Field(..., description="URL ou caminho do arquivo de origem")
    source_kind: str = Field(..., description="'url' ou 'upload'")
    params: JobParams = Field(default_factory=JobParams)

    # Progresso
    stage: Optional[str] = Field(None, description="Etapa atual (download/transcribe/...)")
    message: Optional[str] = Field(None, description="Mensagem humana do estado atual")
    percent: int = Field(0, ge=0, le=100, description="Progresso aproximado 0-100")

    # Timestamps
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: Optional[datetime] = None
    finished_at: Optional[datetime] = None

    # Resultado
    clips: list[str] = Field(default_factory=list,
                              description="Nomes de arquivo dos MP4s finais (relativos a data/outputs/)")
    error: Optional[str] = Field(None, description="Stack trace / mensagem de erro se falhou")


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

    O frontend deve esperar esse formato em cada mensagem JSON do WS.
    """
    job_id: str
    status: JobStatus
    stage: str = Field(..., description="Etapa atual (download/transcribe/refine/analyze/crop/caption)")
    message: str = Field(..., description="Mensagem humana")
    percent: int = Field(..., ge=0, le=100)
    timestamp: datetime = Field(default_factory=datetime.utcnow)

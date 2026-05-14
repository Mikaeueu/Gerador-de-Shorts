"""
JobStore - persistencia de jobs em arquivos JSON.

Por que JSON files (em vez de SQLite/Redis):
    - Sem deps extras alem das que a API ja precisa.
    - Persiste reinicios do server (data/jobs/<id>.json fica no disco).
    - Inspecao manual trivial (abrir o JSON em editor de texto).
    - Suficiente pra dezenas/centenas de jobs (uso pessoal).
    - Migracao pra SQL futura e simples (serializacao ja esta pronta).

Diretorio dos arquivos:
    data/jobs/<job_id>.json - cada job e um arquivo independente.
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from src.api.schemas import Job, JobParams, JobStatus
from src.common.paths import DATA_DIR, ensure_dirs

logger = logging.getLogger(__name__)

# Pasta dos jobs - criada on-demand
JOBS_DIR = DATA_DIR / "jobs"


def _ensure_jobs_dir() -> None:
    """Garante que data/jobs/ existe (idempotente)."""
    ensure_dirs()
    JOBS_DIR.mkdir(parents=True, exist_ok=True)


def _job_path(job_id: str) -> Path:
    """Caminho do JSON de um job especifico."""
    return JOBS_DIR / f"{job_id}.json"


def _new_id() -> str:
    """
    Gera ID unico curto pra um job.

    Usamos uuid4 truncado em 12 chars - suficiente pra evitar colisao
    com milhoes de jobs e fica visualmente manuseavel em logs/URLs.
    """
    return uuid.uuid4().hex[:12]


# ============================================================
# CRUD
# ============================================================

def create_job(
    source: str,
    source_kind: str,
    params: Optional[JobParams] = None,
) -> Job:
    """
    Cria um novo job em estado 'queued' e persiste no disco.

    Args:
        source:      URL ou caminho local do arquivo.
        source_kind: 'url' ou 'upload'.
        params:      Parametros customizados. None = usa defaults.

    Returns:
        Job recem-criado com id gerado.
    """
    _ensure_jobs_dir()
    job = Job(
        id=_new_id(),
        source=source,
        source_kind=source_kind,
        params=params or JobParams(),
    )
    save_job(job)
    logger.info("Job criado: %s (source=%s, kind=%s)", job.id, source[:60], source_kind)
    return job


def save_job(job: Job) -> None:
    """
    Persiste o job no disco (sobrescreve o JSON).

    Chamada APOS qualquer mudanca de estado (status, percent, etc.).
    """
    _ensure_jobs_dir()
    path = _job_path(job.id)
    # mode_json_dump_json com indent fica legivel se voce abrir no editor
    path.write_text(job.model_dump_json(indent=2), encoding="utf-8")


def get_job(job_id: str) -> Optional[Job]:
    """
    Carrega um job do disco.

    Returns:
        Job ou None se nao existir.
    """
    path = _job_path(job_id)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return Job.model_validate(data)
    except Exception as e:
        logger.warning("Erro ao carregar job %s: %s", job_id, e)
        return None


def list_jobs(limit: int = 50) -> list[Job]:
    """
    Lista jobs ordenados por created_at decrescente (mais recentes primeiro).

    Args:
        limit: Maximo de jobs a retornar.

    Returns:
        Lista de Job.
    """
    _ensure_jobs_dir()
    jobs: list[Job] = []
    for path in JOBS_DIR.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            jobs.append(Job.model_validate(data))
        except Exception as e:
            logger.warning("Skipping corrupted job file %s: %s", path.name, e)
    # Ordena por created_at desc
    jobs.sort(key=lambda j: j.created_at, reverse=True)
    return jobs[:limit]


def update_job_progress(
    job_id: str,
    *,
    status: Optional[JobStatus] = None,
    stage: Optional[str] = None,
    message: Optional[str] = None,
    percent: Optional[int] = None,
    clips: Optional[list[str]] = None,
    error: Optional[str] = None,
) -> Optional[Job]:
    """
    Atualiza um job parcialmente.

    Args:
        job_id: ID do job.
        Demais: campos opcionais a atualizar (None = nao mexe).

    Returns:
        Job atualizado ou None se nao existir.

    Side effect:
        Atualiza started_at quando status passa pra 'running'.
        Atualiza finished_at quando status vai pra 'done' ou 'failed'.
    """
    job = get_job(job_id)
    if job is None:
        return None

    if status is not None:
        # Marca timestamps automaticamente nas transicoes
        if status == JobStatus.running and job.started_at is None:
            job.started_at = datetime.utcnow()
        if status in (JobStatus.done, JobStatus.failed) and job.finished_at is None:
            job.finished_at = datetime.utcnow()
        job.status = status

    if stage is not None:
        job.stage = stage
    if message is not None:
        job.message = message
    if percent is not None:
        job.percent = max(0, min(100, percent))
    if clips is not None:
        job.clips = clips
    if error is not None:
        job.error = error

    save_job(job)
    return job

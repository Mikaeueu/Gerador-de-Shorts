"""
Etapa 7 - API FastAPI do Gerador de Shorts.

Endpoints:
    POST   /jobs                 - cria job (URL via JSON ou upload multipart)
    GET    /jobs                 - lista jobs (mais recentes primeiro)
    GET    /jobs/{id}            - estado atual de um job
    WS     /jobs/{id}/ws         - stream de progresso em tempo real
    GET    /jobs/{id}/clips/{n}  - download do MP4 final de um clip

    GET    /health               - healthcheck
    GET    /                     - info da API + link pra docs

Documentacao interativa automatica:
    GET    /docs    - Swagger UI
    GET    /redoc   - ReDoc

Como rodar:
    uvicorn src.api.main:app --reload
    # ou
    python -m src.api.cli
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse

from src.api.jobs import create_job, get_job, list_jobs
from src.api.schemas import Job, JobCreateRequestUrl, JobParams, JobStatus
from src.api.worker import broker, schedule_job
from src.common.paths import INPUTS_DIR, OUTPUTS_DIR, ensure_dirs
from src.downloader import is_url

logger = logging.getLogger(__name__)


# ============================================================
# App + CORS
# ============================================================

app = FastAPI(
    title="Gerador de Shorts API",
    description="API pra transformar videos longos em Shorts verticais com legendas.",
    version="0.1.0",
)

# CORS aberto pra desenvolvimento local. Em producao, restringir aos
# dominios do frontend.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# Endpoints basicos
# ============================================================

@app.get("/")
async def root() -> dict:
    """Info basica da API."""
    return {
        "name": "Gerador de Shorts API",
        "version": "0.1.0",
        "docs": "/docs",
        "endpoints": {
            "create_job_url": "POST /jobs (JSON com source)",
            "create_job_upload": "POST /jobs/upload (multipart com file)",
            "list_jobs": "GET /jobs",
            "get_job": "GET /jobs/{id}",
            "websocket_progress": "WS /jobs/{id}/ws",
            "download_clip": "GET /jobs/{id}/clips/{n}",
        },
    }


@app.get("/health")
async def health() -> dict:
    """Healthcheck pra load balancers / monitoring."""
    return {"status": "ok"}


# ============================================================
# Jobs
# ============================================================

@app.post("/jobs", response_model=Job, status_code=201)
async def create_job_from_url(req: JobCreateRequestUrl) -> Job:
    """
    Cria um job a partir de URL ou caminho local.

    Body JSON:
        {
            "source": "https://www.youtube.com/watch?v=..." OU "/caminho/video.mp4",
            "params": { "whisper_model": "small", "max_clips": 3, ... }  // opcional
        }

    Returns:
        Job criado em estado 'queued'. O processamento comeca em background.
        Cliente deve usar WS /jobs/{id}/ws pra acompanhar progresso.
    """
    source_kind = "url" if is_url(req.source) else "local"
    job = create_job(req.source, source_kind=source_kind, params=req.params)
    schedule_job(job.id)
    return job


@app.post("/jobs/upload", response_model=Job, status_code=201)
async def create_job_from_upload(
    file: UploadFile = File(..., description="Arquivo de video (.mp4, .mkv, .webm)"),
    params_json: Optional[str] = Form(None, description="JSON com JobParams (opcional)"),
) -> Job:
    """
    Cria um job a partir de upload de arquivo.

    Multipart form data:
        file:        arquivo de video
        params_json: JSON com parametros (opcional)

    Salva o upload em data/inputs/<filename>, depois trata como source local.
    """
    ensure_dirs()
    if not file.filename:
        raise HTTPException(400, "Filename ausente no upload")

    # Salva o upload em data/inputs/. Se ja existe arquivo com mesmo nome,
    # sobrescreve (consistente com o comportamento do downloader).
    target = INPUTS_DIR / file.filename
    with target.open("wb") as f:
        shutil.copyfileobj(file.file, f)
    logger.info("Upload salvo: %s (%d bytes)", target.name, target.stat().st_size)

    # Parseia params se fornecido
    params: Optional[JobParams] = None
    if params_json:
        import json as json_lib
        try:
            params = JobParams.model_validate(json_lib.loads(params_json))
        except Exception as e:
            raise HTTPException(400, f"params_json invalido: {e}")

    job = create_job(str(target), source_kind="upload", params=params)
    schedule_job(job.id)
    return job


@app.get("/jobs", response_model=list[Job])
async def get_jobs(limit: int = 50) -> list[Job]:
    """Lista os jobs (mais recentes primeiro)."""
    return list_jobs(limit=limit)


@app.get("/jobs/{job_id}", response_model=Job)
async def get_job_endpoint(job_id: str) -> Job:
    """Retorna o estado atual de um job."""
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Job nao encontrado: {job_id}")
    return job


# ============================================================
# WebSocket pra progresso em tempo real
# ============================================================

@app.websocket("/jobs/{job_id}/ws")
async def job_progress_ws(websocket: WebSocket, job_id: str) -> None:
    """
    WebSocket pra receber progresso em tempo real.

    O cliente deve conectar APOS criar o job via POST. Ao conectar,
    recebe imediatamente a ultima mensagem conhecida (pra recuperar estado
    se a conexao tivesse caido).

    Mensagens enviadas (JSON, formato ProgressMessage):
        {
            "job_id": "abc123",
            "status": "running",
            "stage": "transcribe",
            "message": "Transcrevendo com Whisper small...",
            "percent": 25,
            "timestamp": "2026-05-13T16:00:00"
        }

    Quando o job termina (done/failed), envia mensagem final e fecha.
    """
    job = get_job(job_id)
    if job is None:
        await websocket.close(code=4404, reason=f"Job nao encontrado: {job_id}")
        return

    await broker.connect(job_id, websocket)
    try:
        # Mantem a conexao aberta - o broker faz broadcast quando ha update.
        # Loop apenas pra detectar desconexao do cliente.
        while True:
            # receive_text bloqueia ate o cliente mandar algo OU desconectar.
            # Nao usamos o conteudo - cliente s'o lê. Se cliente fechar, lança WebSocketDisconnect.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        broker.disconnect(job_id, websocket)


# ============================================================
# Download de clips finais
# ============================================================

@app.get("/jobs/{job_id}/clips/{clip_index}")
async def download_clip(job_id: str, clip_index: int) -> FileResponse:
    """
    Baixa o MP4 final de um clip especifico.

    Args:
        job_id:     ID do job.
        clip_index: Indice do clip (1-baseado: 1, 2, 3, ...).

    Returns:
        FileResponse com o MP4. Browser renderiza video inline ou baixa.

    Raises:
        404 se job nao existe, nao terminou, ou clip_index fora do range.
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Job nao encontrado: {job_id}")
    if job.status != JobStatus.done:
        raise HTTPException(409, f"Job ainda nao terminou (status={job.status})")
    if clip_index < 1 or clip_index > len(job.clips):
        raise HTTPException(404, f"clip_index fora do range (1-{len(job.clips)})")

    filename = job.clips[clip_index - 1]
    path = OUTPUTS_DIR / filename
    if not path.exists():
        raise HTTPException(404, f"Arquivo nao encontrado no disco: {filename}")

    return FileResponse(
        str(path),
        media_type="video/mp4",
        filename=filename,
    )


@app.get("/jobs/{job_id}/clips")
async def list_job_clips(job_id: str) -> dict:
    """
    Lista os clips finais de um job (com URLs de download).

    Returns:
        {
            "job_id": "abc123",
            "status": "done",
            "clips": [
                {"index": 1, "filename": "...", "url": "/jobs/abc123/clips/1"},
                ...
            ]
        }
    """
    job = get_job(job_id)
    if job is None:
        raise HTTPException(404, f"Job nao encontrado: {job_id}")
    return {
        "job_id": job.id,
        "status": job.status,
        "clips": [
            {
                "index": i + 1,
                "filename": name,
                "url": f"/jobs/{job_id}/clips/{i + 1}",
            }
            for i, name in enumerate(job.clips)
        ],
    }

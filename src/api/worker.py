"""
Worker assincrono + WebSocket broker.

Componentes:
    - WSBroker: gerencia conexoes WebSocket por job_id, broadcast de mensagens
    - run_job_async: executa o pipeline em background com callback de progresso

Por que asyncio + threading hibrido:
    - WebSockets do FastAPI sao asyncio nativos
    - O run_pipeline faz I/O bloqueante (FFmpeg, modelos ML)
    - Solucao: rodar pipeline em ThreadPoolExecutor pra nao travar o event loop
    - Callback de progresso usa asyncio.run_coroutine_threadsafe pra falar com WS

Pra producao seria melhor: Celery + Redis. Pra MVP, ThreadPool e suficiente.
"""
from __future__ import annotations

import asyncio
import logging
import traceback
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from typing import Dict, List

from fastapi import WebSocket

from src.api.jobs import get_job, update_job_progress
from src.api.schemas import JobStatus, ProgressMessage
from src.common.paths import OUTPUTS_DIR
from src.pipeline import run_pipeline

logger = logging.getLogger(__name__)


# ============================================================
# WebSocket Broker
# ============================================================

class WSBroker:
    """
    Mantem conexoes WS ativas indexadas por job_id e faz broadcast.

    Multiplo clientes podem se conectar ao mesmo job (ex: 2 abas do browser).
    Cada mensagem e enviada pra TODAS as conexoes daquele job.

    Quando um job termina, sinalizamos um "evento final" e fechamos o WS.
    """
    def __init__(self) -> None:
        # job_id -> lista de WebSocket conectados
        self._connections: Dict[str, List[WebSocket]] = {}
        # job_id -> ultima mensagem (pra mandar pro novo cliente conectado)
        self._last_message: Dict[str, ProgressMessage] = {}

    async def connect(self, job_id: str, ws: WebSocket) -> None:
        """Aceita uma conexao WS e registra. Manda imediatamente o ultimo estado conhecido."""
        await ws.accept()
        self._connections.setdefault(job_id, []).append(ws)
        logger.info("WS conectado: job=%s (total=%d)", job_id, len(self._connections[job_id]))

        # Envia o ultimo estado conhecido pro cliente recem-conectado.
        # Sem isso, o cliente teria que esperar a proxima atualizacao.
        last = self._last_message.get(job_id)
        if last is not None:
            try:
                await ws.send_text(last.model_dump_json())
            except Exception:
                pass

    def disconnect(self, job_id: str, ws: WebSocket) -> None:
        """Remove uma conexao WS (ja desconectada)."""
        if job_id in self._connections:
            try:
                self._connections[job_id].remove(ws)
            except ValueError:
                pass
            if not self._connections[job_id]:
                del self._connections[job_id]
        logger.info("WS desconectado: job=%s", job_id)

    async def broadcast(self, job_id: str, message: ProgressMessage) -> None:
        """
        Envia message pra TODAS as conexoes WS de um job.

        Args:
            job_id:  ID do job.
            message: ProgressMessage a transmitir.
        """
        self._last_message[job_id] = message
        if job_id not in self._connections:
            return
        text = message.model_dump_json()
        # Itera sobre copia pq pode haver remocao durante o loop (conexao caida)
        dead: list[WebSocket] = []
        for ws in list(self._connections[job_id]):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        # Limpa conexoes mortas
        for ws in dead:
            self.disconnect(job_id, ws)


# ============================================================
# Singleton do broker (instancia compartilhada na app)
# ============================================================

broker = WSBroker()


# ============================================================
# Executor de jobs em thread separada
# ============================================================

# ThreadPoolExecutor compartilhado. max_workers=2 evita sobrecarregar
# CPU/RAM quando varios jobs sao submetidos ao mesmo tempo.
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="shorts-worker")


def _make_progress_callback(
    job_id: str,
    loop: asyncio.AbstractEventLoop,
):
    """
    Cria o callback de progresso que sera passado pro run_pipeline.

    Como o pipeline roda em thread separada, mas o broker.broadcast e
    asyncio (precisa ser awaited), usamos run_coroutine_threadsafe pra
    fazer a ponte entre os dois mundos.

    Args:
        job_id: ID do job sendo processado.
        loop:   event loop asyncio principal (do FastAPI).

    Returns:
        Funcao callback que pode ser chamada de qualquer thread.
    """
    def callback(stage: str, message: str, percent: int) -> None:
        # 1. Persiste no disco (operacao sincrona, sem problema)
        update_job_progress(
            job_id,
            stage=stage,
            message=message,
            percent=percent,
        )
        # 2. Broadcast via WS (precisa do event loop)
        msg = ProgressMessage(
            job_id=job_id,
            status=JobStatus.running,
            stage=stage,
            message=message,
            percent=percent,
        )
        try:
            asyncio.run_coroutine_threadsafe(broker.broadcast(job_id, msg), loop)
        except Exception as e:
            logger.warning("Falha broadcast WS: %s", e)
    return callback


def _run_job_blocking(job_id: str, loop: asyncio.AbstractEventLoop) -> None:
    """
    Executa o job de forma BLOQUEANTE.

    Sera invocado dentro de um ThreadPoolExecutor pelo run_job_async.
    Nao chame essa funcao diretamente do event loop - vai travar.
    """
    job = get_job(job_id)
    if job is None:
        logger.error("Job %s nao encontrado pra executar", job_id)
        return

    update_job_progress(job_id, status=JobStatus.running, percent=0)

    callback = _make_progress_callback(job_id, loop)

    try:
        clips = run_pipeline(
            job.source,
            whisper_model=job.params.whisper_model,
            language=job.params.language,
            refine=job.params.refine,
            refine_context=job.params.refine_context,
            template=job.params.template,
            min_clip_seconds=job.params.min_clip_seconds,
            max_clip_seconds=job.params.max_clip_seconds,
            max_clips=job.params.max_clips,
            min_score=job.params.min_score,
            font_size=job.params.font_size,
            words_per_chunk=job.params.words_per_chunk,
            fade_out_seconds=job.params.fade_out_seconds,
            on_progress=callback,
        )
        # Salva caminhos relativos a data/outputs/
        clip_names = [p.name for p in clips]
        update_job_progress(
            job_id,
            status=JobStatus.done,
            stage="done",
            message=f"Concluido: {len(clip_names)} clips",
            percent=100,
            clips=clip_names,
        )
        # Broadcast final
        final_msg = ProgressMessage(
            job_id=job_id, status=JobStatus.done,
            stage="done", message=f"Concluido: {len(clip_names)} clips",
            percent=100,
        )
        asyncio.run_coroutine_threadsafe(broker.broadcast(job_id, final_msg), loop)
    except Exception as e:
        err = f"{type(e).__name__}: {e}\n{traceback.format_exc()}"
        logger.exception("Job %s falhou", job_id)
        update_job_progress(
            job_id,
            status=JobStatus.failed,
            stage="error",
            message=str(e),
            error=err,
        )
        fail_msg = ProgressMessage(
            job_id=job_id, status=JobStatus.failed,
            stage="error", message=str(e), percent=0,
        )
        try:
            asyncio.run_coroutine_threadsafe(broker.broadcast(job_id, fail_msg), loop)
        except Exception:
            pass


def schedule_job(job_id: str) -> None:
    """
    Agenda um job pra rodar no ThreadPool.

    Pega o event loop atual (do FastAPI) e o passa pro worker pra que
    possa fazer broadcast WS de volta.

    Chamada apos POST /jobs.
    """
    loop = asyncio.get_event_loop()
    _executor.submit(_run_job_blocking, job_id, loop)
    logger.info("Job %s agendado pro ThreadPool", job_id)

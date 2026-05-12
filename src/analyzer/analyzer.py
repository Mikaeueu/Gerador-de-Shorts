"""
Etapa 3 - Analise viral via LLM (Google Gemini)

O que essa etapa faz:
    Recebe um Transcript da Etapa 2, manda pro Gemini com um prompt
    customizado por nicho, e devolve uma lista de ViralClip - os trechos
    com maior potencial de virar Shorts.

Pipeline:
    Transcript (Etapa 2)
        -> prompts.py monta o texto do prompt (com timestamps)
            -> google.genai chama o Gemini com response_schema=list[ViralClip]
                -> Gemini retorna JSON estruturado
                    -> analyzer.py valida/filtra (duracao, score, timestamps)
                        -> cache em data/temp/<nome>.viral.json
                            -> ViralAnalysis pronta pra Etapa 4 (cropper)

Por que Gemini 2.5 Flash:
    - Free tier generoso (1500 req/dia, sem cartao de credito).
    - 1M tokens de contexto (aguenta transcricao de pregacao de 1h+).
    - Suporta response_schema Pydantic nativo (forcando JSON correto).
    - Rapido (~3-10s pra analisar uma pregacao).
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from src.analyzer.prompts import TEMPLATES
from src.analyzer.schemas import ViralAnalysis, ViralClip
from src.common.paths import TEMP_DIR, ensure_dirs
from src.transcriber import Transcript

logger = logging.getLogger(__name__)

# Modelo default se a variavel de ambiente nao tiver GEMINI_MODEL.
DEFAULT_MODEL = "gemini-2.5-flash"


# ============================================================
# Cliente Gemini - preguicoso, importa so quando precisa
# ============================================================

def _load_env() -> None:
    """
    Carrega variaveis do arquivo .env pra os.environ.

    Funcao "privada".

    Por que try/except ImportError:
        python-dotenv e uma dependencia opcional. Se alguem so quer USAR
        as dataclasses (ViralClip, ViralAnalysis) sem chamar o Gemini,
        nao precisa instalar a lib. Se nao tiver instalada, simplesmente
        nao carrega o .env (vai depender de variaveis ja no ambiente).

    Side effects:
        Mexe em os.environ adicionando o que tiver no .env.
        Variaveis JA definidas no ambiente NAO sao sobrescritas.
    """
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _get_gemini_client():
    """
    Cria e retorna o cliente Google GenAI configurado com a API key.

    Funcao "privada".

    Returns:
        Instancia de google.genai.Client pronta pra chamar
        models.generate_content(...).

    Raises:
        RuntimeError: Se GOOGLE_API_KEY nao estiver definida nem no .env
                      nem como variavel de ambiente do sistema.

    Decisao sobre import tardio:
        'from google import genai' e caro (puxa varias deps do Google).
        Importar dentro da funcao evita esse custo se o modulo for usado
        so pelas dataclasses.
    """
    _load_env()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY nao definida. "
            "Crie sua chave em https://aistudio.google.com/app/apikey e "
            "coloque em .env (veja .env.example)."
        )

    from google import genai
    return genai.Client(api_key=api_key)


# ============================================================
# API principal
# ============================================================

def analyze(
    transcript: Transcript,
    *,
    template: str = "evangelical_preaching",
    model: str | None = None,
    min_clip_seconds: float = 45,
    max_clip_seconds: float = 90,
    max_clips: int = 5,
    min_score: float = 7.0,
    cache_key: str | None = None,
    use_cache: bool = True,
) -> ViralAnalysis:
    """
    Funcao PRINCIPAL da Etapa 3 - chama o Gemini e devolve clips virais.

    Args:
        transcript:       Resultado da Etapa 2 (transcricao com timestamps).
        template:         Qual template de prompt usar.
                          Default: "evangelical_preaching".
                          Opcoes: ver prompts.TEMPLATES.
        model:            Modelo Gemini a usar (ex: "gemini-2.5-flash").
                          Default: le env GEMINI_MODEL, fallback DEFAULT_MODEL.
        min_clip_seconds: Duracao minima aceita de cada clip. Default 45.
        max_clip_seconds: Duracao maxima aceita. Default 90.
        max_clips:        Quantidade maxima de clips retornados. Default 5.
        min_score:        Score minimo (0-10) pra considerar viral. Default 7.0.
        cache_key:        Nome base do cache (ex: "pregacao").
                          None = nao persiste cache.
        use_cache:        Se True e cache existir, retorna ele em vez
                          de chamar o Gemini. Default True.

    Returns:
        ViralAnalysis com a lista de clips filtrada/ordenada por score (desc).
        TAMBEM salva JSON no cache_path como efeito colateral.

    Raises:
        ValueError:   Se o template nao existir em TEMPLATES.
        RuntimeError: Se GOOGLE_API_KEY nao estiver configurada.
        Pode tambem propagar excecoes de rede do Gemini.

    Exemplo:
        >>> from src.transcriber import transcribe
        >>> from src.analyzer import analyze
        >>> t = transcribe("data/inputs/pregacao.mp4")
        >>> result = analyze(t, cache_key="pregacao")

    Notas sobre o pos-processamento:
        Mesmo que o Gemini "alucine" e devolva clips invalidos (duracao
        errada, timestamps fora do video, score absurdo), filtramos AQUI
        antes de retornar. Output dessa funcao e SEMPRE confiavel.

    Sobre o cache:
        Se cache_key for fornecido e use_cache=True e o arquivo existir,
        NAO chamamos o Gemini. Cada chamada conta contra a quota de 1500/dia.
    """
    ensure_dirs()
    model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    if template not in TEMPLATES:
        raise ValueError(f"Template desconhecido: {template}. Disponiveis: {list(TEMPLATES)}")

    # ----- Cache hit? Retorna sem chamar Gemini. -----
    cache_path: Path | None = None
    if cache_key:
        cache_path = TEMP_DIR / f"{cache_key}.viral.json"
        if use_cache and cache_path.exists():
            logger.info("Cache hit: %s", cache_path.name)
            data = json.loads(cache_path.read_text(encoding="utf-8"))
            return ViralAnalysis.model_validate(data)

    # ----- Monta prompt usando o template escolhido -----
    build_prompt = TEMPLATES[template]
    prompt = build_prompt(
        transcript,
        min_clip_seconds=min_clip_seconds,
        max_clip_seconds=max_clip_seconds,
        max_clips=max_clips,
        min_score=min_score,
    )

    # ----- Chama Gemini com saida estruturada -----
    logger.info("Chamando %s (template=%s)...", model, template)
    client = _get_gemini_client()

    # MAGICA do response_schema:
    #   Passamos list[ViralClip] e o SDK traduz pra um JSON Schema
    #   forcando o Gemini a respeitar. NUNCA recebemos texto solto.
    # temperature=0.3:
    #   Baixa = saida mais deterministica. Pra curadoria queremos
    #   consistencia, nao criatividade.
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={
            "response_mime_type": "application/json",
            "response_schema": list[ViralClip],
            "temperature": 0.3,
        },
    )

    clips_raw = response.parsed or []
    clips: list[ViralClip] = [
        c if isinstance(c, ViralClip) else ViralClip.model_validate(c)
        for c in clips_raw
    ]

    # ----- Pos-processamento defensivo -----
    # Mesmo com schema forcado, LLM pode retornar valores absurdos.
    # Filtramos aqui pra garantir output sempre valido.
    valid_clips = [
        c for c in clips
        if min_score <= c.score <= 10
        and min_clip_seconds <= c.duration <= max_clip_seconds
        and 0 <= c.start < c.end <= transcript.duration
    ]
    invalid = len(clips) - len(valid_clips)
    if invalid:
        logger.warning("Filtrados %d clips fora dos limites.", invalid)

    valid_clips.sort(key=lambda c: c.score, reverse=True)
    valid_clips = valid_clips[:max_clips]

    result = ViralAnalysis(
        video_duration=transcript.duration,
        language=transcript.language,
        template=template,
        model=model,
        clips=valid_clips,
    )

    if cache_path:
        cache_path.write_text(result.model_dump_json(indent=2), encoding="utf-8")
        logger.info("Analise salva: %s (%d clips)", cache_path.name, len(valid_clips))

    return result

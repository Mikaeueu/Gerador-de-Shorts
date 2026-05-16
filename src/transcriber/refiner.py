"""
Etapa 2.5 - Refinamento da transcricao via LLM.

Estrategia de IAs (cadeia de fallback):
    1. Groq + Llama 3.3 70B (PRIMARIO)
       - Free tier sem limite diario fixo (30 req/min)
       - Latencia super baixa (~1-3s)
       - Sem cartao de credito necessario
       - DEIXA O GEMINI LIVRE pro analyzer (Etapa 3) que e mais critico
    2. Gemini 2.5 Flash (FALLBACK)
       - Usado SO se Groq falhar (quota, rede, etc.)
       - Consome quota diaria do Gemini
    3. Se ambos falharem: retorna transcript ORIGINAL sem modificacao
       - Garantia: nunca pioramos a transcricao

Por que essa ordem:
    A correcao da transcricao e uma tarefa LINEAR (so trocar palavras erradas).
    Llama 3.3 70B faz isso com qualidade indistinguivel do Gemini.
    Reservamos o Gemini pro analyzer, que e uma tarefa mais CRIATIVA
    (escolher quais trechos sao virais, escrever titulos com gancho).

Validacao defensiva (importante):
    Se o LLM quebrar a regra de "manter mesmo numero de palavras",
    fazemos fallback pra transcricao original.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import replace
from pathlib import Path
from typing import Callable, Optional

from src.common.paths import TEMP_DIR, ensure_dirs
from src.transcriber.transcriber import Segment, Transcript, Word

logger = logging.getLogger(__name__)


# ============================================================
# Helpers de tokenizacao + carregamento de .env
# ============================================================

_WORD_PATTERN = re.compile(r"\S+")


def _tokenize(text: str) -> list[str]:
    """Divide texto em tokens 'palavra' (qualquer sequencia nao-espaco)."""
    return _WORD_PATTERN.findall(text)


def _load_env() -> None:
    """Carrega .env (no-op se dotenv nao estiver instalado)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


# ============================================================
# Construcao do prompt (compartilhado por todos os providers)
# ============================================================

def _build_refinement_prompt(transcript: Transcript, context_hint: str) -> str:
    """
    Monta o prompt de refinamento.

    Args:
        transcript:   Transcript original do Whisper.
        context_hint: Pista do tipo de conteudo (ex: "pregacao evangelica").

    Returns:
        Prompt completo (string) compartilhado por TODOS os providers.
    """
    return f"""Voce e um revisor especializado em transcricoes de {context_hint}.

A transcricao abaixo foi gerada automaticamente por um sistema (Whisper) e \
contem erros tipicos:
- Palavras homofonas erradas (cessao/sessao, ha/a, mas/mais, houve/ouve)
- Termos especificos mal transcritos
- Nomes proprios errados
- Conjugacoes verbais incorretas
- Palavras compostas separadas ou juntadas erroneamente

REGRAS RIGIDAS - NAO QUEBRE NENHUMA:
1. Mantenha EXATAMENTE o mesmo numero de palavras (separadas por espaco).
2. Mantenha a ORDEM exata das palavras.
3. NAO adicione palavras novas.
4. NAO remova palavras.
5. NAO junte 2 palavras em 1 nem separe 1 palavra em 2.
6. APENAS substitua palavras erradas pela versao correta no contexto.
7. Mantenha pontuacao colada nas mesmas palavras.
8. Se uma palavra ja esta correta, copie ela EXATAMENTE como esta.

# TRANSCRICAO ORIGINAL

{transcript.text}

# SAIDA

Devolva APENAS a transcricao corrigida. Sem explicacoes, sem cabecalhos, \
sem aspas, sem markdown. Apenas o texto puro com as correcoes aplicadas, \
preservando o numero exato de palavras.
"""


# ============================================================
# Provider: GROQ (primario)
# ============================================================

def _refine_with_groq(prompt: str) -> str:
    """
    Refina via Groq (Llama 3.3 70B). Provider PRIMARIO.

    Raises:
        RuntimeError: Se GROQ_API_KEY nao definida.
        Outras excecoes (rede/quota): propagadas pro caller.
    """
    _load_env()
    api_key = os.getenv("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY nao definida (skip Groq)")
    from groq import Groq
    model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    client = Groq(api_key=api_key)
    response = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,  # baixa = consistente
    )
    return (response.choices[0].message.content or "").strip()


# ============================================================
# Provider: GEMINI (fallback)
# ============================================================

def _refine_with_gemini(prompt: str) -> str:
    """
    Refina via Gemini 2.5 Flash. Provider FALLBACK.

    Usado APENAS se Groq falhar. Reserva quota do Gemini pro analyzer.

    Raises:
        RuntimeError: Se GOOGLE_API_KEY nao definida.
        Outras excecoes do Gemini: propagadas pro caller.
    """
    _load_env()
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GOOGLE_API_KEY nao definida (skip Gemini)")
    from google import genai
    model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    client = genai.Client(api_key=api_key)
    response = client.models.generate_content(
        model=model,
        contents=prompt,
        config={"temperature": 0.1},
    )
    return (response.text or "").strip()


# ============================================================
# Cadeia de providers
# ============================================================

# Ordem: Groq (gratis e rapido) -> Gemini (gasta quota, ultimo recurso).
# Se ambos falharem, refine_transcript() retorna o original.
_REFINER_CHAIN: list[tuple[str, Callable[[str], str]]] = [
    ("groq", _refine_with_groq),
    ("gemini", _refine_with_gemini),
]


def _call_refiner_chain(prompt: str) -> tuple[str, str] | None:
    """
    Tenta cada provider em ordem ate um funcionar.

    Returns:
        Tupla (texto_refinado, provider_usado) ou None se TODOS falharam.
    """
    erros = []
    for name, func in _REFINER_CHAIN:
        try:
            logger.info("Refiner: tentando %s...", name)
            text = func(prompt)
            if not text:
                erros.append(f"{name}: resposta vazia")
                continue
            logger.info("Refiner: sucesso com %s", name)
            return text, name
        except Exception as e:
            erros.append(f"{name}: {type(e).__name__}: {e}")
            logger.warning("Refiner: %s falhou (%s). Tentando proximo...", name, e)

    logger.warning(
        "Refiner: TODOS os providers falharam:\n%s",
        "\n".join(f"  - {x}" for x in erros),
    )
    return None


# ============================================================
# Aplicacao das correcoes preservando timestamps
# ============================================================

def _apply_corrections(original: Transcript, refined_text: str) -> Transcript | None:
    """
    Aplica o texto refinado ao Transcript original, preservando timestamps.

    Se a contagem de palavras NAO bater, retorna None (caller faz fallback).
    """
    refined_tokens = _tokenize(refined_text)
    original_words = list(original.all_words())

    if len(refined_tokens) != len(original_words):
        logger.warning(
            "Refinamento mudou contagem de palavras (%d -> %d). "
            "Fazendo fallback pra transcricao original.",
            len(original_words), len(refined_tokens),
        )
        return None

    refined_iter = iter(refined_tokens)
    new_segments: list[Segment] = []
    for seg in original.segments:
        new_words: list[Word] = []
        text_parts: list[str] = []
        for w in seg.words:
            new_text = next(refined_iter)
            new_words.append(replace(w, text=new_text))
            text_parts.append(new_text)
        new_text_for_seg = " ".join(text_parts)
        new_segments.append(replace(seg, text=new_text_for_seg, words=new_words))

    return Transcript(
        language=original.language,
        language_probability=original.language_probability,
        duration=original.duration,
        model_size=f"{original.model_size}+refined",
        segments=new_segments,
    )


# ============================================================
# API principal
# ============================================================

def refine_transcript(
    transcript: Transcript,
    *,
    context_hint: str = "pregacao evangelica em portugues do Brasil",
    cache_key: str | None = None,
    use_cache: bool = True,
    model: str | None = None,  # mantido pra compat, mas ignorado (chain decide)
) -> Transcript:
    """
    Refina a transcricao do Whisper usando cadeia de LLMs.

    Estrategia:
        1. Tenta Groq (Llama 3.3 70B) - free tier sem limite diario
        2. Se Groq falhar, tenta Gemini (consome quota Gemini)
        3. Se ambos falharem ou refinamento quebrar regras: retorna original

    Args:
        transcript:   Transcript original do transcribe().
        context_hint: Descricao do conteudo pra orientar revisao.
        cache_key:    Nome base do cache (ex: 'pregacao').
                      None = nao persiste.
        use_cache:    Se True e cache existir, retorna ele.
        model:        IGNORADO. Mantido por compat com chamadas antigas.
                      A escolha do modelo agora vem da chain + env vars.

    Returns:
        Transcript refinado, OU o original se nada funcionou.
        Garantia: NUNCA piora a transcricao.
    """
    ensure_dirs()

    # ----- Cache hit? -----
    cache_path: Path | None = None
    if cache_key:
        cache_path = TEMP_DIR / f"{cache_key}.transcript.refined.json"
        if use_cache and cache_path.exists():
            logger.info("Cache hit (refined): %s", cache_path.name)
            return Transcript.load_json(cache_path)

    # ----- Tenta a cadeia de providers -----
    total_words = sum(len(s.words) for s in transcript.segments)
    logger.info("Refinando transcricao (%d palavras)...", total_words)

    prompt = _build_refinement_prompt(transcript, context_hint)
    result = _call_refiner_chain(prompt)
    if result is None:
        # Todos falharam - usa original
        return transcript
    refined_text, provider_used = result

    # ----- Aplica correcoes -----
    refined = _apply_corrections(transcript, refined_text)
    if refined is None:
        # Contagem nao bateu - usa original
        return transcript

    # ----- Persiste cache -----
    if cache_path:
        refined.save_json(cache_path)
        logger.info("Refinamento salvo: %s (provider=%s)",
                    cache_path.name, provider_used)

    # Telemetria: quantas palavras foram alteradas
    n_changed = sum(
        1
        for w_orig, w_new in zip(transcript.all_words(), refined.all_words())
        if w_orig.text.strip() != w_new.text.strip()
    )
    logger.info(
        "Refinamento aplicado via %s: %d/%d palavras alteradas (%.1f%%)",
        provider_used, n_changed, total_words,
        100 * n_changed / max(1, total_words),
    )

    return refined

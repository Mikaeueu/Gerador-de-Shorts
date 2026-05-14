"""
Etapa 2.5 - Refinamento da transcricao via Gemini.

O problema que esse modulo resolve:
    O Whisper (mesmo modelo 'small') comete erros tipicos de transcricao:
        - Homofonos: "cessao/sessao", "ha/a", "mas/mais", "houve/ouve"
        - Termos religiosos: "Filipenses", "ecumenico", "soteriologia"
        - Nomes proprios biblicos: "Habacuque", "Eclesiastes"
        - Conjugacoes: "viesse/visse", "houvesse/ouvesse"

    Esses erros passam batidos pra parte humana mas ficam visiveis nas
    legendas estilo Opus (palavra-por-palavra) - ficam OBVIOS na tela.

A solucao:
    Mandamos a transcricao pro Gemini com instrucoes ESTRITAS de:
        - SO substituir palavras erradas (nao adicionar/remover/reordenar)
        - Manter EXATAMENTE o mesmo numero de palavras
        - Manter ordem
    Resultado: timestamps por palavra ficam INTACTOS.

Validacao defensiva:
    Se o Gemini quebrar a regra (mudou contagem de palavras), fazemos
    FALLBACK pro Transcript original. Garantia: nunca pioramos a transcricao,
    no maximo nao melhoramos.
"""
from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import replace
from pathlib import Path

from src.common.paths import TEMP_DIR, ensure_dirs
from src.transcriber.transcriber import Segment, Transcript, Word

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gemini-2.5-flash"


# ============================================================
# Tokenizer simples
# ============================================================

# Regex que captura "palavras" (incluindo letras com acento, apostrofo, hifen).
# Usada pra contar e dividir tokens consistentemente entre original e refinado.
_WORD_PATTERN = re.compile(r"\S+")


def _tokenize(text: str) -> list[str]:
    """
    Divide texto em tokens "palavra" (qualquer sequencia nao-espaco).

    Por que nao usar split() puro:
        split() normaliza multiplos espacos automaticamente, mas regex
        permite ajuste futuro (ex: ignorar pontuacao isolada).

    Returns:
        Lista de strings sem espacos em branco.
    """
    return _WORD_PATTERN.findall(text)


# ============================================================
# Cliente Gemini (reusa logica do analyzer pra nao duplicar)
# ============================================================

def _get_gemini_client():
    """Cria cliente Gemini lendo GOOGLE_API_KEY (idempotente, lazy)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GOOGLE_API_KEY nao definida. "
            "Crie sua chave em https://aistudio.google.com/app/apikey"
        )
    from google import genai
    return genai.Client(api_key=api_key)


# ============================================================
# Construcao do prompt
# ============================================================

def _build_refinement_prompt(transcript: Transcript, context_hint: str) -> str:
    """
    Monta o prompt de refinamento.

    Args:
        transcript:   Transcript original do Whisper.
        context_hint: Pista do tipo de conteudo
                      (ex: "pregacao evangelica em portugues do Brasil").
                      Ajuda o LLM a corrigir termos especificos do nicho.

    Returns:
        String do prompt completo.
    """
    return f"""Voce e um revisor especializado em transcricoes de {context_hint}.

A transcricao abaixo foi gerada automaticamente por um sistema (Whisper) e \
contem erros tipicos:
- Palavras homofonas erradas (cessao/sessao, ha/a, mas/mais, houve/ouve)
- Termos religiosos especificos mal transcritos (livros da Biblia, doutrinas)
- Nomes proprios biblicos errados
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
# Aplicacao das correcoes preservando timestamps
# ============================================================

def _apply_corrections(original: Transcript, refined_text: str) -> Transcript | None:
    """
    Tenta aplicar o texto refinado ao Transcript original, preservando timestamps.

    Estrategia:
        - Tokeniza o texto refinado em palavras.
        - Compara contagem com palavras do original.
        - Se contagem BATER: substitui 1:1 (timestamps mantidos).
        - Se NAO bater: retorna None (caller faz fallback).

    Args:
        original:     Transcript do Whisper com palavras+timestamps.
        refined_text: Texto retornado pelo Gemini.

    Returns:
        Transcript refinado se conseguiu aplicar, None caso contrario.
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

    # Substitui 1:1 dentro de cada segmento, mantendo timestamps
    refined_iter = iter(refined_tokens)
    new_segments: list[Segment] = []
    for seg in original.segments:
        new_words: list[Word] = []
        text_parts: list[str] = []
        for w in seg.words:
            new_text = next(refined_iter)
            new_words.append(replace(w, text=new_text))
            text_parts.append(new_text)
        # Texto do segmento e a juncao das palavras refinadas
        new_text_for_seg = " ".join(text_parts)
        new_segments.append(replace(seg, text=new_text_for_seg, words=new_words))

    return Transcript(
        language=original.language,
        language_probability=original.language_probability,
        duration=original.duration,
        # Marca o modelo pra deixar claro que foi refinado
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
    model: str | None = None,
) -> Transcript:
    """
    Refina a transcricao do Whisper usando Gemini, preservando timestamps.

    Args:
        transcript:   Transcript original (output do transcribe()).
        context_hint: Descricao do tipo de conteudo. Default: pregacao
                      evangelica. Mude se for outro nicho.
        cache_key:    Nome base do cache. Ex: "pregacao" ->
                      data/temp/pregacao.transcript.refined.json.
                      None = nao persiste.
        use_cache:    Se True e cache existir, retorna ele. Default True.
        model:        Modelo Gemini. Default: GEMINI_MODEL env ou flash.

    Returns:
        Transcript refinado. Se algo der errado (LLM quebrou regra,
        falha de rede), retorna o original SEM modificacoes.

    Raises:
        Apenas erros catastroficos (sem GOOGLE_API_KEY). Erros do LLM
        ou do match sao convertidos em fallback silencioso.
    """
    ensure_dirs()
    model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)

    # ----- Cache hit? -----
    cache_path: Path | None = None
    if cache_key:
        cache_path = TEMP_DIR / f"{cache_key}.transcript.refined.json"
        if use_cache and cache_path.exists():
            logger.info("Cache hit (refined): %s", cache_path.name)
            return Transcript.load_json(cache_path)

    # ----- Chama Gemini -----
    logger.info("Refinando transcricao via %s (%d palavras)...",
                model, sum(len(s.words) for s in transcript.segments))

    try:
        client = _get_gemini_client()
        prompt = _build_refinement_prompt(transcript, context_hint)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                # Temperatura BAIXA = saida deterministica (correcoes consistentes)
                "temperature": 0.1,
            },
        )
        refined_text = (response.text or "").strip()
    except Exception as e:
        logger.warning("Falha ao refinar (%s: %s). Usando transcricao original.",
                       type(e).__name__, e)
        return transcript

    if not refined_text:
        logger.warning("Gemini retornou texto vazio. Usando transcricao original.")
        return transcript

    # ----- Aplica correcoes -----
    refined = _apply_corrections(transcript, refined_text)
    if refined is None:
        # Fallback: contagem nao bateu, retorna original
        return transcript

    # ----- Persiste cache -----
    if cache_path:
        refined.save_json(cache_path)
        logger.info("Refinamento salvo: %s", cache_path.name)

    # Conta quantas palavras mudaram (telemetria pro user)
    n_changed = sum(
        1
        for w_orig, w_new in zip(transcript.all_words(), refined.all_words())
        if w_orig.text.strip() != w_new.text.strip()
    )
    total = sum(len(s.words) for s in transcript.segments)
    logger.info("Refinamento aplicado: %d/%d palavras alteradas (%.1f%%)",
                n_changed, total, 100 * n_changed / max(1, total))

    return refined

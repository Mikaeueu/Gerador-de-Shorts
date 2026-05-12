"""
CLI do analyzer — testa a Etapa 3 sozinha, sem API/frontend.

O que esse CLI faz de diferente dos outros:
    Aceita DOIS tipos de input — JSON de transcrição OU vídeo direto.
    Se for vídeo, ele aproveita o cache da Etapa 2 OU transcreve antes.
    Isso significa que você pode pular direto pra Etapa 3 sem ter que
    rodar os CLIs anteriores manualmente.

Exemplos:
    # Já tendo transcrito antes (modo rápido):
    python -m src.analyzer.cli "data/temp/video.transcript.json"

    # Direto do vídeo (faz transcrição se necessário):
    python -m src.analyzer.cli "data/inputs/pregacao.mp4"

    # Mudando template ou limites:
    python -m src.analyzer.cli "data/inputs/podcast.mp4" \\
        --template generic --max-clips 8 --min-score 6
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from src.analyzer import analyze
from src.analyzer.prompts import TEMPLATES
from src.transcriber import Transcript, transcribe


def _load_transcript(path: Path) -> tuple[Transcript, str]:
    """
    Resolve uma `Transcript` a partir de um caminho qualquer (JSON OU vídeo).

    Função "privada" usada apenas pelo CLI.

    Args:
        path: Pode apontar pra:
              - Um `.transcript.json` (cache da Etapa 2 ou exportado manualmente).
              - Um arquivo de vídeo (.mp4, .mkv, etc.) que será transcrito on-demand.

    Returns:
        Tupla `(transcript, cache_key)`:
            - `transcript`: A Transcript pronta pra análise.
            - `cache_key`: Nome base pra salvar a análise. Vem do nome do arquivo
                           (com `.transcript` removido pra ficar limpo).

    Comportamento:
        - Se `path.suffix == ".json"`: carrega via `Transcript.load_json()`.
        - Caso contrário: trata como vídeo e chama `transcribe()`, que TAMBÉM
          tem cache próprio (data/temp/<nome>.transcript.json), então a 2a chamada
          é instantânea mesmo passando o caminho do vídeo.
    """
    if path.suffix == ".json":
        # Caminho de transcrição já existente
        transcript = Transcript.load_json(path)
        # Remove ".transcript" do final pra cache_key ficar limpo.
        # "video.transcript" → "video"
        cache_key = path.stem.removesuffix(".transcript")
        return transcript, cache_key

    # Caminho de vídeo — transcreve (ou usa cache se já existir)
    print(f"[analyzer] transcrevendo vídeo (pode demorar na 1a vez)…")
    transcript = transcribe(path)
    return transcript, path.stem


def main() -> int:
    """
    Ponto de entrada do CLI da Etapa 3.

    Fluxo:
        1. Lê argumentos (com escolhas explícitas pra template).
        2. Carrega/gera a Transcript via `_load_transcript()`.
        3. Mostra resumo do input antes de chamar o Gemini.
        4. Chama `analyze()` com os parâmetros do usuário.
        5. Imprime os clips encontrados de forma bonita (com emojis pra leitura rápida).

    Returns:
        0 = sucesso
        1 = arquivo inexistente
        2 = erro durante análise (API key faltando, quota estourou, etc.)
    """
    parser = argparse.ArgumentParser(
        description="Detecta trechos virais numa transcrição usando Gemini"
    )
    parser.add_argument("source", help="Caminho do .transcript.json OU do vídeo")
    parser.add_argument("--template", default="evangelical_preaching",
                        choices=list(TEMPLATES),
                        help="Template de prompt (default: evangelical_preaching)")
    parser.add_argument("--min-seconds", type=float, default=45,
                        help="Duração mínima de cada clip (default: 45)")
    parser.add_argument("--max-seconds", type=float, default=90,
                        help="Duração máxima de cada clip (default: 90)")
    parser.add_argument("--max-clips", type=int, default=5,
                        help="Quantidade máxima de clips retornados (default: 5)")
    parser.add_argument("--min-score", type=float, default=7.0,
                        help="Score mínimo (0-10) pra considerar um clip viral (default: 7.0)")
    parser.add_argument("--no-cache", action="store_true",
                        help="Ignora cache existente em data/temp/<nome>.viral.json")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    source = Path(args.source)
    if not source.exists():
        print(f"[erro] arquivo não encontrado: {source}", file=sys.stderr)
        return 1

    transcript, cache_key = _load_transcript(source)

    # Resumo do que vai rodar — pra você confirmar antes da chamada à API.
    print(f"[analyzer] {len(transcript.segments)} segmentos, {transcript.duration:.0f}s de áudio")
    print(f"           idioma: {transcript.language} | template: {args.template}")
    print(f"           limites: {args.min_seconds:.0f}-{args.max_seconds:.0f}s, "
          f"até {args.max_clips} clips, score >= {args.min_score:.1f}")
    print("")

    try:
        result = analyze(
            transcript,
            template=args.template,
            min_clip_seconds=args.min_seconds,
            max_clip_seconds=args.max_seconds,
            max_clips=args.max_clips,
            min_score=args.min_score,
            cache_key=cache_key,
            use_cache=not args.no_cache,
        )
    except Exception as e:
        print(f"[erro] {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    # Mostra resultado de forma bonitinha (emojis ajudam scan visual).
    print("=" * 70)
    print(f"Modelo: {result.model} | Template: {result.template}")
    print(f"Clips encontrados: {len(result.clips)}")
    print("=" * 70)

    for i, clip in enumerate(result.clips, 1):
        print(f"\n#{i}  [score {clip.score:.1f}]  {clip.title}")
        print(f"    ⏱  {clip.start:.1f}s → {clip.end:.1f}s  ({clip.duration:.1f}s)")
        print(f"    🎣 hook: {clip.hook[:120]}{'…' if len(clip.hook) > 120 else ''}")
        if clip.quote:
            print(f"    💬 quote: \"{clip.quote}\"")
        print(f"    💡 {clip.reason}")

    print("")
    print(f"JSON salvo em: data/temp/{cache_key}.viral.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

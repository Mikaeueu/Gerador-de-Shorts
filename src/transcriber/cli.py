"""
CLI do transcriber — testa a Etapa 2 sozinha, sem API/frontend.

Pra que serve:
    - Validar se faster-whisper instalou direito.
    - Transcrever um vídeo manualmente pra inspecionar o JSON.
    - Experimentar diferentes tamanhos de modelo e comparar qualidade.

Uso:
    python -m src.transcriber.cli <arquivo> [opções]

Exemplos:
    # Básico (modelo base, idioma auto-detectado):
    python -m src.transcriber.cli "data/inputs/video.mp4"

    # Recomendado pra português (modelo small, idioma forçado):
    python -m src.transcriber.cli "data/inputs/video.mp4" --model small --lang pt

    # Forçar retranscrever ignorando cache:
    python -m src.transcriber.cli "data/inputs/video.mp4" --no-cache
"""
import argparse
import logging
import sys
from pathlib import Path

from src.transcriber import transcribe


def main() -> int:
    """
    Ponto de entrada do CLI da Etapa 2.

    Fluxo:
        1. Lê argumentos da linha de comando via argparse.
        2. Configura logging (DEBUG se -v, senão INFO).
        3. Chama `transcribe()`.
        4. Imprime um preview dos resultados.

    Returns:
        0 = sucesso
        1 = arquivo inexistente
        2 = erro durante transcrição (modelo não baixou, áudio corrompido, etc.)
    """
    # argparse: lib padrão pra construir CLIs no Python.
    # description aparece quando o usuário roda com `--help`.
    parser = argparse.ArgumentParser(description="Transcrever vídeo com faster-whisper")
    parser.add_argument("media", help="Caminho do vídeo/áudio")
    parser.add_argument("--model", default="base",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Tamanho do modelo Whisper (default: base)")
    parser.add_argument("--lang", default=None,
                        help="Código ISO da língua (ex: pt, en). Default: auto-detect")
    parser.add_argument("--no-cache", action="store_true",
                        help="Ignora transcrição cacheada em data/temp/")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Mostra logs DEBUG (mais detalhes do que o Whisper tá fazendo)")
    args = parser.parse_args()

    # Configura o sistema de logging do Python.
    # `level` controla o que aparece: DEBUG mostra TUDO, INFO mostra só o relevante.
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    media = Path(args.media)
    if not media.exists():
        # `file=sys.stderr` faz o erro ir pro canal de erro (não saída normal).
        # Em scripts shell isso permite redirecionar erros separadamente.
        print(f"[erro] Arquivo não encontrado: {media}", file=sys.stderr)
        return 1

    print(f"[transcrever] {media.name}")
    print(f"  modelo: {args.model}")
    print(f"  idioma: {args.lang or '(auto-detect)'}")
    print("")

    try:
        transcript = transcribe(
            media,
            model_size=args.model,
            language=args.lang,
            use_cache=not args.no_cache,
        )
    except Exception as e:
        print(f"[erro] {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    # Preview do resultado pra você inspecionar.
    # Não imprime o texto inteiro porque pode ter milhares de linhas.
    print("─" * 60)
    print(f"Idioma detectado : {transcript.language} (prob {transcript.language_probability:.2%})")
    print(f"Duração do áudio : {transcript.duration:.1f}s")
    print(f"Segmentos        : {len(transcript.segments)}")
    print(f"Palavras totais  : {sum(len(s.words) for s in transcript.segments)}")
    print("─" * 60)
    print("Primeiros 3 segmentos:")
    for seg in transcript.segments[:3]:
        print(f"  [{seg.start:6.2f}s → {seg.end:6.2f}s] {seg.text.strip()}")
    print("")
    print("Texto completo (primeiros 400 chars):")
    print(f"  {transcript.text[:400]}{'…' if len(transcript.text) > 400 else ''}")
    print("")
    print(f"JSON salvo em: data/temp/{media.stem}.transcript.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

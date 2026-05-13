"""
CLI da Etapa 5 - queima legendas estilo Opus nos clips cropados.

Pre-requisitos:
    - Etapa 2 (transcript.json em data/temp/)
    - Etapa 3 (viral.json em data/temp/)
    - Etapa 4 (clips cropados em data/outputs/<base>_clip_N.mp4)

Exemplo:
    python -m src.captioner.cli \\
        "data\\temp\\pregacao.transcript.json" \\
        "data\\temp\\pregacao.viral.json"

Ou com configuracao customizada:
    python -m src.captioner.cli "..." "..." --font-size 80 --words 2
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from src.analyzer.schemas import ViralAnalysis
from src.captioner import caption_all_clips
from src.transcriber import Transcript


def main() -> int:
    """
    Ponto de entrada do CLI da Etapa 5.

    Returns:
        0 = sucesso
        1 = arquivos invalidos
        2 = erro durante processamento (FFmpeg falhou, fonte indisponivel)
    """
    parser = argparse.ArgumentParser(
        description="Queima legendas estilo Opus (palavra-por-palavra) nos clips cropados"
    )
    parser.add_argument("transcript_json", help="Caminho do .transcript.json (Etapa 2)")
    parser.add_argument("viral_json", help="Caminho do .viral.json (Etapa 3)")
    parser.add_argument("--font-size", type=int, default=90,
                        help="Tamanho da fonte em pontos (default: 90)")
    parser.add_argument("--words", type=int, default=3,
                        help="Palavras por chunk visivel (default: 3, range: 1-5)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    transcript_path = Path(args.transcript_json)
    viral_path = Path(args.viral_json)
    if not transcript_path.exists():
        print(f"[erro] transcript nao encontrado: {transcript_path}", file=sys.stderr)
        return 1
    if not viral_path.exists():
        print(f"[erro] viral.json nao encontrado: {viral_path}", file=sys.stderr)
        return 1

    transcript = Transcript.load_json(transcript_path)
    analysis = ViralAnalysis.model_validate(json.loads(viral_path.read_text(encoding="utf-8")))

    # cache_key_base = nome base sem sufixos
    cache_key_base = viral_path.stem.removesuffix(".viral")

    print(f"[captioner] {len(analysis.clips)} clips, {args.words} palavras/chunk, fonte {args.font_size}pt")
    print(f"            cache_key_base: {cache_key_base}")
    print("")

    try:
        outputs = caption_all_clips(
            transcript, analysis,
            cache_key_base=cache_key_base,
            font_size=args.font_size,
            max_words_per_chunk=args.words,
        )
    except Exception as e:
        print(f"[erro] {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    print("=" * 60)
    print(f"Concluido: {len(outputs)} clips com legendas")
    print("=" * 60)
    for path in outputs:
        print(f"  - {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

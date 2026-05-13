"""
CLI da Etapa 4 - testa o reenquadramento vertical.

Aceita o .viral.json (saida da Etapa 3) + caminho do video original.
Processa cada clip detectado e exporta em data/outputs/.

Exemplos:
    # Processa todos os clips do viral.json:
    python -m src.cropper.cli "data/temp/pregacao.viral.json" \\
        "data/inputs/pregacao.mp4"

    # Reusa crop plans editados manualmente (preserva edicoes em .crop.json):
    python -m src.cropper.cli "data/temp/pregacao.viral.json" \\
        "data/inputs/pregacao.mp4" --use-cache-plan
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

from src.analyzer.schemas import ViralAnalysis
from src.cropper import crop_all_clips


def main() -> int:
    """
    Ponto de entrada do CLI da Etapa 4.

    Returns:
        0 = sucesso
        1 = arquivos invalidos
        2 = erro durante processamento (FFmpeg falhou, etc.)
    """
    parser = argparse.ArgumentParser(
        description="Reenquadra clips virais em vertical 1080x1920 com face tracking"
    )
    parser.add_argument("viral_json", help="Caminho do .viral.json (saida da Etapa 3)")
    parser.add_argument("video", help="Caminho do video original")
    parser.add_argument("--use-cache-plan", action="store_true",
                        help="Reusa .crop.json existentes (preserva edicoes manuais)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    viral_path = Path(args.viral_json)
    video_path = Path(args.video)
    if not viral_path.exists():
        print(f"[erro] viral.json nao encontrado: {viral_path}", file=sys.stderr)
        return 1
    if not video_path.exists():
        print(f"[erro] video nao encontrado: {video_path}", file=sys.stderr)
        return 1

    # Carrega analise viral
    data = json.loads(viral_path.read_text(encoding="utf-8"))
    analysis = ViralAnalysis.model_validate(data)

    # cache_key_base: usa o stem do viral_json (sem .viral.json)
    cache_key_base = viral_path.stem.removesuffix(".viral")

    print(f"[cropper] processando {len(analysis.clips)} clips de '{video_path.name}'")
    print(f"          cache_key_base: {cache_key_base}")
    print(f"          target: 1080x1920")
    print("")

    try:
        outputs = crop_all_clips(
            video_path,
            analysis,
            cache_key_base=cache_key_base,
            use_cache_plan=args.use_cache_plan,
        )
    except Exception as e:
        print(f"[erro] {type(e).__name__}: {e}", file=sys.stderr)
        return 2

    print("")
    print("=" * 60)
    print(f"Concluido: {len(outputs)} clips exportados")
    print("=" * 60)
    for path in outputs:
        print(f"  - {path}")
    print("")
    print("Crop plans editaveis em data/temp/<nome>.crop.json")
    print("Re-rode com --use-cache-plan pra aplicar edicoes manuais.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

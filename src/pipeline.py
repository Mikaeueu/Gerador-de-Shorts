"""
Etapa 6 - Pipeline orquestrador END-TO-END.

Roda TODO o pipeline com UM unico comando, encadeando as 6 etapas:
    1. Downloader   (yt-dlp)
    2. Transcriber  (faster-whisper)
    2.5 Refiner     (Gemini revisa palavras)
    3. Analyzer     (Gemini detecta clips virais)
    4. Cropper      (MediaPipe/Haar + FFmpeg)
    5. Captioner    (ASS + FFmpeg + fade out + cleanup)

Caches em data/temp/ sao reaproveitados em re-runs.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Callable, Optional

from src.analyzer import analyze
from src.analyzer.prompts import TEMPLATES
from src.captioner import caption_all_clips
from src.cropper import crop_all_clips
from src.downloader import ingest
from src.transcriber import refine_transcript, transcribe

logger = logging.getLogger(__name__)

# Tipo do callback de progresso. Recebe:
#   stage:   nome da etapa ("download", "transcribe", "refine", etc.)
#   message: texto humano do que esta acontecendo
#   percent: 0-100, progresso geral aproximado
ProgressCallback = Callable[[str, str, int], None]


def _section(num: int, total: int, label: str) -> None:
    """Cabecalho visual pra cada etapa."""
    print("")
    print("=" * 60)
    print(f" [{num}/{total}] {label}")
    print("=" * 60)


def run_pipeline(
    source: str,
    *,
    whisper_model: str = "base",
    language: str | None = None,
    refine: bool = True,
    refine_context: str = "pregacao evangelica em portugues do Brasil",
    template: str = "evangelical_preaching",
    min_clip_seconds: float = 45,
    max_clip_seconds: float = 90,
    max_clips: int = 5,
    min_score: float = 7.0,
    font_size: int = 90,
    words_per_chunk: int = 3,
    fade_out_seconds: float = 3.0,
    on_progress: Optional[ProgressCallback] = None,
) -> list[Path]:
    """
    Roda o pipeline completo: source -> MP4s finais com legendas.

    Args:
        source:           URL ou caminho local.
        whisper_model:    "base"/"small"/etc. Default: base.
        language:         Codigo ISO ("pt", "en"). None = auto-detect.
        refine:           Refinar transcricao via Gemini. Default True.
        refine_context:   Contexto pra orientar o refinamento.
        template:         Template do analyzer.
        min/max_clip_seconds: Faixa de duracao dos clips.
        max_clips:        Maximo de clips. Default 5.
        min_score:        Score minimo. Default 7.0.
        font_size:        Tamanho da fonte das legendas. Default 90.
        words_per_chunk:  Palavras por chunk de legenda. Default 3.
        fade_out_seconds: Duracao do fade out. Default 3.0.
        on_progress:      Callback opcional pra reportar progresso
                          (usado pela API com WebSocket).

    Returns:
        Lista de Paths dos MP4s finais.
    """
    total_steps = 6 if refine else 5
    started_at = time.time()

    def progress(stage: str, msg: str, percent: int) -> None:
        """Reporta progresso pra callback (se houver)."""
        if on_progress:
            try:
                on_progress(stage, msg, percent)
            except Exception:
                pass  # nunca quebrar pipeline por erro do callback

    # ----- Etapa 1: Download/ingest -----
    _section(1, total_steps, "Download / ingest do video")
    progress("download", "Iniciando download/ingest...", 5)
    video_source = ingest(source)
    print(f"  ok  {video_source.path.name}")
    print(f"  ok  duracao: {video_source.duration_s:.1f}s")
    progress("download", f"OK: {video_source.path.name}", 15)

    cache_key = video_source.path.stem

    # ----- Etapa 2: Transcricao -----
    _section(2, total_steps, f"Transcricao com Whisper ({whisper_model})")
    progress("transcribe", f"Transcrevendo com Whisper {whisper_model}...", 20)
    transcript = transcribe(
        video_source.path,
        model_size=whisper_model,
        language=language,
    )
    print(f"  ok  idioma: {transcript.language} ({transcript.language_probability:.0%})")
    print(f"  ok  {len(transcript.segments)} segmentos, "
          f"{sum(len(s.words) for s in transcript.segments)} palavras")
    progress("transcribe", f"OK: {len(transcript.segments)} segmentos", 40)

    # ----- Etapa 2.5: Refinamento (opcional) -----
    step_offset = 0
    if refine:
        _section(3, total_steps, "Refinamento da transcricao via Gemini")
        progress("refine", "Refinando transcricao via Gemini...", 45)
        transcript = refine_transcript(
            transcript,
            context_hint=refine_context,
            cache_key=cache_key,
        )
        print(f"  ok  transcricao refinada (timestamps preservados)")
        progress("refine", "OK: transcricao refinada", 55)
        step_offset = 1

    # ----- Etapa 3: Analise viral -----
    _section(3 + step_offset, total_steps, f"Analise viral via Gemini (template={template})")
    progress("analyze", "Detectando trechos virais...", 60)
    analysis = analyze(
        transcript,
        template=template,
        min_clip_seconds=min_clip_seconds,
        max_clip_seconds=max_clip_seconds,
        max_clips=max_clips,
        min_score=min_score,
        cache_key=cache_key,
    )
    print(f"  ok  {len(analysis.clips)} clips identificados")
    for i, clip in enumerate(analysis.clips, 1):
        print(f"    #{i} [score {clip.score:.1f}] {clip.title[:60]}")
    progress("analyze", f"OK: {len(analysis.clips)} clips identificados", 70)

    if not analysis.clips:
        print("\n[aviso] Nenhum clip viral identificado. Pipeline encerrado.")
        return []

    # ----- Etapa 4: Crop vertical -----
    _section(4 + step_offset, total_steps, "Reenquadramento vertical (face tracking)")
    progress("crop", "Reenquadrando clips verticais...", 75)
    cropped = crop_all_clips(
        video_source.path,
        analysis,
        cache_key_base=cache_key,
        use_cache_plan=False,
    )
    print(f"  ok  {len(cropped)} clips verticais gerados")
    progress("crop", f"OK: {len(cropped)} clips verticais", 88)

    # ----- Etapa 5: Legendas + fade -----
    _section(5 + step_offset, total_steps, "Legendas estilo Opus + fade out")
    progress("caption", "Queimando legendas + fade...", 90)
    final = caption_all_clips(
        transcript, analysis,
        cache_key_base=cache_key,
        font_size=font_size,
        max_words_per_chunk=words_per_chunk,
        fade_out_seconds=fade_out_seconds,
    )
    progress("caption", f"OK: {len(final)} clips finais", 100)

    elapsed = time.time() - started_at
    print("")
    print("=" * 60)
    print(f" PIPELINE CONCLUIDO em {elapsed/60:.1f} min")
    print("=" * 60)
    print(f" {len(final)} Shorts prontos em data/outputs/:")
    for path in final:
        print(f"   - {path.name}")
    print("")

    return final


def main() -> int:
    """CLI do pipeline completo."""
    parser = argparse.ArgumentParser(
        description="Pipeline completo: URL/video -> Shorts verticais com legendas"
    )
    parser.add_argument("source", help="URL do YouTube OU caminho de video local")
    parser.add_argument("--model", default="base",
                        choices=["tiny", "base", "small", "medium", "large-v3"],
                        help="Modelo Whisper (default: base)")
    parser.add_argument("--lang", default=None,
                        help="Codigo ISO do idioma. Default: auto-detect")
    parser.add_argument("--no-refine", action="store_true",
                        help="Desativa refinamento da transcricao via Gemini")
    parser.add_argument("--refine-context", default="pregacao evangelica em portugues do Brasil",
                        help="Contexto pra refinamento")
    parser.add_argument("--fade-out", type=float, default=3.0,
                        help="Fade out em segundos (default: 3.0; 0=desativa)")
    parser.add_argument("--template", default="evangelical_preaching",
                        choices=list(TEMPLATES),
                        help="Template do analyzer")
    parser.add_argument("--min-seconds", type=float, default=45,
                        help="Duracao minima de clip (default: 45)")
    parser.add_argument("--max-seconds", type=float, default=90,
                        help="Duracao maxima de clip (default: 90)")
    parser.add_argument("--max-clips", type=int, default=5,
                        help="Maximo de clips (default: 5)")
    parser.add_argument("--min-score", type=float, default=7.0,
                        help="Score minimo 0-10 (default: 7.0)")
    parser.add_argument("--font-size", type=int, default=90,
                        help="Tamanho da fonte (default: 90)")
    parser.add_argument("--words", type=int, default=3,
                        help="Palavras por chunk (default: 3)")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    try:
        run_pipeline(
            args.source,
            whisper_model=args.model,
            language=args.lang,
            refine=not args.no_refine,
            refine_context=args.refine_context,
            template=args.template,
            min_clip_seconds=args.min_seconds,
            max_clip_seconds=args.max_seconds,
            max_clips=args.max_clips,
            min_score=args.min_score,
            font_size=args.font_size,
            words_per_chunk=args.words,
            fade_out_seconds=args.fade_out,
        )
    except Exception as e:
        print(f"\n[erro] {type(e).__name__}: {e}", file=sys.stderr)
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 2

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

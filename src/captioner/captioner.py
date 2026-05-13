"""
Etapa 5 - Orquestrador do captioner.

Fluxo:
    1. Carrega Transcript (.transcript.json) - tem palavras com timestamps.
    2. Carrega ViralAnalysis (.viral.json) - tem start/end de cada clip viral.
    3. Pra cada clip:
       a. Filtra as palavras do Whisper que caem dentro [clip.start, clip.end]
       b. Ajusta timestamps pra serem RELATIVOS ao clip (subtrai clip.start)
       c. Agrupa em chunks de 2-3 palavras
       d. Gera arquivo .ass
       e. FFmpeg queima as legendas no MP4 cropado (output da Etapa 4)
    4. Output: data/outputs/<nome>_clip_N_captioned.mp4
"""
from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

from src.analyzer.schemas import ViralAnalysis, ViralClip
from src.captioner.ass_builder import build_ass_content, group_words_into_chunks
from src.common.paths import OUTPUTS_DIR, TEMP_DIR, ensure_dirs
from src.transcriber import Transcript, Word

logger = logging.getLogger(__name__)


def _filter_words_for_clip(transcript: Transcript, clip: ViralClip) -> list[Word]:
    """
    Filtra as palavras do Whisper que caem dentro do intervalo do clip.

    Args:
        transcript: Transcript completo do video original.
        clip:       ViralClip com start/end no video original.

    Returns:
        Lista de Word ordenada por tempo, todas com start >= clip.start
        e end <= clip.end (com tolerancia de 0.1s nas bordas).

    Por que tolerancia nas bordas:
        Palavras podem estar parcialmente sobrepostas ao corte. Aceitamos
        palavras que terminam ate 0.1s antes do start, ou comecam ate
        0.1s depois do end - melhor incluir uma palavra "meio" cortada
        do que perder o contexto.
    """
    tolerance = 0.1
    words = []
    for w in transcript.all_words():
        if w.end < clip.start - tolerance:
            continue  # palavra terminou antes do clip
        if w.start > clip.end + tolerance:
            break  # passou do clip (transcript e ordenado, podemos sair)
        words.append(w)
    return words


def generate_ass_for_clip(
    transcript: Transcript,
    clip: ViralClip,
    output_ass_path: Path,
    *,
    max_words_per_chunk: int = 3,
    max_chunk_duration: float = 1.8,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    font_size: int = 90,
) -> Path:
    """
    Gera o arquivo .ass de legendas pra um clip especifico.

    Args:
        transcript:           Transcript completo do video.
        clip:                 ViralClip com start/end.
        output_ass_path:      Onde salvar o .ass.
        max_words_per_chunk:  Quantas palavras por chunk visivel. Default 3.
        max_chunk_duration:   Tempo maximo de um chunk na tela.
        play_res_x/y:         Resolucao do video de destino.
        font_size:            Tamanho da fonte em pontos.

    Returns:
        Path do .ass salvo.

    Raises:
        ValueError: Se o clip nao tiver palavras (transcript pode estar
                    incompleto ou ter sido cortado antes desse range).
    """
    words = _filter_words_for_clip(transcript, clip)
    if not words:
        raise ValueError(
            f"Nenhuma palavra encontrada no intervalo [{clip.start}-{clip.end}]. "
            f"Verifique o transcript."
        )

    chunks = group_words_into_chunks(
        words,
        max_words_per_chunk=max_words_per_chunk,
        max_chunk_duration=max_chunk_duration,
        clip_start_offset=clip.start,  # converte pra timeline relativa ao clip
    )

    content = build_ass_content(
        chunks,
        play_res_x=play_res_x,
        play_res_y=play_res_y,
        font_size=font_size,
    )

    output_ass_path.parent.mkdir(parents=True, exist_ok=True)
    output_ass_path.write_text(content, encoding="utf-8")
    logger.info("ASS gerado: %s (%d chunks)", output_ass_path.name, len(chunks))
    return output_ass_path


def burn_subtitles(video_path: Path | str, ass_path: Path | str, output_path: Path | str) -> Path:
    """
    Queima as legendas .ass no video usando FFmpeg subtitles filter.

    Args:
        video_path:  MP4 cropado (output da Etapa 4).
        ass_path:    Arquivo .ass com as legendas.
        output_path: Onde salvar o MP4 final.

    Returns:
        Path do video final.

    Raises:
        RuntimeError: Se o FFmpeg falhar.

    Por que copiamos os arquivos pra um diretorio temporario:
        O filter `subtitles=` do FFmpeg tem um parser MUITO sensivel a
        caracteres especiais no caminho:
            ! , | ( ) espacos acentos ' (aspas simples)
        Mesmo escapando, varios casos quebram. A solucao 100% confiavel
        e copiar o video + .ass pra um diretorio tempo com nomes ASCII
        simples (input.mp4 / subs.ass), rodar FFmpeg, e mover o output
        de volta pro caminho final desejado.

        Custo: copia 1x cada arquivo. Pra clips de Shorts (poucos MB),
        e instantaneo. Bem melhor do que ficar brigando com escape.
    """
    video = Path(video_path).resolve()
    ass = Path(ass_path).resolve()
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    # Cria diretorio temporario com nome curto/ASCII
    # `delete=False` nao se aplica a TemporaryDirectory - ele apaga automaticamente.
    with tempfile.TemporaryDirectory(prefix="shorts_cap_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)

        # Copia inputs com nomes ASCII safe
        tmp_video = tmp_dir_path / "input.mp4"
        tmp_ass = tmp_dir_path / "subs.ass"
        tmp_output = tmp_dir_path / "output.mp4"

        shutil.copy2(video, tmp_video)
        shutil.copy2(ass, tmp_ass)

        # Path do .ass pro FFmpeg: forward slashes + escape do ':' da unidade.
        # Como agora os nomes sao ASCII, esse escape e suficiente.
        ass_str = str(tmp_ass).replace("\\", "/")
        if len(ass_str) >= 2 and ass_str[1] == ":":
            ass_str = ass_str[0] + "\\:" + ass_str[2:]

        vf = f"subtitles='{ass_str}'"

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
            "-i", str(tmp_video),
            "-vf", vf,
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-c:a", "copy",   # audio sem re-encode (rapido + sem perda)
            "-movflags", "+faststart",
            str(tmp_output),
        ]

        logger.info("Queimando legendas em %s", video.name)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg falhou:\n{result.stderr[-1500:]}")

        # Move o output pra path final (que pode ter nome complicado)
        shutil.move(str(tmp_output), str(output))

    logger.info("Video com legendas salvo: %s", output.name)
    return output


def caption_all_clips(
    transcript: Transcript,
    analysis: ViralAnalysis,
    *,
    cache_key_base: str,
    font_size: int = 90,
    max_words_per_chunk: int = 3,
) -> list[Path]:
    """
    Gera legendas pra todos os clips da analise, usando os MP4s cropados
    da Etapa 4 como input.

    Args:
        transcript:          Transcript completo do video original.
        analysis:            ViralAnalysis com os clips.
        cache_key_base:      Mesmo prefixo usado na Etapa 4
                             (ex: 'pregacao' -> usa pregacao_clip_1.mp4 etc).
        font_size:           Tamanho da fonte.
        max_words_per_chunk: 1-3 e o range util.

    Returns:
        Lista de Paths dos MP4s finais com legendas em data/outputs/.

    Pre-requisito:
        Etapa 4 ja precisa ter rodado - os MP4s cropados devem existir
        em data/outputs/<cache_key_base>_clip_N.mp4.
    """
    ensure_dirs()
    outputs: list[Path] = []

    for idx, clip in enumerate(analysis.clips, 1):
        cropped_video = OUTPUTS_DIR / f"{cache_key_base}_clip_{idx}.mp4"
        if not cropped_video.exists():
            logger.warning("Pulando clip %d: %s nao existe (rode Etapa 4 primeiro)",
                           idx, cropped_video.name)
            continue

        # Gera .ass em data/temp/
        ass_path = TEMP_DIR / f"{cache_key_base}_clip_{idx}.ass"
        try:
            generate_ass_for_clip(
                transcript, clip, ass_path,
                font_size=font_size,
                max_words_per_chunk=max_words_per_chunk,
            )
        except ValueError as e:
            logger.warning("Pulando clip %d: %s", idx, e)
            continue

        # Queima no MP4 final
        final_output = OUTPUTS_DIR / f"{cache_key_base}_clip_{idx}_captioned.mp4"
        burn_subtitles(cropped_video, ass_path, final_output)
        outputs.append(final_output)

    return outputs

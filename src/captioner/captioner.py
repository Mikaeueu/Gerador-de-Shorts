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


def _probe_duration(video_path: Path) -> float:
    """
    Le duracao do video via ffprobe. Retorna 0.0 se falhar.

    Necessario pra calcular onde comecar o fade out (ultimos N segundos).
    """
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(video_path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip()) if result.returncode == 0 else 0.0
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        return 0.0


def burn_subtitles(
    video_path: Path | str,
    ass_path: Path | str,
    output_path: Path | str,
    *,
    fade_out_seconds: float = 3.0,
    fade_in_seconds: float = 0.3,
) -> Path:
    """
    Queima legendas .ass no video + aplica fade in/out de video e audio.

    Args:
        video_path:       MP4 cropado (output da Etapa 4).
        ass_path:         Arquivo .ass com as legendas.
        output_path:      Onde salvar o MP4 final.
        fade_out_seconds: Duracao do fade pra preto + audio fade out
                          aplicado nos ULTIMOS N segundos. Default 3.0.
                          Use 0 pra desativar.
        fade_in_seconds:  Duracao do fade in (do preto pro video) no INICIO.
                          Default 0.3. Use 0 pra desativar.

    Returns:
        Path do video final.

    Raises:
        RuntimeError: Se o FFmpeg falhar.

    Por que copiamos os arquivos pra um diretorio temporario:
        O filter `subtitles=` do FFmpeg tem parser MUITO sensivel a
        caracteres especiais no caminho (! , | ( ) espacos acentos).
        Copiar pra path ASCII (input.mp4 / subs.ass) elimina o problema.

    Por que re-encodar audio agora:
        afade= filter exige re-encode (nao da pra usar -c:a copy).
        Custo perceptivel quase zero (audio AAC mantem qualidade alta).

    Filtros aplicados na ordem:
        Video:  subtitles -> fade in -> fade out
        Audio:  afade in  -> afade out
    """
    video = Path(video_path).resolve()
    ass = Path(ass_path).resolve()
    output = Path(output_path).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)

    # Pega duracao do video pra calcular onde comeca o fade out
    duration = _probe_duration(video)
    if duration <= 0 and fade_out_seconds > 0:
        logger.warning("Nao consegui ler duracao - desativando fade out")
        fade_out_seconds = 0

    # Calcula start do fade out (max evita negativo)
    fade_out_start = max(0.0, duration - fade_out_seconds)

    with tempfile.TemporaryDirectory(prefix="shorts_cap_") as tmp_dir:
        tmp_dir_path = Path(tmp_dir)

        # Copia inputs com nomes ASCII safe
        tmp_video = tmp_dir_path / "input.mp4"
        tmp_ass = tmp_dir_path / "subs.ass"
        tmp_output = tmp_dir_path / "output.mp4"

        shutil.copy2(video, tmp_video)
        shutil.copy2(ass, tmp_ass)

        # Path do .ass formato FFmpeg-compativel
        ass_str = str(tmp_ass).replace("\\", "/")
        if len(ass_str) >= 2 and ass_str[1] == ":":
            ass_str = ass_str[0] + "\\:" + ass_str[2:]

        # Monta a video filter chain
        vf_parts = [f"subtitles='{ass_str}'"]
        if fade_in_seconds > 0:
            vf_parts.append(f"fade=t=in:st=0:d={fade_in_seconds}")
        if fade_out_seconds > 0:
            vf_parts.append(f"fade=t=out:st={fade_out_start}:d={fade_out_seconds}")
        vf = ",".join(vf_parts)

        # Monta a audio filter chain (so se houver fade pra aplicar)
        af_parts = []
        if fade_in_seconds > 0:
            af_parts.append(f"afade=t=in:st=0:d={fade_in_seconds}")
        if fade_out_seconds > 0:
            af_parts.append(f"afade=t=out:st={fade_out_start}:d={fade_out_seconds}")

        cmd = [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "warning",
            "-i", str(tmp_video),
            "-vf", vf,
        ]
        # Audio: aplica fade SE solicitado, senao copia direto (mais rapido)
        if af_parts:
            cmd += ["-af", ",".join(af_parts), "-c:a", "aac", "-b:a", "128k"]
        else:
            cmd += ["-c:a", "copy"]

        cmd += [
            "-c:v", "libx264", "-preset", "medium", "-crf", "20",
            "-pix_fmt", "yuv420p",
            "-movflags", "+faststart",
            str(tmp_output),
        ]

        fade_msg = f" (fade out {fade_out_seconds}s)" if fade_out_seconds > 0 else ""
        logger.info("Queimando legendas em %s%s", video.name, fade_msg)
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg falhou:\n{result.stderr[-1500:]}")

        shutil.move(str(tmp_output), str(output))

    logger.info("Video com legendas + fade salvo: %s", output.name)
    return output


def caption_all_clips(
    transcript: Transcript,
    analysis: ViralAnalysis,
    *,
    cache_key_base: str,
    font_size: int = 90,
    max_words_per_chunk: int = 3,
    fade_out_seconds: float = 3.0,
    fade_in_seconds: float = 0.3,
    cleanup_intermediates: bool = True,
) -> list[Path]:
    """
    Gera legendas pra todos os clips da analise + queima nos MP4 cropados.

    Args:
        transcript:            Transcript completo do video original.
        analysis:              ViralAnalysis com os clips.
        cache_key_base:        Mesmo prefixo da Etapa 4 (ex: pregacao).
        font_size:             Tamanho da fonte das legendas.
        max_words_per_chunk:   1-3 e o range util.
        fade_out_seconds:      Duracao do fade out (default 3.0).
        fade_in_seconds:       Duracao do fade in (default 0.3).
        cleanup_intermediates: Se True (default), apaga os _clip_N.mp4 sem
                               legenda e renomeia os _captioned pro nome
                               final simples. Se False, mantem ambos.

    Returns:
        Lista de Paths dos MP4s finais com legendas.

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

        # Queima no MP4 com sufixo _captioned (intermediario do nome final)
        captioned_temp = OUTPUTS_DIR / f"{cache_key_base}_clip_{idx}_captioned.mp4"
        burn_subtitles(
            cropped_video, ass_path, captioned_temp,
            fade_out_seconds=fade_out_seconds,
            fade_in_seconds=fade_in_seconds,
        )

        # Limpa intermediarios e renomeia pro nome final.
        # Comportamento padrao: data/outputs/ fica SOMENTE com os finais
        # com legenda, com nome simples <base>_clip_N.mp4.
        if cleanup_intermediates:
            try:
                cropped_video.unlink()  # remove o cropado sem legenda
            except FileNotFoundError:
                pass
            # Renomeia _captioned -> nome final (sem sufixo)
            final_path = OUTPUTS_DIR / f"{cache_key_base}_clip_{idx}.mp4"
            if final_path.exists():
                final_path.unlink()  # garante override em re-runs
            captioned_temp.rename(final_path)
            outputs.append(final_path)
            logger.info("Limpeza: %s removido, final em %s",
                        cropped_video.name, final_path.name)
        else:
            outputs.append(captioned_temp)

    return outputs

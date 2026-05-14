"""
Etapa 1 — Downloader / Ingest de vídeo

O que essa etapa faz:
    Recebe a "fonte" de um vídeo (URL do YouTube OU caminho de arquivo local)
    e devolve um VideoSource padronizado, com o arquivo já dentro de
    `data/inputs/` e seus metadados (título, duração).

Por que essa abstração existe:
    O resto do pipeline (transcrição, análise, corte) não precisa saber
    DE ONDE o vídeo veio. Seja de YouTube ou de um upload, todo mundo
    recebe o mesmo tipo: `VideoSource`. Isso isola a complexidade do
    download e torna fácil testar com arquivos locais sem depender de rede.

Ferramentas usadas:
    - `yt-dlp` (biblioteca) — baixa de YouTube e centenas de outros sites
    - `ffprobe` (binário do sistema, vem com ffmpeg) — lê duração de arquivos locais
"""
from __future__ import annotations

import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yt_dlp

from src.common.paths import INPUTS_DIR, ensure_dirs


# Regex pra detectar se uma string parece uma URL HTTP(S).
# `^https?://` = começa com "http://" ou "https://".
# `re.IGNORECASE` = aceita "HTTP", "Https" etc. (alguns usuários escrevem com caixa alta).
# Não validamos se é YouTube especificamente — o yt-dlp suporta muito mais sites,
# então deixamos ele decidir o que sabe baixar.
URL_PATTERN = re.compile(r"^https?://", re.IGNORECASE)


@dataclass
class VideoSource:
    """
    Resultado padronizado da Etapa 1 (ingest).

    Todas as próximas etapas (transcriber, analyzer, cropper) recebem
    instâncias dessa classe e operam sobre `path`.

    Attributes:
        path:        Caminho LOCAL do arquivo de vídeo (sempre dentro de data/inputs/).
                     É um `Path`, então funciona em Windows e Linux.
        title:       Título original do vídeo. Pra YouTube vem do metadado;
                     pra arquivo local, vem do nome do arquivo (sem extensão).
        duration_s:  Duração total do vídeo em segundos (float, com casas decimais).
                     Pode ser 0.0 se não conseguimos ler (não é crítico nessa etapa).
        source_url:  URL original SE o vídeo veio da internet.
                     `None` se foi um upload de arquivo local.
    """
    path: Path
    title: str
    duration_s: float
    source_url: str | None = None


def is_url(value: str) -> bool:
    """
    Testa se uma string parece ser uma URL HTTP(S).

    Args:
        value: A string a testar (geralmente o input bruto do usuário).

    Returns:
        True se começar com "http://" ou "https://" (case-insensitive).
        False caso contrário.

    Exemplos:
        >>> is_url("https://www.youtube.com/watch?v=abc")
        True
        >>> is_url("C:\\Users\\foo\\video.mp4")
        False
        >>> is_url("/tmp/video.mp4")
        False
        >>> is_url("HTTPS://YOUTU.BE/abc")  # caixa alta funciona
        True

    Nota:
        Não validamos se é uma URL VÁLIDA, nem se o site é suportado pelo yt-dlp.
        Só checamos se "parece" uma URL. O yt-dlp vai dar erro se a URL for inválida.
    """
    return bool(URL_PATTERN.match(value.strip()))


def ingest(source: str, output_dir: Path | None = None) -> VideoSource:
    """
    Ponto de entrada ÚNICO da Etapa 1. Aceita URL ou caminho local.

    Args:
        source: URL HTTP(S) OU caminho absoluto/relativo de um arquivo local.
                Exemplos válidos:
                  - "https://www.youtube.com/watch?v=jNQXAC9IVRw"
                  - "/home/maicon/videos/pregacao.mp4"
                  - "C:\\Users\\maicon\\Downloads\\video.mp4"
                  - "data/inputs/ja_existe.mp4"
        output_dir: Pasta onde salvar o arquivo final.
                    Default (`None`) = usa `data/inputs/` do projeto.

    Returns:
        VideoSource com tudo que as próximas etapas precisam:
        caminho do arquivo, título, duração, URL original (se aplicável).

    Raises:
        FileNotFoundError: Se `source` for caminho local e o arquivo não existir.
        ValueError: Se `source` for caminho local que aponta pra algo que NÃO é arquivo
                    (ex: uma pasta).
        RuntimeError: Se foi URL mas o download falhou (rede caiu, vídeo privado, etc.).

    Exemplos:
        >>> # Baixar do YouTube:
        >>> result = ingest("https://www.youtube.com/watch?v=jNQXAC9IVRw")
        >>> print(result.path)  # data/inputs/Me at the zoo [jNQXAC9IVRw].mp4

        >>> # Ingerir arquivo local:
        >>> result = ingest("/tmp/meu_video.mp4")
        >>> print(result.title)  # "meu_video"

    Como funciona internamente:
        1. Detecta se `source` é URL ou caminho via `is_url()`.
        2. Se URL → chama `_download_from_url()` (usa yt-dlp).
        3. Se caminho → chama `_ingest_local_file()` (copia pra data/inputs/).
        4. Em ambos os casos, garante que data/inputs/ existe via `ensure_dirs()`.
    """
    ensure_dirs()
    out_dir = output_dir or INPUTS_DIR

    if is_url(source):
        return _download_from_url(source, out_dir)
    return _ingest_local_file(source, out_dir)


def _download_from_url(url: str, out_dir: Path) -> VideoSource:
    """
    Baixa um vídeo da internet via yt-dlp e devolve um VideoSource.

    Função "privada" (prefixo `_`) — não importar de fora desse módulo.
    Use `ingest()` ao invés disso, que decide automaticamente se baixa
    ou trata como arquivo local.

    Args:
        url: URL HTTP(S) de um vídeo suportado pelo yt-dlp.
        out_dir: Pasta onde o arquivo final será salvo.

    Returns:
        VideoSource com `source_url` preenchido.

    Raises:
        RuntimeError: Se o download "terminou" mas o arquivo final não foi
                      encontrado no disco (caso raro de erro no yt-dlp).

    Decisões técnicas explicadas:

        format = 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/bestvideo+bestaudio/best':
            Pega a MELHOR QUALIDADE disponível, sem limite de resolução.
            Estratégia em 3 fallbacks (yt-dlp tenta na ordem):
                1. Melhor vídeo MP4 + melhor áudio M4A (preferido = compatível com FFmpeg)
                2. Melhor vídeo + melhor áudio em qualquer formato
                3. Melhor stream pré-combinado (caso o site não separe trilhas)

            Por que sem limite de altura:
                Vídeos da fonte podem ter qualquer resolução (1080p, 4K).
                Mesmo o output sendo 1080x1920, partir de uma fonte 4K dá:
                    - Mais detalhe pra cropar (rosto fica nítido após crop)
                    - Mais opções de tracking (mais pixels, melhor detecção)
                    - Qualidade visual superior nos Shorts finais
                FUTURO: quando tiver frontend, deixar o usuário escolher
                a qualidade (HD/FullHD/4K) baseado em banda disponível.

        merge_output_format = 'mp4':
            Força o arquivo final a ser .mp4 (mais simples pra FFmpeg processar depois).

        outtmpl = '<title> [<id>].<ext>':
            Nome do arquivo: "Título original [vídeo_id].mp4".
            O ID entre colchetes evita conflito se 2 vídeos têm título idêntico.
            yt-dlp sanitiza o título (remove `/`, `:`, etc. ilegais em filesystems).

        noplaylist = True:
            Se o usuário colar uma URL de playlist, baixa só o primeiro vídeo.
            Sem isso, o yt-dlp tentaria baixar 50+ vídeos sem avisar.
    """
    outtmpl = str(out_dir / "%(title)s [%(id)s].%(ext)s")

    ydl_opts = {
        # Sem restrição de altura — pega a melhor qualidade disponível
        "format": "bestvideo+bestaudio/best",
        "merge_output_format": "mp4",
        "outtmpl": outtmpl,
        "noplaylist": True,
        "quiet": False,
        "no_warnings": False,
        "writethumbnail": False,
    }

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        # extract_info baixa o vídeo E retorna um dict com metadados (título, duração, etc.)
        info = ydl.extract_info(url, download=True)
        # prepare_filename traduz o `outtmpl` em um caminho REAL no disco.
        downloaded_path = Path(ydl.prepare_filename(info))
        # Edge case: às vezes o merge muda a extensão pra .mp4 mas o nome
        # devolvido ainda aponta pra extensão original. Corrigimos manualmente.
        if not downloaded_path.exists() and downloaded_path.with_suffix(".mp4").exists():
            downloaded_path = downloaded_path.with_suffix(".mp4")

    if not downloaded_path.exists():
        raise RuntimeError(f"Download terminou mas o arquivo não foi encontrado: {downloaded_path}")

    return VideoSource(
        path=downloaded_path,
        title=info.get("title", downloaded_path.stem),
        duration_s=float(info.get("duration") or 0.0),
        source_url=url,
    )


def _ingest_local_file(path_str: str, out_dir: Path) -> VideoSource:
    """
    Trata um arquivo local: copia pra data/inputs/ e lê a duração via ffprobe.

    Função "privada" — use `ingest()`.

    Por que copiar ao invés de só apontar pro arquivo original?
        Padronização. Todo arquivo passa por data/inputs/ — facilita backup,
        organização, e evita que o pipeline quebre se o arquivo original
        sumir no meio do processamento.

    Por que NÃO copia se já está em data/inputs/?
        Evita duplicar gigabytes desnecessariamente. A checagem é feita
        comparando os paths resolvidos (absolutos).

    Args:
        path_str: Caminho do arquivo local (string).
        out_dir: Pasta de destino (geralmente data/inputs/).

    Returns:
        VideoSource com `source_url=None` (não veio da internet).

    Raises:
        FileNotFoundError: Arquivo não existe.
        ValueError: Caminho aponta pra algo que não é arquivo (ex: diretório).
    """
    # `.expanduser()` resolve "~" em paths tipo "~/videos/foo.mp4".
    # `.resolve()` transforma em caminho absoluto canônico.
    src_path = Path(path_str).expanduser().resolve()
    if not src_path.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {src_path}")
    if not src_path.is_file():
        raise ValueError(f"Caminho não é um arquivo: {src_path}")

    dest = out_dir / src_path.name
    # Se origem == destino, não copiamos (seria desperdício de tempo/disco).
    if src_path.resolve() != dest.resolve():
        # copy2 preserva metadados (timestamps) — útil pra auditoria.
        shutil.copy2(src_path, dest)

    duration = _probe_duration(dest)

    return VideoSource(
        path=dest,
        title=src_path.stem,    # nome do arquivo sem extensão
        duration_s=duration,
        source_url=None,
    )


def _probe_duration(path: Path) -> float:
    """
    Lê a duração de um arquivo de vídeo/áudio chamando o binário `ffprobe`.

    Função "privada".

    Args:
        path: Caminho do arquivo.

    Returns:
        Duração em segundos (float). Retorna `0.0` se:
        - o `ffprobe` não está instalado no sistema
        - o arquivo não é um vídeo válido
        - o `ffprobe` demora mais de 30 segundos (timeout)

        Por que não levantar exceção? Porque duração não é crítica na Etapa 1.
        Etapa 2 (transcrição) também detecta duração e usa essa informação.
        Se aqui falhar, o pipeline continua funcionando.

    Por que `subprocess` ao invés de uma lib Python?
        ffprobe é um binário externo (vem com FFmpeg). Não existe uma lib Python
        100% confiável que substitua. `subprocess` é a forma padrão de chamá-lo.

    Comando que rodamos por baixo:
        ffprobe -v error -show_entries format=duration \\
                -of default=noprint_wrappers=1:nokey=1 <arquivo>

        Saída esperada: uma linha com o número de segundos, ex: "97.234"
    """
    import subprocess

    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True, text=True, timeout=30,
        )
        return float(result.stdout.strip()) if result.returncode == 0 else 0.0
    except (FileNotFoundError, ValueError, subprocess.TimeoutExpired):
        # FileNotFoundError = ffprobe não instalado
        # ValueError = saída do ffprobe não é um número (arquivo corrompido)
        # TimeoutExpired = ffprobe travou
        return 0.0

"""
Testes do downloader que NÃO dependem de rede.
Pra teste end-to-end com YouTube real, use o CLI: `python -m src.downloader.cli <url>`
"""
import subprocess
from pathlib import Path

from src.downloader import is_url, ingest


def test_is_url_detects_http_and_https():
    assert is_url("http://youtube.com/watch?v=abc")
    assert is_url("https://youtu.be/abc")
    assert is_url("HTTPS://YOUTU.BE/abc")  # case-insensitive


def test_is_url_rejects_local_paths():
    assert not is_url("/tmp/video.mp4")
    assert not is_url("C:\\Users\\foo\\video.mp4")
    assert not is_url("./video.mp4")
    assert not is_url("video.mp4")


def test_ingest_local_file_copies_to_inputs(tmp_path):
    """Cria um vídeo dummy de 1 segundo via FFmpeg e confirma que ingest copia pra pasta."""
    fake_video = tmp_path / "fake.mp4"
    # Vídeo preto de 1s, 320x240 — minúsculo, suficiente pra testar o fluxo.
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", str(fake_video)],
        capture_output=True, check=True,
    )

    result = ingest(str(fake_video), output_dir=tmp_path / "outputs")

    assert result.path.exists()
    assert result.title == "fake"
    assert result.source_url is None
    assert result.duration_s > 0  # ffprobe deve ler ~1.0


def test_ingest_local_file_raises_on_missing():
    import pytest
    with pytest.raises(FileNotFoundError):
        ingest("/nao/existe/video.mp4")

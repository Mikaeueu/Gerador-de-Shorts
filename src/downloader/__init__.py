"""Etapa 1 — Ingest de vídeo (YouTube ou upload local)."""
from src.downloader.downloader import VideoSource, ingest, is_url

__all__ = ["VideoSource", "ingest", "is_url"]

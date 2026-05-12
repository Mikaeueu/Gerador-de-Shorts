"""
CLI mínimo do downloader — interface de linha de comando pra testar manualmente.

Pra que serve?
    Permite rodar a Etapa 1 sozinha, sem API/frontend, direto do terminal.
    Útil pra:
        - testar se yt-dlp está funcionando
        - baixar um vídeo rapidamente pra usar com os próximos módulos
        - debug isolado da etapa

Uso:
    python -m src.downloader.cli <URL-ou-caminho>

Exemplos:
    python -m src.downloader.cli "https://www.youtube.com/watch?v=jNQXAC9IVRw"
    python -m src.downloader.cli "/home/maicon/Downloads/pregacao.mp4"
    python -m src.downloader.cli "C:\\Users\\maicon\\video.mp4"
"""
import sys

from src.downloader import ingest


def main() -> int:
    """
    Ponto de entrada do CLI.

    Lê o argumento da linha de comando, chama `ingest()`, imprime o resultado
    de forma legível, e retorna um exit code apropriado.

    Returns:
        0 = sucesso
        1 = uso incorreto (argumentos faltando)
        2 = erro durante o ingest (rede caiu, arquivo não existe, etc.)

    Por que retornar exit codes?
        Permite encadear comandos em scripts shell. Ex:
            python -m src.downloader.cli "$URL" && python -m src.transcriber.cli ...
    """
    if len(sys.argv) != 2:
        print("Uso: python -m src.downloader.cli <url-ou-caminho>")
        return 1

    source = sys.argv[1]
    print(f"[ingest] processando: {source}")

    try:
        result = ingest(source)
    except Exception as e:
        # Capturamos QUALQUER exceção pra imprimir uma mensagem amigável.
        # `type(e).__name__` mostra o tipo (FileNotFoundError, RuntimeError, etc.)
        # ao invés de só a mensagem — ajuda a debugar.
        print(f"[erro] {type(e).__name__}: {e}")
        return 2

    print("[ok]")
    print(f"  título    : {result.title}")
    print(f"  arquivo   : {result.path}")
    print(f"  duração   : {result.duration_s:.1f}s")
    print(f"  origem    : {result.source_url or '(arquivo local)'}")
    return 0


if __name__ == "__main__":
    # `raise SystemExit(N)` é a forma idiomática de retornar exit code do Python.
    # Equivalente a `sys.exit(N)` mas mais explícito sobre o que tá acontecendo.
    raise SystemExit(main())

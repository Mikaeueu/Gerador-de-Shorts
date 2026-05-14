"""
Launcher do servidor da API.

Uso:
    python -m src.api.cli              # rodar com defaults (porta 8000)
    python -m src.api.cli --port 8080  # porta custom
    python -m src.api.cli --reload     # auto-reload em mudancas de codigo (dev)

Equivalente direto via uvicorn:
    uvicorn src.api.main:app --host 0.0.0.0 --port 8000 --reload
"""
import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="Inicia a API do Gerador de Shorts")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Host pra bind (default: 127.0.0.1; use 0.0.0.0 pra rede)")
    parser.add_argument("--port", type=int, default=8000,
                        help="Porta (default: 8000)")
    parser.add_argument("--reload", action="store_true",
                        help="Auto-reload em mudanca de codigo (modo dev)")
    args = parser.parse_args()

    # Import tardio: uvicorn carrega varias deps grandes.
    import uvicorn

    print("=" * 60)
    print(" Gerador de Shorts API")
    print("=" * 60)
    print(f"  URL          : http://{args.host}:{args.port}")
    print(f"  Docs Swagger : http://{args.host}:{args.port}/docs")
    print(f"  ReDoc        : http://{args.host}:{args.port}/redoc")
    print(f"  Reload       : {'ATIVADO' if args.reload else 'desativado'}")
    print("=" * 60)
    print("")

    uvicorn.run(
        "src.api.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

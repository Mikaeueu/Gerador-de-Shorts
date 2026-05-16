"""
Caminhos centralizados do projeto.

Por que esse módulo existe?
- Pra evitar que cada parte do código tenha que descobrir "onde fica a pasta de
  inputs?". Toda etapa importa daqui (ex: `from src.common.paths import INPUTS_DIR`).
- Mudar a estrutura de pastas vira uma alteração em UM lugar só.
- Cross-platform garantido: usamos `pathlib.Path` (funciona em Windows, Linux e Mac).

Estrutura de pastas que esse módulo representa:

    Gerador de Shorts/         ← ROOT_DIR
    ├── src/
    │   └── common/paths.py    ← este arquivo
    └── data/                  ← DATA_DIR
        ├── inputs/            ← INPUTS_DIR   (vídeos baixados / uploads)
        ├── outputs/           ← OUTPUTS_DIR  (shorts finais — em subpastas por vídeo)
        │   ├── <video_A>/
        │   │   ├── <titulo_clip_1>.mp4
        │   │   └── <titulo_clip_2>.mp4
        │   └── <video_B>/
        │       └── ...
        └── temp/              ← TEMP_DIR     (cache: transcripts.json, viral.json)
"""
import re
from pathlib import Path

# `__file__` aponta pra ESTE arquivo (paths.py). `.resolve()` transforma em absoluto.
# `.parent.parent.parent` sobe 3 níveis: paths.py → common/ → src/ → raiz do projeto.
ROOT_DIR = Path(__file__).resolve().parent.parent.parent

DATA_DIR = ROOT_DIR / "data"
INPUTS_DIR = DATA_DIR / "inputs"      # vídeos baixados ou enviados pelo usuário
OUTPUTS_DIR = DATA_DIR / "outputs"    # shorts finais prontos pra postar
TEMP_DIR = DATA_DIR / "temp"          # arquivos intermediários (JSON de transcrição, análise viral, etc.)


def ensure_dirs() -> None:
    """
    Garante que todas as pastas de dados existam — cria as que faltarem.

    Quando chamar:
        No início de qualquer função que vá ESCREVER dentro de data/ (ex:
        `ingest()`, `transcribe()`, `analyze()`). Idempotente: chamar várias
        vezes não causa erro.

    Por que `parents=True`:
        Se `data/` não existir ainda, cria ele junto com `data/inputs/` etc.
        Sem isso, daria erro tentando criar uma subpasta dentro de uma pasta
        inexistente.

    Por que `exist_ok=True`:
        Não dá erro se a pasta JÁ existe — fundamental pra idempotência.
    """
    for d in (INPUTS_DIR, OUTPUTS_DIR, TEMP_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _sanitize_folder_name(name: str, max_length: int = 120) -> str:
    """
    Converte um nome qualquer (geralmente título de vídeo) em nome de pasta safe.

    Args:
        name:       Nome bruto (ex: cache_key vindo do downloader).
        max_length: Tamanho máximo do nome (default 120 — sobra pro filename
                    final dentro da pasta).

    Returns:
        String segura pra usar como nome de diretório em Windows/Linux/macOS.
        Caracteres ilegais (`< > : " / \\ | ? *`) viram espaço. Pontuação
        final é removida. Trunca em palavra inteira. Fallback "video" se vazio.
    """
    sanitized = re.sub(r'[<>:"/\\|?*]', " ", name)
    sanitized = re.sub(r"[\x00-\x1f]", "", sanitized)
    sanitized = re.sub(r"\s+", " ", sanitized).strip()
    sanitized = sanitized.rstrip(".!?,;: ")
    if len(sanitized) > max_length:
        cut = sanitized[:max_length].rsplit(" ", 1)[0]
        sanitized = cut if cut else sanitized[:max_length]
    return sanitized.strip() or "video"


def get_video_output_dir(cache_key_base: str) -> Path:
    """
    Retorna a subpasta de outputs dedicada a UM vídeo, criando se necessário.

    Cada vídeo processado pelo pipeline tem sua própria pasta dentro de
    `data/outputs/`. Isso organiza os shorts por origem — em vez de
    todos os clips de todos os vídeos misturados numa pasta gigante.

    Args:
        cache_key_base: Identificador do vídeo (geralmente o stem do arquivo
                        de input). Ex: "Não Ande Ansioso [X18HYF5HTAU]".

    Returns:
        Path da subpasta, garantida existente. Ex:
            data/outputs/Não Ande Ansioso [X18HYF5HTAU]/

    Side effect:
        Cria a pasta se ainda não existir.
    """
    ensure_dirs()
    folder = OUTPUTS_DIR / _sanitize_folder_name(cache_key_base)
    folder.mkdir(parents=True, exist_ok=True)
    return folder

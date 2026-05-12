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
        ├── outputs/           ← OUTPUTS_DIR  (shorts finais prontos)
        └── temp/              ← TEMP_DIR     (cache: transcripts.json, viral.json)
"""
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

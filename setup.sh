#!/usr/bin/env bash
# ============================================================
# Gerador de Shorts — Setup automatizado para Linux Mint XFCE
# ============================================================
# Este script é IDEMPOTENTE: pode ser rodado várias vezes sem problema.
# Ele instala dependências do sistema, cria o venv e instala libs Python.
#
# Uso:
#   chmod +x setup.sh
#   ./setup.sh
# ============================================================

set -euo pipefail

# Cores pra output mais legível (XFCE terminal suporta ANSI colors)
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'  # No Color

info()  { echo -e "${GREEN}[setup]${NC} $*"; }
warn()  { echo -e "${YELLOW}[setup]${NC} $*"; }
error() { echo -e "${RED}[setup]${NC} $*" >&2; }

# Garante que rodamos da pasta do projeto
cd "$(dirname "$0")"
PROJECT_DIR="$(pwd)"
info "Projeto: $PROJECT_DIR"

# ------------------------------------------------------------
# 1. Dependências do sistema (apt)
# ------------------------------------------------------------
info "Verificando dependências do sistema..."

NEED_APT_INSTALL=()
command -v ffmpeg  >/dev/null 2>&1 || NEED_APT_INSTALL+=(ffmpeg)
command -v ffprobe >/dev/null 2>&1 || true  # vem com ffmpeg
command -v python3 >/dev/null 2>&1 || NEED_APT_INSTALL+=(python3)
dpkg -l python3-venv >/dev/null 2>&1 || NEED_APT_INSTALL+=(python3-venv)
dpkg -l python3-pip  >/dev/null 2>&1 || NEED_APT_INSTALL+=(python3-pip)

if [ ${#NEED_APT_INSTALL[@]} -gt 0 ]; then
    warn "Vou instalar via apt: ${NEED_APT_INSTALL[*]}"
    warn "Você vai precisar digitar sua senha (sudo)."
    sudo apt update
    sudo apt install -y "${NEED_APT_INSTALL[@]}"
else
    info "Todas as dependências do sistema já estão instaladas."
fi

# ------------------------------------------------------------
# 2. Versão do Python (precisa ser >= 3.10)
# ------------------------------------------------------------
PYTHON_VERSION=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
info "Python detectado: $PYTHON_VERSION"

PYTHON_MAJOR=$(echo "$PYTHON_VERSION" | cut -d. -f1)
PYTHON_MINOR=$(echo "$PYTHON_VERSION" | cut -d. -f2)
if [ "$PYTHON_MAJOR" -lt 3 ] || { [ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 10 ]; }; then
    error "Python 3.10+ é necessário. Versão atual: $PYTHON_VERSION"
    exit 1
fi

# ------------------------------------------------------------
# 3. Ambiente virtual
# ------------------------------------------------------------
if [ ! -d "venv" ]; then
    info "Criando ambiente virtual em ./venv ..."
    python3 -m venv venv
else
    info "Ambiente virtual já existe."
fi

# ------------------------------------------------------------
# 4. Instalar dependências Python dentro do venv
# ------------------------------------------------------------
info "Atualizando pip e instalando dependências de requirements.txt ..."
# Usamos o pip do venv diretamente (sem precisar 'source activate')
./venv/bin/pip install --upgrade pip --quiet
./venv/bin/pip install -r requirements.txt

# ------------------------------------------------------------
# 5. Criar pastas de dados (caso não existam)
# ------------------------------------------------------------
mkdir -p data/inputs data/outputs data/temp

# ------------------------------------------------------------
# 6. Pronto!
# ------------------------------------------------------------
echo ""
info "Setup concluído com sucesso!"
echo ""
echo "Pra ativar o ambiente em qualquer terminal novo:"
echo "  source venv/bin/activate"
echo ""
echo "Pra testar agora (baixa um vídeo de 19s do YouTube):"
echo "  source venv/bin/activate"
echo "  python -m src.downloader.cli 'https://www.youtube.com/watch?v=jNQXAC9IVRw'"
echo ""

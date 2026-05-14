# Gerador de Shorts

Pipeline open-source pra transformar vídeos longos (YouTube ou upload local) em shorts verticais com legendas automáticas — inspirado no Opus Clip.

## Arquitetura

```
┌──────────┐   ┌─────────────┐   ┌──────────┐   ┌──────────────┐   ┌────────────┐   ┌──────────┐
│ INPUT    │ → │ TRANSCRIBER │ → │ ANALYZER │ → │  CROPPER     │ → │ CAPTIONER  │ → │  EXPORT  │
│ yt-dlp / │   │ faster-     │   │ Gemini / │   │ MediaPipe +  │   │ ASS subs + │   │  FFmpeg  │
│ upload   │   │ whisper     │   │ Groq LLM │   │ FFmpeg crop  │   │ FFmpeg     │   │          │
└──────────┘   └─────────────┘   └──────────┘   └──────────────┘   └────────────┘   └──────────┘
```

## Stack escolhida

| Componente            | Ferramenta                    | Por quê                                                 |
|-----------------------|-------------------------------|---------------------------------------------------------|
| Backend API           | FastAPI + Uvicorn             | Async nativo, validação automática, docs Swagger grátis |
| Download YouTube      | yt-dlp                        | Padrão de mercado, mantido ativamente                   |
| Transcrição           | faster-whisper (CPU)          | 4x mais rápido que Whisper original, roda em CPU        |
| Análise viral (LLM)   | Google Gemini 2.0 Flash       | Free tier generoso (1500 req/dia), rápido               |
| Detecção de rosto     | MediaPipe Face Detection      | Leve, otimizado pra CPU                                 |
| Corte/edição          | FFmpeg (subprocess)           | Mais rápido e confiável que MoviePy                     |
| Legendas              | ASS subtitles + FFmpeg burn-in| Estilo profissional (karaokê, palavra por palavra)      |

## Roadmap por etapas

O projeto é construído etapa por etapa, cada módulo testável de forma isolada antes de integrar.

- [x] **Etapa 0** — Estrutura de pastas e setup
- [x] **Etapa 1** — Downloader (YouTube + upload local)
- [x] **Etapa 2** — Transcrição com faster-whisper (timestamps por palavra)
- [x] **Etapa 3** — Análise viral via Gemini (templates por nicho)
- [x] **Etapa 4** — Reenquadramento vertical com tracking de rosto (MediaPipe + FFmpeg)
- [x] **Etapa 5** — Legendas estilo Opus (palavra-por-palavra, ASS + FFmpeg)
- [x] **Etapa 6** — Pipeline orquestrador end-to-end (1 comando faz tudo)
- [x] **Etapa 7** — API FastAPI com WebSocket pra progresso em tempo real
- [ ] **Etapa 8** — Frontend simples (HTML → React no futuro)

## Estrutura do projeto

```
Gerador de Shorts/
├── src/
│   ├── downloader/      # Etapa 1 — entrada do vídeo
│   ├── transcriber/     # Etapa 2 — Whisper
│   ├── analyzer/        # Etapa 3 — LLM viral
│   ├── cropper/         # Etapa 4 — vertical + face tracking
│   ├── captioner/       # Etapa 5 — legendas .ass
│   ├── api/             # Etapa 7 — FastAPI
│   └── common/          # utilitários compartilhados
├── data/
│   ├── inputs/          # vídeos baixados/enviados
│   ├── outputs/         # shorts gerados
│   └── temp/            # arquivos intermediários
├── tests/
├── requirements.txt
└── README.md
```

## Setup

O projeto roda em **Linux** e **Windows 10/11**. Escolha sua plataforma abaixo.

### Linux Mint / Ubuntu / Debian

```bash
# Setup automatizado (recomendado)
chmod +x setup.sh
./setup.sh
```

Ou manualmente:

```bash
sudo apt update && sudo apt install -y ffmpeg python3-venv python3-pip
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Windows 10 / 11

Pré-requisito: **Python 3.10+** instalado (https://www.python.org/downloads/ — marcar "Add Python to PATH").

```bat
:: 1. Instalar FFmpeg (uma vez só, via winget)
winget install Gyan.FFmpeg

:: 2. Setup automatizado
setup.bat
```

Ou manualmente, no PowerShell ou cmd:

```bat
python -m venv venv
venv\Scripts\activate
pip install -r requirements.txt
```

> **Sobre FFmpeg no Windows:** depois de `winget install Gyan.FFmpeg`, **abra um novo terminal** pra que o `PATH` seja recarregado. Teste com `ffmpeg -version`.

### Configurar API keys (a partir da Etapa 3)

```bash
# Linux
cp .env.example .env && nano .env

# Windows
copy .env.example .env
notepad .env
```

### Verificar instalação

```bash
# Linux
source venv/bin/activate
# Windows
venv\Scripts\activate

# Em qualquer SO:
python -m src.downloader.cli "https://www.youtube.com/watch?v=jNQXAC9IVRw"
# Deve baixar "Me at the zoo" (primeiro vídeo do YouTube, 19s) em data/inputs/
```

## Hardware alvo

Otimizado pra rodar em **notebook 16GB RAM, CPU only** (sem GPU dedicada):
- Whisper: modelo `base` ou `small` (não `large`)
- MediaPipe: roda nativamente em CPU
- FFmpeg: super eficiente em CPU
- XFCE consome pouca RAM, sobra recurso pro processamento

Vídeos curtos (< 15 min) processam em tempo razoável. Vídeos longos podem levar várias dezenas de minutos — perfeitamente aceitável pra uso pessoal.

> **Dica:** monitore uso de CPU/RAM enquanto processa — `htop` no Linux (`sudo apt install htop`) ou Gerenciador de Tarefas no Windows.

## Status atual

**Etapas 1, 2, 3 e 4 concluídas.** Próxima: Etapa 5 (legendas estilo karaokê).

### Pipeline completo

```bash
# 1. Baixar um vídeo
python -m src.downloader.cli "https://www.youtube.com/watch?v=..."

# 2. Transcrever (modelo `base` = rápido; `small` = mais preciso)
python -m src.transcriber.cli "data/inputs/pregacao.mp4" --model small --lang pt

# 3. Detectar trechos virais (template padrão = pregação evangélica)
python -m src.analyzer.cli "data/inputs/pregacao.mp4"

# 4. Cortar verticalmente com face tracking
python -m src.cropper.cli "data/temp/pregacao.viral.json" "data/inputs/pregacao.mp4"

# 5. Queimar legendas estilo Opus (palavra-por-palavra)
python -m src.captioner.cli "data/temp/pregacao.transcript.json" "data/temp/pregacao.viral.json"

# Resultado final: data/outputs/pregacao_clip_N_captioned.mp4
```

### API HTTP (Etapa 7)

Pra usar o pipeline via HTTP/WebSocket (ideal pra frontend ou integração):

```bash
# Subir o servidor (default: porta 8000):
python -m src.api.cli

# Modo dev com auto-reload:
python -m src.api.cli --reload

# Acessar:
#   http://127.0.0.1:8000/         - info da API
#   http://127.0.0.1:8000/docs     - Swagger UI (testa endpoints no browser)
#   http://127.0.0.1:8000/redoc    - documentação alternativa
```

**Endpoints principais:**
- `POST /jobs` — cria job a partir de URL (JSON `{"source": "..."}`)
- `POST /jobs/upload` — cria job via upload de arquivo (multipart)
- `GET /jobs` — lista todos os jobs
- `GET /jobs/{id}` — estado atual de um job
- `WS /jobs/{id}/ws` — stream de progresso em tempo real
- `GET /jobs/{id}/clips` — lista os MP4s finais
- `GET /jobs/{id}/clips/{n}` — baixa um clip específico

### Pipeline em 1 comando (Etapa 6)

Pra rodar tudo de uma vez sem chamar cada etapa separadamente:

```bash
# Direto da URL do YouTube:
python -m src.pipeline "https://www.youtube.com/watch?v=..."

# Ou de um arquivo local:
python -m src.pipeline "data/inputs/meu_video.mp4"

# Customizando opções:
python -m src.pipeline "URL" --model small --lang pt --max-clips 3 --words 2
```

O pipeline reusa **todos os caches** de etapas intermediárias — se você rodar 2x no mesmo vídeo, transcrição e análise são puladas.

Todos os intermediários são **cacheados em `data/temp/`** — rodar de novo é instantâneo.

### Editar manualmente o crop

Se o tracking automático errou em algum clip, edite `data/temp/<nome>_clip_N.crop.json` na mão e re-rode com `--use-cache-plan`:

```bash
python -m src.cropper.cli "data/temp/pregacao.viral.json" "data/inputs/pregacao.mp4" --use-cache-plan
```

Os keyframes têm `x_center` de 0.0 (esquerda) a 1.0 (direita), com 0.5 = centro.

### Templates do analyzer

| Template                 | Pra quê                                                        |
|--------------------------|----------------------------------------------------------------|
| `evangelical_preaching`  | Pregações cristãs — busca frase de impacto, versículo+aplicação, confronto, testemunho, quote-friendly |
| `generic`                | Qualquer outro tipo de conteúdo (podcast, aula, palestra)      |

Pra adicionar um template novo: editar `src/analyzer/prompts.py` e registrar em `TEMPLATES`.

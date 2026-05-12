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
- [ ] **Etapa 4** — Reenquadramento vertical com tracking de rosto
- [ ] **Etapa 5** — Geração de legendas estilo karaokê
- [ ] **Etapa 6** — Exportação final (FFmpeg)
- [ ] **Etapa 7** — API FastAPI envolvendo o pipeline
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

**Etapas 1, 2 e 3 concluídas.** Próxima: Etapa 4 (reenquadramento vertical com tracking de rosto).

### Como usar o que já está pronto

```bash
# 1. Baixar um vídeo
python -m src.downloader.cli "https://www.youtube.com/watch?v=..."

# 2. Transcrever (modelo `base` = rápido; `small` = mais preciso)
python -m src.transcriber.cli "data/inputs/pregacao.mp4" --model small --lang pt

# 3. Detectar trechos virais (template padrão = pregação evangélica)
python -m src.analyzer.cli "data/inputs/pregacao.mp4"

# Mudando template ou limites:
python -m src.analyzer.cli "data/inputs/podcast.mp4" --template generic --max-clips 8
```

Todos os intermediários (transcrição + análise) são **cacheados em `data/temp/`** — rodar de novo é instantâneo.

### Templates do analyzer

| Template                 | Pra quê                                                        |
|--------------------------|----------------------------------------------------------------|
| `evangelical_preaching`  | Pregações cristãs — busca frase de impacto, versículo+aplicação, confronto, testemunho, quote-friendly |
| `generic`                | Qualquer outro tipo de conteúdo (podcast, aula, palestra)      |

Pra adicionar um template novo: editar `src/analyzer/prompts.py` e registrar em `TEMPLATES`.

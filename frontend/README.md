# Frontend — Shorts Generator

Interface React do Gerador de Shorts, no estilo Linear/Vercel (dark mode minimalista).

## Stack

- **Vite** + **React 18** + **TypeScript**
- **Tailwind CSS v4** (com design tokens custom no `index.css`)
- **Lucide React** pra ícones
- **WebSocket nativo** pra progresso em tempo real

## Setup

Pré-requisito: **Node.js 18+** instalado.

```bash
cd frontend
npm install
npm run dev
```

Abre em `http://localhost:5173`.

> **Importante:** o backend (API FastAPI) precisa estar rodando em `http://127.0.0.1:8000`. Em outro terminal:
>
> ```bash
> cd ..
> python -m src.api.cli
> ```
>
> O Vite faz proxy automático: `/api/*` → `http://127.0.0.1:8000/*`.

## Build de produção

```bash
npm run build
```

Gera arquivos estáticos em `dist/`. Pra servir, basta hostear essa pasta com qualquer servidor estático (Caddy, Nginx, GitHub Pages, etc.). Em produção, configure as variáveis de ambiente:

```env
VITE_API_BASE_URL=https://api.seu-dominio.com
VITE_WS_BASE_URL=wss://api.seu-dominio.com
```

## Estrutura

```
frontend/
├── package.json
├── vite.config.ts        # config + proxy /api e /ws
├── tsconfig.json
├── index.html
└── src/
    ├── main.tsx
    ├── App.tsx           # composição principal (single-page)
    ├── index.css         # design tokens Linear-style
    ├── types.ts          # types espelhando Pydantic schemas
    ├── api.ts            # cliente HTTP fetch wrapper
    ├── useJobProgress.ts # hook de WebSocket por job
    └── components/
        ├── Header.tsx     # header sticky + status API
        ├── HeroInput.tsx  # input de URL + upload + settings
        ├── JobsList.tsx   # section com lista de jobs
        ├── JobCard.tsx    # card de um job (3 estados)
        └── ClipsGrid.tsx  # grid 9:16 + player modal
```

## Decisões de design

- **Single-page** — input + jobs + preview tudo numa tela só, igual Opus Clip.
- **Dark mode default** — preto profundo `#08080B`, accent azul `#5E6AD2` (cor exata do Linear).
- **WebSocket por job em running** — economiza conexões, fecha quando termina.
- **Polling de 5s** pra mudanças de status — pega queued→running→done sem precisar de WS persistente.
- **Sem Redux/Zustand** — useState + useEffect bastam pra esse escopo.
- **Sem React Router** — single page.

"""
Cadeia de providers LLM para a Etapa 3 (analise viral).

Quando o Gemini acaba quota (ou falha por qualquer motivo), tentamos
automaticamente o proximo provider na cadeia. Ordem:

    1. Gemini 2.5 Flash    - primario (free tier 1500 req/dia)
    2. Groq + Llama 3.3    - cloud rapido, free tier sem limite diario
    3. OpenAI GPT-4o-mini  - cloud pago, alta qualidade
    4. Ollama local        - offline, ilimitado (depende do hardware)

Cada provider implementa a mesma interface:
    - is_available() -> bool   (checa se tem credenciais/conexao)
    - analyze(prompt) -> list[ViralClip]   (chama o LLM e retorna clips)

A funcao publica analyze_with_fallback(prompt) faz o loop em ordem
ate algum funcionar. Se TODOS falharem, levanta RuntimeError com
o motivo de cada um.

Variaveis de ambiente reconhecidas (em .env):
    GOOGLE_API_KEY    - habilita GeminiProvider
    GEMINI_MODEL      - default "gemini-2.5-flash"
    GROQ_API_KEY      - habilita GroqProvider
    GROQ_MODEL        - default "llama-3.3-70b-versatile"
    OPENAI_API_KEY    - habilita OpenAIProvider
    OPENAI_MODEL      - default "gpt-4o-mini"
    OLLAMA_HOST       - default "http://localhost:11434"
    OLLAMA_MODEL      - default "llama3.2:3b"
"""
from __future__ import annotations

import json
import logging
import os
from abc import ABC, abstractmethod
from typing import Optional

from src.analyzer.schemas import ViralClip

logger = logging.getLogger(__name__)


# ============================================================
# Helpers
# ============================================================

def _load_env() -> None:
    """Carrega .env se python-dotenv estiver disponivel (no-op se nao)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass


def _parse_clips_from_json(text: str) -> list[ViralClip]:
    """
    Parseia JSON de resposta de LLM em lista de ViralClip.

    Aceita varios formatos comuns que LLMs retornam:
        - Array puro:           [{...}, {...}]
        - Objeto com 'clips':   {"clips": [...]}
        - Objeto com 'items':   {"items": [...]}
        - Objeto generico:      {"qualquer_chave": [...]}

    Args:
        text: Resposta bruta do LLM (string).

    Returns:
        Lista de ViralClip validados via Pydantic. Pode ser vazia.

    Raises:
        ValueError: Se o JSON for invalido ou nao contiver lista.
    """
    text = text.strip()
    # Remove fences markdown se LLM colou (acontece com Ollama as vezes)
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])

    data = json.loads(text)

    # Resolve a lista de clips de formatos diferentes
    if isinstance(data, list):
        clips_data = data
    elif isinstance(data, dict):
        # Tenta keys comuns primeiro
        clips_data = None
        for key in ("clips", "items", "results", "data", "shorts", "viral_clips"):
            if key in data and isinstance(data[key], list):
                clips_data = data[key]
                break
        # Fallback: pega o primeiro valor que for lista
        if clips_data is None:
            for v in data.values():
                if isinstance(v, list):
                    clips_data = v
                    break
        if clips_data is None:
            raise ValueError(f"Nao encontrei lista de clips no JSON: keys={list(data.keys())}")
    else:
        raise ValueError(f"JSON nao e lista nem objeto: tipo={type(data).__name__}")

    return [ViralClip.model_validate(c) for c in clips_data]


# ============================================================
# Interface base
# ============================================================

class LLMProvider(ABC):
    """Interface abstrata pra qualquer provider de LLM."""
    name: str = "base"

    @abstractmethod
    def is_available(self) -> bool:
        """True se o provider tem credenciais/conexao configurados."""

    @abstractmethod
    def analyze(self, prompt: str) -> list[ViralClip]:
        """Manda o prompt pro LLM e retorna clips. Levanta excecao se falhar."""


# ============================================================
# 1. Gemini (primario)
# ============================================================

class GeminiProvider(LLMProvider):
    """
    Provider primario - Gemini 2.5 Flash.

    Vantagens:
        - response_schema Pydantic nativo (output garantidamente valido)
        - 1M tokens de contexto
        - Free tier 1500 req/dia
    """
    name = "gemini"

    def is_available(self) -> bool:
        _load_env()
        return bool(os.getenv("GOOGLE_API_KEY"))

    def analyze(self, prompt: str) -> list[ViralClip]:
        _load_env()
        from google import genai
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        api_key = os.getenv("GOOGLE_API_KEY")
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config={
                "response_mime_type": "application/json",
                "response_schema": list[ViralClip],
                "temperature": 0.3,
            },
        )
        clips_raw = response.parsed or []
        return [
            c if isinstance(c, ViralClip) else ViralClip.model_validate(c)
            for c in clips_raw
        ]


# ============================================================
# 2. Groq (Llama 3.3 70B)
# ============================================================

# Instrucao adicional pra LLMs que nao tem schema forcado.
# Pedimos envelope {"clips": [...]} pq alguns "json_object" mode
# exigem um objeto top-level (nao array).
_JSON_ENVELOPE_INSTRUCTION = (
    "\n\nIMPORTANTE: Retorne UM OBJETO JSON valido no formato exato:\n"
    '{"clips": [<lista de clips no schema>]}\n'
    "Sem markdown, sem texto antes ou depois."
)


class GroqProvider(LLMProvider):
    """
    Provider 2 - Groq + Llama 3.3 70B.

    Vantagens:
        - Free tier MUITO generoso (sem limite diario fixo)
        - Latencia super baixa (~1-3s)
        - Llama 3.3 70B e bem capable
    """
    name = "groq"

    def is_available(self) -> bool:
        _load_env()
        return bool(os.getenv("GROQ_API_KEY"))

    def analyze(self, prompt: str) -> list[ViralClip]:
        _load_env()
        from groq import Groq
        model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        api_key = os.getenv("GROQ_API_KEY")
        client = Groq(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt + _JSON_ENVELOPE_INSTRUCTION}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        text = response.choices[0].message.content or ""
        return _parse_clips_from_json(text)


# ============================================================
# 3. OpenAI (GPT-4o-mini)
# ============================================================

class OpenAIProvider(LLMProvider):
    """
    Provider 3 - OpenAI GPT-4o-mini.

    Vantagens:
        - Modelo barato com qualidade alta
        - JSON mode confiavel
    Desvantagem:
        - Precisa cartao de credito mesmo no free tier inicial
    """
    name = "openai"

    def is_available(self) -> bool:
        _load_env()
        return bool(os.getenv("OPENAI_API_KEY"))

    def analyze(self, prompt: str) -> list[ViralClip]:
        _load_env()
        from openai import OpenAI
        model = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
        api_key = os.getenv("OPENAI_API_KEY")
        client = OpenAI(api_key=api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt + _JSON_ENVELOPE_INSTRUCTION}],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        text = response.choices[0].message.content or ""
        return _parse_clips_from_json(text)


# ============================================================
# 4. Ollama local (offline ilimitado)
# ============================================================

class OllamaProvider(LLMProvider):
    """
    Provider 4 - Ollama local (offline).

    Vantagens:
        - 100% offline, sem quota, sem custo
        - Sem cartao, sem internet
    Desvantagens:
        - Depende do hardware (CPU/RAM)
        - Modelos pequenos (3B) tem qualidade inferior aos grandes
        - Precisa Ollama instalado: https://ollama.com/

    Pre-requisito no notebook do user:
        ollama pull llama3.2:3b
    """
    name = "ollama"

    def _host(self) -> str:
        _load_env()
        return os.getenv("OLLAMA_HOST", "http://localhost:11434")

    def is_available(self) -> bool:
        # Tenta conectar no Ollama (timeout curto pra nao travar fallback)
        import urllib.request
        try:
            urllib.request.urlopen(f"{self._host()}/api/tags", timeout=2)
            return True
        except Exception:
            return False

    def analyze(self, prompt: str) -> list[ViralClip]:
        import urllib.request
        model = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
        host = self._host()
        body = json.dumps({
            "model": model,
            "prompt": prompt + _JSON_ENVELOPE_INSTRUCTION,
            "format": "json",   # Ollama tem modo JSON nativo
            "stream": False,
            "options": {"temperature": 0.3},
        }).encode("utf-8")

        req = urllib.request.Request(
            f"{host}/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        # Timeout generoso pq modelos locais sao lentos
        with urllib.request.urlopen(req, timeout=600) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        text = data.get("response", "")
        return _parse_clips_from_json(text)


# ============================================================
# Cadeia + funcao publica de fallback
# ============================================================

# Ordem default: Gemini -> Groq -> OpenAI -> Ollama
# Pra mudar a ordem, edite essa lista. Pra desativar um provider,
# basta nao configurar a env var dele (is_available() retorna False).
DEFAULT_CHAIN: list[type[LLMProvider]] = [
    GeminiProvider,
    GroqProvider,
    OpenAIProvider,
    OllamaProvider,
]


def get_provider_chain() -> list[LLMProvider]:
    """Instancia todos os providers na ordem default."""
    return [cls() for cls in DEFAULT_CHAIN]


def analyze_with_fallback(prompt: str) -> tuple[list[ViralClip], str]:
    """
    Tenta cada provider em ordem ate um funcionar.

    Args:
        prompt: O prompt completo pra mandar pro LLM (vem do prompts.py).

    Returns:
        Tupla (clips, provider_name). provider_name vai tipo
        "gemini" / "groq" / "openai" / "ollama" - util pra logging
        e pra preencher o campo `model` da ViralAnalysis.

    Raises:
        RuntimeError: Se TODOS os providers falharem ou nenhum estiver
                      configurado. A mensagem inclui o motivo de cada um.
    """
    chain = get_provider_chain()
    erros: list[str] = []
    for provider in chain:
        if not provider.is_available():
            erros.append(f"{provider.name}: nao configurado (env var ausente ou servico offline)")
            continue
        try:
            logger.info("Tentando provider: %s", provider.name)
            clips = provider.analyze(prompt)
            logger.info("Sucesso com %s: %d clips retornados", provider.name, len(clips))
            return clips, provider.name
        except Exception as e:
            err_msg = f"{type(e).__name__}: {e}"
            erros.append(f"{provider.name}: {err_msg}")
            logger.warning("Provider %s falhou (%s). Tentando proximo...",
                           provider.name, err_msg)

    raise RuntimeError(
        "TODOS os providers de LLM falharam.\n"
        "Tentativas:\n" + "\n".join(f"  - {e}" for e in erros) +
        "\n\nVerifique as variaveis de ambiente em .env "
        "(GOOGLE_API_KEY, GROQ_API_KEY, OPENAI_API_KEY) "
        "ou inicie o Ollama local."
    )

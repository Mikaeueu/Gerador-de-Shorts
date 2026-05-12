"""
Etapa 2 — Transcrição com faster-whisper

O que essa etapa faz:
    Recebe um arquivo de vídeo/áudio e devolve a transcrição completa COM
    timestamps por palavra. Isso é fundamental porque:
        - A Etapa 3 (analyzer) usa o texto + timestamps de segmento pra decidir
          quais trechos viram Short.
        - A Etapa 5 (captioner) usa os timestamps por palavra pra criar
          legendas estilo karaokê (palavra por palavra destacada).

Por que faster-whisper e não openai-whisper:
    - 4x mais rápido em CPU (usa CTranslate2 — uma reimplementação otimizada).
    - Mesma qualidade (carrega os mesmos pesos do Whisper original).
    - Suporta `word_timestamps=True` nativo, sem hacks.
    - Pode rodar em CPU com quantização int8, cabendo em 16GB RAM tranquilo.

Decisão importante sobre cache:
    Transcrever é o passo MAIS LENTO do pipeline (pode levar minutos em CPU).
    Por isso, cada transcrição é salva em data/temp/<nome>.transcript.json
    e reusada se você rodar de novo. Pra forçar reprocessar, use `use_cache=False`.
"""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Iterable

from src.common.paths import TEMP_DIR, ensure_dirs

logger = logging.getLogger(__name__)


# ============================================================
# Dataclasses do output
# ============================================================

@dataclass
class Word:
    """
    Uma única palavra reconhecida pelo Whisper, com seu timing exato.

    Esses dados vêm DIRETO do faster-whisper quando rodamos com
    `word_timestamps=True`. Sem essa flag, só temos timestamps de segmento.

    Attributes:
        text:        A palavra reconhecida. PODE incluir espaço/pontuação no início
                     (Whisper às vezes retorna " palavra," — não é bug, é como funciona).
        start:       Tempo em segundos do início da palavra no áudio.
        end:         Tempo em segundos do fim da palavra.
        probability: Confiança do modelo (0.0 a 1.0). Útil pra filtrar palavras
                     "alucinadas" — palavras com prob < 0.3 costumam ser ruído.
                     Não filtramos automaticamente porque depende do uso.
    """
    text: str
    start: float
    end: float
    probability: float


@dataclass
class Segment:
    """
    Um "segmento" = uma frase/chunk natural identificada pelo Whisper.

    O Whisper agrupa palavras em segmentos automaticamente, geralmente
    quebrando em pausas longas ou fim de frase. Isso é mais útil que
    palavra-por-palavra pro analyzer raciocinar sobre cortes.

    Attributes:
        text:   Texto completo do segmento (geralmente 1-3 frases).
        start:  Tempo de início em segundos.
        end:    Tempo de fim em segundos.
        words:  Lista de palavras dentro desse segmento, cada uma com seu timing.
                Vazia se rodamos sem `word_timestamps=True` (mas nós sempre rodamos com).
    """
    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)


@dataclass
class Transcript:
    """
    Resultado completo da transcrição de um vídeo. Esse é o objeto principal
    que circula entre etapas: transcribe() → analyzer → captioner.

    Attributes:
        language:             Código ISO do idioma detectado (ex: "pt", "en", "es").
                              Detecção é automática se você passa `language=None`.
        language_probability: Confiança da detecção (0.0 a 1.0). < 0.5 = duvidoso,
                              vale forçar `--lang pt` no CLI.
        duration:             Duração total do áudio processado em segundos.
        model_size:           Qual modelo foi usado ("tiny", "base", "small", "medium",
                              "large-v3"). Guardado pra invalidar cache se você
                              decidir rodar com um modelo melhor depois.
        segments:             Lista ordenada de Segments cobrindo todo o áudio
                              (com silêncios já filtrados pelo VAD).
    """
    language: str
    language_probability: float
    duration: float
    model_size: str
    segments: list[Segment] = field(default_factory=list)

    # ----- Conveniências (computed properties) -----

    @property
    def text(self) -> str:
        """
        Texto corrido da transcrição, sem timestamps.

        Útil pra:
            - Imprimir/debugar a transcrição rapidamente.
            - Pesquisar uma palavra específica.
            - Mostrar um preview pro usuário.

        Returns:
            String com todos os segmentos concatenados, separados por espaço,
            sem espaços extras no início/fim.

        Exemplo:
            >>> t = Transcript(...)  # com 2 segmentos: "Olá mundo." e "Tudo bem?"
            >>> t.text
            'Olá mundo. Tudo bem?'
        """
        return " ".join(s.text.strip() for s in self.segments).strip()

    def all_words(self) -> Iterable[Word]:
        """
        Iterador "achatado" sobre TODAS as palavras de TODOS os segmentos.

        Pra que serve:
            Etapa 5 (captioner) precisa percorrer palavras em ordem cronológica
            ignorando a divisão por segmentos.

        Returns:
            Generator de Word. Não materializa lista — eficiente em vídeos longos.

        Exemplo:
            >>> for w in transcript.all_words():
            ...     print(f"{w.start:.2f}s: {w.text}")
        """
        for seg in self.segments:
            yield from seg.words

    # ----- Persistência (JSON) -----

    def to_dict(self) -> dict:
        """
        Serializa o Transcript inteiro pra um dict Python (pronto pra JSON).

        Usa `dataclasses.asdict` que recursivamente converte dataclasses
        aninhadas (Segment, Word) em dicts.

        Returns:
            Dict com todas as chaves: language, segments, etc.
        """
        return asdict(self)

    def save_json(self, path: Path) -> None:
        """
        Salva a transcrição como arquivo JSON.

        Args:
            path: Caminho onde salvar (ex: data/temp/video.transcript.json).
                  Cria pastas pai automaticamente se não existirem.

        Detalhes:
            - `ensure_ascii=False`: preserva acentos (importante pra português).
            - `indent=2`: JSON formatado bonito (pra você poder abrir num editor).
            - UTF-8 explícito: evita bug no Windows que às vezes salva em CP1252.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)

    @classmethod
    def from_dict(cls, data: dict) -> "Transcript":
        """
        Reconstrói um Transcript a partir de um dict (geralmente do JSON do cache).

        É o inverso de `to_dict()`. Faz a "hidratação" recursiva: dicts viram
        Word e Segment de volta.

        Args:
            data: Dict com a mesma estrutura que `to_dict()` produz.

        Returns:
            Transcript pronto pra uso.

        Raises:
            KeyError: Se faltar campo obrigatório no dict (formato inválido/antigo).
        """
        segments = [
            Segment(
                text=s["text"], start=s["start"], end=s["end"],
                words=[Word(**w) for w in s.get("words", [])],
            )
            for s in data.get("segments", [])
        ]
        return cls(
            language=data["language"],
            language_probability=data.get("language_probability", 1.0),
            duration=data.get("duration", 0.0),
            model_size=data.get("model_size", "unknown"),
            segments=segments,
        )

    @classmethod
    def load_json(cls, path: Path) -> "Transcript":
        """
        Carrega um Transcript salvo em JSON (cache ou compartilhamento entre etapas).

        Args:
            path: Caminho do arquivo .transcript.json.

        Returns:
            Transcript hidratado.

        Raises:
            FileNotFoundError: Se o arquivo não existir.
            json.JSONDecodeError: Se o arquivo estiver corrompido.
        """
        with path.open("r", encoding="utf-8") as f:
            return cls.from_dict(json.load(f))


# ============================================================
# Cache de modelos — evita recarregar a cada chamada
# ============================================================

# Dict global que guarda os modelos carregados em memória.
# Chave: "<model_size>:<compute_type>" (ex: "base:int8").
# Valor: instância de WhisperModel.
# Por que global? Porque carregar o modelo demora 5-10s e ocupa RAM —
# se chamamos transcribe() várias vezes no mesmo processo, queremos reusar.
_MODEL_CACHE: dict[str, object] = {}


def _get_model(model_size: str, compute_type: str = "int8"):
    """
    Carrega (e cacheia) o modelo faster-whisper.

    Função "privada" — use `transcribe()` ao invés disso.

    Args:
        model_size:   "tiny" | "base" | "small" | "medium" | "large-v3".
                      Maior = mais preciso, mais lento, mais RAM.
        compute_type: Como o modelo executa internamente:
                      - "int8" (recomendado em CPU): quantização inteira de 8 bits.
                                                     ~2x mais rápido que float, perda
                                                     mínima de qualidade.
                      - "float16" (GPU): meia precisão. Só faz sentido em GPU CUDA.
                      - "float32": precisão total. Mais lento e mais RAM. Raramente útil.

    Returns:
        Instância de `faster_whisper.WhisperModel` pronta pra usar.

    Detalhe da primeira chamada:
        Na PRIMEIRA vez que você usa um model_size novo, o faster-whisper
        baixa os pesos da internet (~140MB pro 'base', ~470MB pro 'small').
        Eles ficam em ~/.cache/huggingface/ (Linux/Mac) ou
        C:\\Users\\<voce>\\.cache\\huggingface\\ (Windows).
        Chamadas seguintes são instantâneas (depois do download inicial).
    """
    cache_key = f"{model_size}:{compute_type}"
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    # Import tardio: a lib `faster_whisper` é PESADA (importa torch indiretamente).
    # Se alguém só quer usar as dataclasses (`Transcript`, `Word`), não carregamos
    # nada disso. Importar dentro da função adia o custo até o último momento.
    from faster_whisper import WhisperModel

    logger.info("Carregando modelo Whisper '%s' (compute=%s)…", model_size, compute_type)
    model = WhisperModel(model_size, device="cpu", compute_type=compute_type)
    _MODEL_CACHE[cache_key] = model
    return model


# ============================================================
# API principal
# ============================================================

def transcribe(
    media_path: Path | str,
    *,
    model_size: str = "base",
    language: str | None = None,
    compute_type: str = "int8",
    use_cache: bool = True,
    cache_dir: Path | None = None,
) -> Transcript:
    """
    Transcreve um arquivo de áudio/vídeo e retorna o resultado completo.

    Args:
        media_path:   Caminho do arquivo. Pode ser vídeo (.mp4, .mkv, .webm) OU
                      áudio puro (.mp3, .wav, .m4a). O Whisper internamente extrai
                      o áudio com FFmpeg, então funciona com tudo que o FFmpeg
                      consegue abrir.
        model_size:   Tamanho do modelo. Default "base" (bom equilíbrio).
                      Recomendações práticas:
                          - "tiny":     ~75MB, super rápido, qualidade ruim em pt.
                          - "base":     ~140MB, rápido, qualidade OK em pt.
                          - "small":    ~470MB, ~2x mais lento que base, MUITO melhor em pt.
                          - "medium":   ~1.5GB, lento em CPU, qualidade excelente.
                          - "large-v3": ~3GB, MUITO lento em CPU, melhor possível.
        language:     Código ISO do idioma ("pt", "en", "es") ou None pra detectar.
                      Recomendação: passe "pt" se você sabe que é português —
                      evita o modelo gastar tempo detectando e às vezes errar.
        compute_type: Padrão "int8" pra CPU. Não mude a não ser que saiba o que faz.
        use_cache:    True (default) = se já existe data/temp/<nome>.transcript.json
                      e foi gerado pelo mesmo `model_size`, reusa ao invés de
                      retranscrever. False = sempre retranscreve do zero.
        cache_dir:    Onde gravar o cache. Default = data/temp/.

    Returns:
        Transcript com:
            - `language` detectado (ou o que foi forçado)
            - `segments` cobrindo todo o áudio falado
            - cada Segment com `words` (timestamps por palavra)
        TAMBÉM salva o JSON em disco como efeito colateral.

    Raises:
        FileNotFoundError: Arquivo não existe.
        Outras exceções podem vir do faster-whisper (problemas com FFmpeg,
        arquivo corrompido, etc.) — deixamos elas propagarem.

    Exemplos:
        >>> # Uso básico (auto-detect idioma, modelo base):
        >>> t = transcribe("data/inputs/video.mp4")
        >>> print(t.text[:200])

        >>> # Modelo melhor, idioma forçado pra português:
        >>> t = transcribe("data/inputs/pregacao.mp4", model_size="small", language="pt")

        >>> # Ignorar cache (forçar retranscrever):
        >>> t = transcribe("data/inputs/video.mp4", use_cache=False)

    Detalhes técnicos importantes:

        vad_filter=True:
            VAD = Voice Activity Detection. Ignora trechos de silêncio.
            Isso REDUZ DRASTICAMENTE alucinações do Whisper, que tem mania
            de "inventar" texto em silêncios (frases tipo "Obrigado por assistir!"
            no meio do nada). Vale ouro em conteúdo evangélico com pausas longas.

        min_silence_duration_ms=500:
            Silêncio precisa durar pelo menos 0.5s pra ser filtrado.
            Valores menores filtram demais; maiores deixam alucinação passar.

        word_timestamps=True:
            Faz o Whisper retornar timestamps por palavra. Custa ~10% mais
            tempo de processamento, mas é ESSENCIAL pra legendas estilo karaokê
            (Etapa 5). Como o custo é baixo, sempre deixamos ligado.
    """
    ensure_dirs()
    media = Path(media_path).resolve()
    if not media.exists():
        raise FileNotFoundError(f"Arquivo não encontrado: {media}")

    cache_path = (cache_dir or TEMP_DIR) / f"{media.stem}.transcript.json"

    # ----- Cache hit? -----
    if use_cache and cache_path.exists():
        logger.info("Cache hit: %s", cache_path.name)
        cached = Transcript.load_json(cache_path)
        # Só reusa se foi gerado pelo MESMO modelo — qualidades diferentes
        # entre modelos dariam resultados inconsistentes na Etapa 3.
        if cached.model_size == model_size:
            return cached
        logger.info("Cache descartado: foi gerado com modelo '%s', queremos '%s'.",
                    cached.model_size, model_size)

    # ----- Transcrição real -----
    model = _get_model(model_size, compute_type)

    # `segments_iter` é um GENERATOR — o Whisper só processa quando iteramos.
    # Não é lista pronta. O processamento real acontece no `for seg in segments_iter`.
    segments_iter, info = model.transcribe(
        str(media),
        language=language,
        word_timestamps=True,
        vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 500},
    )

    segments: list[Segment] = []
    for seg in segments_iter:
        # Converte palavras do tipo do faster-whisper pro nosso `Word`.
        # `seg.words` PODE ser None se VAD filtrou tudo do segmento.
        words = [
            Word(text=w.word, start=float(w.start), end=float(w.end),
                 probability=float(w.probability))
            for w in (seg.words or [])
        ]
        segments.append(Segment(
            text=seg.text, start=float(seg.start), end=float(seg.end), words=words,
        ))

    transcript = Transcript(
        language=info.language,
        language_probability=float(info.language_probability),
        duration=float(info.duration),
        model_size=model_size,
        segments=segments,
    )

    # Persiste cache pra próximas chamadas
    transcript.save_json(cache_path)
    logger.info("Transcrição salva: %s (%d segmentos, %d palavras)",
                cache_path.name, len(segments), sum(len(s.words) for s in segments))

    return transcript

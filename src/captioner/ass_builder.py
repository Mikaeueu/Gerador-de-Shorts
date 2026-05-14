"""
Etapa 5a - Construtor de arquivos .ass (Advanced SubStation Alpha).

Por que .ass e nao .srt:
    SRT eh limitado: so texto e timing, sem controle de fonte/cor/posicao.
    ASS suporta:
        - Multiplas styles (fonte, tamanho, cor, contorno, sombra)
        - Posicionamento exato via \\pos(x,y)
        - Animacoes (\\fad, \\move, \\t)
        - Override tags inline (\\b, \\i, \\c)
    Resultado: legendas indistinguiveis do Opus / Submagic.

Estrutura de um arquivo .ass:
    [Script Info]   <- metadata global (resolucao, wrap mode)
    [V4+ Styles]    <- definicoes de estilo reutilizaveis
    [Events]        <- as legendas em si (Dialogue lines)

Cores no ASS:
    Formato &HAABBGGRR (ABGR, com alpha primeiro).
    Atencao: NAO eh RGB normal! Bytes invertidos.
        Branco:   &H00FFFFFF
        Preto:    &H00000000
        Amarelo:  &H0000FFFF  (R=FF, G=FF, B=00)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from src.transcriber import Word


@dataclass
class CaptionChunk:
    """
    Um "chunk" de legenda = grupo de palavras que aparecem juntas na tela.

    Pro estilo Opus, agrupamos 1-3 palavras por chunk pra criar a sensacao
    de palavra-por-palavra rapida que prende atencao.

    Attributes:
        text:  Texto a exibir (junção das palavras com espaco).
        start: Tempo de inicio (segundos relativos ao clip).
        end:   Tempo de fim.
    """
    text: str
    start: float
    end: float


def group_words_into_chunks(
    words: list[Word],
    *,
    max_words_per_chunk: int = 3,
    max_chunk_duration: float = 1.8,
    clip_start_offset: float = 0.0,
) -> list[CaptionChunk]:
    """
    Agrupa palavras consecutivas em chunks visualizaveis.

    Args:
        words: Palavras (do Whisper) na ordem cronologica.
        max_words_per_chunk: Maximo de palavras por chunk. 3 e bom pra Shorts.
                             (2 = mais rapido/dinamico, 4+ = textao confuso).
        max_chunk_duration: Tempo maximo (segundos) de um chunk na tela.
                            Mesmo com 1 palavra, se ela durar mais que isso,
                            vamos quebrar (raro - palavras nao costumam durar tanto).
        clip_start_offset: Se as palavras do Whisper estao em timeline do video
                           ORIGINAL, mas o output e do CLIP, subtraimos isso
                           pra timestamps ficarem 0-relativos ao clip.

    Returns:
        Lista de CaptionChunk em ordem cronologica.

    Detalhe sobre o "texto" da palavra:
        Whisper as vezes retorna palavra com espaco no comeco (" Olá").
        A gente strip() pra evitar espacos duplicados na concatenacao.
    """
    chunks: list[CaptionChunk] = []
    current: list[Word] = []

    def flush_current():
        """Empurra o chunk atual pra lista de chunks."""
        if not current:
            return
        text = " ".join(w.text.strip() for w in current)
        chunks.append(CaptionChunk(
            text=text,
            start=current[0].start - clip_start_offset,
            end=current[-1].end - clip_start_offset,
        ))

    for word in words:
        if not current:
            current = [word]
            continue
        # Tamanho do chunk se incluirmos essa palavra
        proposed_duration = word.end - current[0].start
        if len(current) >= max_words_per_chunk or proposed_duration > max_chunk_duration:
            flush_current()
            current = [word]
        else:
            current.append(word)
    flush_current()

    return chunks


# ============================================================
# Conversao de tempo pra formato ASS
# ============================================================

def _seconds_to_ass_time(t: float) -> str:
    """
    Converte segundos pra formato H:MM:SS.cc (centisegundos).

    O ASS usa precisao de centisegundo (10ms), nao milissegundo.

    Exemplos:
        0.0    -> "0:00:00.00"
        65.43  -> "0:01:05.43"
        3661.5 -> "1:01:01.50"
    """
    t = max(0.0, t)  # ASS nao aceita negativo
    h = int(t // 3600)
    m = int((t % 3600) // 60)
    s = t % 60
    return f"{h}:{m:02d}:{s:05.2f}"


# ============================================================
# Construtor do arquivo .ass completo
# ============================================================

DEFAULT_FONT = "Arial Black"      # disponivel em qualquer Windows e Linux Mint
DEFAULT_FONT_SIZE = 100            # bem grande pra Shorts
DEFAULT_OUTLINE_WIDTH = 5         # contorno preto grosso
DEFAULT_SHADOW = 2                # sombra leve
DEFAULT_POS_X = 540               # centro horizontal de 1080
DEFAULT_POS_Y = 1450               # centro inferior vertical de 1920


def build_ass_content(
    chunks: list[CaptionChunk],
    *,
    play_res_x: int = 1080,
    play_res_y: int = 1920,
    font_name: str = DEFAULT_FONT,
    font_size: int = DEFAULT_FONT_SIZE,
    outline_width: int = DEFAULT_OUTLINE_WIDTH,
    shadow: int = DEFAULT_SHADOW,
    pos_x: int = DEFAULT_POS_X,
    pos_y: int = DEFAULT_POS_Y,
) -> str:
    """
    Constroi o conteudo completo de um arquivo .ass.

    Args:
        chunks:        Chunks ordenados cronologicamente.
        play_res_x/y:  Resolucao do video (1080x1920 pra Shorts).
        font_name:     Nome da fonte (deve estar instalada no sistema).
        font_size:     Tamanho em pontos. 100 e legivel em mobile sem ocupar metade da tela.
        outline_width: Espessura do contorno preto. 5 = grosso, ajuda em qualquer fundo.
        shadow:        Sombra deslocada. 2 = subtil mas perceptivel.
        pos_x/y:       Posicao do centro da legenda (\\an5 = anchor no centro).

    Returns:
        String com o .ass completo, pronto pra salvar em disco.

    Detalhes do formato:
        - PrimaryColour:   cor principal do texto (branco)
        - SecondaryColour: usada em efeitos karaoke (nao usamos aqui)
        - OutlineColour:   cor do contorno (preto)
        - BackColour:      cor da sombra/fundo (preto semi-transparente)
        - Bold = -1        (True em ASS)
        - BorderStyle = 1  (contorno + sombra, em vez de caixa cheia)
        - Alignment = 5    (\\an5 - centro horizontal e vertical)
    """
    # Cabecalho do script
    header = f"""[Script Info]
Title: Gerador de Shorts - Auto Captions
ScriptType: v4.00+
PlayResX: {play_res_x}
PlayResY: {play_res_y}
WrapStyle: 2
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{font_size},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,-1,0,0,0,100,100,0,0,1,{outline_width},{shadow},5,30,30,30,1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""

    # Cada chunk vira uma linha Dialogue
    lines = []
    for chunk in chunks:
        start_str = _seconds_to_ass_time(chunk.start)
        end_str = _seconds_to_ass_time(chunk.end)
        # \pos(x,y) sobrescreve o alignment - posicao exata na tela
        # Texto ASS escapa { e } com \\{ \\} mas nosso texto nao tem -- safe.
        text_escaped = chunk.text.replace("\n", " ").replace("{", "(").replace("}", ")")
        line = f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{{\\pos({pos_x},{pos_y})}}{text_escaped}"
        lines.append(line)

    return header + "\n".join(lines) + "\n"

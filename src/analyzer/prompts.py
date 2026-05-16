"""
Templates de prompt pra analise viral via LLM.

O QUE e um "template" aqui:
    Uma funcao que recebe a Transcript + parametros (limites de duracao,
    quantidade etc.) e devolve uma STRING - o prompt pronto pra enviar
    ao Gemini.

Por que separar em varios templates:
    Tipos de conteudo diferentes tem criterios virais MUITO diferentes.
    O que faz uma pregacao evangelica viralizar (frase de impacto sobre fe,
    versiculo aplicado, confronto biblico) e completamente diferente do que
    faz um video educativo (insight novo, dica pratica) ou de humor (timing
    de piada). Cada template encapsula essa especificidade.

Como ADICIONAR um template novo:
    1. Crie uma funcao build_<nome>_prompt(transcript, **kwargs) -> str.
    2. Registre no dict TEMPLATES no fim do arquivo.
    3. Pronto - ja da pra usar com analyze(..., template="<nome>").
"""
from __future__ import annotations

from src.transcriber import Transcript


def _format_transcript_with_timestamps(transcript: Transcript) -> str:
    """
    Converte a transcricao numa string com linhas no formato '[start-end] texto'.

    Funcao "privada" usada pelos builders de prompt.

    Por que esse formato:
        - O LLM precisa SABER os timestamps pra escolher inicio/fim dos clips.
        - Usamos segmentos (nao palavras) porque palavra-por-palavra explodiria
          o tamanho do prompt sem ganho real - o LLM raciocina no nivel de frase.

    Args:
        transcript: Resultado da Etapa 2.

    Returns:
        String multi-linha. Cada linha e tipo:
        "[12.34-18.90] A graca de Deus e maior que o seu pecado."
    """
    lines = []
    for seg in transcript.segments:
        lines.append(f"[{seg.start:.2f}-{seg.end:.2f}] {seg.text.strip()}")
    return "\n".join(lines)


# ============================================================
# Template: PREGACAO EVANGELICA
# ============================================================

def build_evangelical_preaching_prompt(
    transcript: Transcript,
    *,
    min_clip_seconds: float = 45,
    max_clip_seconds: float = 90,
    max_clips: int = 5,
    min_score: float = 7.0,
) -> str:
    """
    Constroi o prompt do Gemini pra detectar trechos virais em PREGACOES EVANGELICAS.

    Esse e o template PRINCIPAL do projeto (o nicho do Maicon).

    Por que um prompt customizado pra esse nicho:
        Pregacoes evangelicas tem padroes virais MUITO especificos que o LLM
        nao capturaria com um prompt generico. Listamos 9 padroes explicitos:
        frase de impacto, versiculo+aplicacao, confronto, pergunta retorica,
        testemunho, promessa decodificada, revelacao espiritual,
        quote-friendly, e convite direto.

    Args:
        transcript:       Resultado da Etapa 2. Sera incluido NO prompt
                          como contexto pro LLM.
        min_clip_seconds: Duracao MINIMA aceita de cada clip (segundos).
        max_clip_seconds: Duracao MAXIMA aceita.
        max_clips:        Quantos clips o LLM pode retornar no maximo.
        min_score:        Score minimo (0-10) pra considerar viral.

    Returns:
        Prompt completo (string) pronto pra mandar pro Gemini via
        generate_content(contents=prompt, ...).

    Nota sobre o tamanho do prompt:
        Esse prompt pode ficar grande em videos longos (~1h de pregacao
        = ~3000 segmentos = ~30000 tokens so de transcricao). Gemini Flash
        aguenta 1M tokens de contexto, entao ainda da folga grande.
        Se algum dia estourar, precisaremos fazer chunking.
    """
    transcript_text = _format_transcript_with_timestamps(transcript)

    return f"""Voce e um especialista em conteudo viral para redes sociais (Shorts/Reels/TikTok), com foco em PREGACOES EVANGELICAS e conteudo cristao.

Sua tarefa: analisar a transcricao abaixo (com timestamps em segundos) e identificar os melhores trechos para virarem Shorts verticais de 60-90 segundos.

# Criterios virais em conteudo evangelico

Um trecho tem ALTO potencial viral quando contem UM OU MAIS desses elementos:

1. **Frase de impacto auto-contida** - declaracao marcante que faz sentido sozinha, fora do contexto da pregacao completa. Ex: "Deus nao te ama pelo que voce faz, Ele te ama pelo que Cristo fez."

2. **Versiculo + aplicacao pratica** - citacao biblica seguida de uma aplicacao clara e imediata a vida do espectador.

3. **Confronto biblico** - quebra de paradigma religioso, correcao de visao errada sobre Deus/fe. Ex: "Voce esta orando ou esta negociando com Deus?"

4. **Pergunta retorica forte** - pergunta que faz o espectador refletir sobre a propria vida.

5. **Testemunho curto e marcante** - relato pessoal ou de terceiros, auto-contido, com licao clara.

6. **Promessa biblica decodificada** - explicacao de uma promessa de Deus de forma simples e poderosa.

7. **Revelacao espiritual** - insight teologico apresentado de forma acessivel.

8. **Quote-friendly** - frase que funcionaria como print/legenda viral no Instagram.

9. **Convite/desafio direto** - chamada a acao espiritual feita com forca.

# Criterios tecnicos OBRIGATORIOS

- Duracao de CADA clip: entre {min_clip_seconds:.0f} e {max_clip_seconds:.0f} segundos.
- Use os timestamps EXATOS da transcricao (nao invente). Pode juntar segmentos adjacentes.
- O clip DEVE comecar e terminar em pontos naturais (inicio de frase, fim de pensamento).
- NAO corte versiculos pela metade.
- NAO inicie clips no meio de uma frase.
- Score de 0 a 10. So inclua clips com score >= {min_score:.1f}.
- Retorne NO MAXIMO {max_clips} clips. Se o video so tiver 2 trechos realmente bons, retorne 2.
- Prefira QUALIDADE a quantidade.

# Sobre os campos da resposta

- `title`: titulo curto pro Short (max 80 chars). Pode usar emoji moderadamente.
  Bom: "O erro que TODO cristao comete na oracao"
  Ruim: "Sobre oracao" / "Pregacao parte 3"

- `hook`: as primeiras 1-2 frases do clip exatas como estao na transcricao (gancho).

- `quote`: A frase mais "printavel" do trecho - vai virar caption no Instagram.
  Se nao houver uma frase clara, deixe null.

- `reason`: 1-2 frases explicando POR QUE esse trecho funcionaria como Short.

# Transcricao (formato: [inicio-fim em segundos] texto)

{transcript_text}

# Saida esperada

Retorne APENAS um JSON valido seguindo o schema. Sem texto antes/depois, sem markdown.
Idioma: o mesmo da transcricao (provavelmente portugues).
"""


# ============================================================
# Template: GENERICO
# ============================================================

def build_generic_prompt(
    transcript: Transcript,
    *,
    min_clip_seconds: float = 45,
    max_clip_seconds: float = 90,
    max_clips: int = 5,
    min_score: float = 7.0,
) -> str:
    """
    Prompt generico pra QUALQUER tipo de conteudo nao-evangelico.

    Usado pra podcasts, aulas, palestras, entrevistas, etc.
    Criterios mais amplos que o template evangelico.

    Args:
        Mesmos do build_evangelical_preaching_prompt.

    Returns:
        Prompt em string pronto pro Gemini.

    Quando usar:
        Quando o conteudo NAO e uma pregacao crista. Pra conteudo cristao,
        o template evangelical_preaching tende a dar resultados melhores
        porque foi calibrado pra esse nicho.
    """
    transcript_text = _format_transcript_with_timestamps(transcript)

    return f"""Voce e especialista em conteudo viral para Shorts/Reels/TikTok.

Analise a transcricao abaixo e identifique os melhores trechos para virarem videos verticais de {min_clip_seconds:.0f}-{max_clip_seconds:.0f} segundos.

Criterios virais: gancho forte na abertura, frase de impacto, emocao, insight novo, momento engracado/marcante, narrativa auto-contida (faz sentido sem ver o resto do video).

REGRAS:
- Duracao: entre {min_clip_seconds:.0f} e {max_clip_seconds:.0f} segundos.
- Score 0-10. So inclua clips com score >= {min_score:.1f}.
- Maximo {max_clips} clips. Qualidade > quantidade.
- Use timestamps EXATOS da transcricao.
- Comece/termine em pontos naturais (nao no meio de frase).

# Transcricao

{transcript_text}

Retorne APENAS JSON valido. Sem markdown.
"""


# ============================================================
# Template: GAMEPLAY HUMOR (livestreams, reacoes, fails, clutches)
# ============================================================

def build_gameplay_humor_prompt(
    transcript: Transcript,
    *,
    min_clip_seconds: float = 15,
    max_clip_seconds: float = 60,
    max_clips: int = 8,
    min_score: float = 7.0,
) -> str:
    """
    Prompt customizado pra detectar trechos virais em GAMEPLAY DE HUMOR.

    Diferente de pregacao (que valoriza profundidade e versiculo+aplicacao),
    gameplay de humor depende de:
        - Reacao EXAGERADA do streamer (susto, grito, riso histerico)
        - Timing de comedia (setup curto + punchline)
        - Fail epico ou clutch improvavel
        - Quebra da quarta parede (reagindo ao chat, ao jogo, a si mesmo)
        - Frase aleatoria que vira meme

    Defaults diferentes do template evangelico:
        - Clips MAIS CURTOS (15-60s) - atencao em gaming e mais rapida
        - MAIS clips por video (8 default) - lives sao longas e tem
          muitos momentos isolados
        - Score 7.0 mantido - ainda queremos qualidade

    Args:
        transcript:       Resultado da Etapa 2.
        min_clip_seconds: Default 15s (vs 45s evangelico).
        max_clip_seconds: Default 60s.
        max_clips:        Default 8.
        min_score:        Default 7.0.

    Returns:
        Prompt completo pra mandar pro Gemini.
    """
    transcript_text = _format_transcript_with_timestamps(transcript)

    return f"""Voce e um especialista em conteudo viral de GAMEPLAY E HUMOR para TikTok, Shorts e Reels.

Sua tarefa: analisar a transcricao abaixo (de uma live/video de gameplay) e identificar os melhores momentos para virarem clips curtos e engracados.

# Criterios virais em gameplay/humor

Um trecho tem ALTO potencial viral quando contem UM OU MAIS desses elementos:

1. **Reacao exagerada do streamer** - grito de susto, riso histerico, palavrao de surpresa, exclamacao espontanea. Quanto mais barulho/intensidade, melhor.
   Ex: "AAAAA NÃO ACREDITO!", "QUE QUE FOI ISSO?!"

2. **Fail epico** - personagem morre/falha de jeito ridiculo, comete erro absurdo, cai num lugar improvavel. Bonus se o streamer reage com frustracao comica.

3. **Clutch / virada improvavel** - vitoria no ultimo segundo, jogada absurda que deu certo, streak miraculoso. O publico AMA "no last second".

4. **Bug / glitch engracado** - fisica do jogo dando merda, NPC fazendo algo bizarro, animacao quebrada de forma comica.

5. **Quebra da quarta parede** - streamer respondendo ao chat de forma engracada, comentario auto-depreciativo, reconhecendo que algo absurdo aconteceu.

6. **Timing de comedia** - sequencia onde o setup curto leva a um punchline. Frustracao crescente que culmina num momento explosivo.

7. **Frase meme-worthy** - bordao espontaneo, comentario aleatorio que e tao especifico que vira meme. Ex: "VAI TOMAR NO C* JOÃO", "TA RINDO DE QUE?"

8. **Momento de troll** - streamer trollando alguem ou sendo trollado de jeito hilario.

9. **Coincidencia perfeita** - algo no jogo aconteceu EXATAMENTE quando o streamer disse algo - sincronizacao improvavel.

# Criterios tecnicos OBRIGATORIOS

- Duracao de CADA clip: entre {min_clip_seconds:.0f} e {max_clip_seconds:.0f} segundos.
- INCLUA 1-3 segundos de SETUP antes do momento engracado (contexto e essencial pra graca fazer sentido).
- TERMINE LOGO APOS o momento de impacto (nao deixe a graca "morrer" com silencio depois).
- Use timestamps EXATOS da transcricao (nao invente).
- Evite clips com 5+ segundos de silencio - perde o ritmo.
- Score 0-10. So inclua clips com score >= {min_score:.1f}.
- Retorne NO MAXIMO {max_clips} clips. Lives tem muitos momentos - filtre os MELHORES.
- PRIORIZE clips com REACAO BARULHENTA do streamer (gameplay sem grito = clipe morto).

# Sobre os campos da resposta

- `title`: titulo curto pro Short (max 80 chars). Use linguagem casual de gamer/internet.
  Pode usar maiusculas pra enfase, emoji moderado.
  Bom: "Ele MORREU do nada e a reação foi PERFEITA 😂"
  Bom: "Esse clutch é IMPOSSIVEL"
  Ruim: "Momento engracado do video" / "Gameplay parte 5"

- `hook`: as primeiras 1-2 falas do clip (que dao o setup pra graca).

- `quote`: A frase mais "memetic" do trecho - aquela que pode virar bordao/print.
  Se nao houver uma frase clara que se destaca sozinha, deixe null.

- `reason`: 1-2 frases explicando POR QUE esse trecho funcionaria como Short.
  Ex: "Setup de frustracao construindo + reacao explosiva no fim. Frase 'ta de brincadeira' ja virou meme em outros clipes."

# Transcricao (formato: [inicio-fim em segundos] texto)

{transcript_text}

# Saida esperada

Retorne APENAS um JSON valido seguindo o schema. Sem texto antes/depois, sem markdown.
Idioma: o mesmo da transcricao.
"""


# ============================================================
# Registro de templates disponiveis
# ============================================================

# Dict que mapeia NOME do template -> funcao que constroi o prompt.
# Usado pelo analyzer.analyze() pra resolver template="evangelical_preaching".
#
# Pra adicionar template novo:
#   TEMPLATES["meu_novo_template"] = build_meu_novo_template_prompt
TEMPLATES = {
    "evangelical_preaching": build_evangelical_preaching_prompt,
    "gameplay_humor": build_gameplay_humor_prompt,
    "generic": build_generic_prompt,
}


# ============================================================
# Smart defaults POR TEMPLATE
# ============================================================
# Cada nicho tem duracao/quantidade ideais diferentes.
# Quando o user nao passa explicitamente, usamos esses defaults.
# Pregacao = clips longos e densos (45-90s, ~5).
# Gameplay = clips curtos e em volume (15-60s, ate 8).
TEMPLATE_DEFAULTS: dict[str, dict] = {
    "evangelical_preaching": {
        "min_clip_seconds": 45.0,
        "max_clip_seconds": 90.0,
        "max_clips": 5,
        "min_score": 7.0,
    },
    "gameplay_humor": {
        "min_clip_seconds": 15.0,
        "max_clip_seconds": 60.0,
        "max_clips": 8,
        "min_score": 7.0,
    },
    "generic": {
        "min_clip_seconds": 45.0,
        "max_clip_seconds": 90.0,
        "max_clips": 5,
        "min_score": 7.0,
    },
}


def get_template_defaults(template: str) -> dict:
    """
    Retorna os defaults apropriados pro template.

    Se template nao tem defaults explicitos, cai no 'generic'.

    Args:
        template: Nome do template (ex: "gameplay_humor").

    Returns:
        Dict com min_clip_seconds, max_clip_seconds, max_clips, min_score.
    """
    return TEMPLATE_DEFAULTS.get(template, TEMPLATE_DEFAULTS["generic"]).copy()


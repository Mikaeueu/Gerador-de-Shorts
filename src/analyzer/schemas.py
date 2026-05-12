"""
Schemas Pydantic da Etapa 3 - analise viral.

Esses schemas tem DUPLO papel:
    1. Estruturam o output do Gemini. Quando passamos
       response_schema=list[ViralClip] pro modelo, ele e FORCADO a devolver
       JSON com exatamente esses campos (sem texto extra, sem markdown).
    2. Validam o cache em data/temp/<nome>.viral.json. Se voce editar o JSON
       manualmente com um campo errado, o Pydantic detecta na hora de carregar.

Por que Pydantic e nao dataclass?
    - Validacao automatica (ex: score precisa estar entre 0 e 10 - declarado
      UMA vez, vale tanto pra carregar do JSON quanto pra validar resposta
      do Gemini).
    - model_validate() e model_dump_json() sao a prova de bala em casos
      esquisitos.
    - O Google SDK do Gemini suporta Pydantic v2 nativamente em
      response_schema.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ViralClip(BaseModel):
    """
    Um trecho candidato a virar Short. E o "produto" da Etapa 3.

    Cada instancia representa UM clip que o LLM identificou como viral.
    A Etapa 4 (cropper) vai usar start e end pra cortar o video,
    e a Etapa 5 (captioner) vai gerar legendas baseado nas palavras
    da transcricao que caem nesse intervalo.

    Attributes:
        start: Inicio do clip em segundos desde o comeco do video original.
               Float pra permitir precisao sub-segundo (ex: 234.5).

        end:   Fim do clip em segundos. SEMPRE > start.

        score: Pontuacao 0-10 atribuida pelo LLM. Pydantic VALIDA
               automaticamente que esta nessa faixa (ge=0, le=10) -
               se o Gemini retornar 11, vira erro de validacao.

        title: Titulo sugerido pro Short (curto, com gancho).
               Limitado a 80 chars pra caber bem em previews/UI.
               Pode conter emojis moderadamente.
               Ex: "O erro que TODO cristao comete na oracao"

        hook:  Primeira frase/gancho - o texto exato dos primeiros segundos
               do clip. Util pra mostrar pro usuario antes do corte real.

        reason: 1-2 frases explicando POR QUE esse trecho funciona como Short.
                Ajuda voce a julgar se o LLM acertou no criterio.

        quote: Citacao principal "printavel" do trecho - vai virar caption
               no Instagram/legenda do post. PODE SER None se o trecho
               nao tem uma frase auto-contida boa.
    """
    start: float = Field(..., description="Inicio do clip em segundos")
    end: float = Field(..., description="Fim do clip em segundos")
    score: float = Field(..., ge=0, le=10, description="Pontuacao de potencial viral (0-10)")
    title: str = Field(..., max_length=80, description="Titulo sugerido pro Short")
    hook: str = Field(..., description="Primeira frase/gancho - o que faz parar de rolar o feed")
    reason: str = Field(..., description="Por que esse trecho tem potencial (1-2 frases)")
    quote: str | None = Field(None, description="Citacao principal pra usar como caption (opcional)")

    @property
    def duration(self) -> float:
        """
        Duracao do clip em segundos (= end - start).

        Computed property - nao precisa armazenar em disco.

        Returns:
            Duracao em segundos (float).
        """
        return self.end - self.start


class ViralAnalysis(BaseModel):
    """
    Resultado completo da analise de UM video - agrega todos os clips encontrados
    mais metadados de auditoria (qual modelo gerou, qual template foi usado).

    Esse e o objeto que circula pra Etapa 4 (cropper) e que fica salvo no
    cache .viral.json em data/temp/.

    Attributes:
        video_duration: Duracao total do video original (segundos). Util pra
                        validar que nenhum clip extrapola o video.

        language:       Idioma da transcricao que originou essa analise.
                        Copiado do Transcript pra rastreabilidade.

        template:       Nome do template de prompt que gerou essa analise.
                        Ex: "evangelical_preaching" ou "generic".
                        Util pra debugar resultados.

        model:          Modelo LLM exato usado. Ex: "gemini-2.5-flash".
                        Importante porque modelos diferentes dao resultados
                        diferentes - ajuda a reproduzir/comparar.

        clips:          Lista de ViralClip aprovados. Pode estar vazia se o
                        video nao tinha trechos bons o suficiente
                        (preferimos qualidade sobre quantidade).
    """
    video_duration: float
    language: str
    template: str = Field(..., description="Qual template de prompt foi usado")
    model: str = Field(..., description="Modelo LLM que gerou")
    clips: list[ViralClip] = Field(default_factory=list)

    def top_n(self, n: int) -> list[ViralClip]:
        """
        Retorna os N clips com maior score, ordenados decrescente.

        Pra que serve:
            Se o LLM aprovou 5 clips mas voce so quer postar 3 hoje,
            pega os melhores com analysis.top_n(3).

        Args:
            n: Quantos clips retornar. Se n > len(clips), retorna todos.

        Returns:
            Lista de ViralClip ordenada por score decrescente (melhor primeiro).
            NAO modifica self.clips - e uma copia ordenada.

        Exemplo:
            >>> analysis.top_n(3)  # 3 melhores clips
        """
        return sorted(self.clips, key=lambda c: c.score, reverse=True)[:n]

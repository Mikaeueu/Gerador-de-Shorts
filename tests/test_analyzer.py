"""
Testes do analyzer que NÃO dependem de rede/API.
Pra teste end-to-end com Gemini real, use o CLI:
    python -m src.analyzer.cli <transcript.json>
"""
import json
from pathlib import Path

from src.analyzer.prompts import TEMPLATES, build_evangelical_preaching_prompt
from src.analyzer.schemas import ViralAnalysis, ViralClip
from src.transcriber import Segment, Transcript


def _sample_transcript() -> Transcript:
    return Transcript(
        language="pt", language_probability=0.99, duration=120.0, model_size="base",
        segments=[
            Segment(text="A graça de Deus é maior que o seu pecado.", start=0.0, end=4.0, words=[]),
            Segment(text="Você não precisa se esforçar pra ser amado por Ele.", start=4.0, end=8.5, words=[]),
            Segment(text="Em Romanos 5 versículo 8 diz...", start=8.5, end=12.0, words=[]),
            Segment(text="que Cristo morreu por nós quando ainda éramos pecadores.", start=12.0, end=18.0, words=[]),
        ],
    )


def test_templates_disponiveis_incluem_evangelico_e_generico():
    assert "evangelical_preaching" in TEMPLATES
    assert "generic" in TEMPLATES


def test_prompt_evangelico_inclui_transcricao_e_limites():
    transcript = _sample_transcript()
    prompt = build_evangelical_preaching_prompt(
        transcript, min_clip_seconds=45, max_clip_seconds=90, max_clips=5, min_score=7.0
    )
    # Contém parte da transcrição
    assert "graça de Deus" in prompt
    # Contém os limites injetados
    assert "45" in prompt and "90" in prompt
    # Inclui os timestamps formatados
    assert "[0.00-4.00]" in prompt


def test_viral_clip_duration_property():
    clip = ViralClip(
        start=10.0, end=70.0, score=8.5,
        title="Teste", hook="Bom dia", reason="É um teste"
    )
    assert clip.duration == 60.0


def test_viral_analysis_top_n_ordena_por_score():
    clips = [
        ViralClip(start=0, end=60, score=7.0, title="a", hook="h", reason="r"),
        ViralClip(start=60, end=120, score=9.0, title="b", hook="h", reason="r"),
        ViralClip(start=120, end=180, score=8.0, title="c", hook="h", reason="r"),
    ]
    analysis = ViralAnalysis(
        video_duration=180, language="pt", template="generic",
        model="gemini-2.5-flash", clips=clips,
    )
    top2 = analysis.top_n(2)
    assert [c.title for c in top2] == ["b", "c"]


def test_viral_analysis_round_trip_json(tmp_path: Path):
    """Cache deve preservar todos os campos."""
    original = ViralAnalysis(
        video_duration=200.0, language="pt", template="evangelical_preaching",
        model="gemini-2.5-flash",
        clips=[
            ViralClip(start=10.0, end=70.0, score=8.5, title="Título",
                      hook="Hook", reason="Reason", quote="Citação"),
        ],
    )
    path = tmp_path / "out.viral.json"
    path.write_text(original.model_dump_json(indent=2), encoding="utf-8")

    data = json.loads(path.read_text(encoding="utf-8"))
    loaded = ViralAnalysis.model_validate(data)

    assert loaded.template == "evangelical_preaching"
    assert len(loaded.clips) == 1
    assert loaded.clips[0].quote == "Citação"
    assert loaded.clips[0].duration == 60.0


def test_analyze_template_invalido_da_erro():
    import pytest
    from src.analyzer import analyze
    with pytest.raises(ValueError, match="Template desconhecido"):
        analyze(_sample_transcript(), template="nao_existe")

"""
Testes do transcriber que NÃO dependem do faster-whisper estar instalado nem da rede.
Pra teste end-to-end com modelo real, use o CLI:
    python -m src.transcriber.cli <video.mp4>
"""
from pathlib import Path

from src.transcriber import Segment, Transcript, Word


def test_transcript_text_property_concatena_segmentos():
    t = Transcript(
        language="pt", language_probability=0.99, duration=10.0, model_size="base",
        segments=[
            Segment(text=" Olá mundo. ", start=0.0, end=2.0, words=[]),
            Segment(text=" Tudo bem? ", start=2.0, end=4.0, words=[]),
        ],
    )
    assert t.text == "Olá mundo. Tudo bem?"


def test_transcript_all_words_achata_segmentos():
    t = Transcript(
        language="pt", language_probability=0.99, duration=5.0, model_size="base",
        segments=[
            Segment(text="a b", start=0.0, end=1.0, words=[
                Word("a", 0.0, 0.5, 0.9), Word("b", 0.5, 1.0, 0.9),
            ]),
            Segment(text="c", start=1.0, end=2.0, words=[
                Word("c", 1.0, 2.0, 0.8),
            ]),
        ],
    )
    palavras = list(t.all_words())
    assert [w.text for w in palavras] == ["a", "b", "c"]
    assert palavras[2].start == 1.0


def test_transcript_round_trip_json(tmp_path: Path):
    """Salvar e recarregar deve preservar tudo."""
    original = Transcript(
        language="en", language_probability=0.95, duration=3.5, model_size="small",
        segments=[
            Segment(text="hello world", start=0.0, end=1.5, words=[
                Word("hello", 0.0, 0.7, 0.99),
                Word("world", 0.7, 1.5, 0.95),
            ]),
        ],
    )
    path = tmp_path / "out.json"
    original.save_json(path)

    loaded = Transcript.load_json(path)
    assert loaded.language == "en"
    assert loaded.model_size == "small"
    assert len(loaded.segments) == 1
    assert len(loaded.segments[0].words) == 2
    assert loaded.segments[0].words[0].text == "hello"
    assert loaded.text == "hello world"


def test_transcribe_raises_on_missing_file():
    import pytest
    from src.transcriber import transcribe
    with pytest.raises(FileNotFoundError):
        transcribe("/nao/existe/audio.mp3")

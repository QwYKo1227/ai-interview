from pathlib import Path
from types import SimpleNamespace

import pytest

from app.services import audio_service


class _Sound:
    def set_frame_rate(self, _rate):
        return self

    def set_channels(self, _channels):
        return self

    def export(self, path, format):
        Path(path).write_bytes(b"wav")

    def __len__(self):
        return 1


def test_transcription_removes_temporary_wav_when_provider_raises(tmp_path, monkeypatch):
    source = tmp_path / "voice.webm"
    source.write_bytes(b"audio")
    exported = []

    def export(path, format):
        exported.append(Path(path))
        Path(path).write_bytes(b"wav")

    sound = _Sound()
    sound.export = export
    monkeypatch.setattr(audio_service.AudioSegment, "from_file", lambda _path: sound)

    class BrokenRecognition:
        def __init__(self, **_kwargs):
            pass

        def call(self, _path):
            raise RuntimeError("provider secret must not escape")

    monkeypatch.setattr(audio_service, "Recognition", BrokenRecognition)
    with pytest.raises(audio_service.AudioTranscriptionError):
        audio_service.transcribe_audio(str(source))
    assert exported
    assert all(not path.exists() for path in exported)
    assert all(path.parent != source.parent for path in exported)

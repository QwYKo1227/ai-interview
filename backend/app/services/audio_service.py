import os
from http import HTTPStatus
import httpx
from dashscope.audio.asr import Recognition
from dotenv import load_dotenv
from pydub import AudioSegment
import tempfile
import logging
from sqlalchemy.orm import Session

from app.services.system_config_service import get_system_config

load_dotenv()

logger = logging.getLogger(__name__)

class AudioTranscriptionError(RuntimeError):
    """Safe domain error raised when audio transcription cannot complete."""

    error_code = "audio_transcription_failed"


class AsrServiceError(RuntimeError):
    """Sanitized failure returned by the OpenAI-compatible ASR service."""

    def __init__(
        self,
        *,
        retryable: bool = True,
        status_code: int | None = None,
        retry_after: int | None = None,
    ):
        super().__init__("ASR service request failed")
        self.retryable = retryable
        self.status_code = status_code
        self.retry_after = retry_after


def get_transcription_config(db: Session) -> dict:
    """Resolve tenant-specific ASR settings independently from the text model."""
    config = get_system_config(db)
    return {
        "provider": (
            config.asr_provider if config and config.asr_provider
            else os.getenv("ASR_PROVIDER", "openai_compatible")
        ),
        "base_url": (
            config.asr_base_url if config and config.asr_base_url
            else os.getenv("ASR_BASE_URL")
        ),
        "model": (
            config.asr_model if config and config.asr_model
            else os.getenv("ASR_MODEL", "paraformer-offline")
        ),
        "api_key": (
            config.asr_api_key if config and config.asr_api_key
            else os.getenv("ASR_API_KEY")
        ),
    }


def _openai_compatible_endpoint(config: dict, suffix: str) -> str:
    base_url = (config.get("base_url") or "").rstrip("/")
    if not base_url:
        raise AsrServiceError(retryable=False)
    return f"{base_url}/{suffix.lstrip('/')}"


def _asr_headers(config: dict) -> dict[str, str]:
    api_key = (config.get("api_key") or "").strip()
    return {"Authorization": f"Bearer {api_key}"} if api_key else {}


def _raise_asr_service_error(error: Exception) -> None:
    status_code = None
    retry_after = None
    if isinstance(error, httpx.HTTPStatusError):
        status_code = error.response.status_code
        raw_retry_after = error.response.headers.get("Retry-After")
        if raw_retry_after and raw_retry_after.isdigit():
            retry_after = min(int(raw_retry_after), 3600)
    retryable = status_code not in {400, 401, 403, 404, 413, 422}
    logger.warning(
        "ASR service request failed",
        extra={
            "error_code": "asr_service_request",
            "exception_type": type(error).__name__,
            "provider_status": status_code,
        },
    )
    raise AsrServiceError(
        retryable=retryable,
        status_code=status_code,
        retry_after=retry_after,
    ) from None


def create_realtime_session(config: dict) -> dict:
    """Create an ephemeral realtime credential without exposing the long-lived key."""
    if config.get("provider") != "openai_compatible":
        raise AsrServiceError(retryable=False)
    try:
        response = httpx.post(
            _openai_compatible_endpoint(config, "realtime/sessions"),
            headers=_asr_headers(config),
            timeout=15,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("token") or not payload.get("expires_at"):
            raise ValueError("Invalid realtime session response")
        return payload
    except (httpx.HTTPError, ValueError) as error:
        _raise_asr_service_error(error)


def create_transcription_job(audio_file_path: str, config: dict) -> dict:
    """Upload one sealed interview recording to the durable ASR job API."""
    if config.get("provider") != "openai_compatible":
        raise AsrServiceError(retryable=False)
    try:
        with open(audio_file_path, "rb") as audio_file:
            response = httpx.post(
                _openai_compatible_endpoint(config, "audio/transcription_jobs"),
                headers=_asr_headers(config),
                data={
                    "model": (config.get("model") or "paraformer-offline").strip(),
                    "response_format": "bundle",
                    "diarization": "true",
                },
                files={"file": (os.path.basename(audio_file_path), audio_file, "audio/webm")},
                timeout=300,
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("id"):
            raise ValueError("Invalid transcription job response")
        return payload
    except (OSError, httpx.HTTPError, ValueError) as error:
        _raise_asr_service_error(error)


def get_transcription_job(job_id: str, config: dict) -> dict:
    try:
        response = httpx.get(
            _openai_compatible_endpoint(config, f"audio/transcription_jobs/{job_id}"),
            headers=_asr_headers(config),
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or not payload.get("status"):
            raise ValueError("Invalid transcription job status response")
        return payload
    except (httpx.HTTPError, ValueError) as error:
        _raise_asr_service_error(error)


def delete_transcription_job(job_id: str, config: dict) -> None:
    try:
        response = httpx.delete(
            _openai_compatible_endpoint(config, f"audio/transcription_jobs/{job_id}"),
            headers=_asr_headers(config),
            timeout=30,
        )
        if response.status_code != 404:
            response.raise_for_status()
    except httpx.HTTPError as error:
        _raise_asr_service_error(error)


def _transcribe_openai_compatible(wav_path: str, config: dict) -> dict:
    base_url = (config.get("base_url") or "").rstrip("/")
    model = (config.get("model") or "").strip()
    if not base_url or not model:
        raise AudioTranscriptionError()

    endpoint = (
        base_url
        if base_url.endswith("/audio/transcriptions")
        else f"{base_url}/audio/transcriptions"
    )
    headers = {}
    if config.get("api_key"):
        headers["Authorization"] = f"Bearer {config['api_key']}"

    with open(wav_path, "rb") as audio_file:
        response = httpx.post(
            endpoint,
            headers=headers,
            data={"model": model},
            files={"file": ("interview.wav", audio_file, "audio/wav")},
            timeout=300,
        )
    response.raise_for_status()
    payload = response.json()
    text = payload.get("text", "") if isinstance(payload, dict) else ""
    raw_segments = payload.get("segments", []) if isinstance(payload, dict) else []
    segments = []
    for segment in raw_segments if isinstance(raw_segments, list) else []:
        if not isinstance(segment, dict):
            continue
        segments.append({
            "speaker": segment.get("speaker", "说话人"),
            "text": segment.get("text", ""),
            "start": segment.get("start", 0),
            "end": segment.get("end", 0),
        })
    return {"text": text, "segments": segments}


def transcribe_audio(
    audio_file_path: str,
    enable_diarization: bool = True,
    *,
    config: dict | None = None,
) -> dict:
    """
    Transcribe audio file using DashScope ASR SDK (FunASR).
    支持说话人分离，返回结构化的转写结果。
    
    Returns:
        dict: {
            "text": "完整转写文本",
            "segments": [
                {"speaker": "说话人1", "text": "...", "start": 0, "end": 5.2},
                ...
            ]
        }
    """
    if not os.path.exists(audio_file_path):
        logger.error(
            "Audio transcription failed",
            extra={"error_code": "missing_input", "exception_type": "FileNotFoundError"},
        )
        raise AudioTranscriptionError()

    resolved_config = config or {
        "provider": os.getenv("ASR_PROVIDER", "dashscope"),
        "base_url": os.getenv("ASR_BASE_URL"),
        "model": os.getenv("ASR_MODEL", "paraformer-realtime-v2"),
        "api_key": os.getenv("ASR_API_KEY") or os.getenv("DASHSCOPE_API_KEY"),
    }
        
    wav_path = None
    temp_dir = None
    try:
        sound = AudioSegment.from_file(audio_file_path)
        sound = sound.set_frame_rate(16000).set_channels(1)
        
        temp_dir = tempfile.TemporaryDirectory(prefix="ai-interview-audio-")
        wav_path = os.path.join(temp_dir.name, "converted.wav")
        sound.export(wav_path, format="wav")

        if resolved_config.get("provider") == "openai_compatible":
            return _transcribe_openai_compatible(wav_path, resolved_config)

        resolved_api_key = resolved_config.get("api_key")
        if not resolved_api_key:
            raise AudioTranscriptionError()
        
        recognition = Recognition(
            model=resolved_config.get("model") or "paraformer-realtime-v2",
            format='wav',
            sample_rate=16000,
            language_hints=['zh', 'en'],
            callback=None,
            api_key=resolved_api_key,
        )
        
        result = recognition.call(wav_path)
        
        if result.status_code == HTTPStatus.OK:
            sentences = result.get_sentence()
            
            if not sentences:
                logger.warning(
                    "Audio transcription returned no sentences",
                    extra={"error_code": "empty_result"},
                )
                return {"text": "", "segments": []}
            
            segments = []
            full_text = ""
            
            if isinstance(sentences, list):
                for idx, s in enumerate(sentences):
                    if isinstance(s, dict):
                        text = s.get('text', '')
                        start = s.get('begin_time', 0) / 1000.0
                        end = s.get('end_time', 0) / 1000.0
                        speaker = s.get('speaker', f"说话人{(idx % 2) + 1}")
                        
                        segments.append({
                            "speaker": speaker,
                            "text": text,
                            "start": round(start, 2),
                            "end": round(end, 2)
                        })
                        full_text += text + " "
                        
            elif isinstance(sentences, dict) and 'text' in sentences:
                text = sentences.get('text', '')
                full_text = text
                segments.append({
                    "speaker": "说话人1",
                    "text": text,
                    "start": 0,
                    "end": len(sound) / 1000.0
                })
            else:
                full_text = str(sentences)
                segments.append({
                    "speaker": "说话人1",
                    "text": full_text,
                    "start": 0,
                    "end": len(sound) / 1000.0
                })
            
            return {
                "text": full_text.strip(),
                "segments": segments
            }
        else:
            logger.error(
                "Audio transcription failed",
                extra={
                    "error_code": "provider_status",
                    "exception_type": "ProviderResponseError",
                },
            )
            raise AudioTranscriptionError()
            
    except AudioTranscriptionError:
        raise
    except Exception as error:
        logger.error(
            "Audio transcription failed",
            extra={
                "error_code": "unexpected_error",
                "exception_type": type(error).__name__,
            },
        )
        raise AudioTranscriptionError() from None
    finally:
        if temp_dir is not None:
            temp_dir.cleanup()


def transcribe_audio_simple(audio_file_path: str) -> str:
    """
    简单转写，只返回文本（向后兼容）
    """
    result = transcribe_audio(audio_file_path)
    return result.get("text", "")


def format_transcript_for_display(transcript_data: dict) -> str:
    """
    格式化转写结果用于显示
    """
    if isinstance(transcript_data, str):
        return transcript_data
    
    segments = transcript_data.get("segments", [])
    if not segments:
        return transcript_data.get("text", "")
    
    lines = []
    for seg in segments:
        speaker = seg.get("speaker", "说话人")
        text = seg.get("text", "")
        timestamp = f"[{seg.get('start', 0):.1f}s]"
        lines.append(f"{timestamp} {speaker}: {text}")
    
    return "\n".join(lines)

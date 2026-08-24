"""Voice-plan service (POST /api/v1/voice/plan).

One utterance, one plan: Groq Whisper STT turns the uploaded recording into
text that acts as a pure trigger for the existing stateless planner — the
transcript never modulates the plan and surfaces only in the Heard chip and
telemetry. The plan itself is ``planner.service.create_plan`` verbatim.
"""

import asyncio
import logging
import time

from openai import OpenAI

from app.config import GROQ_API_KEY, WHISPER_MODEL
from app.knowledge.assistant import AssistantNotConfiguredError

logger = logging.getLogger(__name__)

# Hard request cap (spec §3); duration is trusted to the client (~60 s
# auto-stop) but bytes are checked server-side.
MAX_AUDIO_BYTES = 5 * 1024 * 1024


def _stt_client() -> OpenAI:
    """Lazily build the Groq client used only for Whisper STT; fail fast when
    no key is configured. STT stays pinned to Groq regardless of LLM_PROVIDER —
    WHISPER_MODEL names a Groq-hosted model."""
    if not GROQ_API_KEY:
        raise AssistantNotConfiguredError("GROQ_API_KEY is not configured")
    return OpenAI(api_key=GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")


def is_blank_transcript(text: str) -> bool:
    """The 422 gate: whitespace-only transcripts never reach the planner."""
    return not text.strip()


async def transcribe_audio(audio_bytes: bytes, filename: str = "audio.webm") -> tuple[str, float]:
    """Transcribe one recording via Groq Whisper; returns (transcript, latency s).

    No codec pre-check — Groq accepts webm/opus and mp4/AAC natively. The
    transcript is whitespace-stripped; blankness is the caller's 422 gate.
    Provider errors propagate as ``openai.APIError`` → 503 at the router.
    """
    client = _stt_client()
    start = time.monotonic()
    response = await asyncio.to_thread(
        client.audio.transcriptions.create,
        model=WHISPER_MODEL,
        file=(filename, audio_bytes),
    )
    latency = time.monotonic() - start
    return (response.text or "").strip(), latency

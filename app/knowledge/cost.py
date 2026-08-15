"""Provider-aware pricing: config-driven cost calculation for one LLM call.

Rates come from config (USD per 1M tokens), selected by the active provider:
openai (gpt-4o-mini) or groq (llama-3.3-70b-versatile). Groq's free tier
charges nothing; the rate is kept for accounting consistency.
"""

from app.config import (
    GROQ_INPUT_RATE_PER_1M,
    GROQ_OUTPUT_RATE_PER_1M,
    LLM_PROVIDER,
    OPENAI_INPUT_RATE_PER_1M,
    OPENAI_OUTPUT_RATE_PER_1M,
)

_RATES: dict[str, tuple[float, float]] = {
    "openai": (OPENAI_INPUT_RATE_PER_1M, OPENAI_OUTPUT_RATE_PER_1M),
    "groq": (GROQ_INPUT_RATE_PER_1M, GROQ_OUTPUT_RATE_PER_1M),
}


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """Price a call in USD: (input*rate_in + output*rate_out) per 1M tokens."""
    in_rate, out_rate = _RATES.get(LLM_PROVIDER, _RATES["openai"])
    return (input_tokens * in_rate + output_tokens * out_rate) / 1_000_000

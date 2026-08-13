"""OpenAI pricing: config-driven cost calculation for one LLM call.

Rates come from config (USD per 1M tokens). Changing models = change
OPENAI_MODEL + OPENAI_INPUT_RATE_PER_1M / OPENAI_OUTPUT_RATE_PER_1M.
"""

from app.config import OPENAI_INPUT_RATE_PER_1M, OPENAI_OUTPUT_RATE_PER_1M


def calculate_cost(input_tokens: int, output_tokens: int) -> float:
    """Price a call in USD: (input*rate_in + output*rate_out) per 1M tokens."""
    return (
        input_tokens * OPENAI_INPUT_RATE_PER_1M + output_tokens * OPENAI_OUTPUT_RATE_PER_1M
    ) / 1_000_000

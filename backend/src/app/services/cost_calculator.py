"""Bedrock per-model pricing lookup for cost estimation (Task 04).

Prices are per 1000 tokens. Values are approximate (us-east-1) and refreshed
from AWS published pricing; treat as estimates, not billing-accurate.
"""

from __future__ import annotations

from typing import Optional

# Per-1000-token pricing, (input, output), USD
MODEL_PRICING: dict[str, tuple[float, float]] = {
    # Anthropic
    "anthropic.claude-opus-4-5-20250101-v1:0": (0.015, 0.075),
    "anthropic.claude-opus-4-20250101-v1:0": (0.015, 0.075),
    "anthropic.claude-sonnet-4-20250514-v1:0": (0.003, 0.015),
    "anthropic.claude-3-5-sonnet-20241022-v2:0": (0.003, 0.015),
    "anthropic.claude-3-5-haiku-20241022-v1:0": (0.001, 0.005),
    "anthropic.claude-3-haiku-20240307-v1:0": (0.00025, 0.00125),
    # Amazon Nova
    "amazon.nova-pro-v1:0": (0.0008, 0.0032),
    "amazon.nova-lite-v1:0": (0.00006, 0.00024),
    "amazon.nova-micro-v1:0": (0.000035, 0.00014),
    # Meta
    "meta.llama3-1-70b-instruct-v1:0": (0.00099, 0.00099),
    "meta.llama3-1-8b-instruct-v1:0": (0.00022, 0.00022),
    # Mistral
    "mistral.mistral-large-2407-v1:0": (0.002, 0.006),
    # Cohere
    "cohere.command-r-plus-v1:0": (0.003, 0.015),
}

# Fallback for unknown models (Sonnet-class average)
DEFAULT_PRICING = (0.003, 0.015)


def _pricing_for(model_id: str) -> tuple[float, float]:
    # Strip any cross-region prefix (e.g., 'us.' / 'eu.' / 'ap.')
    base = model_id
    for prefix in ("us.", "eu.", "ap."):
        if base.startswith(prefix):
            base = base[len(prefix) :]
            break
    return MODEL_PRICING.get(base, DEFAULT_PRICING)


def estimate_cost(
    model_id: Optional[str], input_tokens: int, output_tokens: int
) -> float:
    """Return the estimated cost in USD for one invocation."""
    if not model_id:
        return 0.0
    in_price, out_price = _pricing_for(model_id)
    return round(
        (input_tokens / 1000.0) * in_price
        + (output_tokens / 1000.0) * out_price,
        6,
    )

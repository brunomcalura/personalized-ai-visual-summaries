"""Summarize recorded API attempts using OpenAI Standard prices in USD."""

import argparse
import json
from collections import Counter
from decimal import Decimal
from pathlib import Path


RATES = {
    "gpt-5.6-terra": {"text_input": "2", "cached_input": "0.20", "cache_write": "2.50", "text_output": "12"},
    "gpt-image-2.5-sunburst-2026-09-08": {"text_input": "5", "image_input": "8", "image_output": "30"},
}
STAGES = ("expansion", "portrait_prompt", "image")


def count(attempt):
    usage = attempt.get("usage")
    rates = RATES.get(attempt["requested_model"])
    if rates is None or not isinstance(usage, dict):
        return None
    inputs = usage.get("input_tokens")
    outputs = usage.get("output_tokens")
    if inputs is None or outputs is None:
        return None
    input_details = usage.get("input_tokens_details") or {}
    output_details = usage.get("output_tokens_details") or {}
    if attempt["stage"] == "image":
        # The adapter sends a text prompt and requests one image.
        image_in = input_details.get("image_tokens", 0)
        text_in = input_details.get("text_tokens", inputs - image_in)
        image_out = output_details.get("image_tokens", outputs)
        tokens = {
            "text_input": text_in, "image_input": image_in,
            "image_output": image_out, "text_output": outputs - image_out,
        }
    else:
        cached = input_details.get("cached_tokens", 0)
        cache_write = input_details.get("cache_write_tokens", 0)
        tokens = {
            "text_input": inputs - cached - cache_write, "cached_input": cached,
            "cache_write": cache_write, "text_output": outputs,
        }
    if any(value < 0 or (value and name not in rates) for name, value in tokens.items()):
        return None
    cost = sum(Decimal(rates[name]) * value for name, value in tokens.items() if value) / Decimal(1_000_000)
    return {
        "input_tokens": inputs,
        "output_tokens": outputs,
        "reasoning_tokens_in_output": output_details.get("reasoning_tokens", 0),
        "billable_token_breakdown": tokens,
        "estimated_usd": str(cost),
    }


def summarize(attempts):
    details = [{**entry, "accounting": count(entry)} for entry in attempts]
    totals = {}
    for stage in STAGES:
        rows = [entry for entry in details if entry["stage"] == stage]
        known = [entry["accounting"] for entry in rows if entry["accounting"] is not None]
        breakdown = Counter()
        for row in known:
            breakdown.update(row["billable_token_breakdown"])
        totals[stage] = {
            "attempts": len(rows),
            "attempts_without_cost": len(rows) - len(known),
            "input_tokens": sum(row["input_tokens"] for row in known),
            "output_tokens": sum(row["output_tokens"] for row in known),
            "reasoning_tokens_in_output": sum(row["reasoning_tokens_in_output"] for row in known),
            "billable_token_breakdown": dict(breakdown),
            "estimated_usd": str(sum(Decimal(row["estimated_usd"]) for row in known)),
        }
    return {
        "standard_usd_per_million_tokens": RATES,
        "by_stage": totals,
        "recorded_estimated_usd": str(sum(Decimal(stage["estimated_usd"]) for stage in totals.values())),
        "attempts": details,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path)
    args = parser.parse_args()
    with args.ledger.open(encoding="utf-8") as stream:
        attempts = [json.loads(line) for line in stream if line.strip()]
    print(json.dumps(summarize(attempts), ensure_ascii=True, indent=2))


if __name__ == "__main__":
    main()

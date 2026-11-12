"""Evaluate saved document drafts locally; never contact a provider or load credentials."""

import argparse
import json
import os
from pathlib import Path

from alphasense.document_benchmark import evaluate
from alphasense.document_benchmark_contracts import BenchmarkResponses, BenchmarkSuite

MAX_INPUT_BYTES = 16 * 1024 * 1024


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _constant(value: str) -> object:
    raise ValueError("Non-JSON constant")


def _read(path: Path) -> object:
    with path.open("rb") as source:
        raw = source.read(MAX_INPUT_BYTES + 1)
    if len(raw) > MAX_INPUT_BYTES:
        raise ValueError("Input size")
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, required=True)
    parser.add_argument("--responses", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        suite = BenchmarkSuite.model_validate(_read(args.suite))
        responses = BenchmarkResponses.model_validate(_read(args.responses))
        result = evaluate(suite, responses)
        payload = result.model_dump(mode="json")
        if args.output:
            # O_EXCL refuses existing files and symlinks, even on ambiguous retries.
            descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as destination:
                destination.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        # Do not print case IDs, labels, source bytes, facts or model drafts.
        summary = {key: value for key, value in payload.items() if key != "cases"}
        print(json.dumps(summary, ensure_ascii=True, sort_keys=True, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, RecursionError):
        print('{"error_code":"DOCUMENT_BENCHMARK_INVALID"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

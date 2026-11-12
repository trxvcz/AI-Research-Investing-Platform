"""Prepare or verify private source-bound benchmark samples, without fetching URLs."""

import argparse
import json
from pathlib import Path

from alphasense.benchmark_corpus import (
    MAX_JSON_BYTES,
    CorpusManifest,
    prepare_corpus,
    verify_corpus,
)


def _unique(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON field")
        result[key] = value
    return result


def _constant(_value: str) -> object:
    raise ValueError("Non-JSON constant")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--manifest", type=Path)
    mode.add_argument("--verify", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.verify:
            if args.output:
                raise ValueError("Unexpected output")
            result = verify_corpus(args.verify)
        else:
            if not args.output:
                raise ValueError("Missing output")
            with args.manifest.open("rb") as source:
                raw = source.read(MAX_JSON_BYTES + 1)
            if len(raw) > MAX_JSON_BYTES:
                raise ValueError("Manifest size")
            payload = json.loads(
                raw.decode("utf-8"), object_pairs_hook=_unique, parse_constant=_constant
            )
            manifest = CorpusManifest.model_validate(payload)
            result = prepare_corpus(manifest, args.manifest.resolve().parent, args.output)
        print(json.dumps(result, sort_keys=True, ensure_ascii=True, allow_nan=False))
        return 0
    except (OSError, ValueError, TypeError, RecursionError):
        print('{"error_code":"DOCUMENT_CORPUS_INVALID"}')
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

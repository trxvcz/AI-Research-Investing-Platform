"""Offline benchmark CLI refuses ambiguous inputs and never prints source material."""

import json
import os
import runpy
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator, FormatChecker
from pydantic import ValidationError

from alphasense.document_benchmark import canonical_hash, evaluate
from alphasense.document_benchmark_contracts import (
    BenchmarkCase,
    BenchmarkRatio,
    BenchmarkResponses,
    BenchmarkResult,
    BenchmarkSuite,
)

ROOT = Path(__file__).resolve().parents[3]
FIXTURES = Path(__file__).parent / "fixtures"
SUITE = FIXTURES / "document-benchmark.synthetic.json"
RESPONSES = FIXTURES / "document-benchmark-reference.synthetic.json"


def invoke(monkeypatch, *arguments):
    module = runpy.run_path(str(ROOT / "scripts/benchmark_documents.py"))
    monkeypatch.setattr(sys, "argv", ["benchmark_documents.py", *map(str, arguments)])
    return module["main"]()


def test_reference_suite_is_synthetic_and_result_does_not_qualify_any_model():
    suite = BenchmarkSuite.model_validate_json(SUITE.read_text("utf-8"))
    responses = BenchmarkResponses.model_validate_json(RESPONSES.read_text("utf-8"))
    result = evaluate(suite, responses)
    assert len(suite.cases) == 8
    assert len({case.issuer_label for case in suite.cases}) == 3
    assert {case.format for case in suite.cases} == {"text", "html", "pdf"}
    assert all(case.data_origin == "synthetic" for case in suite.cases)
    assert result.true_positives == 7
    assert result.false_positives == result.false_negatives == result.invalid_responses == 0
    assert result.successful_abstentions == result.expected_abstentions == 2
    assert result.response_origin == "hand_authored_reference"
    assert result.qualification_status == "not_qualified_offline"
    for name, instance in (("suite", suite), ("responses", responses), ("result", result)):
        schema = json.loads(
            (ROOT / f"contracts/v1/document-benchmark-{name}.schema.json").read_text()
        )
        Draft202012Validator(schema, format_checker=FormatChecker()).validate(
            instance.model_dump(mode="json")
        )


def test_cli_creates_private_artifact_but_stdout_contains_only_summary(
    tmp_path, monkeypatch, capsys
):
    output = tmp_path / "result.json"
    assert invoke(monkeypatch, "--suite", SUITE, "--responses", RESPONSES, "--output", output) == 0
    summary = json.loads(capsys.readouterr().out)
    artifact = BenchmarkResult.model_validate_json(output.read_text("utf-8"))
    assert "cases" not in summary
    assert artifact.suite_sha256 == summary["suite_sha256"]
    assert artifact.true_positives == 7
    text = output.read_text("utf-8")
    for forbidden in ("content_base64", "raw_json", "expected_facts", "value_token", "quote"):
        assert forbidden not in text
    if os.name != "nt":
        assert output.stat().st_mode & 0o777 == 0o600


def test_cli_never_overwrites_existing_output(tmp_path, monkeypatch, capsys):
    output = tmp_path / "existing.json"
    output.write_bytes(b"preserve existing work")
    assert invoke(monkeypatch, "--suite", SUITE, "--responses", RESPONSES, "--output", output) == 2
    assert output.read_bytes() == b"preserve existing work"
    assert json.loads(capsys.readouterr().out) == {"error_code": "DOCUMENT_BENCHMARK_INVALID"}


@pytest.mark.parametrize("raw", [b'{"x":1,"x":2}', b'{"x":NaN}', b'{"secret":"PRIVATE"'])
def test_cli_input_errors_are_redacted(raw, tmp_path, monkeypatch, capsys):
    invalid = tmp_path / "invalid.json"
    invalid.write_bytes(raw)
    assert invoke(monkeypatch, "--suite", invalid, "--responses", RESPONSES) == 2
    assert capsys.readouterr().out.strip() == '{"error_code":"DOCUMENT_BENCHMARK_INVALID"}'


def test_cli_has_no_implicit_env_loading_or_provider_calls(monkeypatch, capsys):
    import socket

    def forbidden(*args, **kwargs):
        pytest.fail("An offline evaluation attempted a network request")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setenv("GEMINI_API_KEY", "PRIVATE-SECRET-DO-NOT-PRINT")
    monkeypatch.setenv("ALPHASENSE_DATABASE_URL", "PRIVATE-DATABASE-DO-NOT-READ")
    assert invoke(monkeypatch, "--suite", SUITE, "--responses", RESPONSES) == 0
    assert "PRIVATE" not in capsys.readouterr().out


@pytest.mark.parametrize(
    "payload",
    [
        {"numerator": 0, "denominator": 0, "value": "0.000000"},
        {"numerator": 1, "denominator": 0, "value": None},
        {"numerator": 1, "denominator": 3, "value": "0.333334"},
        {"numerator": True, "denominator": 1, "value": "1.000000"},
    ],
)
def test_ratio_contract_rejects_contradictions(payload):
    with pytest.raises(ValidationError):
        BenchmarkRatio.model_validate(payload)


def test_gold_duplicates_compare_decimals_without_rounding():
    suite = BenchmarkSuite.model_validate_json(SUITE.read_text("utf-8"))
    case = suite.cases[0].model_dump(mode="json")
    first = case["expected_facts"][0]
    case["expected_facts"].append(first | {"value": first["value"] + ".00"})
    with pytest.raises(ValidationError):
        BenchmarkCase.model_validate(case)


def test_result_rejects_forged_aggregate_or_qualification():
    suite = BenchmarkSuite.model_validate_json(SUITE.read_text("utf-8"))
    responses = BenchmarkResponses.model_validate_json(RESPONSES.read_text("utf-8"))
    result = evaluate(suite, responses).model_dump(mode="json")
    for updates in ({"true_positives": 8}, {"qualification_status": "qualified"}):
        with pytest.raises(ValidationError):
            BenchmarkResult.model_validate(result | updates)
    assert canonical_hash(suite) == responses.suite_sha256

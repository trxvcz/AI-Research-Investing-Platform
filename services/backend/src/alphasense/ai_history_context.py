"""Validate and freeze report-bound historical evidence without inference or IO."""

import json
import re
from datetime import UTC, datetime
from decimal import Decimal

from alphasense.ai_history_contracts import (
    AiHistoryComparison,
    AiHistoryContext,
    AiHistoryFact,
    AiHistoryNarrative,
)
from alphasense.contracts import AvailableObservation
from alphasense.document_agent import _constant, _unique
from alphasense.financial_history import FinancialHistory, _points
from alphasense.report_contracts import ReportRevision, canonical_sha256

MAX_CONTEXT_BYTES = 256 * 1024
_UNSAFE = re.compile(r"\d|https?://|<[^>]*>|\b(?:kupuj|kup|sprzedaj|buy|sell)\b", re.I)


class AiHistoryInvalid(ValueError):
    def __init__(self, code: str = "AI_HISTORY_INVALID") -> None:
        self.code = code
        super().__init__(code)


def _plain(value: Decimal) -> str:
    exponent = value.as_tuple().exponent
    if (
        not value.is_finite()
        or abs(value.adjusted()) > 127
        or not isinstance(exponent, int)
        or exponent < -127
    ):
        raise ValueError("Financial decimal out of bounds")
    raw = format(value, "f")
    if len(raw) > 128:
        raise ValueError("Financial decimal out of bounds")
    return "0" if value == 0 else (raw.rstrip("0").rstrip(".") if "." in raw else raw)


def _expected_comparison(previous: AiHistoryFact, current: AiHistoryFact) -> dict[str, object]:
    values = {
        (previous.period_start.date(), previous.period_end.date()): Decimal(previous.value),
        (current.period_start.date(), current.period_end.date()): Decimal(current.value),
    }
    if len(values) != 2:
        raise ValueError("Duplicate comparison period")
    points = _points(values, current.available_at.date())
    item = points[-1]
    return {
        key: getattr(item, key) for key in ("delta_value", "delta_percent", "comparison_reason")
    }


def _validate_internal(context: AiHistoryContext) -> None:
    """Called by the context contract after canonical hash validation."""
    if len(context.model_dump_json().encode()) > MAX_CONTEXT_BYTES:
        raise ValueError("Context too large")
    original_indexes: set[int] = set()
    fact_keys: set[tuple[object, ...]] = set()
    comparison_keys: set[tuple[int, int]] = set()
    for index, evidence in enumerate(context.evidence):
        if evidence.index != index:
            raise ValueError("Evidence indexes must be dense")
        if isinstance(evidence, AiHistoryFact):
            if evidence.available_at > context.as_of:
                raise ValueError("Evidence was unavailable as of report")
            key = (
                evidence.metric,
                evidence.unit,
                evidence.currency,
                evidence.period_start,
                evidence.period_end,
                evidence.source.source_id,
                evidence.source.snapshot_id,
            )
            if key in fact_keys:
                raise ValueError("Duplicate evidence fact")
            fact_keys.add(key)
            if evidence.report_observation_index is not None:
                if evidence.report_observation_index in original_indexes:
                    raise ValueError("Duplicate original observation")
                original_indexes.add(evidence.report_observation_index)
            elif evidence.filing_accession is None:
                raise ValueError("Historical fact requires a filing")
            continue
        if (
            not evidence.previous_index < evidence.index
            or not evidence.current_index < evidence.index
        ):
            raise ValueError("Comparison must reference preceding facts")
        previous = context.evidence[evidence.previous_index]
        current = context.evidence[evidence.current_index]
        if not isinstance(previous, AiHistoryFact) or not isinstance(current, AiHistoryFact):
            raise ValueError("Comparison references must be facts")
        if (
            previous.metric != current.metric
            or current.metric != evidence.metric
            or previous.currency != current.currency
            or previous.unit != current.unit
            or previous.currency != "USD"
            or previous.unit != "currency"
            or previous.source != current.source
            or previous.filing_accession is None
            or previous.filing_accession != current.filing_accession
            or previous.period_end >= current.period_start
            or not all(
                300 <= (f.period_end - f.period_start).days <= 400 for f in (previous, current)
            )
        ):
            raise ValueError("Incompatible comparison evidence")
        pair = evidence.previous_index, evidence.current_index
        if pair in comparison_keys:
            raise ValueError("Duplicate comparison")
        comparison_keys.add(pair)
        expected = _expected_comparison(previous, current)
        if any(getattr(evidence, key) != value for key, value in expected.items()):
            raise ValueError("Comparison arithmetic mismatch")
    for fact in context.evidence:
        if not isinstance(fact, AiHistoryFact) or fact.report_observation_index is not None:
            continue
        anchors = [
            candidate
            for candidate in context.evidence
            if isinstance(candidate, AiHistoryFact)
            and candidate.report_observation_index is not None
            and (
                candidate.metric,
                candidate.unit,
                candidate.currency,
                candidate.source,
                candidate.filing_accession,
            )
            == (fact.metric, fact.unit, fact.currency, fact.source, fact.filing_accession)
            and fact.period_end < candidate.period_start
        ]
        if not anchors or not any(fact.index in pair for pair in comparison_keys):
            raise ValueError("Historical fact is not linked to an original anchor")


def validate_history_context(
    context: AiHistoryContext, report: ReportRevision | None = None
) -> AiHistoryContext:
    try:
        checked = AiHistoryContext.model_validate(context.model_dump(mode="python"))
        if report is None:
            return checked
        source_report = ReportRevision.model_validate(report.model_dump(mode="python"))
        if (checked.report_id, checked.revision, checked.report_checksum, checked.as_of) != (
            source_report.report_id,
            source_report.revision,
            source_report.checksum,
            source_report.input.as_of,
        ):
            raise ValueError("Report identity mismatch")
        sources = {(s.source_id, s.snapshot_id): s for s in source_report.sources}
        seen: set[int] = set()
        for evidence in checked.evidence:
            if not isinstance(evidence, AiHistoryFact):
                continue
            if (
                sources.get((evidence.source.source_id, evidence.source.snapshot_id))
                != evidence.source
            ):
                raise ValueError("Foreign source")
            original = evidence.report_observation_index
            if original is None:
                continue
            if original >= len(source_report.input.observations):
                raise ValueError("Unknown original observation")
            observation = source_report.input.observations[original]
            if not isinstance(observation, AvailableObservation) or (
                evidence.metric,
                evidence.unit,
                evidence.currency,
                evidence.period_start,
                evidence.period_end,
                Decimal(evidence.value),
                evidence.available_at,
            ) != (
                observation.metric,
                observation.unit,
                observation.currency,
                observation.period_start,
                observation.period_end,
                Decimal(str(observation.value)),
                observation.available_at,
            ):
                raise ValueError("Original observation mismatch")
            if (evidence.source.source_id, evidence.source.snapshot_id) != (
                observation.source_id,
                observation.snapshot_id,
            ):
                raise ValueError("Original source mismatch")
            seen.add(original)
        if seen != {
            i for i, o in enumerate(source_report.input.observations) if o.status == "available"
        }:
            raise ValueError("Original observations not exactly covered")
        return checked
    except (
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        IndexError,
        RecursionError,
        ArithmeticError,
    ):
        raise AiHistoryInvalid("AI_HISTORY_CONTEXT_INVALID") from None


def build_history_context(report: ReportRevision, history: FinancialHistory) -> AiHistoryContext:
    try:
        report = ReportRevision.model_validate(report.model_dump(mode="python"))
        history = FinancialHistory.model_validate(history.model_dump(mode="python"))
        if (history.report_id, history.revision, history.report_checksum, history.as_of) != (
            report.report_id,
            report.revision,
            report.checksum,
            report.input.as_of,
        ):
            raise ValueError("History belongs to another report")
        sources = {(s.source_id, s.snapshot_id): s for s in report.sources}
        evidence: list[AiHistoryFact | AiHistoryComparison] = []
        for index, observation in enumerate(report.input.observations):
            if not isinstance(observation, AvailableObservation):
                continue
            evidence.append(
                AiHistoryFact(
                    index=len(evidence),
                    metric=observation.metric,
                    unit=observation.unit,
                    currency=observation.currency,
                    value=_plain(Decimal(str(observation.value))),
                    period_start=observation.period_start,
                    period_end=observation.period_end,
                    available_at=observation.available_at,
                    source=sources[(observation.source_id, observation.snapshot_id)],
                    report_observation_index=index,
                    filing_accession=None,
                )
            )
        comparisons: list[tuple[str, int, int, dict[str, object]]] = []
        seen_metrics: set[str] = set()
        for series in sorted(history.series, key=lambda s: s.metric):
            if series.metric in seen_metrics:
                raise ValueError("Duplicate history metric")
            seen_metrics.add(series.metric)
            source_matches = [
                s for s in report.sources if s.snapshot_id == str(series.source_snapshot_id)
            ]
            if len(source_matches) != 1:
                raise ValueError("Unknown history source")
            source = source_matches[0]
            if (source.sha256, str(source.url), source.retrieved_at) != (
                series.source_sha256,
                series.source_url,
                series.available_at,
            ):
                raise ValueError("History provenance mismatch")
            if series.status == "unavailable":
                if series.points or series.filing_accession is not None or not series.reason:
                    raise ValueError("Invalid unavailable series")
                continue
            if (
                not series.points
                or not series.filing_accession
                or (
                    series.status == "available"
                    and (len(series.points) != 3 or series.reason is not None)
                )
                or (series.status == "partial" and (len(series.points) > 2 or not series.reason))
            ):
                raise ValueError("Invalid history status")
            points = series.points
            if points != sorted(points, key=lambda p: (p.period_end, p.period_start)):
                raise ValueError("Unordered history")
            latest = points[-1]
            anchors = [
                (i, o)
                for i, o in enumerate(report.input.observations)
                if isinstance(o, AvailableObservation)
                and o.metric == series.metric
                and o.currency == series.currency
                and o.unit == "currency"
                and o.period_start.date() == latest.period_start
                and o.period_end.date() == latest.period_end
                and Decimal(str(o.value)) == Decimal(latest.value)
                and (o.source_id, o.snapshot_id) == (source.source_id, source.snapshot_id)
            ]
            if len(anchors) != 1:
                raise ValueError("History anchor mismatch")
            _original, anchor = anchors[0]
            if (
                latest.filing_date > anchor.event_time.date()
                or latest.filing_date < latest.period_end
            ):
                raise ValueError("History filing was unavailable at anchor")
            if any(
                p.filing_date != latest.filing_date
                or not 300 <= (p.period_end - p.period_start).days <= 400
                for p in points
            ):
                raise ValueError("Invalid history dates")
            values = {(p.period_start, p.period_end): Decimal(p.value) for p in points}
            if len(values) != len(points):
                raise ValueError("Duplicate history period")
            expected = _points(values, latest.filing_date)
            if any(
                p.model_dump(mode="json") != q.model_dump(mode="json")
                for p, q in zip(points, expected, strict=True)
            ):
                raise ValueError("History arithmetic mismatch")
            positions = []
            for point in points:
                matches = [
                    i
                    for i, item in enumerate(evidence)
                    if isinstance(item, AiHistoryFact)
                    and item.report_observation_index is not None
                    and item.metric == series.metric
                    and item.source == source
                    and item.currency == series.currency
                    and item.unit == "currency"
                    and item.period_start.date() == point.period_start
                    and item.period_end.date() == point.period_end
                    and Decimal(item.value) == Decimal(point.value)
                ]
                if len(matches) > 1:
                    raise ValueError("Ambiguous original history fact")
                if matches:
                    position = matches[0]
                    old = evidence[position]
                    assert isinstance(old, AiHistoryFact)
                    evidence[position] = old.model_copy(
                        update={"filing_accession": series.filing_accession}
                    )
                else:
                    position = len(evidence)
                    evidence.append(
                        AiHistoryFact(
                            index=position,
                            metric=series.metric,
                            unit="currency",
                            currency="USD",
                            value=point.value,
                            period_start=datetime.combine(
                                point.period_start, datetime.min.time(), UTC
                            ),
                            period_end=datetime.combine(point.period_end, datetime.min.time(), UTC),
                            available_at=series.available_at,
                            source=source,
                            report_observation_index=None,
                            filing_accession=series.filing_accession,
                        )
                    )
                positions.append(position)
            for offset, point in enumerate(points[1:], 1):
                comparisons.append(
                    (
                        series.metric,
                        positions[offset - 1],
                        positions[offset],
                        {
                            "delta_value": point.delta_value,
                            "delta_percent": point.delta_percent,
                            "comparison_reason": point.comparison_reason,
                        },
                    )
                )
        for metric, previous, current, comparison_values in comparisons:
            evidence.append(
                AiHistoryComparison.model_validate(
                    {
                        "index": len(evidence),
                        "metric": metric,
                        "previous_index": previous,
                        "current_index": current,
                        **comparison_values,
                    }
                )
            )
        limitations = list(dict.fromkeys(history.limitations))
        if not comparisons:
            limitations.append(
                "Brak porównywalnej historii w zamrożonym kontekście; nie oceniaj trendów."
            )
        # The previous history view warns that it is not yet AI input; that warning
        # is obsolete for this new context and must not be sent to the model.
        limitations = [s for s in limitations if "nie jest jeszcze wejściem" not in s]
        if not limitations:
            limitations = ["Dane ograniczone do przypisanych publicznych źródeł raportu."]
        draft = AiHistoryContext.model_construct(
            report_id=report.report_id,
            revision=report.revision,
            report_checksum=report.checksum,
            as_of=report.input.as_of,
            evidence=evidence,
            limitations=limitations,
            context_sha256="0" * 64,
        )
        data = draft.model_dump(mode="json", exclude={"context_sha256"})
        data["context_sha256"] = canonical_sha256(data)
        return validate_history_context(AiHistoryContext.model_validate(data), report)
    except (
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        IndexError,
        RecursionError,
        ArithmeticError,
    ):
        raise AiHistoryInvalid("AI_HISTORY_CONTEXT_INVALID") from None


def validate_history_narrative(context: AiHistoryContext, raw_json: str) -> AiHistoryNarrative:
    try:
        checked = validate_history_context(context)
        if not isinstance(raw_json, str) or len(raw_json.encode()) > 256 * 1024:
            raise ValueError("Narrative size")
        result = AiHistoryNarrative.model_validate(
            json.loads(raw_json, object_pairs_hook=_unique, parse_constant=_constant)
        )
        for claim in result.summary + result.strengths + result.risks + result.questions:
            if _UNSAFE.search(claim.text):
                raise ValueError("Unsafe narrative content")
            if any(i >= len(checked.evidence) for i in claim.evidence_indexes):
                raise ValueError("Unknown evidence")
            cited = [checked.evidence[i] for i in claim.evidence_indexes]
            if claim.kind == "state" and any(not isinstance(e, AiHistoryFact) for e in cited):
                raise ValueError("State requires facts")
            if claim.kind == "trend":
                comparison = cited[0]
                if (
                    not isinstance(comparison, AiHistoryComparison)
                    or comparison.delta_value is None
                ):
                    raise ValueError("Trend requires comparable periods")
                delta = Decimal(comparison.delta_value)
                direction = "increase" if delta > 0 else "decrease" if delta < 0 else "unchanged"
                if claim.direction != direction:
                    raise ValueError("Trend direction mismatch")
        if any(_UNSAFE.search(text) for text in result.limitations):
            raise ValueError("Unsafe limitations")
        return result
    except (
        ValueError,
        TypeError,
        AttributeError,
        KeyError,
        IndexError,
        RecursionError,
        ArithmeticError,
    ):
        raise AiHistoryInvalid("AI_HISTORY_RESPONSE_INVALID") from None

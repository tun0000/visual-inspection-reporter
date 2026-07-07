"""VLM 回傳解析防呆：finding_id 對齊、幻覺剔除、缺漏標記。"""

from inspector.schema import (
    FindingAssessment,
    ImageAssessment,
    Severity,
    Verdict,
    reconcile,
)


def _fa(finding_id: int, severity: Severity = Severity.MINOR) -> FindingAssessment:
    return FindingAssessment(
        finding_id=finding_id, severity=severity, description_zh="描述", action_zh="處置"
    )


def test_reconcile_clean_passthrough():
    assessment = ImageAssessment(
        verdict=Verdict.REWORK, summary_zh="總評", findings=[_fa(1), _fa(2)]
    )
    rec = reconcile(assessment, [1, 2])
    assert rec.dropped_ids == [] and rec.missing_ids == [] and rec.warnings == []
    assert rec.assessment.verdict is Verdict.REWORK


def test_reconcile_drops_hallucinated_and_duplicate_ids():
    assessment = ImageAssessment(
        verdict=Verdict.FAIL,
        summary_zh="總評",
        findings=[_fa(1), _fa(99), _fa(1, Severity.CRITICAL)],
    )
    rec = reconcile(assessment, [1, 2])
    kept = [fa.finding_id for fa in rec.assessment.findings]
    assert kept == [1]
    assert rec.assessment.findings[0].severity is Severity.MINOR  # 重複時保留第一筆
    assert rec.dropped_ids == [1, 99] or rec.dropped_ids == [99, 1] or set(rec.dropped_ids) == {1, 99}
    assert rec.missing_ids == [2]
    assert len(rec.warnings) == 2


def test_reconcile_missing_ids_listed_sorted():
    assessment = ImageAssessment(verdict=Verdict.PASS, summary_zh="總評", findings=[_fa(3)])
    rec = reconcile(assessment, [1, 2, 3])
    assert rec.missing_ids == [1, 2]


def test_schema_enum_values_are_stable():
    # 這些字串進 VLM 的 JSON schema 與快取：改了要 bump SCHEMA_VERSION
    assert [s.value for s in Severity] == ["critical", "major", "minor"]
    assert [v.value for v in Verdict] == ["pass", "rework", "fail"]

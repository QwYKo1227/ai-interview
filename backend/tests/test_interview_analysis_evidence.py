import pytest

from app.services.interview_lifecycle_service import (
    AnalysisContractError,
    SCORE_DIMENSIONS,
    enforce_analysis_contract,
)


@pytest.fixture
def analysis_payload():
    return {
        "format_version": 2,
        "dimensions": {
            key: {
                "score": 8,
                "assessment": "回答有转写证据支持",
                "evidence": [{"start": 1, "end": 2, "quote": "真实回答"}],
            }
            for key in SCORE_DIMENSIONS
        },
        "recommendation": "passed",
        "summary": "综合表现说明",
        "strengths": [],
        "risks": [],
        "recommendation_reason": "岗位匹配说明",
        "next_round_questions": [],
    }


TRANSCRIPT = {"segments": [{"start": 1, "end": 2, "text": "真实回答"}]}


@pytest.mark.parametrize("dimension", SCORE_DIMENSIONS)
def test_single_evidence_object_is_verified_and_returned_as_array(analysis_payload, dimension):
    analysis_payload["dimensions"][dimension]["evidence"] = {
        "start": 100,
        "end": 101,
        "quote": "真实回答",
    }

    result = enforce_analysis_contract(analysis_payload, TRANSCRIPT)

    assert result["dimensions"][dimension]["evidence"] == [
        {"start": 1.0, "end": 2.0, "quote": "真实回答"},
    ]
    assert result["dimensions"][dimension]["score"] == 8
    assert result["coverage"] == 100
    assert result["weighted_score"] == 8
    assert result["recommendation"] == "passed"


@pytest.mark.parametrize("dimension", SCORE_DIMENSIONS)
@pytest.mark.parametrize("score", [None, 8])
@pytest.mark.parametrize("evidence_format", ["null", "missing"])
def test_absent_evidence_marks_dimension_unscored(analysis_payload, dimension, score, evidence_format):
    item = analysis_payload["dimensions"][dimension]
    item["score"] = score
    if evidence_format == "missing":
        item.pop("evidence")
    else:
        item["evidence"] = None

    result = enforce_analysis_contract(analysis_payload, TRANSCRIPT)

    assert result["dimensions"][dimension]["evidence"] == []
    assert result["dimensions"][dimension]["score"] is None
    assert result["coverage"] == 100 - SCORE_DIMENSIONS[dimension]["weight"]
    if SCORE_DIMENSIONS[dimension]["gate"]:
        assert result["recommendation"] == "inconclusive"
        assert result["next_round_questions"]
    else:
        assert result["recommendation"] == "passed"


@pytest.mark.parametrize("evidence", [
    {"start": 1, "end": 2, "quote": "虚构回答"},
    {},
    {"start": 1, "end": 2},
])
def test_single_object_does_not_bypass_evidence_verification(analysis_payload, evidence):
    analysis_payload["dimensions"]["technical_fit"]["evidence"] = evidence

    result = enforce_analysis_contract(analysis_payload, TRANSCRIPT)

    assert result["dimensions"]["technical_fit"]["score"] is None
    assert result["dimensions"]["technical_fit"]["evidence"] == []
    assert result["recommendation"] == "inconclusive"


@pytest.mark.parametrize("evidence", ["真实回答", "", 1, False])
def test_scalar_evidence_still_rejected(analysis_payload, evidence):
    analysis_payload["dimensions"]["technical_fit"]["evidence"] = evidence

    with pytest.raises(AnalysisContractError, match="评分维度 technical_fit 的 evidence 必须是数组"):
        enforce_analysis_contract(analysis_payload, TRANSCRIPT)

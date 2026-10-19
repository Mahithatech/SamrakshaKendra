from app.anomaly_service import run_synthetic_anomaly_screening_fixture


def test_synthetic_screening_demo_detects_expected_spike():
    result = run_synthetic_anomaly_screening_fixture()
    assert result["status"] == "passed"
    assert result["is_synthetic"] is True
    assert result["input_periods"] == 6
    assert result["input_case_counts"] == [10, 10, 10, 10, 10, 100]
    assert result["expected_flags"] == 1
    assert result["count"] == 1
    anomaly = result["items"][0]
    assert anomaly["cases"] == 100
    assert anomaly["is_synthetic"] is True
    assert anomaly["source"] == "synthetic_validation_fixture"
    assert anomaly["district"] == "DEMO ONLY"
    assert "not a real disease report" in anomaly["message"]


def test_synthetic_screening_fixture_never_claims_real_surveillance():
    result = run_synthetic_anomaly_screening_fixture()
    assert "no database reads or writes" in result["message"].lower()
    assert "not surveillance data" in result["caution"].lower()
    assert "do not represent an outbreak" in result["caution"].lower()

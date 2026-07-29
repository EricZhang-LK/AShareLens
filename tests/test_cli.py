import json

from typer.testing import CliRunner

from asharelens.cli import app


def test_demo_json_reports_reproducible_closed_loop() -> None:
    result = CliRunner().invoke(app, ["demo", "--json"])

    assert result.exit_code == 0
    payload = json.loads(result.stdout)
    assert payload["data_source"] == "deterministic_synthetic"
    assert payload["sessions"] == 80
    assert payload["strategy"] == "moving_average"
    assert payload["signals"] > 0
    assert payload["fills"] > 0
    assert len(payload["fingerprint"]) == 64


def test_demo_human_output_labels_synthetic_data_and_risk() -> None:
    result = CliRunner().invoke(app, ["demo"])

    assert result.exit_code == 0
    assert "确定性合成数据" in result.stdout
    assert "不构成投资建议" in result.stdout

import json

from aurai_knowledge.cli import main

from .conftest import ROOT


def test_validate_corpus_ok(capsys):
    assert main(["validate-corpus", "--source", str(ROOT / "corpus")]) == 0
    assert "corpus ok" in capsys.readouterr().out


def test_validate_corpus_reports_problems(tmp_path, capsys):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "a.md").write_text("# A\n\ntext")
    assert main(["validate-corpus", "--source", str(tmp_path)]) == 1
    assert "collection.yaml is missing" in capsys.readouterr().out


def test_offline_eval_passes(capsys):
    code = main(
        [
            "eval",
            "--golden",
            str(ROOT / "eval" / "golden-set.yaml"),
            "--policy",
            str(ROOT / "config" / "entitlements.yaml"),
            "--corpus",
            str(ROOT / "corpus"),
        ]
    )
    out = capsys.readouterr().out
    assert code == 0 and "leaks=0" in out


def test_eval_can_write_a_json_report(tmp_path, capsys):
    report = tmp_path / "report.json"
    code = main(
        [
            "eval",
            "--golden",
            str(ROOT / "eval" / "golden-set.yaml"),
            "--policy",
            str(ROOT / "config" / "entitlements.yaml"),
            "--corpus",
            str(ROOT / "corpus"),
            "--json",
            str(report),
        ]
    )
    capsys.readouterr()
    data = json.loads(report.read_text())
    assert code == 0
    assert data["mode"] == "offline" and data["leaks"] == 0 and data["cases"] >= 28
    assert len(data["golden_set_sha256"]) == 64
    assert data["thresholds"]["hit_rate"] == 0.85
    assert data["executed_at"].endswith("Z") and "T" in data["executed_at"]

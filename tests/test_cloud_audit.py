import importlib.util
from pathlib import Path


def load(name):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).parents[1] / "scripts" / (name + ".py"))
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_hardware_measurement_does_not_qualify_solver_or_license():
    audit = load("audit_cloud")
    result = audit.readiness()
    assert result["ready_for_full_simulation"] is False
    assert {gate["status"] for gate in result["gates"]} == {
        "blocked_environment", "blocked_license", "blocked_platform_policy",
    }


def test_publication_scan_identifies_secret_without_returning_value():
    audit = load("audit_publication")
    token = "ghp_" + "A" * 36
    result = audit.inspect("settings.json", token.encode())
    assert result == ["github_token"]
    assert token not in str(result)
    assert "credential_or_activation_file" in audit.inspect("license.lic", b"example")


def test_measurement_records_free_space_not_a_fixed_disk_limit(tmp_path, monkeypatch):
    audit = load("audit_cloud")
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path))
    report = audit.measure()
    assert report["disks"]
    assert all(0 <= d["free_bytes"] <= d["total_bytes"] for d in report["disks"])
    assert report["disk_budget"]["measured"] is False
    assert report["scratch_candidate"] in [d["path"] for d in report["disks"] if not d["ram_backed"]]

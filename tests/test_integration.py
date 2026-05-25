"""Integration tests — run pi_monitor.py as a subprocess and check its output."""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent


def _run(tmp_path, *extra_args):
    output = tmp_path / "pi_monitor.html"
    result = subprocess.run(
        [sys.executable, str(ROOT / "pi_monitor.py"), "--output", str(output), *extra_args],
        capture_output=True,
        text=True,
    )
    return result, output


def test_exits_zero(tmp_path):
    result, _ = _run(tmp_path)
    assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"

def test_stdout_confirmation(tmp_path):
    result, _ = _run(tmp_path)
    assert "[pi_monitor] Written to" in result.stdout

def test_output_file_exists(tmp_path):
    _, output = _run(tmp_path)
    assert output.exists()

def test_output_is_html(tmp_path):
    _, output = _run(tmp_path)
    assert output.read_text().startswith("<!DOCTYPE html>")

def test_output_non_trivial_size(tmp_path):
    _, output = _run(tmp_path)
    assert output.stat().st_size > 5_000

def test_output_has_expected_sections(tmp_path):
    _, output = _run(tmp_path)
    content = output.read_text()
    for section in ("CPU Usage", "Memory", "Temperature", "Disk Usage", "Listening Ports", "Top Processes"):
        assert section in content, f"Missing section: {section}"

def test_ping_host_flag(tmp_path):
    result, output = _run(tmp_path, "--ping-host", "127.0.0.1")
    assert result.returncode == 0
    assert "127.0.0.1" in output.read_text()

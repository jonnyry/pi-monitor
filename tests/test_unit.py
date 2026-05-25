"""Unit tests for pi_monitor.py — pure functions and mocked data-collection functions."""
import pathlib
from unittest.mock import patch

import pi_monitor


# ── Colour helpers ─────────────────────────────────────────────────────────────

def test_pct_color_ok():
    assert pi_monitor.pct_color(0) == "ok"
    assert pi_monitor.pct_color(59) == "ok"

def test_pct_color_warn():
    assert pi_monitor.pct_color(60) == "warn"
    assert pi_monitor.pct_color(84) == "warn"

def test_pct_color_crit():
    assert pi_monitor.pct_color(85) == "crit"
    assert pi_monitor.pct_color(100) == "crit"


def test_temp_color_none_is_ok():
    assert pi_monitor.temp_color(None) == "ok"

def test_temp_color_ok():
    assert pi_monitor.temp_color(0) == "ok"
    assert pi_monitor.temp_color(64) == "ok"

def test_temp_color_warn():
    assert pi_monitor.temp_color(65) == "warn"
    assert pi_monitor.temp_color(79) == "warn"

def test_temp_color_crit():
    assert pi_monitor.temp_color(80) == "crit"
    assert pi_monitor.temp_color(95) == "crit"


def test_invert_pct_color_ok():
    assert pi_monitor.invert_pct_color(100) == "ok"

def test_invert_pct_color_warn():
    assert pi_monitor.invert_pct_color(95) == "warn"
    assert pi_monitor.invert_pct_color(90) == "warn"

def test_invert_pct_color_crit():
    assert pi_monitor.invert_pct_color(89) == "crit"
    assert pi_monitor.invert_pct_color(0) == "crit"


# ── bar / status_dot ───────────────────────────────────────────────────────────

def test_bar_class_and_width():
    result = pi_monitor.bar(50, "ok")
    assert 'class="bar-fill ok"' in result
    assert "width:50%" in result

def test_bar_clamps_low():
    assert "width:0%" in pi_monitor.bar(-10, "ok")

def test_bar_clamps_high():
    assert "width:100%" in pi_monitor.bar(150, "crit")


def test_status_dot_ok():
    assert "dot-ok" in pi_monitor.status_dot(True)

def test_status_dot_crit():
    assert "dot-crit" in pi_monitor.status_dot(False)


# ── _safe_iface ────────────────────────────────────────────────────────────────

def test_safe_iface_valid():
    assert pi_monitor._safe_iface("wlan0") == "wlan0"
    assert pi_monitor._safe_iface("eth0") == "eth0"
    assert pi_monitor._safe_iface("enp3s0") == "enp3s0"

def test_safe_iface_rejects_injection():
    assert pi_monitor._safe_iface("wlan0; rm -rf /") is None
    assert pi_monitor._safe_iface("$(evil)") is None

def test_safe_iface_rejects_empty_and_none():
    assert pi_monitor._safe_iface("") is None
    assert pi_monitor._safe_iface(None) is None

def test_safe_iface_rejects_too_long():
    assert pi_monitor._safe_iface("a" * 16) is None


# ── get_uptime ─────────────────────────────────────────────────────────────────

def test_get_uptime_hours_and_minutes():
    with patch("pi_monitor.read", return_value="7262.5 1234.0"):
        assert pi_monitor.get_uptime() == "2h 1m"

def test_get_uptime_days_hours_minutes():
    with patch("pi_monitor.read", return_value="90061.0 0.0"):
        assert pi_monitor.get_uptime() == "1d 1h 1m"

def test_get_uptime_minutes_only():
    with patch("pi_monitor.read", return_value="300.0 0.0"):
        assert pi_monitor.get_uptime() == "5m"


# ── get_memory / get_swap ─────────────────────────────────────────────────────

_MEMINFO = """\
MemTotal:        4096000 kB
MemFree:          512000 kB
MemAvailable:    1024000 kB
Buffers:          128000 kB
Cached:           512000 kB
SwapTotal:       1048576 kB
SwapFree:        1048576 kB
"""

def test_get_memory_percentage():
    with patch("pi_monitor.read", return_value=_MEMINFO):
        _, _, _, pct = pi_monitor.get_memory()
    assert pct == 75.0

def test_get_memory_units():
    with patch("pi_monitor.read", return_value=_MEMINFO):
        total, used, avail, _ = pi_monitor.get_memory()
    assert "GB" in total
    assert "GB" in used
    assert "MB" in avail  # 1024000 kB < 1 GB threshold, so MB

def test_get_swap_all_free():
    with patch("pi_monitor.read", return_value=_MEMINFO):
        _, _, pct = pi_monitor.get_swap()
    assert pct == 0.0

def test_get_swap_no_swap():
    no_swap = "SwapTotal:       0 kB\nSwapFree:        0 kB\n"
    with patch("pi_monitor.read", return_value=no_swap):
        _, _, pct = pi_monitor.get_swap()
    assert pct == 0


# ── get_load_avg ───────────────────────────────────────────────────────────────

def test_get_load_avg():
    with patch("pi_monitor.read", return_value="0.50 0.75 1.00 2/500 12345"):
        la1, la5, la15 = pi_monitor.get_load_avg()
    assert la1 == "0.50"
    assert la5 == "0.75"
    assert la15 == "1.00"


# ── get_throttle ───────────────────────────────────────────────────────────────

def test_get_throttle_ok():
    with patch("pi_monitor.run", return_value="throttled=0x0"):
        ok, flags = pi_monitor.get_throttle()
    assert ok is True
    assert flags == []

def test_get_throttle_active():
    # 0x50005 → bits 0, 2, 16, 18 (under-voltage, throttled, historical variants)
    with patch("pi_monitor.run", return_value="throttled=0x50005"):
        ok, flags = pi_monitor.get_throttle()
    assert ok is False
    assert "Under-voltage detected" in flags
    assert "Currently throttled" in flags
    assert "Under-voltage has occurred" in flags
    assert "Throttling has occurred" in flags

def test_get_throttle_unavailable():
    with patch("pi_monitor.run", return_value="N/A"):
        ok, flags = pi_monitor.get_throttle()
    assert ok is None


# ── get_disks ──────────────────────────────────────────────────────────────────

_DF_OUTPUT = (
    "Target     Size  Used  Avail  Use%\n"
    "/          30G   10G   20G    33%\n"
    "/boot      256M  50M   206M   20%\n"
)

def test_get_disks_count():
    with patch("pi_monitor.run", return_value=_DF_OUTPUT):
        disks = pi_monitor.get_disks()
    assert len(disks) == 2

def test_get_disks_root_mount():
    with patch("pi_monitor.run", return_value=_DF_OUTPUT):
        disks = pi_monitor.get_disks()
    assert disks[0]["mount"] == "/"
    assert disks[0]["pct"] == 33


# ── get_listening_ports ────────────────────────────────────────────────────────

_TCP = (
    "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
    "   0: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 12345 1 0 0 0\n"
)
_EMPTY = "  sl  local_address rem_address   st\n"

_PROC_FILES = {
    "/proc/net/tcp":  _TCP,
    "/proc/net/tcp6": _EMPTY,
    "/proc/net/udp":  _EMPTY,
    "/proc/net/udp6": _EMPTY,
}

def _make_read_text(files):
    def _read(self, **kwargs):
        content = files.get(str(self))
        if content is None:
            raise OSError(f"Mock: no such file: {self}")
        return content
    return _read

def test_get_listening_ports_parses_ssh():
    with patch.object(pathlib.Path, "read_text", _make_read_text(_PROC_FILES)):
        ports = pi_monitor.get_listening_ports()
    assert any(p["proto"] == "tcp" and p["port"] == "22" for p in ports)

def test_get_listening_ports_result_structure():
    with patch.object(pathlib.Path, "read_text", _make_read_text(_PROC_FILES)):
        ports = pi_monitor.get_listening_ports()
    for p in ports:
        assert "proto" in p
        assert "port" in p
        assert "addr" in p

def test_get_listening_ports_skips_non_listen_tcp():
    # State 01 = ESTABLISHED, not LISTEN (0A) — port 80 should not appear
    established = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:0050 00000000:0000 01 00000000:00000000 00:00000000 00000000     0        0 12345 1 0 0 0\n"
    )
    files = {**_PROC_FILES, "/proc/net/tcp": established}
    with patch.object(pathlib.Path, "read_text", _make_read_text(files)):
        ports = pi_monitor.get_listening_ports()
    assert not any(p["port"] == "80" for p in ports)

def test_get_listening_ports_sorted_by_port():
    multi = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:01BB 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1 0 0 0\n"
        "   1: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 2 1 0 0 0\n"
    )
    files = {**_PROC_FILES, "/proc/net/tcp": multi}
    with patch.object(pathlib.Path, "read_text", _make_read_text(files)):
        ports = pi_monitor.get_listening_ports()
    port_nums = [int(p["port"]) for p in ports]
    assert port_nums == sorted(port_nums)


# ── build_html ─────────────────────────────────────────────────────────────────

_DATA = {
    "hostname":    "test-pi",
    "datetime":    ("Monday 25 May 2026", "12:00:00"),
    "uptime":      "2h 15m",
    "cpu_pct":     42.5,
    "load":        ("0.50", "0.60", "0.70"),
    "cpu_freq":    "1500 MHz",
    "temperature": 45.0,
    "throttle":    (True, []),
    "memory":      ("3.9 GB", "2.9 GB", "1000 MB", 75.0),
    "swap":        ("1.0 GB", "0 MB", 0.0),
    "disks": [
        {"mount": "/", "size": "30G", "used": "10G", "avail": "20G", "pct": 33},
    ],
    "wifi": None,
    "eth": {"iface": "eth0", "state": "up", "ip": "192.168.1.100", "speed": "1000 Mbps"},
    "tailscale": None,
    "docker":    None,
    "ping":      (True, 0, 15.3),
    "wan_ip":    "1.2.3.4",
    "processes": [{"pid": "123", "cpu": "5.0", "mem": "2.1", "name": "python3"}],
    "gpu_mem":   "128M",
    "voltage":   "1.2000V",
    "os":        ("Raspberry Pi OS", "6.1.21-v8+", "aarch64"),
    "ports":     [{"proto": "tcp", "port": "22", "addr": "*"}],
}

def _html():
    return pi_monitor.build_html(_DATA)

def test_build_html_is_valid_html():
    assert _html().startswith("<!DOCTYPE html>")

def test_build_html_contains_hostname():
    assert "test-pi" in _html()

def test_build_html_section_titles():
    h = _html()
    for title in ("CPU Usage", "Memory", "Temperature", "Disk Usage", "Listening Ports", "Top Processes"):
        assert title in h, f"Missing section: {title}"

def test_build_html_cpu_percentage():
    assert "42.5%" in _html()

def test_build_html_ethernet_ip():
    assert "192.168.1.100" in _html()

def test_build_html_no_wifi_when_none():
    assert "Wi-Fi" not in _html()

def test_build_html_port_22():
    assert ">22<" in _html()

def test_build_html_escapes_xss_in_hostname():
    evil = {**_DATA, "hostname": "<script>alert('xss')</script>"}
    assert "<script>alert" not in pi_monitor.build_html(evil)

#!/usr/bin/env python3
"""
pi_monitor.py — Raspberry Pi static HTML health dashboard generator

Run via cron every 5 minutes:
  */5 * * * * /usr/bin/python3 /home/pi/pi_monitor.py

Run with --help for options:
  python3 pi_monitor.py --help

Copyright (c) 2026 Jonny Rylands
Licensed under the MIT License — see https://github.com/jonnyry/pi_monitor
"""

import subprocess
import socket
import os
import re
import time
import html
import json
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────
SCRIPT_DIR  = Path(__file__).resolve().parent
OUTPUT_PATH = SCRIPT_DIR / "pi_monitor.html"  # change if needed
PING_HOST   = "8.8.8.8"
PING_COUNT  = 4
TAILSCALE_ENABLED = False
TAILSCALE_CONTAINER = "tailscale"

# ── Helpers ───────────────────────────────────────────────────────────────────

def run(cmd, fallback="N/A"):
    try:
        env = os.environ.copy()
        env["PATH"] = "/usr/sbin:/usr/local/sbin:/sbin:" + env.get("PATH", "/usr/bin:/bin")
        return subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL, text=True, env=env).strip()
    except Exception:
        return fallback

def run_cmd(cmd, fallback=None):
    try:
        env = os.environ.copy()
        env["PATH"] = "/usr/sbin:/usr/local/sbin:/sbin:" + env.get("PATH", "/usr/bin:/bin")
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL, text=True, env=env).strip()
    except Exception:
        return fallback

def read(path, fallback="N/A"):
    try:
        return Path(path).read_text().strip()
    except Exception:
        return fallback

def _safe_iface(iface):
    """Reject interface names that contain shell-unsafe characters."""
    if iface and re.match(r'^[A-Za-z0-9_.:-]{1,15}$', iface):
        return iface
    return None

# ── Data collection ───────────────────────────────────────────────────────────

def get_hostname():
    return socket.getfqdn()

def get_datetime():
    now = datetime.now()
    return now.strftime("%A %d %B %Y"), now.strftime("%H:%M:%S")

def get_uptime():
    raw = read("/proc/uptime", "0")
    secs = float(raw.split()[0])
    days, rem = divmod(int(secs), 86400)
    hours, rem = divmod(rem, 3600)
    mins = rem // 60
    parts = []
    if days:  parts.append(f"{days}d")
    if hours: parts.append(f"{hours}h")
    parts.append(f"{mins}m")
    return " ".join(parts)

def get_cpu_percent():
    def read_stat():
        line = Path("/proc/stat").read_text().splitlines()[0].split()
        total = sum(int(x) for x in line[1:])
        idle  = int(line[4])
        return total, idle
    t1, i1 = read_stat()
    time.sleep(0.5)
    t2, i2 = read_stat()
    diff_total = t2 - t1
    diff_idle  = i2 - i1
    if diff_total == 0:
        return 0.0
    return round(100.0 * (1 - diff_idle / diff_total), 1)

def get_load_avg():
    raw = read("/proc/loadavg", "? ? ?")
    parts = raw.split()
    return parts[0], parts[1], parts[2]

def get_cpu_freq():
    raw = read("/sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", None)
    if raw and raw != "N/A":
        return f"{int(raw) // 1000} MHz"
    raw2 = run("vcgencmd measure_clock arm 2>/dev/null | cut -d= -f2")
    if raw2 and raw2 != "N/A":
        return f"{int(raw2) // 1_000_000} MHz"
    return "N/A"

def get_temperature():
    raw = read("/sys/class/thermal/thermal_zone0/temp", None)
    if raw and raw != "N/A":
        return round(int(raw) / 1000, 1)
    raw2 = run("vcgencmd measure_temp 2>/dev/null")
    if raw2 != "N/A":
        m = re.search(r"[\d.]+", raw2)
        if m:
            return float(m.group())
    return None

def get_throttle():
    raw = run("vcgencmd get_throttled 2>/dev/null")
    if raw == "N/A" or "=" not in raw:
        return None, []
    val = int(raw.split("=")[1], 16)
    flags = {
        0:  "Under-voltage detected",
        1:  "ARM frequency capped",
        2:  "Currently throttled",
        3:  "Soft temperature limit active",
        16: "Under-voltage has occurred",
        17: "ARM frequency capped (historical)",
        18: "Throttling has occurred",
        19: "Soft temperature limit (historical)",
    }
    active = [desc for bit, desc in flags.items() if val & (1 << bit)]
    return val == 0, active

def get_memory():
    raw = read("/proc/meminfo", "")
    info = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            info[parts[0].rstrip(":")] = int(parts[1])
    total = info.get("MemTotal", 0)
    avail = info.get("MemAvailable", 0)
    used  = total - avail
    pct   = round(100 * used / total, 1) if total else 0
    def fmt(kb):
        if kb >= 1024*1024: return f"{kb/1024/1024:.1f} GB"
        return f"{kb/1024:.0f} MB"
    return fmt(total), fmt(used), fmt(avail), pct

def get_swap():
    raw = read("/proc/meminfo", "")
    info = {}
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 2:
            info[parts[0].rstrip(":")] = int(parts[1])
    total = info.get("SwapTotal", 0)
    free  = info.get("SwapFree", 0)
    used  = total - free
    pct   = round(100 * used / total, 1) if total else 0
    def fmt(kb):
        if kb >= 1024*1024: return f"{kb/1024/1024:.1f} GB"
        return f"{kb/1024:.0f} MB"
    return fmt(total), fmt(used), pct

def get_disks():
    disks = []
    raw = run("df -h --output=target,size,used,avail,pcent -x tmpfs -x devtmpfs -x squashfs")
    for line in raw.splitlines()[1:]:
        parts = line.split()
        if len(parts) == 5:
            mount, size, used, avail, pct_str = parts
            pct = int(pct_str.rstrip("%"))
            disks.append({"mount": mount, "size": size, "used": used, "avail": avail, "pct": pct})
    return disks

def get_wifi():
    iface = run("iw dev 2>/dev/null | awk '/Interface/{print $2}' | head -1")
    if iface == "N/A" or not iface:
        return None
    iface = _safe_iface(iface)
    if not iface:
        return None
    ssid    = run(f"iw {iface} link 2>/dev/null | awk '/SSID/{{print $2}}'")
    signal  = run(f"iw {iface} link 2>/dev/null | awk '/signal/{{print $2}}'")
    ip      = run(f"ip -4 addr show {iface} 2>/dev/null | awk '/inet /{{print $2}}' | cut -d/ -f1")
    bitrate = run(f"iw {iface} link 2>/dev/null | awk '/tx bitrate/{{print $3, $4}}'")
    return {"iface": iface, "ssid": ssid or "N/A", "signal": signal or "N/A",
            "ip": ip or "N/A", "bitrate": bitrate or "N/A"}

def get_ethernet():
    iface = run("ip link show | awk -F: '/^[0-9]+: e/{print $2}' | tr -d ' ' | head -1")
    if iface == "N/A" or not iface:
        return None
    iface = _safe_iface(iface)
    if not iface:
        return None
    state = run(f"cat /sys/class/net/{iface}/operstate 2>/dev/null")
    ip    = run(f"ip -4 addr show {iface} 2>/dev/null | awk '/inet /{{print $2}}' | cut -d/ -f1")
    speed = run(f"cat /sys/class/net/{iface}/speed 2>/dev/null")
    speed_str = f"{speed} Mbps" if speed not in ("N/A", "-1", "") else "N/A"
    return {"iface": iface, "state": state, "ip": ip or "N/A", "speed": speed_str}

def get_tailscale():
    sources = [
        ("native", ["tailscale", "status", "--json"]),
        ("docker", ["docker", "exec", TAILSCALE_CONTAINER, "tailscale", "status", "--json"]),
    ]

    raw = None
    source = "none"
    for label, cmd in sources:
        raw = run_cmd(cmd)
        if raw:
            source = label
            break

    if not raw:
        return {
            "available": False,
            "source": source,
            "state": "unavailable",
            "error": "tailscale not found natively or via Docker",
        }

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {
            "available": False,
            "source": source,
            "state": "invalid",
            "error": "tailscale returned invalid JSON",
        }

    self_info = data.get("Self") or {}
    peers = list((data.get("Peer") or {}).values())
    online_peers = [p for p in peers if p.get("Online")]
    active_peers = [p for p in peers if p.get("Active")]

    relays = {}
    for p in peers:
        relay = p.get("Relay")
        if relay:
            relays[relay] = relays.get(relay, 0) + 1

    return {
        "available": True,
        "source": source,
        "state": data.get("BackendState", "unknown"),
        "hostname": self_info.get("HostName", "N/A"),
        "dns": self_info.get("DNSName", "N/A").rstrip("."),
        "ips": self_info.get("TailscaleIPs", []),
        "online_peers": len(online_peers),
        "total_peers": len(peers),
        "active_peers": len(active_peers),
        "relays": relays,
    }

def get_ping():
    raw = run(f"ping -c {PING_COUNT} -W 2 {PING_HOST} 2>/dev/null")
    if raw == "N/A":
        return None, None, None
    loss_m = re.search(r"(\d+)% packet loss", raw)
    rtt_m  = re.search(r"rtt min/avg/max/mdev = [\d.]+/([\d.]+)/[\d.]+/[\d.]+ ms", raw)
    loss   = int(loss_m.group(1)) if loss_m else 100
    avg    = float(rtt_m.group(1)) if rtt_m else None
    return loss == 0, loss, avg

def get_wan_ip():
    for url in ("https://api.ipify.org", "https://icanhazip.com", "https://ifconfig.me"):
        result = run(f"curl -s --max-time 5 {url}")
        if result and result != "N/A" and re.match(r"^\d+\.\d+\.\d+\.\d+$", result.strip()):
            return result.strip()
    return None

def get_processes():
    raw = run("top -bn2 -d0.5 | grep -A 20 'PID' | tail -20")
    procs = []
    for line in raw.splitlines():
        parts = line.split()
        if len(parts) >= 12 and parts[0].isdigit():
            procs.append({
                "pid":  parts[0],
                "cpu":  parts[8],
                "mem":  parts[9],
                "name": parts[11],
            })
    try:
        procs.sort(key=lambda p: float(p["cpu"]), reverse=True)
    except ValueError:
        pass
    return procs[:5]

def get_gpu_memory():
    raw = run("vcgencmd get_mem gpu 2>/dev/null")
    if "=" in raw:
        return raw.split("=")[1]
    return None

def get_os_info():
    pretty = run("grep PRETTY_NAME /etc/os-release | cut -d= -f2 | tr -d '\"'")
    kernel = run("uname -r")
    arch   = run("uname -m")
    return pretty, kernel, arch

def get_voltage():
    raw = run("vcgencmd measure_volts core 2>/dev/null")
    if "=" in raw:
        return raw.split("=")[1]
    return None

# ── New collectors ────────────────────────────────────────────────────────────


def get_listening_ports():
    """Listening TCP/UDP ports from /proc/net — no root required."""
    import socket as _socket

    def hex_to_addr_port(hex_local):
        hex_addr, hex_port = hex_local.split(":")
        port = int(hex_port, 16)
        if len(hex_addr) == 8:
            packed = bytes.fromhex(hex_addr)[::-1]
            addr = _socket.inet_ntop(_socket.AF_INET, packed)
        else:
            b = bytes.fromhex(hex_addr)
            reordered = b""
            for i in range(0, 16, 4):
                reordered += b[i:i+4][::-1]
            addr = _socket.inet_ntop(_socket.AF_INET6, reordered)
        if addr in ("0.0.0.0", "::", "::ffff:0.0.0.0"):
            addr = "*"
        return addr, port

    seen = set()
    ports = []
    proc_files = [
        ("tcp", "/proc/net/tcp"),
        ("tcp", "/proc/net/tcp6"),
        ("udp", "/proc/net/udp"),
        ("udp", "/proc/net/udp6"),
    ]
    for proto, fpath in proc_files:
        try:
            lines = Path(fpath).read_text().splitlines()[1:]
        except OSError:
            continue
        for line in lines:
            fields = line.split()
            if len(fields) < 4:
                continue
            state = fields[3]
            if proto == "tcp" and state != "0A":
                continue
            try:
                addr, port = hex_to_addr_port(fields[1])
            except Exception:
                continue
            key = f"{proto}/{port}"
            if key not in seen:
                seen.add(key)
                ports.append({"proto": proto, "port": str(port), "addr": addr})

    ports.sort(key=lambda p: int(p["port"]))
    return ports


# ── HTML generation ───────────────────────────────────────────────────────────

def pct_color(pct):
    if pct < 60:   return "ok"
    if pct < 85:   return "warn"
    return "crit"

def temp_color(t):
    if t is None: return "ok"
    if t < 65:    return "ok"
    if t < 80:    return "warn"
    return "crit"

def bar(pct, cls="ok"):
    pct = min(max(pct, 0), 100)
    return f'<div class="bar-track"><div class="bar-fill {cls}" style="width:{pct}%"></div></div>'

def status_dot(ok):
    cls = "dot-ok" if ok else "dot-crit"
    return f'<span class="dot {cls}"></span>'

def build_html(d):
    h = html.escape
    date_str, time_str = d["datetime"]
    throttle_ok, throttle_flags = d["throttle"]
    mem_total, mem_used, mem_avail, mem_pct = d["memory"]
    swap_total, swap_used, swap_pct = d["swap"]
    ping_ok, ping_loss, ping_avg = d["ping"]
    pretty_os, kernel, arch = d["os"]

    # throttle
    if throttle_ok is None:
        throttle_section = '<p class="muted">vcgencmd not available</p>'
    elif throttle_ok:
        throttle_section = f'{status_dot(True)} <span class="ok-text">No throttling</span>'
    else:
        items = "".join(f'<li>{f}</li>' for f in throttle_flags)
        throttle_section = (f'{status_dot(False)} <span class="crit-text">Throttling active</span>'
                            f'<ul class="flag-list">{items}</ul>')

    # disks
    disk_rows = ""
    for dk in d["disks"]:
        c = pct_color(dk["pct"])
        disk_rows += f"""
        <tr>
          <td><code>{h(dk['mount'])}</code></td>
          <td>{h(dk['size'])}</td>
          <td>{h(dk['used'])}</td>
          <td>{h(dk['avail'])}</td>
          <td class="{c}">{dk['pct']}%</td>
          <td style="min-width:120px">{bar(dk['pct'], c)}</td>
        </tr>"""

    # wifi
    wifi_html = ""
    if d["wifi"]:
        w = d["wifi"]
        wifi_html = f"""
        <div class="card">
          <div class="card-title">Wi-Fi — {h(w['iface'])}</div>
          <div class="kv-grid">
            <span class="k">SSID</span><span class="v">{h(w['ssid'])}</span>
            <span class="k">IP</span><span class="v"><code>{h(w['ip'])}</code></span>
            <span class="k">Signal</span><span class="v">{h(w['signal'])} dBm</span>
            <span class="k">TX Rate</span><span class="v">{h(w['bitrate'])}</span>
          </div>
        </div>"""

    # ethernet
    eth_html = ""
    if d["eth"]:
        e = d["eth"]
        state_ok = e["state"] == "up"
        eth_html = f"""
        <div class="card">
          <div class="card-title">Ethernet — {h(e['iface'])}</div>
          <div class="kv-grid">
            <span class="k">State</span><span class="v">{status_dot(state_ok)} {h(e['state'])}</span>
            <span class="k">IP</span><span class="v"><code>{h(e['ip'])}</code></span>
            <span class="k">Speed</span><span class="v">{h(e['speed'])}</span>
          </div>
        </div>"""

    # tailscale
    tailscale_html = ""
    if d.get("tailscale"):
        ts = d["tailscale"]
        state = ts.get("state", "unknown")
        available = ts.get("available", False)
        state_ok = available and state == "Running"
        ips = ", ".join(ts.get("ips") or ["N/A"])
        relay_summary = ", ".join(f"{name}: {count}" for name, count in sorted(ts.get("relays", {}).items())) or "None"
        error_html = ""
        if ts.get("error"):
            error_html = f'<span class="k">Error</span><span class="v crit">{h(ts["error"])}</span>'
        tailscale_html = f"""
        <div class="card">
          <div class="card-title">Tailscale</div>
          <div class="kv-grid">
            <span class="k">State</span><span class="v">{status_dot(state_ok)} {h(state)}</span>
            <span class="k">Source</span><span class="v">{h(ts.get('source', 'unknown'))}</span>
            <span class="k">Device</span><span class="v">{h(ts.get('hostname', 'N/A'))}</span>
            <span class="k">DNS</span><span class="v"><code>{h(ts.get('dns', 'N/A'))}</code></span>
            <span class="k">IP</span><span class="v"><code>{h(ips)}</code></span>
            <span class="k">Peers</span><span class="v">{ts.get('online_peers', 0)} / {ts.get('total_peers', 0)} online</span>
            <span class="k">Active</span><span class="v">{ts.get('active_peers', 0)}</span>
            <span class="k">Relays</span><span class="v">{h(relay_summary)}</span>
            {error_html}
          </div>
        </div>"""

    # processes
    proc_rows = ""
    for p in d["processes"]:
        proc_rows += (f"<tr><td>{h(p['pid'])}</td><td>{h(p['cpu'])}%</td>"
                      f"<td>{h(p['mem'])}%</td><td><code>{h(p['name'])}</code></td></tr>")

    # ports
    port_rows = ""
    for p in d["ports"]:
        port_rows += (f"<tr><td><span class='proto-badge'>{h(p['proto'])}</span></td>"
                      f"<td><strong>{h(p['port'])}</strong></td>"
                      f"<td><code>{h(p['addr'])}</code></td></tr>")

    # misc
    temp_val = d["temperature"]
    temp_str = f"{temp_val} °C" if temp_val is not None else "N/A"
    tc = temp_color(temp_val)
    ping_str      = f"{ping_avg} ms" if ping_avg else "—"
    ping_loss_str = f"{ping_loss}% loss" if ping_loss is not None else "—"
    ping_ok_val   = ping_ok if ping_ok is not None else False
    wan_ip_str    = h(d["wan_ip"]) if d.get("wan_ip") else "—"
    gpu_html  = f'<span class="k">GPU RAM</span><span class="v">{h(d["gpu_mem"])}</span>' if d["gpu_mem"] else ""
    volt_html = f'<span class="k">Core voltage</span><span class="v">{h(d["voltage"])}</span>' if d["voltage"] else ""
    la1, la5, la15 = d["load"]

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="300">
<title>pi monitor — {h(d['hostname'])}</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;600;700&family=IBM+Plex+Sans:wght@300;400;500;600&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:       #f4f6f9;
    --panel:    #ffffff;
    --border:   #dde2ec;
    --accent:   #2563eb;
    --accent2:  #7c3aed;
    --ok:       #16a34a;
    --warn:     #d97706;
    --crit:     #dc2626;
    --muted:    #6b7280;
    --text:     #374151;
    --head:     #111827;
    --mono:     'JetBrains Mono', monospace;
    --sans:     'IBM Plex Sans', sans-serif;
    --radius:   10px;
    --shadow:   0 1px 4px rgba(0,0,0,0.07), 0 4px 12px rgba(0,0,0,0.05);
  }}
  [data-theme="dark"] {{
    --bg:       #0b0e14;
    --panel:    #131720;
    --border:   #1e2535;
    --accent:   #60a5fa;
    --accent2:  #a78bfa;
    --ok:       #4ade80;
    --warn:     #fbbf24;
    --crit:     #f87171;
    --muted:    #6b7280;
    --text:     #c9d1e0;
    --head:     #f9fafb;
    --shadow:   none;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    font-size: 14px;
    min-height: 100vh;
    padding: 24px 20px 60px;
    transition: background 0.25s, color 0.25s;
  }}
  .theme-btn {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 20px;
    color: var(--muted);
    cursor: pointer;
    font-family: var(--mono);
    font-size: 11px;
    padding: 5px 12px;
    display: flex;
    align-items: center;
    gap: 6px;
    transition: border-color 0.2s, color 0.2s;
    white-space: nowrap;
    box-shadow: var(--shadow);
  }}
  .theme-btn:hover {{ border-color: var(--accent); color: var(--accent); }}
  .header {{
    display: flex;
    justify-content: space-between;
    align-items: flex-end;
    flex-wrap: wrap;
    gap: 12px;
    margin-bottom: 28px;
    padding-bottom: 20px;
    border-bottom: 1px solid var(--border);
  }}
  .hostname {{
    font-family: var(--mono);
    font-size: clamp(18px, 3vw, 26px);
    font-weight: 700;
    color: var(--head);
    letter-spacing: -0.5px;
  }}
  .hostname span {{ color: var(--accent); }}
  .datetime {{ text-align: right; line-height: 1.5; }}
  .datetime .date {{ color: var(--muted); font-size: 12px; }}
  .datetime .time {{ font-family: var(--mono); font-size: 22px; color: var(--accent); font-weight: 600; }}
  .stale-note {{ font-size: 11px; color: var(--muted); margin-top: 2px; }}
  .grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
    gap: 16px;
  }}
  .grid-wide {{ display: grid; grid-template-columns: 1fr; gap: 16px; margin-top: 16px; }}
  .card {{
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 20px;
    position: relative;
    overflow: hidden;
    box-shadow: var(--shadow);
    transition: background 0.25s, border-color 0.25s;
  }}
  .card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    opacity: 0.6;
  }}
  .card-title {{
    font-family: var(--mono);
    font-size: 11px;
    font-weight: 600;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 14px;
  }}
  .big-stat {{
    font-family: var(--mono);
    font-size: 36px;
    font-weight: 700;
    color: var(--head);
    line-height: 1;
    margin-bottom: 6px;
  }}
  .big-stat.ok   {{ color: var(--ok);   }}
  .big-stat.warn {{ color: var(--warn); }}
  .big-stat.crit {{ color: var(--crit); }}
  .stat-num {{
    font-family: var(--mono);
    font-size: 28px;
    font-weight: 700;
    line-height: 1;
    margin-bottom: 4px;
  }}
  .stat-num.ok   {{ color: var(--ok);   }}
  .stat-num.warn {{ color: var(--warn); }}
  .stat-num.crit {{ color: var(--crit); }}
  .sub {{ font-size: 12px; color: var(--muted); margin-bottom: 10px; }}
  .bar-track {{
    background: var(--border);
    border-radius: 4px;
    height: 6px;
    overflow: hidden;
    margin-top: 4px;
  }}
  .bar-fill {{ height: 100%; border-radius: 4px; transition: width 0.4s ease; }}
  .bar-fill.ok   {{ background: var(--ok);   }}
  .bar-fill.warn {{ background: var(--warn); }}
  .bar-fill.crit {{ background: var(--crit); }}
  .kv-grid {{
    display: grid;
    grid-template-columns: auto 1fr;
    gap: 6px 16px;
    align-items: center;
  }}
  .k {{ color: var(--muted); font-size: 12px; white-space: nowrap; font-weight: 500; }}
  .v {{ font-family: var(--mono); font-size: 13px; color: var(--text); word-break: break-all; }}
  .dot {{
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    margin-right: 6px;
    vertical-align: middle;
  }}
  .dot-ok   {{ background: var(--ok);   box-shadow: 0 0 0 3px color-mix(in srgb, var(--ok)   20%, transparent); }}
  .dot-warn {{ background: var(--warn); box-shadow: 0 0 0 3px color-mix(in srgb, var(--warn) 20%, transparent); }}
  .dot-crit {{ background: var(--crit); box-shadow: 0 0 0 3px color-mix(in srgb, var(--crit) 20%, transparent); animation: blink 1.2s ease infinite; }}
  @keyframes blink {{ 0%,100%{{ opacity:1 }} 50%{{ opacity:0.3 }} }}
  .ok-text   {{ color: var(--ok);   font-weight: 600; }}
  .warn-text {{ color: var(--warn); font-weight: 600; }}
  .crit-text {{ color: var(--crit); font-weight: 600; }}
  .muted     {{ color: var(--muted); font-size: 12px; }}
  table {{ width: 100%; border-collapse: collapse; font-family: var(--mono); font-size: 13px; }}
  th {{
    text-align: left;
    font-size: 10px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--muted);
    padding: 0 10px 8px 0;
    border-bottom: 1px solid var(--border);
    font-family: var(--sans);
    font-weight: 600;
  }}
  td {{ padding: 7px 10px 7px 0; border-bottom: 1px solid var(--border); vertical-align: middle; }}
  tr:last-child td {{ border-bottom: none; }}
  .ok   {{ color: var(--ok);   font-weight: 600; }}
  .warn {{ color: var(--warn); font-weight: 600; }}
  .crit {{ color: var(--crit); font-weight: 600; }}
  .badge {{
    display: inline-block;
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 600;
    padding: 2px 7px;
    border-radius: 20px;
    margin-left: 8px;
    vertical-align: middle;
  }}
  .badge-crit {{ background: color-mix(in srgb, var(--crit) 15%, transparent); color: var(--crit); }}
  .proto-badge {{
    font-family: var(--mono);
    font-size: 10px;
    font-weight: 700;
    padding: 1px 6px;
    border-radius: 4px;
    background: color-mix(in srgb, var(--accent) 12%, transparent);
    color: var(--accent);
    text-transform: uppercase;
  }}
  .flag-list {{ margin: 8px 0 0 16px; font-size: 12px; color: var(--crit); line-height: 1.8; }}
  .footer {{
    margin-top: 36px;
    text-align: center;
    color: var(--muted);
    font-size: 11px;
    font-family: var(--mono);
  }}
  code {{ font-family: var(--mono); }}
  strong {{ font-weight: 600; }}
</style>
</head>
<body>

<header class="header">
  <div>
    <div class="hostname"><span>●</span> {h(d['hostname'])}</div>
    <div style="margin-top:4px;font-size:12px;color:var(--muted);">up {h(d['uptime'])} &nbsp;·&nbsp; {h(pretty_os)} &nbsp;·&nbsp; {h(kernel)} &nbsp;·&nbsp; {h(arch)}</div>
  </div>
  <div style="display:flex;align-items:flex-start;gap:16px;flex-wrap:wrap">
    <button class="theme-btn" onclick="toggleTheme()" id="themeBtn">☾ Dark</button>
    <div class="datetime">
      <div class="date">{date_str}</div>
      <div class="time">{time_str}</div>
      <div class="stale-note">refreshes every 5 min</div>
    </div>
  </div>
</header>

<!-- Row 1: core metrics -->
<div class="grid">

  <div class="card">
    <div class="card-title">CPU Usage</div>
    <div class="big-stat {pct_color(d['cpu_pct'])}">{d['cpu_pct']}%</div>
    <div class="sub">Load avg &nbsp; {h(la1)} &nbsp; {h(la5)} &nbsp; {h(la15)} &nbsp; (1 / 5 / 15 min)</div>
    {bar(d['cpu_pct'], pct_color(d['cpu_pct']))}
    <div style="margin-top:12px" class="kv-grid">
      <span class="k">Frequency</span><span class="v">{h(d['cpu_freq'])}</span>
      {volt_html}
    </div>
  </div>

  <div class="card">
    <div class="card-title">Temperature</div>
    <div class="big-stat {tc}">{temp_str}</div>
    <div class="sub">SoC core temperature</div>
    {bar(temp_val if temp_val else 0, tc) if temp_val else ''}
    <div style="margin-top:14px">
      <div class="card-title" style="margin-bottom:10px">Throttle Status</div>
      {throttle_section}
    </div>
  </div>

  <div class="card">
    <div class="card-title">Memory</div>
    <div class="big-stat {pct_color(mem_pct)}">{mem_pct}%</div>
    <div class="sub">{mem_used} used of {mem_total} &nbsp;·&nbsp; {mem_avail} free</div>
    {bar(mem_pct, pct_color(mem_pct))}
    <div style="margin-top:12px" class="kv-grid">
      <span class="k">Swap used</span><span class="v">{swap_used} / {swap_total} ({swap_pct}%)</span>
      {gpu_html}
    </div>
  </div>

  <div class="card">
    <div class="card-title">Internet Connectivity</div>
    <div style="font-size:18px;font-family:var(--mono);font-weight:600;color:var(--head);margin-bottom:10px">
      {status_dot(ping_ok_val)} {'Reachable' if ping_ok_val else 'Unreachable'}
    </div>
    <div class="kv-grid">
      <span class="k">Public IP</span><span class="v"><code>{wan_ip_str}</code></span>
      <span class="k">Ping target</span><span class="v">{PING_HOST}</span>
      <span class="k">Avg RTT</span><span class="v {('ok' if ping_ok_val else 'crit')}">{ping_str}</span>
      <span class="k">Packet loss</span><span class="v {('ok' if ping_ok_val else 'crit')}">{ping_loss_str}</span>
    </div>
  </div>

  {wifi_html}
  {eth_html}
  {tailscale_html}

</div>

<!-- Row 3: disk -->
<div class="grid-wide">
  <div class="card">
    <div class="card-title">Disk Usage</div>
    <table>
      <thead><tr><th>Mount</th><th>Size</th><th>Used</th><th>Avail</th><th>Use%</th><th></th></tr></thead>
      <tbody>{disk_rows}</tbody>
    </table>
  </div>
</div>

<!-- Row 4: ports + processes -->
<div class="grid" style="margin-top:16px">
  <div class="card">
    <div class="card-title">Listening Ports</div>
    <table>
      <thead><tr><th>Proto</th><th>Port</th><th>Address</th></tr></thead>
      <tbody>{port_rows if port_rows else '<tr><td colspan="3" class="muted">None found</td></tr>'}</tbody>
    </table>
  </div>

  <div class="card">
    <div class="card-title">Top Processes by CPU</div>
    <table>
      <thead><tr><th>PID</th><th>CPU %</th><th>MEM %</th><th>Command</th></tr></thead>
      <tbody>{proc_rows}</tbody>
    </table>
  </div>
</div>

<div class="footer">generated by pi_monitor.py &nbsp;·&nbsp; {date_str} {time_str}</div>

<script>
  const btn  = document.getElementById('themeBtn');
  const root = document.documentElement;
  // localStorage overrides the server-side default if the user has toggled manually
  const stored = localStorage.getItem('theme');
  if (stored === 'dark') {{ root.setAttribute('data-theme', 'dark'); }}
  if (stored === 'light') {{ root.removeAttribute('data-theme'); }}
  // Sync button label to current state
  function syncBtn() {{
    btn.textContent = root.getAttribute('data-theme') === 'dark' ? '☀ Light' : '☾ Dark';
  }}
  syncBtn();
  function toggleTheme() {{
    const isDark = root.getAttribute('data-theme') === 'dark';
    if (isDark) {{
      root.removeAttribute('data-theme');
      localStorage.setItem('theme', 'light');
    }} else {{
      root.setAttribute('data-theme', 'dark');
      localStorage.setItem('theme', 'dark');
    }}
    syncBtn();
  }}
</script>

</body>
</html>"""

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    global OUTPUT_PATH, PING_HOST, PING_COUNT, TAILSCALE_CONTAINER

    parser = argparse.ArgumentParser(
        description="Generate a static HTML monitoring page for this Raspberry Pi."
    )
    parser.add_argument("--output", "-o", metavar="PATH", default=None, help=f"Where to write the HTML file (default: {OUTPUT_PATH})")
    parser.add_argument("--ping-host", metavar="HOST", default=None, help=f"Host to ping for connectivity check (default: {PING_HOST})")
    parser.add_argument("--ping-count", metavar="N", type=int, default=None, help=f"Number of ping packets (default: {PING_COUNT})")
    parser.add_argument("--tailscale", action="store_true", default=TAILSCALE_ENABLED, help="Include Tailscale status panel")
    parser.add_argument("--tailscale-container", metavar="NAME", default=None, help=f"Docker container name for Tailscale (default: {TAILSCALE_CONTAINER})")
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else OUTPUT_PATH
    if args.ping_host:
        PING_HOST = args.ping_host
    if args.ping_count:
        PING_COUNT = args.ping_count
    if args.tailscale_container:
        TAILSCALE_CONTAINER = args.tailscale_container

    data = {
        "hostname":     get_hostname(),
        "datetime":     get_datetime(),
        "uptime":       get_uptime(),
        "cpu_pct":      get_cpu_percent(),
        "load":         get_load_avg(),
        "cpu_freq":     get_cpu_freq(),
        "temperature":  get_temperature(),
        "throttle":     get_throttle(),
        "memory":       get_memory(),
        "swap":         get_swap(),
        "disks":        get_disks(),
        "wifi":         get_wifi(),
        "eth":          get_ethernet(),
        "tailscale":    get_tailscale() if args.tailscale else None,
        "ping":         get_ping(),
        "wan_ip":       get_wan_ip(),
        "processes":    get_processes(),
        "gpu_mem":      get_gpu_memory(),
        "voltage":      get_voltage(),
        "os":           get_os_info(),
        "ports":        get_listening_ports(),
    }

    html = build_html(data)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(f"[pi_monitor] Written to {output_path}")

if __name__ == "__main__":
    main()

# pi-monitor

A single-file Python script that generates a static HTML health dashboard for a Raspberry Pi. Run it on a cron schedule and serve the output with any web server.

## Screenshots

### Light mode:

![](images/pimonitor-light.png)

### Dark mode:

![](images/pimonitor-dark.png)

## Requirements

- Python 3.7+
- Standard library only — no pip dependencies
- Optional: `iw` for Wi-Fi stats, `vcgencmd` for temperature/throttle/voltage (Raspberry Pi firmware tool)


## Usage

```bash
# Write to the default location (same directory as the script)
python3 pi_monitor.py

# Write to a custom path
python3 pi_monitor.py --output /var/www/html/index.html
python3 pi_monitor.py -o /var/www/html/index.html

# Enable optional panels
python3 pi_monitor.py --docker
python3 pi_monitor.py --dagu --dagu-url http://localhost:8080 --dagu-token <token>
```

### Cron setup

```cron
*/5 * * * * /usr/bin/python3 /home/pi/pi_monitor.py --output /var/www/html/index.html > /dev/null
```

The generated page auto-refreshes every 5 minutes to match.

## Configuration

At the top of the script:

| Variable | Default | Description |
|---|---|---|
| `OUTPUT_PATH` | `pi_monitor.html` next to the script | Default output path |
| `PING_HOST` | `8.8.8.8` | Host used for connectivity check |
| `PING_COUNT` | `4` | Number of ping packets |
| `DOCKER_ENABLED` | `False` | Enable Docker panel by default |
| `DAGU_ENABLED` | `False` | Enable Dagu panel by default |
| `DAGU_URL` | `http://localhost:8080` | Base URL of the local Dagu instance |
| `DAGU_TOKEN` | `""` | Bearer token for Dagu API authentication |

All options can also be set at runtime via flags (see Usage above).

## What it monitors

- **CPU** — usage %, load average (1/5/15 min), frequency, core voltage
- **Temperature** — SoC temperature with throttle status and active throttle flags
- **Memory** — used/available RAM and swap
- **Disks** — usage for all non-virtual mounts
- **Network** — Wi-Fi (SSID, signal, TX rate) and Ethernet (state, speed), both with IP
- **Connectivity** — ping RTT and packet loss to `PING_HOST`
- **Listening ports** — TCP/UDP ports read from `/proc/net` (no root required)
- **Top processes** — top 5 by CPU usage
- **System info** — hostname, uptime, OS, kernel, architecture
- **Docker** *(optional)* — container health as a percentage, with counts of running, unhealthy, and stopped containers
- **Dagu** *(optional)* — DAG-run success rate over the last 24 hours, with counts of succeeded, failed, and other runs

## Optional panels

### Docker

Shows the percentage of containers in a healthy running state, plus raw counts of running, unhealthy, and stopped containers. The headline percentage is coloured green (100%), amber (90–99%), or red (below 90%).

**Requirement:** the user running the script must be in the `docker` group:

```bash
sudo usermod -aG docker $USER
```

Enable with:

```bash
python3 pi_monitor.py --docker
```

### Dagu

Shows the percentage of DAG runs that succeeded in the last 24 hours, with raw counts of succeeded, failed, and other runs. The headline percentage is coloured green (100%), amber (90–99%), or red (below 90%). All runs in the window are retrieved using cursor-based pagination.

**Requirements:**
- A running [Dagu](https://github.com/dagu-org/dagu) instance accessible at `DAGU_URL`
- A Bearer token with read access to the Dagu API

Enable with:

```bash
python3 pi_monitor.py --dagu --dagu-url http://localhost:8080 --dagu-token <token>
```

Or set `DAGU_URL` and `DAGU_TOKEN` in the script and use `--dagu` alone.

## Output

A self-contained HTML file with light/dark mode toggle (preference persisted in `localStorage`). The only external resource is the Google Fonts stylesheet.

The page degrades gracefully: any metric that cannot be collected (e.g. `vcgencmd` not available, Docker not accessible, Dagu unreachable) shows an error message in the relevant card rather than crashing the script.

## Serving the output

Any static file server works. A minimal option using Python itself:

```bash
python3 -m http.server 8080 --directory /var/www/html
```

Or with nginx:

```nginx
server {
    listen 80;
    root /var/www/html;
    index index.html;
}
```

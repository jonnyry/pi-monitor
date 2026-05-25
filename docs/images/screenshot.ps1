#
# Screenshot helper powershell script to serve the Pi Monitor 
# page with values replaced, for screenshot purposes.
# Also launches Firefox and sets it to a specific position/size
#
# Invoke with:
# powershell -ExecutionPolicy Bypass -File .\screenshot.ps1
#


Add-Type @"
  using System;
  using System.Runtime.InteropServices;
  public class Win32 {
    [DllImport("user32.dll")]
    public static extern bool MoveWindow(IntPtr hWnd, int X, int Y, int nWidth, int nHeight, bool bRepaint);
    [DllImport("user32.dll")]
    public static extern bool SetForegroundWindow(IntPtr hWnd);
  }
"@

# ============================================================
# Settings
# ============================================================

# Window
$windowX      = 100
$windowY      = 100
$windowWidth  = 1100
$windowHeight = 1275

# URLs
$proxyUrl = "http://localhost:8080/"
$realUrl  = "http://raspberry.home.arpa/pi-monitor"

# HTML replacements
# Each entry: Pattern (regex), Replacement
# Set IsLiteral = $true for plain string replacement instead of regex
$deg = [char]0x00B0

$replacements = @(
  # SSID: the <span class="v"> immediately after <span class="k">SSID</span>
  @{ IsLiteral = $false
     Pattern   = '(<span class="k">SSID</span><span class="v">)[^<]*(</span>)'
     Replacement = '${1}MYNETWORK${2}' }

  # Public IP: the <code> immediately after <span class="k">Public IP</span>
  @{ IsLiteral = $false
     Pattern   = '(<span class="k">Public IP</span><span class="v"><code>)[^<]*(</code>)'
     Replacement = '${1}100.1.1.100${2}' }

  # Time
  @{ IsLiteral = $false
     Pattern   = '(<div class="time">)\d{1,2}:\d{2}:\d{2}(</div>)'
     Replacement = '${1}11:50:00${2}' }

  # Temperature
  @{ IsLiteral = $false
     Pattern   = '(<div class="big-stat[^"]*">)[^<]*C(</div>)'
     Replacement = "`${1}37.5 ${deg}C`${2}" }
)

# ============================================================
# Proxy
# ============================================================

function Apply-Replacements {
  param([string]$html)
  foreach ($r in $replacements) {
    if ($r.IsLiteral) {
      $html = $html.Replace($r.Pattern, $r.Replacement)
    } else {
      $html = $html -replace $r.Pattern, $r.Replacement
    }
  }
  return $html
}

$listener = New-Object System.Net.HttpListener
$listener.Prefixes.Add($proxyUrl)
$listener.Start()
Write-Host "Proxy listening on $proxyUrl"

# ============================================================
# Launch Firefox
# ============================================================

$beforeHandles = @(Get-Process firefox -ErrorAction SilentlyContinue |
  ForEach-Object { $_.MainWindowHandle } |
  Where-Object { $_ -ne 0 })

Start-Process "firefox.exe" -ArgumentList "-new-window", $proxyUrl

$newHandle = 0
$attempts  = 0
while ($newHandle -eq 0 -and $attempts -lt 50) {
  Start-Sleep -Milliseconds 200
  $currentHandles = @(Get-Process firefox -ErrorAction SilentlyContinue |
    ForEach-Object { $_.MainWindowHandle } |
    Where-Object { $_ -ne 0 })
  $diff = $currentHandles | Where-Object { $beforeHandles -notcontains $_ }
  if ($diff) { $newHandle = $diff[0] }
  $attempts++
}

if ($newHandle -ne 0) {
  Start-Sleep -Seconds 1
  [Win32]::MoveWindow($newHandle, $windowX, $windowY, $windowWidth, $windowHeight, $true)
  [Win32]::SetForegroundWindow($newHandle)
} else {
  Write-Host "Couldn't find a new Firefox window (will keep serving anyway)"
}

Write-Host "Ctrl+C to stop the proxy when done."

# ============================================================
# Serve
# ============================================================

try {
  while ($listener.IsListening) {
    $asyncResult = $listener.BeginGetContext($null, $null)
    while (-not $asyncResult.AsyncWaitHandle.WaitOne(500)) { }
    $context = $listener.EndGetContext($asyncResult)

    $bytes = (Invoke-WebRequest $realUrl -UseBasicParsing).RawContentStream.ToArray()
    $html  = [System.Text.Encoding]::UTF8.GetString($bytes)
    $html  = Apply-Replacements $html

    $buffer = [System.Text.Encoding]::UTF8.GetBytes($html)
    $context.Response.ContentType     = "text/html; charset=utf-8"
    $context.Response.ContentEncoding = [System.Text.Encoding]::UTF8
    $context.Response.ContentLength64 = $buffer.Length
    $context.Response.OutputStream.Write($buffer, 0, $buffer.Length)
    $context.Response.OutputStream.Close()
  }
}
finally {
  $listener.Stop()
  $listener.Close()
  Write-Host "Listener stopped."
}
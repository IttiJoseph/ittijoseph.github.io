# download_framer_runtime.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

# Folder setup
$jsDir = "assets/js/framer"
New-Item -ItemType Directory -Force -Path $jsDir | Out-Null

# Runtime files we DO want to self-host (from your export)
$targets = @(
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/react.BmmDi4lq.mjs";               out = "$jsDir/react.BmmDi4lq.mjs" }
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/rolldown-runtime.BvQvo3gj.mjs";   out = "$jsDir/rolldown-runtime.BvQvo3gj.mjs" }
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/framer.DswyfC6g.mjs";             out = "$jsDir/framer.DswyfC6g.mjs" }
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/motion.DLKCuWuG.mjs";             out = "$jsDir/motion.DLKCuWuG.mjs" }
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/ACkyoYKVyMmDuCuhOdbjo126RKDNqQTbHbwAHo5UDjE.DzARouHq.mjs"; out = "$jsDir/ACkyoYKVyMmDuCuhOdbjo126RKDNqQTbHbwAHo5UDjE.DzARouHq.mjs" }
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/zs4P2pScr.BdBSkW05.mjs";          out = "$jsDir/zs4P2pScr.BdBSkW05.mjs" }
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/shared-lib.BrRFLER6.mjs";         out = "$jsDir/shared-lib.BrRFLER6.mjs" }
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/NCcKV4lkP.DvjkmlGg.mjs";          out = "$jsDir/NCcKV4lkP.DvjkmlGg.mjs" }
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/mAzOkHlDx.iQLeU1OY.mjs";          out = "$jsDir/mAzOkHlDx.iQLeU1OY.mjs" }
  @{ url = "https://framerusercontent.com/sites/6K7rpuZtWPSqnbTIrsACod/script_main.Bw_SFk1g.mjs";        out = "$jsDir/script_main.Bw_SFk1g.mjs" }
  # Optional analytics script (self-hosted copy name):
  @{ url = "https://events.framer.com/script?v=2";                                                        out = "$jsDir/events-script-v2.js" }
)

Write-Host "Downloading Framer runtime files locally…" -ForegroundColor Cyan

foreach ($t in $targets) {
  try {
    Invoke-WebRequest -UseBasicParsing -Uri $t.url -OutFile $t.out
    Write-Host "OK  -> $($t.out)"
  } catch {
    Write-Warning "Skip -> $($t.url) ($($_.Exception.Message))"
  }
}

Write-Host "Done." -ForegroundColor Green

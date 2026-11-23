# Start OmniCoder (driver) on llama.cpp with explicit context and GPU layers.
# Viv's voice bridge is separate: .opencode/start_viv_bridge.ps1
param(
    [int]$Ctx = 16384,
    [int]$GpuLayers = 16,
    [int]$Port = 1235
)

$exe   = "L:\LocalCoder\tools\llama.cpp\llama-server.exe"
$model = "L:\AI_Models\mradermacher\OmniCoder-2-9B-GGUF\OmniCoder-2-9B.Q3_K_M.gguf"
$log   = "L:\LocalCoder\.opencode\evals\omnicoder-server.log"
$err   = "L:\LocalCoder\.opencode\evals\omnicoder-server.err.log"

$serverArgs = @(
    "-m", $model,
    "-c", "$Ctx",
    "-ngl", "$GpuLayers",
    "--host", "127.0.0.1",
    "--port", "$Port",
    "--jinja"
)
$p = Start-Process -FilePath $exe -ArgumentList $serverArgs -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError $err

for ($i = 0; $i -lt 90; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2
        Write-Output "OmniCoder up: $($r.data[0].id)  pid=$($p.Id)  ctx=$Ctx  ngl=$GpuLayers  port=$Port"
        exit 0
    } catch { }
}
Write-Error "OmniCoder did not come up. See $err"
exit 1

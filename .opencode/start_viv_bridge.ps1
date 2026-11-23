# Start Viv's OpenAI-compatible voice bridge on the GPU.
# OmniCoder stays in LM Studio on the CPU; this process owns the GPU.
param(
    [string]$Checkpoint = "L:\LocalCoder\models\viv_bpe\20261122T191316Z\model.pt",
    [int]$Port = 8001
)

$py  = "L:\.venv\Scripts\python.exe"
$log = "L:\LocalCoder\.opencode\evals\viv-openai-server.log"
$err = "L:\LocalCoder\.opencode\evals\viv-openai-server.err.log"

$free = [int]((nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits) -replace '\s', '')
if ($free -lt 4000) {
    Write-Error "GPU free ${free} MiB; the bridge needs ~4000 MiB. Stop the other GPU job first."
    exit 1
}

$serverArgs = @(
    "-B", "L:\LocalCoder\workspace\autonomy\viv_openai_server.py",
    "--checkpoint", $Checkpoint,
    "--port", "$Port"
)
$p = Start-Process -FilePath $py -ArgumentList $serverArgs -PassThru -WindowStyle Hidden `
    -RedirectStandardOutput $log -RedirectStandardError $err

for ($i = 0; $i -lt 60; $i++) {
    Start-Sleep -Seconds 2
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/v1/models" -TimeoutSec 2
        Write-Output "Viv bridge up: $($r.data[0].id)  pid=$($p.Id)  port=$Port"
        Write-Output "Provider baseURL: http://127.0.0.1:$Port/v1"
        exit 0
    } catch { }
}

Write-Error "Bridge did not come up. See $err"
exit 1

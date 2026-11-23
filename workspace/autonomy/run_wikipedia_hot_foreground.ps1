Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$py = 'L:\.venv\Scripts\python.exe'
$indexer = 'L:\LocalCoder\workspace\autonomy\wikipedia_hot_index.py'
$db = 'L:\LocalCoder\workspace\autonomy\.tmp\wikipedia_hot_index.sqlite3'
$checkpoint = 'L:\LocalCoder\workspace\autonomy\.tmp\wikipedia_hot_checkpoint.json'
$lastBatch = 1288
$limit = 100000

Write-Host "Viv Wikipedia hot index foreground runner"
Write-Host "Source batches: batch_0000..batch_$('{0:D4}' -f $lastBatch) | limit=$limit"
Write-Host "Press Ctrl+C to stop; checkpoint remains resumable."

while ($true) {
    $state = & $py -c "import json; from pathlib import Path; p=Path(r'$checkpoint'); print(json.loads(p.read_text()).get('batch','batch_-1'))"
    $current = [int]($state.Trim() -replace '^batch_', '')
    $next = $current + 1
    if ($next -gt $lastBatch) { Write-Host 'All inventoried batches processed.'; break }
    $batch = 'batch_{0:D4}' -f $next
    $started = Get-Date
    Write-Host "[$started] START $batch limit=$limit"
    & $py $indexer --batch $batch --limit $limit *> $null
    if ($LASTEXITCODE -ne 0) { throw "Indexer failed for $batch with exit code $LASTEXITCODE" }

    $os = Get-CimInstance Win32_OperatingSystem
    $ram = [math]::Round((($os.TotalVisibleMemorySize-$os.FreePhysicalMemory)/$os.TotalVisibleMemorySize)*100,1)
    $receipt = & $py -c "import sqlite3,json; from pathlib import Path; db=Path(r'$db'); cp=Path(r'$checkpoint'); c=sqlite3.connect(db); print({'indexed':c.execute('select count(*) from wikipedia_hot').fetchone()[0],'weights':c.execute('select count(*) from wikipedia_hot where retrieval_weight is not null and route_credit is not null and verified_count is not null').fetchone()[0],'source_hashes':c.execute('select count(*) from wikipedia_hot where length(source_sha256)=64').fetchone()[0],'unknown_fail_closed':c.execute('select 1 from wikipedia_hot where title=?',('unlearned_xylophone_8472',)).fetchone() is None,'checkpoint':json.loads(cp.read_text()).get('batch')}); c.close()"
    Write-Host "[$(Get-Date)] DONE $batch ram_used_pct=$ram receipt=$receipt"
}

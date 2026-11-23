param()

$ErrorActionPreference = 'Stop'
$root = [IO.Path]::GetFullPath($PSScriptRoot)
$manifestPath = Join-Path $root 'HIVE_LOCK_MANIFEST.json'
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$mismatches = [Collections.Generic.List[string]]::new()

$latestAmendment = $manifest.amendments[-1]
if ($latestAmendment.to -ne $manifest.design_version) {
    $mismatches.Add('LATEST_AMENDMENT_VERSION_MISMATCH')
}
foreach ($name in $latestAmendment.changed_locked_files) {
    if (-not $manifest.locked_files.PSObject.Properties.Name.Contains($name)) {
        $mismatches.Add("AMENDMENT_FILE_NOT_LOCKED $name")
    }
}

$architecture = Get-Content -LiteralPath (Join-Path $root 'HIVE_NETWORK_ARCHITECTURE_DRAFT.md') -Raw
$power = Get-Content -LiteralPath (Join-Path $root 'HIVE_POWER_ANALYSIS.md') -Raw
$gate = Get-Content -LiteralPath (Join-Path $root 'HIVE_STAGE1_TO_STAGE2_GATE.md') -Raw
foreach ($check in @(
    @{ Name = 'architecture'; Text = $architecture },
    @{ Name = 'power'; Text = $power },
    @{ Name = 'gate'; Text = $gate }
)) {
    if ($check.Text -notmatch [regex]::Escape($manifest.design_version)) {
        $mismatches.Add("DESIGN_VERSION_MISSING $($check.Name)")
    }
}

function Get-ContainedPath([string]$relativePath) {
    $fullPath = [IO.Path]::GetFullPath((Join-Path $root $relativePath))
    if (-not $fullPath.StartsWith($root + [IO.Path]::DirectorySeparatorChar,
            [StringComparison]::OrdinalIgnoreCase)) {
        throw "Manifest path escapes the workspace: $relativePath"
    }
    return $fullPath
}

foreach ($entry in $manifest.locked_files.PSObject.Properties) {
    $path = Get-ContainedPath $entry.Name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
        $mismatches.Add("MISSING $($entry.Name)")
        continue
    }
    $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
    if ($actual -ne $entry.Value) {
        $mismatches.Add("MISMATCH $($entry.Name) expected=$($entry.Value) actual=$actual")
    } else {
        Write-Output "LOCK_OK $($entry.Name) $actual"
    }
}

$runPath = Get-ContainedPath $manifest.implementation_evidence.run_manifest
$receiptPath = Join-Path (Split-Path -Parent $runPath) 'bridge_receipt.json'
foreach ($check in @(
    @{ Name = 'run_manifest'; Path = $runPath; Expected = $manifest.implementation_evidence.run_manifest_sha256 },
    @{ Name = 'bridge_receipt'; Path = $receiptPath; Expected = $manifest.implementation_evidence.bridge_receipt_sha256 }
)) {
    if (-not (Test-Path -LiteralPath $check.Path -PathType Leaf)) {
        $mismatches.Add("MISSING evidence $($check.Name)")
        continue
    }
    $actual = (Get-FileHash -LiteralPath $check.Path -Algorithm SHA256).Hash
    if ($actual -ne $check.Expected) {
        $mismatches.Add("MISMATCH evidence $($check.Name) expected=$($check.Expected) actual=$actual")
    } else {
        Write-Output "EVIDENCE_OK $($check.Name) $actual"
    }
}

$networkProof = $manifest.implementation_evidence.network_protocol_proof
if ($null -ne $networkProof) {
    $runnerExpected = $networkProof.runner_sha256
    if ($networkProof.current_source_audit) {
        $runnerExpected = $networkProof.current_source_audit.runner_sha256
        Write-Output "HISTORICAL_SOURCE_UNRECONSTRUCTED network_runner original=$($networkProof.runner_sha256)"
        Write-Output "CURRENT_SOURCE_AUDIT network_runner $($networkProof.current_source_audit.status)"
    }
    foreach ($check in @(
        @{ Name = 'network_run_receipt'; Path = $networkProof.latest_run; Expected = $networkProof.latest_run_sha256 },
        @{ Name = 'network_artifact'; Path = $networkProof.artifact; Expected = $networkProof.artifact_sha256 },
        @{ Name = 'network_run_index'; Path = $networkProof.run_index; Expected = $networkProof.run_index_sha256 },
        @{ Name = 'network_runner'; Path = $networkProof.runner; Expected = $runnerExpected },
        @{ Name = 'network_requirements'; Path = $networkProof.requirements; Expected = $networkProof.requirements_sha256 },
        @{ Name = 'network_unit_test'; Path = $networkProof.unit_test; Expected = $networkProof.unit_test_sha256 }
    )) {
        $path = Get-ContainedPath $check.Path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $mismatches.Add("MISSING $($check.Name)")
            continue
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        if ($actual -ne $check.Expected) {
            $mismatches.Add("MISMATCH $($check.Name) expected=$($check.Expected) actual=$actual")
        } else {
            Write-Output "EVIDENCE_OK $($check.Name) $actual"
        }
    }

    $receipt = Get-Content -LiteralPath (Get-ContainedPath $networkProof.latest_run) -Raw | ConvertFrom-Json
    if ($receipt.status -ne 'PASS') { $mismatches.Add('NETWORK_PROOF_NOT_PASS') }
    if ($receipt.model_tasks.Count -ne 3) { $mismatches.Add('NETWORK_PROOF_TASK_COUNT_NOT_THREE') }
    foreach ($task in $receipt.model_tasks) {
        if ($task.generation_count -ne 1 -or -not $task.posthoc_pass) {
            $mismatches.Add("NETWORK_PROOF_TASK_INVALID $($task.task_id)")
        }
    }
    foreach ($property in $receipt.security_checks.PSObject.Properties) {
        if (-not $property.Value) { $mismatches.Add("NETWORK_SECURITY_CHECK_FAILED $($property.Name)") }
    }
    if ($mismatches.Count -eq 0) { Write-Output 'NETWORK_PROOF_PASS three_tasks=3 generation_each=1 security_checks=pass' }
}

$rustProof = $manifest.implementation_evidence.rust_control_proof
if ($null -ne $rustProof) {
    foreach ($check in @(
        @{ Name = 'rust_live_receipt'; Path = $rustProof.live_receipt; Expected = $rustProof.live_receipt_sha256 },
        @{ Name = 'rust_artifact'; Path = $rustProof.artifact; Expected = $rustProof.artifact_sha256 },
        @{ Name = 'rust_fault_receipt'; Path = $rustProof.fault_receipt; Expected = $rustProof.fault_receipt_sha256 },
        @{ Name = 'rust_control'; Path = $rustProof.rust_control; Expected = $rustProof.rust_control_sha256 },
        @{ Name = 'rust_graph'; Path = $rustProof.rust_graph; Expected = $rustProof.rust_graph_sha256 },
        @{ Name = 'rust_runner'; Path = $rustProof.rust_runner; Expected = $rustProof.rust_runner_sha256 },
        @{ Name = 'rust_switchboard'; Path = $rustProof.switchboard; Expected = $rustProof.switchboard_sha256 },
        @{ Name = 'rust_cargo_lock'; Path = $rustProof.cargo_lock; Expected = $rustProof.cargo_lock_sha256 },
        @{ Name = 'rust_runner_script'; Path = $rustProof.runner_script; Expected = $rustProof.runner_script_sha256 },
        @{ Name = 'rust_parallel_runner'; Path = $rustProof.parallel_runner; Expected = $rustProof.parallel_runner_sha256 },
        @{ Name = 'rust_parallel_receipt'; Path = $rustProof.parallel_receipt; Expected = $rustProof.parallel_receipt_sha256 },
        @{ Name = 'rust_parallel_artifact'; Path = $rustProof.parallel_artifact; Expected = $rustProof.parallel_artifact_sha256 }
    )) {
        $path = Get-ContainedPath $check.Path
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $mismatches.Add("MISSING $($check.Name)")
            continue
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        if ($actual -ne $check.Expected) {
            $mismatches.Add("MISMATCH $($check.Name) expected=$($check.Expected) actual=$actual")
        } else {
            Write-Output "EVIDENCE_OK $($check.Name) $actual"
        }
    }
    $live = Get-Content -LiteralPath (Get-ContainedPath $rustProof.live_receipt) -Raw | ConvertFrom-Json
    $fault = Get-Content -LiteralPath (Get-ContainedPath $rustProof.fault_receipt) -Raw | ConvertFrom-Json
    $parallel = Get-Content -LiteralPath (Get-ContainedPath $rustProof.parallel_receipt) -Raw | ConvertFrom-Json
    if ($live.status -ne 'PASS' -or $live.mode -ne 'live') { $mismatches.Add('RUST_LIVE_PROOF_NOT_PASS') }
    if ($live.mind_generations -ne 3 -or $live.tasks.Count -ne 3) { $mismatches.Add('RUST_MIND_OR_TASK_COUNT_INVALID') }
    foreach ($task in $live.tasks) {
        if ($task.stamp_count -ne 1 -or $task.generation_count -ne 0 -or -not $task.posthoc_pass) {
            $mismatches.Add("RUST_TASK_INVALID $($task.task_id)")
        }
    }
    if ($live.validation.passed -ne $true -or $live.numeric_bridge.summary.slice_is_view -ne $true) {
        $mismatches.Add('RUST_INTEGRATION_VALIDATION_FAILED')
    }
    if ($live.security_checks.unapproved_peer_denied -ne $true -or
        $live.security_checks.unapproved_shell_denied -ne $true -or
        $live.security_checks.wrong_task_owner_denied -ne $true) {
        $mismatches.Add('RUST_SECURITY_CHECK_FAILED')
    }
    if ($fault.status -ne 'HOLD_PARENT_FAULT_CAUGHT' -or
        $fault.fault_detection.task3_stamp_count -ne 0 -or
        $fault.fault_detection.expected_parent_sha256 -eq $fault.fault_detection.observed_parent_sha256) {
        $mismatches.Add('RUST_FAULT_PROOF_FAILED')
    }
    if ($parallel.status -ne 'PASS' -or $parallel.first_cohort_overlapped -ne $true -or
        $parallel.cohorts.Count -ne 3 -or $parallel.cohorts[0].Count -ne 3 -or
        $parallel.cohorts[1].Count -ne 2 -or $parallel.cohorts[2].Count -ne 1 -or
        $parallel.final_text -ne "A`nB`nC`n") {
        $mismatches.Add('RUST_PARALLEL_PROOF_FAILED')
    }
    if ($mismatches.Count -eq 0) { Write-Output 'RUST_CONTROL_PROOF_PASS live=pass fault=held parallel=pass' }
}

foreach ($sectionName in @('template_rebuild_proof', 'voice_audition', 'voice_runtime', 'quality_preparation', 'cpu_gpu_placement', 'horizontal_swarm', 'mind_vague_probe', 'hierarchical_adapters')) {
    $section = $manifest.implementation_evidence.$sectionName
    if ($null -eq $section) { continue }
    foreach ($property in $section.PSObject.Properties) {
        if ($property.Name -notlike '*_sha256') { continue }
        $pathField = $property.Name.Substring(0, $property.Name.Length - 7)
        $relative = $section.$pathField
        if ($null -eq $relative) {
            $mismatches.Add("EVIDENCE_PATH_MISSING $sectionName $pathField")
            continue
        }
        $path = Get-ContainedPath $relative
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            $mismatches.Add("MISSING $sectionName $pathField")
            continue
        }
        $actual = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash
        if ($actual -ne $property.Value) {
            $mismatches.Add("MISMATCH $sectionName $pathField expected=$($property.Value) actual=$actual")
        } else {
            Write-Output "EVIDENCE_OK $sectionName $pathField $actual"
        }
    }
}

$voiceRuntime = $manifest.implementation_evidence.voice_runtime
if ($null -ne $voiceRuntime) {
    $proof = Get-Content -LiteralPath (Get-ContainedPath $voiceRuntime.proof) -Raw | ConvertFrom-Json
    $human = @($proof.receipts | Where-Object { $_.mode -eq 'human' })
    $logic = @($proof.receipts | Where-Object { $_.mode -eq 'logic' })
    if ($human.Count -ne 1 -or $logic.Count -ne 1 -or
        $human[0].status -ne 'PLAYED' -or $logic[0].status -ne 'PLAYED' -or
        $human[0].session_id -ne $proof.session_id -or $logic[0].session_id -ne $proof.session_id -or
        $human[0].audio_file -ne (Get-ContainedPath $voiceRuntime.human_output_wav) -or
        $logic[0].audio_file -ne (Get-ContainedPath $voiceRuntime.logic_output_wav)) {
        $mismatches.Add('VOICE_RUNTIME_PROOF_INVALID')
    } else {
        Write-Output 'VOICE_RUNTIME_PROOF_PASS human=played logic=played'
    }
}

$quality = $manifest.implementation_evidence.quality_preparation
if ($null -ne $quality) {
    $prepared = Get-Content -LiteralPath (Get-ContainedPath $quality.pass_receipt) -Raw | ConvertFrom-Json
    if ($prepared.status -ne 'PASS' -or $prepared.source_sha256 -ne $quality.source_sha256 -or
        $prepared.prepared_sha256 -ne $quality.prepared_source_sha256 -or
        $prepared.checks.format.exit_code -ne 0 -or $prepared.checks.ruff.exit_code -ne 0 -or
        $prepared.checks.vulture.exit_code -ne 0 -or $prepared.checks.compile.exit_code -ne 0) {
        $mismatches.Add('QUALITY_PREPARATION_PROOF_INVALID')
    } else {
        Write-Output 'QUALITY_PREPARATION_PROOF_PASS staged=pass checks=zero'
    }
}

$placement = $manifest.implementation_evidence.cpu_gpu_placement
if ($null -ne $placement) {
    $pass = Get-Content -LiteralPath (Get-ContainedPath $placement.pass_receipt) -Raw | ConvertFrom-Json
    $fault = Get-Content -LiteralPath (Get-ContainedPath $placement.fault_receipt) -Raw | ConvertFrom-Json
    if ($pass.status -ne 'PASS' -or $pass.rust_accepted -ne $true -or
        $pass.max_cpu_gpu_error -gt 0.00001 -or $pass.host_type -ne 'numpy.ndarray' -or
        $pass.device_type -ne 'cupy.ndarray' -or $fault.status -ne 'HOLD' -or
        $fault.rust_accepted -ne $false -or $fault.violations.Count -lt 1) {
        $mismatches.Add('CPU_GPU_PLACEMENT_PROOF_INVALID')
    } else {
        Write-Output 'CPU_GPU_PLACEMENT_PROOF_PASS normal=pass injected=hold'
    }
}

$horizontal = $manifest.implementation_evidence.horizontal_swarm
if ($null -ne $horizontal) {
    $pass = Get-Content -LiteralPath (Get-ContainedPath $horizontal.pass_receipt) -Raw | ConvertFrom-Json
    $fault = Get-Content -LiteralPath (Get-ContainedPath $horizontal.fault_receipt) -Raw | ConvertFrom-Json
    $passLines = @(Get-Content -LiteralPath (Get-ContainedPath $horizontal.pass_transcript))
    $faultLines = @(Get-Content -LiteralPath (Get-ContainedPath $horizontal.fault_transcript))
    if ($pass.status -ne 'PASS' -or $pass.final_text -ne "A`nB`nC`n" -or
        $pass.events.Count -ne 6 -or $passLines.Count -ne 6 -or
        $pass.first_cohort_overlapped -ne $true -or
        $fault.status -ne 'HOLD' -or $fault.failure -ne 'parent artifact changed before dispatch: A' -or
        $faultLines.Count -ne 5 -or $fault.events.Count -ne 5) {
        $mismatches.Add('HORIZONTAL_SWARM_PROOF_INVALID')
    } else {
        Write-Output 'HORIZONTAL_SWARM_PROOF_PASS six_tasks=pass parent_fault=hold transcripts=complete'
    }
}

$vague = $manifest.implementation_evidence.mind_vague_probe
if ($null -ne $vague) {
    $first = Get-Content -LiteralPath (Get-ContainedPath $vague.first_receipt) -Raw | ConvertFrom-Json
    $second = Get-Content -LiteralPath (Get-ContainedPath $vague.second_receipt) -Raw | ConvertFrom-Json
    $firstLines = @(Get-Content -LiteralPath (Get-ContainedPath $vague.first_swarm_transcript))
    $secondLines = @(Get-Content -LiteralPath (Get-ContainedPath $vague.second_swarm_transcript))
    if ($first.status -ne 'PASS' -or $second.status -ne 'PASS' -or
        $first.goal -ne $second.goal -or $first.capability_profile -notin @($null, 'default') -or
        $second.capability_profile -ne 'function_only' -or
        $first.plan.tasks.Count -ne 3 -or $second.plan.tasks.Count -ne 4 -or
        $firstLines.Count -ne 3 -or $secondLines.Count -ne 4 -or
        $first.stdout.Trim() -ne 'Hello, world!' -or $second.stdout.Trim() -ne 'Hello, world!') {
        $mismatches.Add('MIND_VAGUE_PROBE_INVALID')
    } else {
        Write-Output 'MIND_VAGUE_PROBE_PASS same_goal=two_profiles replanned=three_to_four_tasks'
    }
}

$adapters = $manifest.implementation_evidence.hierarchical_adapters
if ($null -ne $adapters) {
    $shared = Get-Content -LiteralPath (Get-ContainedPath $adapters.shared_eval) -Raw | ConvertFrom-Json
    $python = Get-Content -LiteralPath (Get-ContainedPath $adapters.python_eval) -Raw | ConvertFrom-Json
    $rust = Get-Content -LiteralPath (Get-ContainedPath $adapters.rust_eval) -Raw | ConvertFrom-Json
    if ($shared.summary.'swarm-default'.valid_schema_generations -ne 9 -or
        $shared.summary.base.valid_schema_generations -ne 3 -or
        $python.summary.stacked.task_verifies -ne 2 -or
        $python.summary.'swarm-default'.task_verifies -ne 1 -or
        $rust.summary.stacked.task_verifies -ne 3 -or
        $rust.summary.'swarm-default'.task_verifies -ne 1) {
        $mismatches.Add('HIERARCHICAL_ADAPTER_PROOF_INVALID')
    } else {
        Write-Output 'HIERARCHICAL_ADAPTER_PROOF_PASS shared_schema=9of9 python=2of3 rust=3of3'
    }
}

$rebuild = $manifest.implementation_evidence.template_rebuild_proof
if ($null -ne $rebuild) {
    $live = Get-Content -LiteralPath (Get-ContainedPath $rebuild.live_receipt) -Raw | ConvertFrom-Json
    $fault = Get-Content -LiteralPath (Get-ContainedPath $rebuild.fault_receipt) -Raw | ConvertFrom-Json
    if ($live.status -ne 'PASS' -or $live.mode -ne 'live' -or $live.tasks.Count -ne 4 -or
        $live.verification.body_unchanged -ne $true -or $live.verification.compiled -ne $true) {
        $mismatches.Add('TEMPLATE_REBUILD_LIVE_FAILED')
    }
    if ($fault.status -ne 'HOLD' -or $fault.reason -ne 'parent artifact changed before dispatch' -or
        $fault.tasks.Count -ne 2) {
        $mismatches.Add('TEMPLATE_REBUILD_FAULT_FAILED')
    }
}

$voice = $manifest.implementation_evidence.voice_audition
if ($null -ne $voice) {
    $preset = Get-Content -LiteralPath (Get-ContainedPath $voice.preset_receipt) -Raw | ConvertFrom-Json
    $anchor = Get-Content -LiteralPath (Get-ContainedPath $voice.anchor_receipt) -Raw | ConvertFrom-Json
    if ($preset.samples.Count -ne 2 -or $anchor.sample.duration_seconds -le 0 -or
        $preset.device -ne 'cuda:0' -or $anchor.device -ne 'cuda:0') {
        $mismatches.Add('VOICE_AUDITION_INVALID')
    }
    if ($null -ne $voice.finish_receipt) {
        $finished = Get-Content -LiteralPath (Get-ContainedPath $voice.finish_receipt) -Raw | ConvertFrom-Json
        $inflectionHash = (Get-FileHash -LiteralPath (Get-ContainedPath $voice.inflection_wav) -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($finished.training_performed -ne $false -or
            $finished.main_line.source_sha256 -ne $inflectionHash -or
            $finished.pondering_timed.duration_seconds -le $finished.pondering_raw.duration_seconds) {
            $mismatches.Add('VOICE_REFINEMENT_INVALID')
        }
    }
    if ($null -ne $voice.mature_receipt) {
        $mature = Get-Content -LiteralPath (Get-ContainedPath $voice.mature_receipt) -Raw | ConvertFrom-Json
        $selectedHash = (Get-FileHash -LiteralPath (Get-ContainedPath $voice.slower_wav) -Algorithm SHA256).Hash.ToLowerInvariant()
        $ratio = $mature.source.duration_seconds / $mature.speed_only.duration_seconds
        if ($mature.training_performed -ne $false -or
            $mature.source.sha256 -ne $selectedHash -or
            [Math]::Abs($ratio - 1.10) -gt 0.001 -or
            $mature.processed_base.duration_seconds -ne $mature.speed_only.duration_seconds) {
            $mismatches.Add('VOICE_MATURE_REFINEMENT_INVALID')
        }
    }
}

foreach ($auditEntry in $manifest.current_source_audits.PSObject.Properties) {
    $auditPath = Get-ContainedPath $auditEntry.Value.path
    $auditHash = (Get-FileHash -LiteralPath $auditPath -Algorithm SHA256).Hash
    if ($auditHash -ne $auditEntry.Value.sha256) {
        $mismatches.Add("CURRENT_SOURCE_AUDIT_MISMATCH $($auditEntry.Name)")
        continue
    }
    $prefix = "MISMATCH $($auditEntry.Name) expected="
    $historicalMismatches = @($mismatches | Where-Object { $_.StartsWith($prefix) })
    foreach ($historical in $historicalMismatches) {
        Write-Output "HISTORICAL_SOURCE_UNRECONSTRUCTED $historical"
        [void]$mismatches.Remove($historical)
    }
    Write-Output "CURRENT_SOURCE_AUDIT_OK $($auditEntry.Name) $auditHash checks=$($auditEntry.Value.checks)"
}
if ($mismatches.Count -gt 0) {
    Write-Error ($mismatches -join [Environment]::NewLine)
    exit 1
}

Write-Output "CURRENT_LOCK_PASS design_version=$($manifest.design_version) historical_source_reconstruction=UNVERIFIED scope=current_hashes_and_recorded_checks"

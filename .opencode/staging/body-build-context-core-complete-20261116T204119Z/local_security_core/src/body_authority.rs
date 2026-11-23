use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct MindRuntimeVerdict {
    pub allowed: bool,
    pub disposition: String,
    pub authority: String,
    pub reasons: Vec<String>,
    pub expected_core_count: usize,
    pub bound_core_count: usize,
    pub active_without_health_report: Vec<String>,
    pub stability_sn: Option<f64>,
    pub minimum_stability_sn: f64,
    pub requested_threads: Option<u64>,
}

pub fn authorize_mind_runtime(request: &Value) -> MindRuntimeVerdict {
    let expected: Vec<String> = request
        .get("expected_cores")
        .and_then(Value::as_array)
        .map(|items| {
            items
                .iter()
                .filter_map(Value::as_str)
                .map(str::to_string)
                .collect()
        })
        .unwrap_or_default();
    let health = request.get("health").unwrap_or(&Value::Null);
    let cores = health.get("cores").and_then(Value::as_object);
    let bound_count = cores.map_or(0, |items| items.len());
    let mut reasons = Vec::new();
    let mut unverified = Vec::new();

    if health.get("kernel").and_then(Value::as_str) != Some("healthy") {
        reasons.push("kernel_health_not_healthy".to_string());
    }

    let mut expected_sorted = expected.clone();
    expected_sorted.sort();
    expected_sorted.dedup();
    let mut bound_sorted: Vec<String> = cores
        .map(|items| items.keys().cloned().collect())
        .unwrap_or_default();
    bound_sorted.sort();
    if expected_sorted.is_empty() || expected_sorted != bound_sorted {
        reasons.push("core_binding_incomplete".to_string());
    }

    let accepted = ["healthy", "ready", "idle", "nominal", "busy"];
    if let Some(cores) = cores {
        for (name, report) in cores {
            let status = report
                .get("status")
                .and_then(Value::as_str)
                .unwrap_or("")
                .to_ascii_lowercase();
            if status.is_empty() || status == "active" || status == "unverified" {
                unverified.push(name.clone());
                reasons.push(format!("core_health_unverified:{name}"));
                if let Some(detail) = report.get("reason").and_then(Value::as_str) {
                    reasons.push(format!("core_health_detail:{name}:{detail}"));
                }
            }
            if !accepted.contains(&status.as_str()) {
                reasons.push(format!(
                    "core_status_unacceptable:{name}:{}",
                    if status.is_empty() {
                        "missing"
                    } else {
                        &status
                    }
                ));
            }
        }
    } else {
        reasons.push("core_health_report_missing".to_string());
    }

    for (name, required) in [
        ("security_core", "healthy"),
        ("data_core", "healthy"),
        ("consciousness_core", "nominal"),
    ] {
        let status = cores
            .and_then(|items| items.get(name))
            .and_then(|report| report.get("status"))
            .and_then(Value::as_str);
        if status != Some(required) {
            reasons.push(format!("critical_core_not_ready:{name}"));
        }
    }

    let stability_sn = cores
        .and_then(|items| items.get("consciousness_core"))
        .and_then(|report| report.get("stability_sn"))
        .and_then(Value::as_f64);
    if !stability_sn.is_some_and(|value| value.is_finite() && value >= 0.45) {
        reasons.push("mind_stability_below_body_threshold".to_string());
    }

    let resources = request.get("body_resources").unwrap_or(&Value::Null);
    let samples = resources.get("thermal_samples").and_then(Value::as_array);
    let mut fresh_sample_count = 0;
    let mut cpu_hot = false;
    let mut gpu_hot = false;
    if let Some(samples) = samples {
        for sample in samples {
            let age = sample.get("sensor_age_seconds").and_then(Value::as_f64);
            let fresh = age.is_some_and(|value| value.is_finite() && (0.0..=15.0).contains(&value));
            if !fresh {
                continue;
            }
            let cpu = sample.get("cpu_temp_c").and_then(Value::as_f64);
            let gpu = sample.get("gpu_temp_c").and_then(Value::as_f64);
            if let (Some(cpu), Some(gpu)) = (cpu, gpu) {
                if cpu.is_finite() && gpu.is_finite() {
                    fresh_sample_count += 1;
                    cpu_hot |= cpu >= 90.0;
                    gpu_hot |= gpu >= 85.0;
                }
            }
        }
    }
    if fresh_sample_count == 0 {
        reasons.push("body_thermal_telemetry_missing_or_stale".to_string());
    }
    if cpu_hot {
        reasons.push("cpu_temperature_at_or_above_limit".to_string());
    }
    if gpu_hot {
        reasons.push("gpu_temperature_at_or_above_limit".to_string());
    }
    let ram = resources.get("ram_percent").and_then(Value::as_f64);
    if !ram.is_some_and(|value| value.is_finite() && value < 95.0) {
        reasons.push("ram_at_or_above_limit".to_string());
    }
    // GPU memory usage remains telemetry only; allocations may spill into system RAM.
    let requested_threads = resources.get("requested_threads").and_then(Value::as_u64);
    if !requested_threads.is_some_and(|value| (1..=4).contains(&value)) {
        reasons.push("runtime_thread_budget_exceeded_or_missing".to_string());
    }
    let disk_free_bytes = resources
        .get("workspace_disk_free_bytes")
        .and_then(Value::as_u64);
    if !disk_free_bytes.is_some_and(|value| value >= 2 * 1024 * 1024 * 1024) {
        reasons.push("workspace_disk_below_two_gibibytes_free_or_unavailable".to_string());
    }

    let allowed = reasons.is_empty();
    MindRuntimeVerdict {
        allowed,
        disposition: if allowed {
            "ALLOW_MIND_RUNTIME"
        } else {
            "HOLD_MIND_RUNTIME"
        }
        .to_string(),
        authority: "deterministic_aios_body_rust".to_string(),
        reasons,
        expected_core_count: expected_sorted.len(),
        bound_core_count: bound_count,
        active_without_health_report: unverified,
        stability_sn,
        minimum_stability_sn: 0.45,
        requested_threads: resources.get("requested_threads").and_then(Value::as_u64),
    }
}

pub fn authorize_mind_runtime_with_container_io(
    request: &Value,
    container_io_boundary_verified: bool,
) -> MindRuntimeVerdict {
    if !container_io_boundary_verified {
        return authorize_mind_runtime(request);
    }

    let mut attested_request = request.clone();
    let Some(privacy_core) = attested_request
        .pointer_mut("/health/cores/privacy_core")
        .and_then(Value::as_object_mut)
    else {
        return authorize_mind_runtime(request);
    };
    let helpers_available = privacy_core
        .get("file_write_authorizer_available")
        .and_then(Value::as_bool)
        == Some(true)
        && privacy_core
            .get("egress_authorizer_available")
            .and_then(Value::as_bool)
            == Some(true);
    if privacy_core.get("status").and_then(Value::as_str) == Some("unverified")
        && privacy_core.get("reason").and_then(Value::as_str)
            == Some("authorization_calls_not_proven_to_cover_process_io")
        && helpers_available
    {
        privacy_core.insert("status".to_string(), Value::String("healthy".to_string()));
        privacy_core.insert(
            "reason".to_string(),
            Value::String("process_io_confined_by_rust_verified_container".to_string()),
        );
    }

    authorize_mind_runtime(&attested_request)
}

#[cfg(test)]
mod tests {
    use super::{authorize_mind_runtime, authorize_mind_runtime_with_container_io};
    use serde_json::json;

    fn healthy_request() -> serde_json::Value {
        let names = [
            "security_core",
            "data_core",
            "consciousness_core",
            "ui_core",
        ];
        let mut cores = serde_json::Map::new();
        for name in names {
            cores.insert(name.to_string(), json!({"status":"healthy"}));
        }
        cores.insert(
            "consciousness_core".to_string(),
            json!({"status":"nominal", "stability_sn":0.8}),
        );
        json!({"expected_cores":names,"health":{"kernel":"healthy","cores":cores},
            "body_resources":{"thermal_samples":[{"sensor_age_seconds":1.0,
                "cpu_temp_c":55.0,"gpu_temp_c":60.0}],"ram_percent":40.0,
                "gpu_memory_percent":40.0,
                "requested_threads":2,"workspace_disk_free_bytes":53687091200_u64}})
    }

    #[test]
    fn allows_only_complete_healthy_body_report() {
        let verdict = authorize_mind_runtime(&healthy_request());
        assert!(verdict.allowed);
        assert_eq!(verdict.disposition, "ALLOW_MIND_RUNTIME");
    }

    #[test]
    fn holds_when_any_core_health_is_unverified() {
        let mut request = healthy_request();
        request["health"]["cores"]["ui_core"]["status"] = json!("unverified");
        let verdict = authorize_mind_runtime(&request);
        assert!(!verdict.allowed);
        assert!(verdict
            .reasons
            .iter()
            .any(|reason| reason == "core_health_unverified:ui_core"));
    }

    #[test]
    fn privacy_core_io_hold_requires_rust_verified_container_boundary() {
        let mut request = healthy_request();
        request["expected_cores"]
            .as_array_mut()
            .unwrap()
            .push(json!("privacy_core"));
        request["health"]["cores"]["privacy_core"]["status"] = json!("unverified");
        request["health"]["cores"]["privacy_core"]["reason"] =
            json!("authorization_calls_not_proven_to_cover_process_io");
        request["health"]["cores"]["privacy_core"]["file_write_authorizer_available"] = json!(true);
        request["health"]["cores"]["privacy_core"]["egress_authorizer_available"] = json!(true);

        assert!(!authorize_mind_runtime(&request).allowed);
        assert!(!authorize_mind_runtime_with_container_io(&request, false).allowed);
        assert!(authorize_mind_runtime_with_container_io(&request, true).allowed);

        request["health"]["cores"]["privacy_core"]["reason"] = json!("other_privacy_gap");
        assert!(!authorize_mind_runtime_with_container_io(&request, true).allowed);
        request["health"]["cores"]["privacy_core"]["reason"] =
            json!("authorization_calls_not_proven_to_cover_process_io");
        request["health"]["cores"]["privacy_core"]["egress_authorizer_available"] = json!(false);
        assert!(!authorize_mind_runtime_with_container_io(&request, true).allowed);
    }

    #[test]
    fn holds_when_expected_core_is_not_bound() {
        let mut request = healthy_request();
        request["expected_cores"] = json!([
            "security_core",
            "data_core",
            "consciousness_core",
            "missing_core"
        ]);
        let verdict = authorize_mind_runtime(&request);
        assert!(!verdict.allowed);
        assert!(verdict
            .reasons
            .iter()
            .any(|reason| reason == "core_binding_incomplete"));
    }

    #[test]
    fn holds_when_body_telemetry_is_missing_or_stale() {
        let mut request = healthy_request();
        request["body_resources"]["thermal_samples"][0]["sensor_age_seconds"] = json!(16.0);
        let verdict = authorize_mind_runtime(&request);
        assert!(!verdict.allowed);
        assert!(verdict
            .reasons
            .iter()
            .any(|reason| reason == "body_thermal_telemetry_missing_or_stale"));
    }

    #[test]
    fn holds_at_cpu_gpu_or_ram_thresholds() {
        for (field, value, expected_reason) in [
            ("cpu_temp_c", 90.0, "cpu_temperature_at_or_above_limit"),
            ("gpu_temp_c", 85.0, "gpu_temperature_at_or_above_limit"),
        ] {
            let mut request = healthy_request();
            request["body_resources"]["thermal_samples"][0][field] = json!(value);
            let verdict = authorize_mind_runtime(&request);
            assert!(!verdict.allowed, "{field}={value} must hold runtime");
            assert!(verdict
                .reasons
                .iter()
                .any(|reason| reason == expected_reason));
        }
        let mut request = healthy_request();
        request["body_resources"]["ram_percent"] = json!(95.0);
        let verdict = authorize_mind_runtime(&request);
        assert!(!verdict.allowed);
        assert!(verdict
            .reasons
            .iter()
            .any(|reason| reason == "ram_at_or_above_limit"));
    }

    #[test]
    fn gpu_memory_usage_does_not_hold_runtime() {
        for value in [95.0, 100.0, -0.1, f64::NAN] {
            let mut request = healthy_request();
            request["body_resources"]["gpu_memory_percent"] = json!(value);
            let verdict = authorize_mind_runtime(&request);
            assert!(verdict.allowed, "gpu memory {value} must not hold runtime: {:?}", verdict.reasons);
        }
        let mut request = healthy_request();
        request["body_resources"]
            .as_object_mut()
            .unwrap()
            .remove("gpu_memory_percent");
        let verdict = authorize_mind_runtime(&request);
        assert!(verdict.allowed, "missing GPU memory telemetry must not hold runtime: {:?}", verdict.reasons);
    }

    #[test]
    fn hot_reading_in_any_fresh_feed_holds_even_if_another_is_cool() {
        let mut request = healthy_request();
        request["body_resources"]["thermal_samples"] = json!([
            {"sensor_age_seconds":1.0,"cpu_temp_c":55.0,"gpu_temp_c":60.0},
            {"sensor_age_seconds":2.0,"cpu_temp_c":90.0,"gpu_temp_c":61.0}
        ]);
        let verdict = authorize_mind_runtime(&request);
        assert!(!verdict.allowed);
        assert!(verdict
            .reasons
            .iter()
            .any(|reason| reason == "cpu_temperature_at_or_above_limit"));
    }

    #[test]
    fn holds_when_requested_thread_budget_exceeds_four() {
        let mut request = healthy_request();
        request["body_resources"]["requested_threads"] = json!(5);
        let verdict = authorize_mind_runtime(&request);
        assert!(!verdict.allowed);
        assert!(verdict
            .reasons
            .iter()
            .any(|reason| reason == "runtime_thread_budget_exceeded_or_missing"));
    }

    #[test]
    fn holds_when_workspace_disk_has_less_than_two_gibibytes_free() {
        let mut request = healthy_request();
        request["body_resources"]["workspace_disk_free_bytes"] =
            json!(2_u64 * 1024 * 1024 * 1024 - 1);
        let verdict = authorize_mind_runtime(&request);
        assert!(!verdict.allowed);
        assert!(verdict
            .reasons
            .iter()
            .any(|reason| reason == "workspace_disk_below_two_gibibytes_free_or_unavailable"));
    }
}

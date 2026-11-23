use crate::body_authority::MindRuntimeVerdict;
use serde::{Deserialize, Serialize};
use serde_json::Value;

const SCHEMA: &str = "aios_architect_runtime_permission_v1";
const SCOPE: &str = "localcoder_runtime";
const RAM_HOLD: &str = "ram_at_or_above_limit";
const GPU_HOLD: &str = "gpu_memory_at_or_above_limit_or_unavailable";
const RAM_FLOOR_PERCENT: f64 = 95.0;
const RAM_CEILING_PERCENT: f64 = 96.5;
const GPU_FLOOR_PERCENT: f64 = 95.0;
const GPU_OVERRIDE_CEILING_CAP_PERCENT: f64 = 98.0;
const GPU_SENSOR_MAX_AGE_SECONDS: f64 = 5.0;
const MAX_GRANT_TTL_SECONDS: u64 = 4 * 60 * 60;

#[derive(Debug, Clone, Deserialize)]
pub struct ArchitectRuntimePermission {
    pub schema: String,
    pub allow: bool,
    pub grant_id: String,
    pub scope: String,
    pub goal_id: String,
    pub waived_reasons: Vec<String>,
    pub expires_unix: u64,
    #[serde(default)]
    pub gpu_memory_ceiling_percent: Option<f64>,
}

#[derive(Debug, Clone, Serialize)]
pub struct PermissionAudit {
    pub status: String,
    pub grant_id: String,
    pub scope: String,
    pub goal_id: String,
    pub expires_unix: u64,
    pub waived_reasons: Vec<String>,
    pub observed_ram_percent: Option<f64>,
    pub observed_gpu_memory_percent: Option<f64>,
    pub gpu_memory_ceiling_percent: Option<f64>,
    pub observed_gpu_memory_source: Option<String>,
    pub observed_gpu_sensor_age_seconds: Option<f64>,
}

pub fn apply(
    verdict: &mut MindRuntimeVerdict,
    permission: &ArchitectRuntimePermission,
    request: &Value,
    now_unix: u64,
) -> PermissionAudit {
    let observed_ram_percent = request
        .pointer("/body_resources/ram_percent")
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite());
    let observed_gpu_memory_percent = request
        .pointer("/body_resources/gpu_memory_percent")
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite());
    let observed_gpu_memory_source = request
        .pointer("/body_resources/gpu_memory_source")
        .and_then(Value::as_str)
        .map(str::to_string);
    let observed_gpu_sensor_age_seconds = request
        .pointer("/body_resources/sensor_age_seconds")
        .and_then(Value::as_f64)
        .filter(|value| value.is_finite());
    let mut audit = PermissionAudit {
        status: "invalid_permission".to_string(),
        grant_id: permission.grant_id.clone(),
        scope: permission.scope.clone(),
        goal_id: permission.goal_id.clone(),
        expires_unix: permission.expires_unix,
        waived_reasons: Vec::new(),
        observed_ram_percent,
        observed_gpu_memory_percent,
        gpu_memory_ceiling_percent: permission.gpu_memory_ceiling_percent,
        observed_gpu_memory_source: observed_gpu_memory_source.clone(),
        observed_gpu_sensor_age_seconds,
    };

    if permission.schema != SCHEMA
        || permission.grant_id.is_empty()
        || permission.grant_id.len() > 96
        || !permission
            .grant_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
        || permission.goal_id.is_empty()
        || permission.goal_id.len() > 96
        || !permission
            .goal_id
            .bytes()
            .all(|byte| byte.is_ascii_alphanumeric() || byte == b'-')
    {
        return audit;
    }
    if !permission.allow {
        audit.status = "disabled".to_string();
        return audit;
    }
    if permission.scope != SCOPE {
        audit.status = "scope_mismatch".to_string();
        return audit;
    }
    if permission.expires_unix <= now_unix {
        audit.status = "expired".to_string();
        return audit;
    }
    if permission.expires_unix.saturating_sub(now_unix) > MAX_GRANT_TTL_SECONDS {
        audit.status = "grant_ttl_exceeds_limit".to_string();
        return audit;
    }
    if permission.waived_reasons.len() != 1
        || !matches!(permission.waived_reasons[0].as_str(), RAM_HOLD | GPU_HOLD)
    {
        audit.status = "unsupported_waiver".to_string();
        return audit;
    }
    if verdict.reasons.is_empty() {
        audit.status = "not_needed".to_string();
        return audit;
    }
    if verdict.reasons.len() != 1 {
        audit.status = "other_holds_remain".to_string();
        return audit;
    }
    if request.get("goal_id").and_then(Value::as_str) != Some(permission.goal_id.as_str()) {
        audit.status = "goal_mismatch".to_string();
        return audit;
    }
    match (
        verdict.reasons[0].as_str(),
        permission.waived_reasons[0].as_str(),
    ) {
        (RAM_HOLD, RAM_HOLD) => {
            let Some(ram) = observed_ram_percent else {
                audit.status = "ram_measurement_unavailable".to_string();
                return audit;
            };
            if !(RAM_FLOOR_PERCENT..RAM_CEILING_PERCENT).contains(&ram) {
                audit.status = "ram_outside_grant_range".to_string();
                return audit;
            }
        }
        (GPU_HOLD, GPU_HOLD) => {
            let Some(ceiling) = permission.gpu_memory_ceiling_percent else {
                audit.status = "gpu_ceiling_missing".to_string();
                return audit;
            };
            if !ceiling.is_finite()
                || !(GPU_FLOOR_PERCENT..=GPU_OVERRIDE_CEILING_CAP_PERCENT).contains(&ceiling)
            {
                audit.status = "gpu_ceiling_outside_allowed_range".to_string();
                return audit;
            }
            let Some(gpu) = observed_gpu_memory_percent else {
                audit.status = "gpu_measurement_unavailable".to_string();
                return audit;
            };
            if !(GPU_FLOOR_PERCENT..=ceiling).contains(&gpu) {
                audit.status = "gpu_outside_grant_range".to_string();
                return audit;
            }
            if observed_gpu_memory_source.as_deref() != Some("hwinfo") {
                audit.status = "gpu_sensor_source_untrusted".to_string();
                return audit;
            }
            let Some(sensor_age) = observed_gpu_sensor_age_seconds else {
                audit.status = "gpu_sensor_age_unavailable".to_string();
                return audit;
            };
            if !(0.0..=GPU_SENSOR_MAX_AGE_SECONDS).contains(&sensor_age) {
                audit.status = "gpu_sensor_stale".to_string();
                return audit;
            }
        }
        _ => {
            audit.status = "other_holds_remain".to_string();
            return audit;
        }
    }

    verdict.reasons.clear();
    verdict.allowed = true;
    verdict.disposition = "ALLOW_MIND_RUNTIME".to_string();
    audit.status = "applied".to_string();
    audit
        .waived_reasons
        .push(permission.waived_reasons[0].clone());
    audit
}

#[cfg(test)]
mod tests {
    use super::{apply, ArchitectRuntimePermission};
    use crate::body_authority::MindRuntimeVerdict;
    use serde_json::{json, Value};

    const GOAL_ID: &str = "01a1e340-84ed-77c3-92f3-3eb738b89f5b";

    fn grant() -> ArchitectRuntimePermission {
        ArchitectRuntimePermission {
            schema: "aios_architect_runtime_permission_v1".to_string(),
            allow: true,
            grant_id: "architect-test-ram-grant".to_string(),
            scope: "localcoder_runtime".to_string(),
            goal_id: GOAL_ID.to_string(),
            waived_reasons: vec!["ram_at_or_above_limit".to_string()],
            expires_unix: 200,
            gpu_memory_ceiling_percent: None,
        }
    }

    fn gpu_grant() -> ArchitectRuntimePermission {
        ArchitectRuntimePermission {
            schema: "aios_architect_runtime_permission_v1".to_string(),
            allow: true,
            grant_id: "architect-test-gpu-grant".to_string(),
            scope: "localcoder_runtime".to_string(),
            goal_id: GOAL_ID.to_string(),
            waived_reasons: vec!["gpu_memory_at_or_above_limit_or_unavailable".to_string()],
            expires_unix: 200,
            gpu_memory_ceiling_percent: Some(97.6),
        }
    }

    fn held(reasons: Vec<&str>) -> MindRuntimeVerdict {
        MindRuntimeVerdict {
            allowed: false,
            disposition: "HOLD_MIND_RUNTIME".to_string(),
            authority: "deterministic_aios_body_rust".to_string(),
            reasons: reasons.into_iter().map(str::to_string).collect(),
            expected_core_count: 19,
            bound_core_count: 19,
            active_without_health_report: Vec::new(),
            stability_sn: Some(1.0),
            minimum_stability_sn: 0.45,
            requested_threads: Some(2),
        }
    }

    fn request(goal_id: &str, ram_percent: f64) -> Value {
        json!({"goal_id":goal_id,"body_resources":{"ram_percent":ram_percent}})
    }

    fn gpu_request(goal_id: &str, gpu_percent: f64, source: &str, age: f64) -> Value {
        json!({"goal_id":goal_id,"body_resources":{
            "gpu_memory_percent":gpu_percent,
            "gpu_memory_source":source,
            "sensor_age_seconds":age
        }})
    }

    #[test]
    fn active_goal_bound_grant_waives_only_a_ram_hold_below_ceiling() {
        let mut verdict = held(vec!["ram_at_or_above_limit"]);
        let audit = apply(&mut verdict, &grant(), &request(GOAL_ID, 95.4), 100);
        assert!(verdict.allowed);
        assert_eq!(verdict.disposition, "ALLOW_MIND_RUNTIME");
        assert!(verdict.reasons.is_empty());
        assert_eq!(audit.status, "applied");
        assert_eq!(audit.waived_reasons, vec!["ram_at_or_above_limit"]);
        assert_eq!(audit.observed_ram_percent, Some(95.4));
    }

    #[test]
    fn active_goal_bound_gpu_grant_requires_fresh_hwinfo_and_stays_under_its_cap() {
        let mut verdict = held(vec!["gpu_memory_at_or_above_limit_or_unavailable"]);
        let audit = apply(
            &mut verdict,
            &gpu_grant(),
            &gpu_request(GOAL_ID, 97.6, "hwinfo", 1.6),
            100,
        );
        assert!(verdict.allowed);
        assert_eq!(verdict.reasons, Vec::<String>::new());
        assert_eq!(audit.status, "applied");
        assert_eq!(
            audit.waived_reasons,
            vec!["gpu_memory_at_or_above_limit_or_unavailable"]
        );
        assert_eq!(audit.observed_gpu_memory_percent, Some(97.6));
        assert_eq!(audit.gpu_memory_ceiling_percent, Some(97.6));
        assert_eq!(audit.observed_gpu_memory_source.as_deref(), Some("hwinfo"));
        assert_eq!(audit.observed_gpu_sensor_age_seconds, Some(1.6));
    }

    #[test]
    fn gpu_grant_fails_closed_above_cap_without_a_fresh_hwinfo_measurement() {
        for (gpu, source, age, expected_status) in [
            (97.7, "hwinfo", 1.0, "gpu_outside_grant_range"),
            (97.0, "nvidia-smi", 1.0, "gpu_sensor_source_untrusted"),
            (97.0, "hwinfo", 5.1, "gpu_sensor_stale"),
        ] {
            let mut verdict = held(vec!["gpu_memory_at_or_above_limit_or_unavailable"]);
            let audit = apply(
                &mut verdict,
                &gpu_grant(),
                &gpu_request(GOAL_ID, gpu, source, age),
                100,
            );
            assert!(!verdict.allowed);
            assert_eq!(audit.status, expected_status);
        }

        let mut missing = held(vec!["gpu_memory_at_or_above_limit_or_unavailable"]);
        let audit = apply(
            &mut missing,
            &gpu_grant(),
            &json!({"goal_id":GOAL_ID,"body_resources":{"gpu_memory_source":"hwinfo","sensor_age_seconds":1.0}}),
            100,
        );
        assert!(!missing.allowed);
        assert_eq!(audit.status, "gpu_measurement_unavailable");
    }

    #[test]
    fn mixed_or_non_ram_holds_are_never_overridden() {
        for reasons in [
            vec!["ram_at_or_above_limit", "cpu_temperature_at_or_above_limit"],
            vec!["gpu_memory_at_or_above_limit_or_unavailable"],
        ] {
            let mut verdict = held(reasons.clone());
            let audit = apply(&mut verdict, &grant(), &request(GOAL_ID, 95.4), 100);
            assert!(!verdict.allowed);
            assert_eq!(verdict.reasons.len(), reasons.len());
            assert_eq!(audit.status, "other_holds_remain");
            assert!(audit.waived_reasons.is_empty());
        }
    }

    #[test]
    fn goal_mismatch_wrong_reason_and_invalid_measurements_fail_closed() {
        let mut wrong_goal_verdict = held(vec!["ram_at_or_above_limit"]);
        let wrong_goal = apply(
            &mut wrong_goal_verdict,
            &grant(),
            &request("other-goal", 95.4),
            100,
        );
        assert!(!wrong_goal_verdict.allowed);
        assert_eq!(wrong_goal.status, "goal_mismatch");

        let mut unsupported = grant();
        unsupported.waived_reasons = vec!["cpu_temperature_at_or_above_limit".to_string()];
        let mut unsupported_verdict = held(vec!["gpu_memory_at_or_above_limit_or_unavailable"]);
        let audit = apply(
            &mut unsupported_verdict,
            &unsupported,
            &request(GOAL_ID, 95.4),
            100,
        );
        assert!(!unsupported_verdict.allowed);
        assert_eq!(audit.status, "unsupported_waiver");

        for ram in [94.9, 96.5, 97.0] {
            let mut verdict = held(vec!["ram_at_or_above_limit"]);
            let audit = apply(&mut verdict, &grant(), &request(GOAL_ID, ram), 100);
            assert!(!verdict.allowed);
            assert_eq!(audit.status, "ram_outside_grant_range");
        }

        let mut missing = held(vec!["ram_at_or_above_limit"]);
        let audit = apply(&mut missing, &grant(), &json!({"goal_id":GOAL_ID}), 100);
        assert!(!missing.allowed);
        assert_eq!(audit.status, "ram_measurement_unavailable");
    }

    #[test]
    fn disabled_expired_and_overlong_grants_fail_closed() {
        let mut expired_verdict = held(vec!["ram_at_or_above_limit"]);
        let expired = apply(&mut expired_verdict, &grant(), &request(GOAL_ID, 95.4), 200);
        assert!(!expired_verdict.allowed);
        assert_eq!(expired.status, "expired");

        let mut disabled_verdict = held(vec!["ram_at_or_above_limit"]);
        let mut disabled_grant = grant();
        disabled_grant.allow = false;
        let disabled = apply(
            &mut disabled_verdict,
            &disabled_grant,
            &request(GOAL_ID, 95.4),
            100,
        );
        assert!(!disabled_verdict.allowed);
        assert_eq!(disabled.status, "disabled");

        let mut overlong_verdict = held(vec!["ram_at_or_above_limit"]);
        let mut overlong_grant = grant();
        overlong_grant.expires_unix = 100 + 4 * 60 * 60 + 1;
        let overlong = apply(
            &mut overlong_verdict,
            &overlong_grant,
            &request(GOAL_ID, 95.4),
            100,
        );
        assert!(!overlong_verdict.allowed);
        assert_eq!(overlong.status, "grant_ttl_exceeds_limit");
    }
}

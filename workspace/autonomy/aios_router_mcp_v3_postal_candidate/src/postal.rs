//! Persistent, encrypted Hive postal records layered onto the existing task router.
//!
//! Message bodies are encrypted before SQLite insertion. The append-only event
//! chain contains hashes and routing metadata only. Role proof is supplied by
//! the OpenCode host gate in `postal_actor` on the fresh Body receipt.

use super::{
    Event, Receipt, Router, Task, hex, parse_utc_millis, valid_agent_id, valid_hash, valid_id,
    valid_privacy_decision,
};
use aes_gcm::{
    Aes256Gcm, Nonce,
    aead::{Aead, KeyInit, Payload},
};
use rand::{RngCore, rngs::OsRng};
use rusqlite::{Connection, OptionalExtension, TransactionBehavior, params};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    fs::{self, File, OpenOptions},
    io::{Read, Write},
    path::{Path, PathBuf},
    time::{SystemTime, UNIX_EPOCH},
};

const MAX_BODY_BYTES: usize = 65_536;
const MAX_INBOX_READ: usize = 4;
const POSTAL_EVENT_SCHEMA: &str = "hive_postal_event_v1";
const OUTBOX_ROLE: &str = "queen";

struct MasterKey([u8; 32]);
impl Drop for MasterKey {
    fn drop(&mut self) {
        self.0.fill(0);
    }
}

#[derive(Clone)]
struct SealedBody {
    nonce: Vec<u8>,
    ciphertext: Vec<u8>,
    key_nonce: Vec<u8>,
    wrapped_key: Vec<u8>,
}

#[derive(Clone, Debug)]
struct PostalEvent {
    seq: i64,
    kind: String,
    message_id: String,
    task_id: String,
    lane_id: String,
    turn: Option<u32>,
    sender_id: String,
    recipient_id: String,
    body_sha256: String,
    reason_code: String,
    previous_hash: String,
    event_hash: String,
    session_id: String,
    assignment_hash: String,
    receipt_ref: String,
}

fn sha(bytes: &[u8]) -> String {
    hex(&Sha256::digest(bytes))
}

fn random<const N: usize>() -> Result<[u8; N], String> {
    let mut bytes = [0_u8; N];
    OsRng
        .try_fill_bytes(&mut bytes)
        .map_err(|e| format!("OS_CSPRNG_unavailable:{e}"))?;
    Ok(bytes)
}

fn random_id(prefix: &str) -> Result<String, String> {
    Ok(format!("{prefix}{}", hex(&random::<16>()?)))
}

fn now_millis() -> Result<i64, String> {
    Ok(SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| "system_clock_before_unix_epoch")?
        .as_millis() as i64)
}

fn key_path(key_dir: &Path) -> PathBuf {
    key_dir.join("postal.master-key-v1")
}

fn read_master_key(path: &Path) -> Result<MasterKey, String> {
    let metadata =
        fs::symlink_metadata(path).map_err(|e| format!("master_key_metadata_unavailable:{e}"))?;
    if !metadata.is_file() || metadata.file_type().is_symlink() || metadata.len() != 32 {
        return Err("master_key_file_invalid".into());
    }
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        if metadata.permissions().mode() & 0o077 != 0 {
            return Err("master_key_permissions_must_be_0600".into());
        }
    }
    let mut file = File::open(path).map_err(|e| format!("master_key_open_failed:{e}"))?;
    let mut bytes = [0_u8; 32];
    file.read_exact(&mut bytes)
        .map_err(|e| format!("master_key_read_failed:{e}"))?;
    Ok(MasterKey(bytes))
}

fn load_or_create_master_key(key_dir: &Path) -> Result<MasterKey, String> {
    fs::create_dir_all(key_dir).map_err(|e| format!("master_key_directory_unavailable:{e}"))?;
    let path = key_path(key_dir);
    if path.exists() {
        return read_master_key(&path);
    }
    let mut bytes = random::<32>()?;
    let mut options = OpenOptions::new();
    options.write(true).create_new(true);
    #[cfg(unix)]
    {
        use std::os::unix::fs::OpenOptionsExt;
        options.mode(0o600);
    }
    match options.open(&path) {
        Ok(mut file) => {
            let write_result = file.write_all(&bytes).and_then(|_| file.sync_all());
            bytes.fill(0);
            write_result.map_err(|e| format!("master_key_persist_failed:{e}"))?;
            read_master_key(&path)
        }
        Err(e) if e.kind() == std::io::ErrorKind::AlreadyExists => {
            bytes.fill(0);
            read_master_key(&path)
        }
        Err(e) => {
            bytes.fill(0);
            Err(format!("master_key_create_failed:{e}"))
        }
    }
}

fn aad(
    message_id: &str,
    purpose: &str,
    task_id: &str,
    lane_id: &str,
    turn: u32,
    sender_id: &str,
    recipient_id: &str,
    reply_to: &str,
) -> Vec<u8> {
    format!("hive-postal-v1\n{purpose}\n{message_id}\n{task_id}\n{lane_id}\n{turn}\n{sender_id}\n{recipient_id}\n{reply_to}").into_bytes()
}

fn seal(
    master: &MasterKey,
    message_id: &str,
    purpose: &str,
    associated: &[u8],
    body: &[u8],
) -> Result<SealedBody, String> {
    if body.len() > MAX_BODY_BYTES {
        return Err("message_body_over_65536_bytes".into());
    }
    let mut content_key = random::<32>()?;
    let body_nonce = random::<12>()?;
    let wrap_nonce = random::<12>()?;
    let body_cipher = Aes256Gcm::new_from_slice(&content_key).map_err(|_| "content_key_invalid")?;
    let ciphertext = body_cipher
        .encrypt(
            Nonce::from_slice(&body_nonce),
            Payload {
                msg: body,
                aad: associated,
            },
        )
        .map_err(|_| "message_encryption_failed")?;
    let master_cipher = Aes256Gcm::new_from_slice(&master.0).map_err(|_| "master_key_invalid")?;
    let wrap_aad = format!("hive-postal-wrap-v1\n{purpose}\n{message_id}");
    let wrapped_key = master_cipher
        .encrypt(
            Nonce::from_slice(&wrap_nonce),
            Payload {
                msg: &content_key,
                aad: wrap_aad.as_bytes(),
            },
        )
        .map_err(|_| "content_key_wrap_failed")?;
    content_key.fill(0);
    Ok(SealedBody {
        nonce: body_nonce.to_vec(),
        ciphertext,
        key_nonce: wrap_nonce.to_vec(),
        wrapped_key,
    })
}

fn open_sealed(
    master: &MasterKey,
    message_id: &str,
    purpose: &str,
    associated: &[u8],
    body_nonce: &[u8],
    ciphertext: &[u8],
    key_nonce: &[u8],
    wrapped_key: &[u8],
    expected_sha256: &str,
) -> Result<String, String> {
    if body_nonce.len() != 12 || key_nonce.len() != 12 {
        return Err("postal_nonce_invalid".into());
    }
    let master_cipher = Aes256Gcm::new_from_slice(&master.0).map_err(|_| "master_key_invalid")?;
    let wrap_aad = format!("hive-postal-wrap-v1\n{purpose}\n{message_id}");
    let mut content_key = master_cipher
        .decrypt(
            Nonce::from_slice(key_nonce),
            Payload {
                msg: wrapped_key,
                aad: wrap_aad.as_bytes(),
            },
        )
        .map_err(|_| "content_key_unwrap_failed")?;
    if content_key.len() != 32 {
        content_key.fill(0);
        return Err("content_key_length_invalid".into());
    }
    let body_cipher = Aes256Gcm::new_from_slice(&content_key).map_err(|_| "content_key_invalid")?;
    let plaintext = body_cipher
        .decrypt(
            Nonce::from_slice(body_nonce),
            Payload {
                msg: ciphertext,
                aad: associated,
            },
        )
        .map_err(|_| "message_authentication_failed")?;
    content_key.fill(0);
    if sha(&plaintext) != expected_sha256 {
        return Err("message_plaintext_hash_mismatch".into());
    }
    String::from_utf8(plaintext).map_err(|_| "message_body_not_utf8".into())
}

fn privacy_target_paths(target: &str) -> [String; 4] {
    [
        target.to_owned(),
        format!("{target}-wal"),
        format!("{target}-shm"),
        format!("{target}-journal"),
    ]
}

fn valid_actor(v: &Value, role: &str, actor_id: &str) -> bool {
    v.get("postal_actor").is_some_and(|a| {
        a.get("role").and_then(Value::as_str) == Some(role)
            && a.get("agent_id").and_then(Value::as_str) == Some(actor_id)
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const TARGET: &str = r"L:\LocalCoder\workspace\aios_rebuild\memory\aios_router\router.sqlite3";

    struct TestTree(PathBuf);
    impl Drop for TestTree {
        fn drop(&mut self) {
            let _ = fs::remove_dir_all(&self.0);
        }
    }

    fn iso_now() -> String {
        let millis = now_millis().unwrap();
        let seconds = millis.div_euclid(1000);
        let ms = millis.rem_euclid(1000);
        let days = seconds.div_euclid(86_400);
        let day_seconds = seconds.rem_euclid(86_400);
        let z = days + 719_468;
        let era = z.div_euclid(146_097);
        let doe = z - era * 146_097;
        let yoe = (doe - doe / 1_460 + doe / 36_524 - doe / 146_096) / 365;
        let mut year = yoe + era * 400;
        let doy = doe - (365 * yoe + yoe / 4 - yoe / 100);
        let mp = (5 * doy + 2) / 153;
        let day = doy - (153 * mp + 2) / 5 + 1;
        let month = mp + if mp < 10 { 3 } else { -9 };
        year += if month <= 2 { 1 } else { 0 };
        let hour = day_seconds / 3_600;
        let minute = (day_seconds % 3_600) / 60;
        let second = day_seconds % 60;
        format!("{year:04}-{month:02}-{day:02}T{hour:02}:{minute:02}:{second:02}.{ms:03}Z")
    }

    fn write_receipt(
        router: &Router,
        source: &str,
        session: &str,
        role: Option<&str>,
        actor_id: Option<&str>,
    ) {
        fs::create_dir_all(&router.receipt_dir).unwrap();
        let checked = privacy_target_paths(&router.privacy_target_path)
            .into_iter()
            .map(|path| {
                json!({
                    "path":path,"allowed":true,"reason":"file_write_policy_passed"
                })
            })
            .collect::<Vec<_>>();
        let mut value = json!({
            "schema":"opencode_body_gate_receipt_v1",
            "source":source,
            "session_id":session,
            "authority":"deterministic_aios_body_rust",
            "disposition":"ALLOW_MIND_RUNTIME",
            "allowed":true,
            "captured_at":iso_now(),
            "privacy_core":{
                "schema":"privacy_core_file_write_decision_v1",
                "authority":"PrivacyCore.authorize_file_write",
                "target_path":router.privacy_target_path,
                "allowed":true,
                "reason":"file_write_policy_passed",
                "checked_paths":checked
            }
        });
        if let (Some(role), Some(actor_id)) = (role, actor_id) {
            value["postal_actor"] = json!({"role":role,"agent_id":actor_id});
        }
        let path = router.receipt_dir.join(format!(
            "test-{}-body-gate.json",
            hex(&random::<8>().unwrap())
        ));
        fs::write(path, serde_json::to_vec(&value).unwrap()).unwrap();
    }

    fn task_and_drone() -> (TestTree, Router, String, String, String, String, String) {
        let base =
            std::env::temp_dir().join(format!("aios-postal-v3-{}", hex(&random::<12>().unwrap())));
        fs::create_dir_all(&base).unwrap();
        let tree = TestTree(base.clone());
        let receipts = base.join("receipts");
        fs::create_dir_all(&receipts).unwrap();
        let router = Router::new(
            base.join("router.sqlite3"),
            receipts,
            TARGET.into(),
            base.join("keys"),
        );
        let session = "postal-test-session".to_string();
        let task_id = "postal-test-task".to_string();
        let agent_id = "localcoder-viv-drone-01".to_string();
        let assignment = "Bounded postal integration test\nAcceptance JSON: {\"version\":1,\"kind\":\"control_plane\"}".to_string();
        let assignment_hash = sha(assignment.as_bytes());
        write_receipt(
            &router,
            "tool:aios_router_open_build_task",
            &session,
            None,
            None,
        );
        router
            .open_build(
                &session,
                &task_id,
                &assignment_hash,
                &assignment,
                &["drone".into()],
                2,
            )
            .unwrap();
        write_receipt(
            &router,
            "tool:aios_router_assign_drone_seed",
            &session,
            None,
            None,
        );
        router
            .assign_drone_seed(&session, &task_id, &assignment_hash, &agent_id)
            .unwrap();
        write_receipt(
            &router,
            "tool:aios_router_postal_register_drone",
            &session,
            Some("drone"),
            Some(&agent_id),
        );
        let registration = router
            .postal_register_drone(&session, &task_id, &assignment_hash, &agent_id)
            .unwrap();
        let inbox_id = registration["inbox_id"].as_str().unwrap().to_string();
        (
            tree,
            router,
            session,
            task_id,
            assignment_hash,
            agent_id,
            inbox_id,
        )
    }

    fn accept_turn(router: &Router, session: &str, task: &str, assignment_hash: &str, turn: u32) {
        write_receipt(
            router,
            "tool:aios_router_accept_self_prompt",
            session,
            None,
            None,
        );
        router
            .accept_prompt(
                session,
                task,
                assignment_hash,
                "drone",
                turn,
                &format!("inspect inbox for turn {turn}"),
            )
            .unwrap();
    }

    fn queen_dispatch(
        router: &Router,
        session: &str,
        task: &str,
        assignment_hash: &str,
        source: &str,
        agent: &str,
        inbox: &str,
        body: &str,
    ) -> Value {
        write_receipt(
            router,
            "tool:aios_router_postal_queen_dispatch",
            session,
            Some("queen"),
            Some("queen"),
        );
        router
            .postal_queen_dispatch(session, task, assignment_hash, source, agent, inbox, body)
            .unwrap()
    }

    #[test]
    fn encrypted_queen_roundtrip_bounces_bad_handshake_and_chains_two_bounded_turns() {
        let (_tree, router, session, task, assignment_hash, agent_id, inbox_id) = task_and_drone();

        accept_turn(&router, &session, &task, &assignment_hash, 0);
        write_receipt(
            &router,
            "tool:aios_router_postal_drone_submit",
            &session,
            Some("drone"),
            Some(&agent_id),
        );
        let submitted = router
            .postal_drone_submit(
                &session,
                &task,
                &assignment_hash,
                "drone",
                0,
                &agent_id,
                None,
                "[DRONE] bounded build report",
            )
            .unwrap();
        let first_id = submitted["message_id"].as_str().unwrap().to_string();

        write_receipt(
            &router,
            "tool:aios_router_postal_queen_list_outbox",
            &session,
            Some("queen"),
            Some("queen"),
        );
        let queue = router
            .postal_queen_list_outbox(&session, &task, &assignment_hash)
            .unwrap();
        assert_eq!(queue["count"], 1);
        assert_eq!(queue["messages"][0]["delivered"], false);
        assert_eq!(
            queue["messages"][0]["body_sha256"],
            submitted["body_sha256"]
        );

        write_receipt(
            &router,
            "tool:aios_router_postal_queen_read_outbox",
            &session,
            Some("queen"),
            Some("queen"),
        );
        let read = router
            .postal_queen_read_outbox(&session, &task, &assignment_hash, &first_id)
            .unwrap();
        assert_eq!(read["body"], "[DRONE] bounded build report");
        assert_eq!(read["verified_aead"], true);

        let delivered = queen_dispatch(
            &router,
            &session,
            &task,
            &assignment_hash,
            &first_id,
            &agent_id,
            &inbox_id,
            "[QUEEN] continue with the next bounded step",
        );
        assert_eq!(delivered["status"], "delivered");
        let first_reply_id = delivered["message_id"].as_str().unwrap().to_string();

        write_receipt(
            &router,
            "tool:aios_router_postal_drone_read_inbox",
            &session,
            Some("drone"),
            Some(&agent_id),
        );
        let inbox = router
            .postal_drone_read_inbox(&session, &task, &assignment_hash, &agent_id, 4)
            .unwrap();
        assert_eq!(inbox["count"], 1);
        assert_eq!(
            inbox["messages"][0]["body"],
            "[QUEEN] continue with the next bounded step"
        );

        accept_turn(&router, &session, &task, &assignment_hash, 1);
        write_receipt(
            &router,
            "tool:aios_router_postal_drone_submit",
            &session,
            Some("drone"),
            Some(&agent_id),
        );
        let second = router
            .postal_drone_submit(
                &session,
                &task,
                &assignment_hash,
                "drone",
                1,
                &agent_id,
                Some(&first_reply_id),
                "[DRONE] second bounded report",
            )
            .unwrap();
        assert_eq!(second["turn_result_recorded"], true);

        write_receipt(
            &router,
            "tool:aios_router_postal_queen_read_outbox",
            &session,
            Some("queen"),
            Some("queen"),
        );
        router
            .postal_queen_read_outbox(
                &session,
                &task,
                &assignment_hash,
                second["message_id"].as_str().unwrap(),
            )
            .unwrap();

        let bounced = queen_dispatch(
            &router,
            &session,
            &task,
            &assignment_hash,
            second["message_id"].as_str().unwrap(),
            &agent_id,
            &format!("inbox_{}", "0".repeat(64)),
            "[QUEEN] response",
        );
        assert_eq!(bounced["status"], "bounced");
        assert_eq!(bounced["reason_code"], "inbox_handshake_mismatch");
        let retried = queen_dispatch(
            &router,
            &session,
            &task,
            &assignment_hash,
            second["message_id"].as_str().unwrap(),
            &agent_id,
            &inbox_id,
            "[QUEEN] route corrected after bounce",
        );
        assert_eq!(retried["status"], "delivered");

        write_receipt(
            &router,
            "tool:aios_router_postal_drone_read_inbox",
            &session,
            Some("drone"),
            Some(&agent_id),
        );
        let inbox = router
            .postal_drone_read_inbox(&session, &task, &assignment_hash, &agent_id, 4)
            .unwrap();
        assert!(inbox["messages"].as_array().unwrap().iter().any(|m| {
            if m["kind"] != "bounce" {
                return false;
            }
            m["body"]
                .as_str()
                .and_then(|body| serde_json::from_str::<Value>(body).ok())
                .is_some_and(|body| body["reason_code"] == "inbox_handshake_mismatch")
        }));
        assert!(
            inbox["messages"]
                .as_array()
                .unwrap()
                .iter()
                .any(|m| m["body"] == "[QUEEN] route corrected after bounce")
        );

        write_receipt(
            &router,
            "tool:aios_router_complete_lane",
            &session,
            None,
            None,
        );
        router
            .finish_lane(
                &session,
                &task,
                &assignment_hash,
                "drone",
                "two bounded turns verified",
            )
            .unwrap();
        write_receipt(
            &router,
            "tool:aios_router_postal_queen_summary",
            &session,
            Some("queen"),
            Some("queen"),
        );
        let summary = router
            .postal_queen_summary(&session, &task, &assignment_hash)
            .unwrap();
        assert_eq!(summary["state"], "completed");
        assert_eq!(summary["outbox_messages"], 2);
        assert_eq!(summary["delivered_messages"], 2);
        assert_eq!(summary["bounce_messages"], 1);

        let c = router.readonly().unwrap();
        assert_eq!(
            Router::postal_events(&c).unwrap().last().unwrap().kind,
            "queen_summary"
        );
        let rows: i64 = c
            .query_row(
                "SELECT COUNT(*) FROM postal_outbox WHERE task_id=?1",
                params![task],
                |r| r.get(0),
            )
            .unwrap();
        assert_eq!(rows, 2);
    }

    #[test]
    fn sealed_message_rejects_ciphertext_tampering() {
        let master = MasterKey(random::<32>().unwrap());
        let associated = aad(
            "msg_test",
            "queen-outbox",
            "task",
            "lane",
            1,
            "drone",
            "queen",
            "",
        );
        let sealed = seal(
            &master,
            "msg_test",
            "queen-outbox",
            &associated,
            b"sealed body",
        )
        .unwrap();
        let body = open_sealed(
            &master,
            "msg_test",
            "queen-outbox",
            &associated,
            &sealed.nonce,
            &sealed.ciphertext,
            &sealed.key_nonce,
            &sealed.wrapped_key,
            &sha(b"sealed body"),
        )
        .unwrap();
        assert_eq!(body, "sealed body");
        let mut tampered = sealed.ciphertext.clone();
        tampered[0] ^= 1;
        assert!(
            open_sealed(
                &master,
                "msg_test",
                "queen-outbox",
                &associated,
                &sealed.nonce,
                &tampered,
                &sealed.key_nonce,
                &sealed.wrapped_key,
                &sha(b"sealed body")
            )
            .is_err()
        );
    }
}

impl Router {
    fn postal_schema(c: &Connection) -> Result<(), String> {
        c.execute_batch(
            "CREATE TABLE IF NOT EXISTS postal_drone_identity(
                agent_id TEXT PRIMARY KEY NOT NULL,
                inbox_id TEXT NOT NULL UNIQUE,
                seed INTEGER NOT NULL UNIQUE CHECK(seed BETWEEN 1 AND 2147483647),
                receipt_ref TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                assignment_hash TEXT NOT NULL,
                created_at_ms INTEGER NOT NULL
             );
             CREATE TRIGGER IF NOT EXISTS postal_drone_identity_no_update BEFORE UPDATE ON postal_drone_identity BEGIN SELECT RAISE(ABORT,'append-only postal identities'); END;
             CREATE TRIGGER IF NOT EXISTS postal_drone_identity_no_delete BEFORE DELETE ON postal_drone_identity BEGIN SELECT RAISE(ABORT,'append-only postal identities'); END;
             CREATE TABLE IF NOT EXISTS postal_outbox(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL UNIQUE,
                task_id TEXT NOT NULL,
                lane_id TEXT NOT NULL,
                turn INTEGER NOT NULL CHECK(turn BETWEEN 0 AND 31),
                sender_id TEXT NOT NULL,
                recipient_role TEXT NOT NULL CHECK(recipient_role='queen'),
                reply_to TEXT,
                body_sha256 TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL,
                key_nonce BLOB NOT NULL,
                wrapped_key BLOB NOT NULL,
                created_at_ms INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                assignment_hash TEXT NOT NULL,
                receipt_ref TEXT NOT NULL UNIQUE,
                UNIQUE(task_id,lane_id,turn)
             );
             CREATE TRIGGER IF NOT EXISTS postal_outbox_no_update BEFORE UPDATE ON postal_outbox BEGIN SELECT RAISE(ABORT,'append-only postal outbox'); END;
             CREATE TRIGGER IF NOT EXISTS postal_outbox_no_delete BEFORE DELETE ON postal_outbox BEGIN SELECT RAISE(ABORT,'append-only postal outbox'); END;
             CREATE TABLE IF NOT EXISTS postal_drone_inbox(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id TEXT NOT NULL UNIQUE,
                source_message_id TEXT NOT NULL,
                message_kind TEXT NOT NULL CHECK(message_kind IN ('queen_message','bounce')),
                task_id TEXT NOT NULL,
                lane_id TEXT NOT NULL,
                turn INTEGER NOT NULL CHECK(turn BETWEEN 0 AND 31),
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                recipient_inbox_id TEXT NOT NULL,
                reply_to TEXT NOT NULL,
                body_sha256 TEXT NOT NULL,
                nonce BLOB NOT NULL,
                ciphertext BLOB NOT NULL,
                key_nonce BLOB NOT NULL,
                wrapped_key BLOB NOT NULL,
                created_at_ms INTEGER NOT NULL,
                session_id TEXT NOT NULL,
                assignment_hash TEXT NOT NULL,
                receipt_ref TEXT NOT NULL UNIQUE
             );
             CREATE UNIQUE INDEX IF NOT EXISTS postal_one_delivery_per_source ON postal_drone_inbox(source_message_id) WHERE message_kind='queen_message';
             CREATE TRIGGER IF NOT EXISTS postal_drone_inbox_no_update BEFORE UPDATE ON postal_drone_inbox BEGIN SELECT RAISE(ABORT,'append-only postal inbox'); END;
             CREATE TRIGGER IF NOT EXISTS postal_drone_inbox_no_delete BEFORE DELETE ON postal_drone_inbox BEGIN SELECT RAISE(ABORT,'append-only postal inbox'); END;
             CREATE TABLE IF NOT EXISTS postal_event(
                seq INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                message_id TEXT NOT NULL,
                task_id TEXT NOT NULL,
                lane_id TEXT NOT NULL,
                turn INTEGER,
                sender_id TEXT NOT NULL,
                recipient_id TEXT NOT NULL,
                body_sha256 TEXT NOT NULL,
                reason_code TEXT NOT NULL,
                previous_hash TEXT NOT NULL,
                event_hash TEXT NOT NULL UNIQUE,
                session_id TEXT NOT NULL,
                assignment_hash TEXT NOT NULL,
                receipt_ref TEXT NOT NULL UNIQUE
             );
             CREATE TRIGGER IF NOT EXISTS postal_event_no_update BEFORE UPDATE ON postal_event BEGIN SELECT RAISE(ABORT,'append-only postal event log'); END;
             CREATE TRIGGER IF NOT EXISTS postal_event_no_delete BEFORE DELETE ON postal_event BEGIN SELECT RAISE(ABORT,'append-only postal event log'); END;"
        ).map_err(|e| format!("postal_schema_unavailable:{e}"))
    }

    fn postal_receipt(
        &self,
        source: &str,
        session: &str,
        role: &str,
        actor_id: &str,
    ) -> Result<Receipt, String> {
        if session.is_empty() || session.len() > 160 || !valid_agent_id(actor_id) {
            return Err("invalid_postal_actor_or_session".into());
        }
        let expected_paths = privacy_target_paths(&self.privacy_target_path);
        let entries =
            fs::read_dir(&self.receipt_dir).map_err(|_| "Body receipt directory unavailable")?;
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .map_err(|_| "system clock is before Unix epoch")?
            .as_millis() as i128;
        let mut best: Option<(i128, String)> = None;
        for entry in entries {
            let path = entry
                .map_err(|_| "Body receipt directory unreadable")?
                .path();
            if !path
                .file_name()
                .and_then(|x| x.to_str())
                .is_some_and(|name| name.ends_with("-body-gate.json"))
            {
                continue;
            }
            let metadata =
                fs::symlink_metadata(&path).map_err(|_| "Body receipt metadata unavailable")?;
            if !metadata.is_file()
                || metadata.file_type().is_symlink()
                || metadata.len() > 16 * 1024
            {
                continue;
            }
            let bytes = fs::read(&path).map_err(|_| "Body receipt unreadable")?;
            let Ok(value) = serde_json::from_slice::<Value>(&bytes) else {
                continue;
            };
            if value.get("schema").and_then(Value::as_str) != Some("opencode_body_gate_receipt_v1")
                || value.get("source").and_then(Value::as_str) != Some(source)
                || value.get("session_id").and_then(Value::as_str) != Some(session)
                || value.get("allowed").and_then(Value::as_bool) != Some(true)
                || value.get("disposition").and_then(Value::as_str) != Some("ALLOW_MIND_RUNTIME")
                || value.get("authority").and_then(Value::as_str)
                    != Some("deterministic_aios_body_rust")
                || !valid_actor(&value, role, actor_id)
                || !value
                    .get("privacy_core")
                    .is_some_and(|p| valid_privacy_decision(p, &self.privacy_target_path))
            {
                continue;
            }
            let paths_ok = value
                .get("privacy_core")
                .and_then(|p| p.get("checked_paths"))
                .and_then(Value::as_array)
                .is_some_and(|paths| {
                    paths.len() == 4
                        && paths
                            .iter()
                            .zip(expected_paths.iter())
                            .all(|(entry, expected)| {
                                entry.get("path").and_then(Value::as_str) == Some(expected.as_str())
                                    && entry.get("allowed").and_then(Value::as_bool) == Some(true)
                                    && entry.get("reason").and_then(Value::as_str)
                                        == Some("file_write_policy_passed")
                            })
                });
            if !paths_ok {
                continue;
            }
            let Some(timestamp) = value
                .get("captured_at")
                .and_then(Value::as_str)
                .and_then(parse_utc_millis)
            else {
                continue;
            };
            let age = now - timestamp;
            if age < 0 || age >= 15_000 {
                continue;
            }
            let id = path
                .file_name()
                .and_then(|x| x.to_str())
                .unwrap_or_default()
                .to_owned();
            if best.as_ref().is_none_or(|(old, _)| timestamp > *old) {
                best = Some((timestamp, id));
            }
        }
        best.map(|(_, id)| Receipt { id }).ok_or_else(|| {
            format!(
                "no fresh Body, PrivacyCore, and postal actor receipt for {source} and this session"
            )
        })
    }

    fn postal_events(c: &Connection) -> Result<Vec<PostalEvent>, String> {
        let mut q = c.prepare("SELECT seq,kind,message_id,task_id,lane_id,turn,sender_id,recipient_id,body_sha256,reason_code,previous_hash,event_hash,session_id,assignment_hash,receipt_ref FROM postal_event ORDER BY seq")
            .map_err(|e| format!("postal_event_log_unavailable:{e}"))?;
        let rows = q
            .query_map([], |r| {
                Ok(PostalEvent {
                    seq: r.get(0)?,
                    kind: r.get(1)?,
                    message_id: r.get(2)?,
                    task_id: r.get(3)?,
                    lane_id: r.get(4)?,
                    turn: r.get(5)?,
                    sender_id: r.get(6)?,
                    recipient_id: r.get(7)?,
                    body_sha256: r.get(8)?,
                    reason_code: r.get(9)?,
                    previous_hash: r.get(10)?,
                    event_hash: r.get(11)?,
                    session_id: r.get(12)?,
                    assignment_hash: r.get(13)?,
                    receipt_ref: r.get(14)?,
                })
            })
            .map_err(|e| e.to_string())?;
        let mut events = Vec::new();
        let mut previous = String::new();
        for row in rows {
            let event = row.map_err(|e| e.to_string())?;
            let body = postal_event_body(&event);
            let expected = sha(format!("{previous}\n{body}").as_bytes());
            if event.previous_hash != previous || event.event_hash != expected {
                return Err(format!(
                    "postal_event_chain_integrity_failure_at_sequence_{}",
                    event.seq
                ));
            }
            previous = event.event_hash.clone();
            events.push(event);
        }
        Ok(events)
    }

    fn receipt_used(c: &Connection, receipt_id: &str) -> Result<bool, String> {
        c.query_row(
            "SELECT EXISTS(SELECT 1 FROM router_event WHERE receipt_id=?1) OR EXISTS(SELECT 1 FROM drone_identity_seed WHERE receipt_id=?1) OR EXISTS(SELECT 1 FROM postal_event WHERE receipt_ref=?1)",
            params![receipt_id], |row| row.get(0),
        ).map_err(|e| format!("postal_receipt_index_unavailable:{e}"))
    }

    fn append_postal_event(c: &Connection, event: &PostalEvent) -> Result<i64, String> {
        let previous: String = c
            .query_row(
                "SELECT event_hash FROM postal_event ORDER BY seq DESC LIMIT 1",
                [],
                |r| r.get(0),
            )
            .optional()
            .map_err(|e| e.to_string())?
            .unwrap_or_default();
        let seq: i64 = c
            .query_row("SELECT COALESCE(MAX(seq),0)+1 FROM postal_event", [], |r| {
                r.get(0)
            })
            .map_err(|e| e.to_string())?;
        let mut next = event.clone();
        next.seq = seq;
        next.previous_hash = previous.clone();
        next.event_hash.clear();
        next.event_hash = sha(format!("{previous}\n{}", postal_event_body(&next)).as_bytes());
        c.execute("INSERT INTO postal_event(kind,message_id,task_id,lane_id,turn,sender_id,recipient_id,body_sha256,reason_code,previous_hash,event_hash,session_id,assignment_hash,receipt_ref) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11,?12,?13,?14)",
            params![next.kind,next.message_id,next.task_id,next.lane_id,next.turn,next.sender_id,next.recipient_id,next.body_sha256,next.reason_code,next.previous_hash,next.event_hash,next.session_id,next.assignment_hash,next.receipt_ref])
            .map_err(|e| format!("postal_event_append_failed:{e}"))?;
        Ok(seq)
    }

    fn authorized_postal_write<T, F>(
        &self,
        source: &str,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
        actor_role: &str,
        actor_id: &str,
        attempt_hash: &str,
        op: F,
    ) -> Result<T, String>
    where
        F: FnOnce(&Connection, &str) -> Result<T, String>,
    {
        let receipt = self.postal_receipt(source, session, actor_role, actor_id)?;
        let mut connection = self.writable()?;
        Self::postal_schema(&connection)?;
        Self::postal_events(&connection)?;
        let mut tx = connection
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|e| format!("postal_transaction_unavailable:{e}"))?;
        if Self::receipt_used(&tx, &receipt.id)? {
            return Err("Body receipt already consumed".into());
        }
        let result = {
            let mut savepoint = tx
                .savepoint()
                .map_err(|e| format!("postal_savepoint_unavailable:{e}"))?;
            let result = op(&savepoint, &receipt.id);
            match result {
                Ok(value) => {
                    savepoint
                        .commit()
                        .map_err(|e| format!("postal_savepoint_commit_failed:{e}"))?;
                    Ok(value)
                }
                Err(error) => {
                    savepoint
                        .rollback()
                        .map_err(|e| format!("postal_savepoint_rollback_failed:{e}"))?;
                    Err(error)
                }
            }
        };
        match result {
            Ok(value) => {
                tx.commit()
                    .map_err(|e| format!("postal_transaction_commit_failed:{e}"))?;
                Ok(value)
            }
            Err(error) => {
                let bounded_task = if valid_id(task_id) {
                    task_id.to_owned()
                } else {
                    format!("invalid:{}", sha(task_id.as_bytes()))
                };
                let bounded_hash = if valid_hash(assignment_hash) {
                    assignment_hash.to_ascii_lowercase()
                } else {
                    format!("invalid:{}", sha(assignment_hash.as_bytes()))
                };
                let reason = postal_reason_code(&error);
                Self::append_postal_event(
                    &tx,
                    &PostalEvent {
                        seq: 0,
                        kind: "denial".into(),
                        message_id: String::new(),
                        task_id: bounded_task,
                        lane_id: String::new(),
                        turn: None,
                        sender_id: actor_id.to_owned(),
                        recipient_id: String::new(),
                        body_sha256: attempt_hash.to_owned(),
                        reason_code: reason.into(),
                        previous_hash: String::new(),
                        event_hash: String::new(),
                        session_id: session.to_owned(),
                        assignment_hash: bounded_hash,
                        receipt_ref: receipt.id,
                    },
                )
                .map_err(|log| format!("{error}; postal_denial_receipt_failed:{log}"))?;
                tx.commit()
                    .map_err(|e| format!("postal_denial_commit_failed:{e}"))?;
                Err(error)
            }
        }
    }

    fn task_context(
        c: &Connection,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
        lane_id: Option<&str>,
    ) -> Result<Task, String> {
        if !valid_id(task_id) || !valid_hash(assignment_hash) {
            return Err("invalid_task_binding".into());
        }
        let events = Self::events(c)?;
        let mut tasks = Self::state(&events)?;
        let task = tasks.remove(task_id).ok_or("unknown_task")?;
        if !task.opened
            || task.stopped
            || task.session_id != session
            || task.assignment_hash != assignment_hash
        {
            return Err("task_binding_mismatch".into());
        }
        if let Some(lane_id) = lane_id {
            let lane = task.lanes.get(lane_id).ok_or("unknown_lane")?;
            if lane.done {
                return Err("lane_already_complete".into());
            }
        }
        Ok(task)
    }

    pub fn postal_register_drone(
        &self,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
        agent_id: &str,
    ) -> Result<Value, String> {
        let attempt =
            sha(format!("{session}\n{task_id}\n{assignment_hash}\n{agent_id}").as_bytes());
        self.authorized_postal_write("tool:aios_router_postal_register_drone", session, task_id, assignment_hash, "drone", agent_id, &attempt,
            |c, receipt_id| {
                if !valid_agent_id(agent_id) { return Err("invalid_drone_identity".into()); }
                Self::task_context(c, session, task_id, assignment_hash, None)?;
                let seed: u32 = c.query_row("SELECT seed FROM drone_identity_seed WHERE agent_id=?1", params![agent_id], |r| r.get(0))
                    .optional().map_err(|e| e.to_string())?.ok_or("drone_identity_seed_missing")?;
                let existing: Option<String> = c.query_row("SELECT inbox_id FROM postal_drone_identity WHERE agent_id=?1", params![agent_id], |r| r.get(0)).optional().map_err(|e| e.to_string())?;
                if let Some(inbox_id) = existing { return Err(format!("drone_inbox_already_registered:{inbox_id}")); }
                let mut inbox_id = String::new();
                for _ in 0..128 {
                    let entropy = random::<32>()?;
                    let id = format!("inbox_{}", sha(&[b"hive-postal-inbox-v1\0".as_slice(), agent_id.as_bytes(), b"\0", &entropy].concat()));
                    let inserted = c.execute("INSERT OR IGNORE INTO postal_drone_identity(agent_id,inbox_id,seed,receipt_ref,session_id,task_id,assignment_hash,created_at_ms) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
                        params![agent_id,id,seed,receipt_id,session,task_id,assignment_hash,now_millis()?]).map_err(|e| format!("postal_identity_insert_failed:{e}"))?;
                    if inserted == 1 { inbox_id = id; break; }
                }
                if inbox_id.is_empty() { return Err("unique_inbox_identity_exhausted".into()); }
                Self::append_postal_event(c, &PostalEvent {
                    seq:0, kind:"drone_registered".into(), message_id:String::new(), task_id:task_id.into(), lane_id:String::new(), turn:None,
                    sender_id:agent_id.into(), recipient_id:inbox_id.clone(), body_sha256:sha(agent_id.as_bytes()), reason_code:String::new(),
                    previous_hash:String::new(), event_hash:String::new(), session_id:session.into(), assignment_hash:assignment_hash.into(), receipt_ref:receipt_id.into(),
                })?;
                Ok(json!({"schema":POSTAL_EVENT_SCHEMA,"registered":true,"agent_id":agent_id,"inbox_id":inbox_id,"identity_source":"OS_CSPRNG","seed_registered":true,"seed_unique":true,"key_material_exposed":false}))
            })
    }

    pub fn postal_drone_submit(
        &self,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
        lane_id: &str,
        turn: u32,
        agent_id: &str,
        reply_to: Option<&str>,
        body: &str,
    ) -> Result<Value, String> {
        let body_hash = sha(body.trim().as_bytes());
        let reply = reply_to.unwrap_or("");
        let attempt = sha(format!("{session}\n{task_id}\n{assignment_hash}\n{lane_id}\n{turn}\n{agent_id}\n{reply}\n{body_hash}").as_bytes());
        self.authorized_postal_write("tool:aios_router_postal_drone_submit", session, task_id, assignment_hash, "drone", agent_id, &attempt,
            |c, receipt_id| {
                if body.trim().is_empty() || body.len() > MAX_BODY_BYTES { return Err("invalid_message_body".into()); }
                if !valid_agent_id(agent_id) || !valid_id(lane_id) || turn >= 32 { return Err("invalid_message_route_or_turn".into()); }
                let task = Self::task_context(c, session, task_id, assignment_hash, Some(lane_id))?;
                let lane = task.lanes.get(lane_id).ok_or("unknown_lane")?;
                if lane.active_turn != Some(turn) || lane.next_turn != turn || turn >= task.max_turns {
                    return Err("postal_turn_not_active_or_over_bound".into());
                }
                let registered: Option<String> = c.query_row("SELECT inbox_id FROM postal_drone_identity WHERE agent_id=?1", params![agent_id], |r| r.get(0)).optional().map_err(|e| e.to_string())?;
                if registered.is_none() { return Err("drone_postal_identity_missing".into()); }
                let existing_count: u32 = c.query_row("SELECT COUNT(*) FROM postal_outbox WHERE task_id=?1 AND lane_id=?2", params![task_id,lane_id], |r| r.get(0)).map_err(|e| e.to_string())?;
                if turn != existing_count { return Err("postal_turn_sequence_mismatch".into()); }
                if turn == 0 {
                    if !reply.is_empty() { return Err("first_postal_turn_cannot_reply".into()); }
                } else {
                    let prior: Option<(String, String)> = c.query_row("SELECT message_id,recipient_id FROM postal_drone_inbox WHERE message_id=?1 AND task_id=?2 AND lane_id=?3 AND turn=?4 AND message_kind='queen_message'", params![reply,task_id,lane_id,turn-1], |r| Ok((r.get(0)?,r.get(1)?))).optional().map_err(|e| e.to_string())?;
                    if prior.as_ref().map(|(_, recipient)| recipient.as_str()) != Some(agent_id) { return Err("postal_reply_chain_mismatch".into()); }
                }
                let message_id = random_id("msg_")?;
                let associated = aad(&message_id, "queen-outbox", task_id, lane_id, turn, agent_id, OUTBOX_ROLE, reply);
                let master = load_or_create_master_key(&self.key_dir)?;
                let sealed = seal(&master, &message_id, "queen-outbox", &associated, body.trim().as_bytes())?;
                let created_at_ms = now_millis()?;
                c.execute("INSERT INTO postal_outbox(message_id,task_id,lane_id,turn,sender_id,recipient_role,reply_to,body_sha256,nonce,ciphertext,key_nonce,wrapped_key,created_at_ms,session_id,assignment_hash,receipt_ref) VALUES(?1,?2,?3,?4,?5,'queen',?6,?7,?8,?9,?10,?11,?12,?13,?14,?15)",
                    params![message_id,task_id,lane_id,turn,agent_id,if reply.is_empty(){None}else{Some(reply)},body_hash,sealed.nonce,sealed.ciphertext,sealed.key_nonce,sealed.wrapped_key,created_at_ms,session,assignment_hash,format!("pending:{receipt_id}")])
                    .map_err(|e| format!("postal_outbox_insert_failed:{e}"))?;
                let previous: String = c.query_row("SELECT hash FROM router_event ORDER BY seq DESC LIMIT 1", [], |r| r.get(0)).optional().map_err(|e| e.to_string())?.unwrap_or_default();
                let seq: i64 = c.query_row("SELECT COALESCE(MAX(seq),0)+1 FROM router_event", [], |r| r.get(0)).map_err(|e| e.to_string())?;
                let mut event = Event { seq, task:task_id.into(), kind:"turn_result".into(), lane:Some(lane_id.into()), turn:Some(turn), digest:body_hash.clone(), previous:previous.clone(), hash:String::new(), session_id:session.into(), assignment_hash:assignment_hash.into(), reason_code:String::new(), receipt_id:receipt_id.into() };
                event.hash = sha(format!("{previous}\n{}", super::event_body(&event)).as_bytes());
                c.execute("INSERT INTO router_event(task,kind,lane,turn,digest,previous,hash,session_id,assignment_hash,reason_code,receipt_id) VALUES(?1,?2,?3,?4,?5,?6,?7,?8,?9,?10,?11)",
                    params![event.task,event.kind,event.lane,event.turn,event.digest,event.previous,event.hash,event.session_id,event.assignment_hash,event.reason_code,event.receipt_id])
                    .map_err(|e| format!("router_turn_result_append_failed:{e}"))?;
                Self::append_postal_event(c, &PostalEvent {
                    seq:0, kind:"drone_outbox".into(), message_id:message_id.clone(), task_id:task_id.into(), lane_id:lane_id.into(), turn:Some(turn),
                    sender_id:agent_id.into(), recipient_id:OUTBOX_ROLE.into(), body_sha256:body_hash.clone(), reason_code:String::new(), previous_hash:String::new(), event_hash:String::new(),
                    session_id:session.into(), assignment_hash:assignment_hash.into(), receipt_ref:format!("router_event:{seq}"),
                })?;
                Ok(json!({"accepted":true,"message_id":message_id,"task_id":task_id,"lane_id":lane_id,"turn":turn,"recipient_role":"queen","body_sha256":body_hash,"body_stored":"AES-256-GCM ciphertext","turn_result_recorded":true,"direct_drone_route":false}))
            })
    }

    pub fn postal_queen_list_drones(
        &self,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
    ) -> Result<Value, String> {
        let attempt =
            sha(format!("{session}\n{task_id}\n{assignment_hash}\nlist_drones").as_bytes());
        self.authorized_postal_write("tool:aios_router_postal_queen_list_drones", session, task_id, assignment_hash, "queen", "queen", &attempt,
            |c, receipt_id| {
                Self::task_context(c, session, task_id, assignment_hash, None)?;
                let mut q = c.prepare("SELECT agent_id,inbox_id,created_at_ms FROM postal_drone_identity ORDER BY agent_id LIMIT 128").map_err(|e| e.to_string())?;
                let rows = q.query_map([], |r| Ok(json!({"agent_id":r.get::<_,String>(0)?,"inbox_id":r.get::<_,String>(1)?,"created_at_ms":r.get::<_,i64>(2)?}))).map_err(|e| e.to_string())?;
                let mut drones = Vec::new();
                for row in rows { drones.push(row.map_err(|e| e.to_string())?); }
                let digest = sha(serde_json::to_vec(&drones).map_err(|e| e.to_string())?.as_slice());
                Self::append_postal_event(c, &PostalEvent { seq:0,kind:"queen_list_drones".into(),message_id:String::new(),task_id:task_id.into(),lane_id:String::new(),turn:None,sender_id:"queen".into(),recipient_id:String::new(),body_sha256:digest,reason_code:String::new(),previous_hash:String::new(),event_hash:String::new(),session_id:session.into(),assignment_hash:assignment_hash.into(),receipt_ref:receipt_id.into() })?;
                Ok(json!({"drones":drones,"count":drones.len(),"only_queen_visible":true}))
            })
    }

    pub fn postal_queen_list_outbox(
        &self,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
    ) -> Result<Value, String> {
        let attempt =
            sha(format!("{session}\n{task_id}\n{assignment_hash}\nlist_outbox").as_bytes());
        self.authorized_postal_write("tool:aios_router_postal_queen_list_outbox", session, task_id, assignment_hash, "queen", "queen", &attempt,
            |c, receipt_id| {
                Self::task_context(c, session, task_id, assignment_hash, None)?;
                let mut q = c.prepare("SELECT o.message_id,o.lane_id,o.turn,o.sender_id,o.reply_to,o.body_sha256,o.created_at_ms,EXISTS(SELECT 1 FROM postal_drone_inbox i WHERE i.source_message_id=o.message_id AND i.message_kind='queen_message') FROM postal_outbox o WHERE o.task_id=?1 ORDER BY o.seq LIMIT 64").map_err(|e| e.to_string())?;
                let rows = q.query_map(params![task_id], |r| Ok(json!({"message_id":r.get::<_,String>(0)?,"lane_id":r.get::<_,String>(1)?,"turn":r.get::<_,u32>(2)?,"sender_id":r.get::<_,String>(3)?,"reply_to":r.get::<_,Option<String>>(4)?,"body_sha256":r.get::<_,String>(5)?,"created_at_ms":r.get::<_,i64>(6)?,"delivered":r.get::<_,bool>(7)?}))).map_err(|e| e.to_string())?;
                let mut messages = Vec::new();
                for row in rows { messages.push(row.map_err(|e| e.to_string())?); }
                let digest = sha(serde_json::to_vec(&messages).map_err(|e| e.to_string())?.as_slice());
                Self::append_postal_event(c, &PostalEvent { seq:0,kind:"queen_list_outbox".into(),message_id:String::new(),task_id:task_id.into(),lane_id:String::new(),turn:None,sender_id:"queen".into(),recipient_id:String::new(),body_sha256:digest,reason_code:String::new(),previous_hash:String::new(),event_hash:String::new(),session_id:session.into(),assignment_hash:assignment_hash.into(),receipt_ref:receipt_id.into() })?;
                Ok(json!({"messages":messages,"count":messages.len(),"bodies_decrypted":false,"only_queen_visible":true}))
            })
    }

    pub fn postal_queen_read_outbox(
        &self,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
        message_id: &str,
    ) -> Result<Value, String> {
        let attempt =
            sha(format!("{session}\n{task_id}\n{assignment_hash}\n{message_id}").as_bytes());
        self.authorized_postal_write("tool:aios_router_postal_queen_read_outbox", session, task_id, assignment_hash, "queen", "queen", &attempt,
            |c, receipt_id| {
                Self::task_context(c, session, task_id, assignment_hash, None)?;
                let row = c.query_row("SELECT lane_id,turn,sender_id,reply_to,body_sha256,nonce,ciphertext,key_nonce,wrapped_key FROM postal_outbox WHERE message_id=?1 AND task_id=?2 AND session_id=?3 AND assignment_hash=?4",
                    params![message_id,task_id,session,assignment_hash], |r| Ok((r.get::<_,String>(0)?,r.get::<_,u32>(1)?,r.get::<_,String>(2)?,r.get::<_,Option<String>>(3)?,r.get::<_,String>(4)?,r.get::<_,Vec<u8>>(5)?,r.get::<_,Vec<u8>>(6)?,r.get::<_,Vec<u8>>(7)?,r.get::<_,Vec<u8>>(8)?)))
                    .optional().map_err(|e| e.to_string())?.ok_or("outbox_message_not_found")?;
                let (lane_id,turn,sender_id,reply_to,body_hash,nonce,ciphertext,key_nonce,wrapped_key) = row;
                let associated = aad(message_id,"queen-outbox",task_id,&lane_id,turn,&sender_id,OUTBOX_ROLE,reply_to.as_deref().unwrap_or(""));
                let master = load_or_create_master_key(&self.key_dir)?;
                let body = open_sealed(&master,message_id,"queen-outbox",&associated,&nonce,&ciphertext,&key_nonce,&wrapped_key,&body_hash)?;
                Self::append_postal_event(c,&PostalEvent { seq:0,kind:"queen_read_outbox".into(),message_id:message_id.into(),task_id:task_id.into(),lane_id:lane_id.clone(),turn:Some(turn),sender_id:"queen".into(),recipient_id:sender_id.clone(),body_sha256:body_hash.clone(),reason_code:String::new(),previous_hash:String::new(),event_hash:String::new(),session_id:session.into(),assignment_hash:assignment_hash.into(),receipt_ref:receipt_id.into() })?;
                Ok(json!({"message_id":message_id,"task_id":task_id,"lane_id":lane_id,"turn":turn,"sender_id":sender_id,"reply_to":reply_to,"body_sha256":body_hash,"body":body,"verified_aead":true}))
            })
    }

    pub fn postal_queen_dispatch(
        &self,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
        source_message_id: &str,
        destination_agent_id: &str,
        destination_inbox_id: &str,
        body: &str,
    ) -> Result<Value, String> {
        let body_hash = sha(body.trim().as_bytes());
        let attempt = sha(format!("{session}\n{task_id}\n{assignment_hash}\n{source_message_id}\n{destination_agent_id}\n{destination_inbox_id}\n{body_hash}").as_bytes());
        self.authorized_postal_write("tool:aios_router_postal_queen_dispatch", session, task_id, assignment_hash, "queen", "queen", &attempt,
            |c, receipt_id| {
                if body.trim().is_empty() || body.len() > MAX_BODY_BYTES { return Err("invalid_message_body".into()); }
                if !valid_agent_id(destination_agent_id) || !destination_inbox_id.starts_with("inbox_") || destination_inbox_id.len() != 70 { return Err("invalid_recipient_handshake".into()); }
                let task = Self::task_context(c, session, task_id, assignment_hash, None)?;
                let source = c.query_row("SELECT lane_id,turn,sender_id,reply_to FROM postal_outbox WHERE message_id=?1 AND task_id=?2 AND session_id=?3 AND assignment_hash=?4",
                    params![source_message_id,task_id,session,assignment_hash], |r| Ok((r.get::<_,String>(0)?,r.get::<_,u32>(1)?,r.get::<_,String>(2)?,r.get::<_,Option<String>>(3)?)))
                    .optional().map_err(|e|e.to_string())?.ok_or("outbox_message_not_found")?;
                let (lane_id,turn,original_sender,_) = source;
                let verified_read: bool = c.query_row("SELECT EXISTS(SELECT 1 FROM postal_event WHERE kind='queen_read_outbox' AND message_id=?1 AND task_id=?2 AND session_id=?3 AND assignment_hash=?4)",
                    params![source_message_id,task_id,session,assignment_hash], |r| r.get(0)).map_err(|e|e.to_string())?;
                if !verified_read { return Err("queen_must_verify_outbox_before_dispatch".into()); }
                if task.lanes.get(&lane_id).is_none_or(|lane|lane.done) { return Err("lane_already_complete".into()); }
                let recipient: Option<String> = c.query_row("SELECT agent_id FROM postal_drone_identity WHERE agent_id=?1 AND inbox_id=?2", params![destination_agent_id,destination_inbox_id], |r| r.get(0))
                    .optional().map_err(|e| e.to_string())?;
                if recipient.is_none() {
                    let reason = if c.query_row("SELECT EXISTS(SELECT 1 FROM postal_drone_identity WHERE agent_id=?1)", params![destination_agent_id], |r| r.get::<_,bool>(0)).unwrap_or(false) { "inbox_handshake_mismatch" } else { "recipient_not_registered" };
                    let bounced_id = if let Some(sender_inbox) = c.query_row("SELECT inbox_id FROM postal_drone_identity WHERE agent_id=?1", params![original_sender], |r| r.get::<_,String>(0)).optional().map_err(|e|e.to_string())? {
                        let bounce_id = random_id("bounce_")?;
                        let bounce_body = json!({"schema":"hive_postal_bounce_v1","task_id":task_id,"message_id":source_message_id,"reason_code":reason}).to_string();
                        let bounce_hash = sha(bounce_body.as_bytes());
                        let associated = aad(&bounce_id,"drone-inbox",task_id,&lane_id,turn,"router",&original_sender,source_message_id);
                        let master = load_or_create_master_key(&self.key_dir)?;
                        let sealed = seal(&master,&bounce_id,"drone-inbox",&associated,bounce_body.as_bytes())?;
                        c.execute("INSERT INTO postal_drone_inbox(message_id,source_message_id,message_kind,task_id,lane_id,turn,sender_id,recipient_id,recipient_inbox_id,reply_to,body_sha256,nonce,ciphertext,key_nonce,wrapped_key,created_at_ms,session_id,assignment_hash,receipt_ref) VALUES(?1,?2,'bounce',?3,?4,?5,'router',?6,?7,?2,?8,?9,?10,?11,?12,?13,?14,?15,?16)",
                            params![bounce_id,source_message_id,task_id,lane_id,turn,original_sender,sender_inbox,bounce_hash,sealed.nonce,sealed.ciphertext,sealed.key_nonce,sealed.wrapped_key,now_millis()?,session,assignment_hash,format!("pending:{receipt_id}")])
                            .map_err(|e| format!("postal_bounce_insert_failed:{e}"))?;
                        Self::append_postal_event(c,&PostalEvent {seq:0,kind:"route_bounced".into(),message_id:bounce_id.clone(),task_id:task_id.into(),lane_id:lane_id.clone(),turn:Some(turn),sender_id:"queen".into(),recipient_id:original_sender.clone(),body_sha256:bounce_hash,reason_code:reason.into(),previous_hash:String::new(),event_hash:String::new(),session_id:session.into(),assignment_hash:assignment_hash.into(),receipt_ref:receipt_id.into()})?;
                        Some(bounce_id)
                    } else { None };
                    if bounced_id.is_none() {
                        Self::append_postal_event(c,&PostalEvent {seq:0,kind:"route_bounced".into(),message_id:source_message_id.into(),task_id:task_id.into(),lane_id:lane_id.clone(),turn:Some(turn),sender_id:"queen".into(),recipient_id:String::new(),body_sha256:body_hash.clone(),reason_code:reason.into(),previous_hash:String::new(),event_hash:String::new(),session_id:session.into(),assignment_hash:assignment_hash.into(),receipt_ref:receipt_id.into()})?;
                    }
                    return Ok(json!({"status":"bounced","source_message_id":source_message_id,"bounce_message_id":bounced_id,"reason_code":reason,"retryable":true}));
                }
                let delivered: Option<(String,String,String)> = c.query_row("SELECT message_id,recipient_id,body_sha256 FROM postal_drone_inbox WHERE source_message_id=?1 AND message_kind='queen_message'", params![source_message_id], |r| Ok((r.get(0)?,r.get(1)?,r.get(2)?))).optional().map_err(|e| e.to_string())?;
                if let Some((existing_id,existing_recipient,existing_hash)) = delivered {
                    if existing_recipient == destination_agent_id && existing_hash == body_hash {
                        Self::append_postal_event(c,&PostalEvent {seq:0,kind:"delivery_retry_confirmed".into(),message_id:existing_id.clone(),task_id:task_id.into(),lane_id:lane_id.clone(),turn:Some(turn),sender_id:"queen".into(),recipient_id:destination_agent_id.into(),body_sha256:body_hash.clone(),reason_code:String::new(),previous_hash:String::new(),event_hash:String::new(),session_id:session.into(),assignment_hash:assignment_hash.into(),receipt_ref:receipt_id.into()})?;
                        return Ok(json!({"status":"already_delivered","message_id":existing_id,"recipient_id":destination_agent_id,"idempotent":true}));
                    }
                    return Err("outbox_message_already_delivered".into());
                }
                let message_id = random_id("msg_")?;
                let associated = aad(&message_id,"drone-inbox",task_id,&lane_id,turn,"queen",destination_agent_id,source_message_id);
                let master = load_or_create_master_key(&self.key_dir)?;
                let sealed = seal(&master,&message_id,"drone-inbox",&associated,body.trim().as_bytes())?;
                c.execute("INSERT INTO postal_drone_inbox(message_id,source_message_id,message_kind,task_id,lane_id,turn,sender_id,recipient_id,recipient_inbox_id,reply_to,body_sha256,nonce,ciphertext,key_nonce,wrapped_key,created_at_ms,session_id,assignment_hash,receipt_ref) VALUES(?1,?2,'queen_message',?3,?4,?5,'queen',?6,?7,?2,?8,?9,?10,?11,?12,?13,?14,?15,?16)",
                    params![message_id,source_message_id,task_id,lane_id,turn,destination_agent_id,destination_inbox_id,body_hash,sealed.nonce,sealed.ciphertext,sealed.key_nonce,sealed.wrapped_key,now_millis()?,session,assignment_hash,format!("pending:{receipt_id}")])
                    .map_err(|e| format!("postal_delivery_insert_failed:{e}"))?;
                Self::append_postal_event(c,&PostalEvent {seq:0,kind:"queen_delivered".into(),message_id:message_id.clone(),task_id:task_id.into(),lane_id:lane_id.clone(),turn:Some(turn),sender_id:"queen".into(),recipient_id:destination_agent_id.into(),body_sha256:body_hash.clone(),reason_code:String::new(),previous_hash:String::new(),event_hash:String::new(),session_id:session.into(),assignment_hash:assignment_hash.into(),receipt_ref:receipt_id.into()})?;
                Ok(json!({"status":"delivered","message_id":message_id,"source_message_id":source_message_id,"recipient_id":destination_agent_id,"recipient_inbox_id":destination_inbox_id,"turn":turn,"body_sha256":body_hash,"direct_drone_route":false}))
            })
    }

    pub fn postal_drone_read_inbox(
        &self,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
        agent_id: &str,
        limit: u8,
    ) -> Result<Value, String> {
        let attempt =
            sha(format!("{session}\n{task_id}\n{assignment_hash}\n{agent_id}\n{limit}").as_bytes());
        self.authorized_postal_write("tool:aios_router_postal_drone_read_inbox", session, task_id, assignment_hash, "drone", agent_id, &attempt,
            |c, receipt_id| {
                if !(1..=MAX_INBOX_READ as u8).contains(&limit) || !valid_agent_id(agent_id) { return Err("invalid_inbox_read_bounds".into()); }
                Self::task_context(c, session, task_id, assignment_hash, None)?;
                let inbox_id: String = c.query_row("SELECT inbox_id FROM postal_drone_identity WHERE agent_id=?1", params![agent_id], |r| r.get(0)).optional().map_err(|e| e.to_string())?.ok_or("drone_postal_identity_missing")?;
                let mut q = c.prepare("SELECT message_id,source_message_id,message_kind,lane_id,turn,sender_id,reply_to,body_sha256,nonce,ciphertext,key_nonce,wrapped_key FROM postal_drone_inbox WHERE recipient_id=?1 AND recipient_inbox_id=?2 AND task_id=?3 ORDER BY seq DESC LIMIT ?4").map_err(|e|e.to_string())?;
                let rows = q.query_map(params![agent_id,inbox_id,task_id,limit], |r| Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,String>(3)?,r.get::<_,u32>(4)?,r.get::<_,String>(5)?,r.get::<_,String>(6)?,r.get::<_,String>(7)?,r.get::<_,Vec<u8>>(8)?,r.get::<_,Vec<u8>>(9)?,r.get::<_,Vec<u8>>(10)?,r.get::<_,Vec<u8>>(11)?))).map_err(|e|e.to_string())?;
                let mut rows = rows.collect::<Result<Vec<_>,_>>().map_err(|e|e.to_string())?;
                rows.reverse();
                let master = load_or_create_master_key(&self.key_dir)?;
                let mut messages = Vec::new();
                for (message_id,source_id,kind,lane_id,turn,sender_id,reply_to,body_hash,nonce,ciphertext,key_nonce,wrapped_key) in rows {
                    let purpose = "drone-inbox";
                    let associated = aad(&message_id,purpose,task_id,&lane_id,turn,&sender_id,agent_id,&reply_to);
                    let body = open_sealed(&master,&message_id,purpose,&associated,&nonce,&ciphertext,&key_nonce,&wrapped_key,&body_hash)?;
                    messages.push(json!({"message_id":message_id,"source_message_id":source_id,"kind":kind,"task_id":task_id,"lane_id":lane_id,"turn":turn,"sender_id":sender_id,"reply_to":reply_to,"body_sha256":body_hash,"body":body,"verified_aead":true}));
                }
                let digest = sha(serde_json::to_vec(&messages.iter().map(|m|m.get("message_id").cloned()).collect::<Vec<_>>()).map_err(|e|e.to_string())?.as_slice());
                Self::append_postal_event(c,&PostalEvent {seq:0,kind:"drone_read_inbox".into(),message_id:String::new(),task_id:task_id.into(),lane_id:String::new(),turn:None,sender_id:agent_id.into(),recipient_id:agent_id.into(),body_sha256:digest,reason_code:String::new(),previous_hash:String::new(),event_hash:String::new(),session_id:session.into(),assignment_hash:assignment_hash.into(),receipt_ref:receipt_id.into()})?;
                Ok(json!({"messages":messages,"count":messages.len(),"agent_id":agent_id,"inbox_id":inbox_id,"direct_drone_messages":false}))
            })
    }

    pub fn postal_queen_summary(
        &self,
        session: &str,
        task_id: &str,
        assignment_hash: &str,
    ) -> Result<Value, String> {
        let attempt =
            sha(format!("{session}\n{task_id}\n{assignment_hash}\nqueen_summary").as_bytes());
        self.authorized_postal_write(
            "tool:aios_router_postal_queen_summary",
            session,
            task_id,
            assignment_hash,
            "queen",
            "queen",
            &attempt,
            |c, receipt_id| {
                let task = Self::task_context(c, session, task_id, assignment_hash, None)?;
                let events = Self::postal_events(c)?;
                let outbox_count: i64 = c.query_row(
                    "SELECT COUNT(*) FROM postal_outbox WHERE task_id=?1",
                    params![task_id],
                    |r| r.get(0),
                ).map_err(|e| e.to_string())?;
                let delivered_count: i64 = c.query_row(
                    "SELECT COUNT(*) FROM postal_drone_inbox WHERE task_id=?1 AND message_kind='queen_message'",
                    params![task_id],
                    |r| r.get(0),
                ).map_err(|e| e.to_string())?;
                let bounce_count: i64 = c.query_row(
                    "SELECT COUNT(*) FROM postal_drone_inbox WHERE task_id=?1 AND message_kind='bounce'",
                    params![task_id],
                    |r| r.get(0),
                ).map_err(|e| e.to_string())?;
                let lanes = task.lanes.iter().map(|(id, lane)| json!({
                    "lane_id":id,
                    "completed":lane.done,
                    "completed_turns":lane.turns,
                    "active_turn":lane.active_turn,
                    "max_turns":task.max_turns,
                })).collect::<Vec<_>>();
                let verification=crate::completion::current(c,task_id,crate::completion::project_root());
                let state = if task.stopped { "stopped" } else if !task.lanes.values().all(|lane| lane.done) { "in_progress" } else if verification["verified"]==true { "completed" } else { "awaiting_verification" };
                let event_receipts = events.iter().filter(|event| event.task_id == task_id).map(|event| json!({
                    "event":event.kind,
                    "message_id":if event.message_id.is_empty(){Value::Null}else{json!(event.message_id)},
                    "turn":event.turn,
                    "body_sha256":if event.body_sha256.is_empty(){Value::Null}else{json!(event.body_sha256)},
                    "reason_code":if event.reason_code.is_empty(){Value::Null}else{json!(event.reason_code)},
                    "event_sha256":event.event_hash,
                })).collect::<Vec<_>>();
                let summary = json!({
                    "schema":POSTAL_EVENT_SCHEMA,
                    "task_id":task_id,
                    "state":state,
                    "verification":verification,
                    "lanes":lanes,
                    "outbox_messages":outbox_count,
                    "delivered_messages":delivered_count,
                    "bounce_messages":bounce_count,
                    "postal_event_chain":"verified",
                    "event_receipts":event_receipts,
                    "queen_summary":"Derived from Rust task and postal receipts; no message body or model-authored success claim is inferred."
                });
                let digest = sha(serde_json::to_vec(&summary).map_err(|e| e.to_string())?.as_slice());
                Self::append_postal_event(c, &PostalEvent {
                    seq:0,kind:"queen_summary".into(),message_id:String::new(),task_id:task_id.into(),lane_id:String::new(),turn:None,
                    sender_id:"queen".into(),recipient_id:String::new(),body_sha256:digest,reason_code:String::new(),previous_hash:String::new(),event_hash:String::new(),
                    session_id:session.into(),assignment_hash:assignment_hash.into(),receipt_ref:receipt_id.into(),
                })?;
                Ok(summary)
            },
        )
    }
}

fn postal_event_body(event: &PostalEvent) -> String {
    format!(
        "{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}\n{}",
        event.seq,
        event.kind,
        event.message_id,
        event.task_id,
        event.lane_id,
        event.turn.map(|x| x.to_string()).unwrap_or_default(),
        event.sender_id,
        event.recipient_id,
        event.body_sha256,
        event.reason_code,
        event.previous_hash,
        event.session_id,
        event.assignment_hash,
        event.receipt_ref
    )
}

fn postal_reason_code(error: &str) -> &'static str {
    match error.split(':').next().unwrap_or(error) {
        "unknown_task" | "unknown_lane" | "outbox_message_not_found" => "unknown_reference",
        "task_binding_mismatch" | "postal_reply_chain_mismatch" => "binding_mismatch",
        "invalid_message_body"
        | "invalid_message_route_or_turn"
        | "invalid_recipient_handshake"
        | "invalid_task_binding"
        | "invalid_drone_identity"
        | "invalid_inbox_read_bounds" => "invalid_arguments",
        "recipient_not_registered" | "inbox_handshake_mismatch" => "invalid_route",
        "postal_turn_not_active_or_over_bound"
        | "postal_turn_sequence_mismatch"
        | "outbox_message_already_delivered"
        | "lane_already_complete" => "invalid_state",
        "queen_must_verify_outbox_before_dispatch" => "verification_required",
        "drone_identity_seed_missing" | "drone_postal_identity_missing" => "identity_unregistered",
        "message_authentication_failed"
        | "content_key_unwrap_failed"
        | "message_plaintext_hash_mismatch"
        | "postal_event_chain_integrity_failure_at_sequence_0" => "integrity_failure",
        _ => "postal_router_rejected",
    }
}

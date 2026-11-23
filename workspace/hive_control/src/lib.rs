//! Small Rust authority boundary for the isolated Hive network proof.
//! Keys and tool decisions stay here; model and template workers see data only.

use aes_gcm::aead::{Aead, KeyInit, Payload};
use aes_gcm::{Aes256Gcm, Nonce};
use rand::{rngs::OsRng, RngCore};
use serde_json::Value;
use sha2::{Digest, Sha256};
use std::collections::HashMap;
use std::time::{Duration, Instant};

pub mod graph;

pub fn sha(bytes: &[u8]) -> String {
    hex::encode(Sha256::digest(bytes))
}

fn fresh<const N: usize>() -> [u8; N] {
    let mut bytes = [0_u8; N];
    OsRng.fill_bytes(&mut bytes);
    bytes
}

fn cipher(key: &[u8; 32]) -> Aes256Gcm {
    Aes256Gcm::new_from_slice(key).expect("32-byte AES key")
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub enum TaskState {
    Sealed,
    Opened,
    Completed,
}

struct Task {
    owner: String,
    parent: Option<String>,
    parent_artifact_sha256: Option<String>,
    checksum: String,
    entropy: [u8; 32],
    nonce: [u8; 12],
    ciphertext: Vec<u8>,
    wrap_nonce: [u8; 12],
    wrapped_key: Vec<u8>,
    state: TaskState,
    artifact_sha256: Option<String>,
}

struct Channel {
    key: [u8; 32],
    expires_at: Instant,
}

pub struct Control {
    master: [u8; 32],
    tasks: HashMap<String, Task>,
    channels: HashMap<(String, String, String, String), Channel>,
    tool_allowlist: Vec<(String, String)>,
}

impl Control {
    pub fn new(tool_allowlist: Vec<(String, String)>) -> Self {
        Self {
            master: fresh(),
            tasks: HashMap::new(),
            channels: HashMap::new(),
            tool_allowlist,
        }
    }

    pub fn approve_tool(&self, mind_approved: bool, tool: &str, scope: &str) -> Result<(), String> {
        if !mind_approved {
            return Err("Mind did not approve this tool request".into());
        }
        if !self
            .tool_allowlist
            .iter()
            .any(|(t, s)| t == tool && s == scope)
        {
            return Err("tool and scope require the Architect's approval".into());
        }
        Ok(())
    }

    pub fn seal_task(
        &mut self,
        id: &str,
        owner: &str,
        parent: Option<&str>,
        parent_artifact_sha256: Option<&str>,
        payload: &Value,
    ) -> Result<String, String> {
        if id.is_empty() || owner.is_empty() || self.tasks.contains_key(id) {
            return Err("invalid or duplicate task identity".into());
        }
        if let Some(parent_id) = parent {
            let prior = self.tasks.get(parent_id).ok_or("unknown parent task")?;
            if prior.state != TaskState::Completed {
                return Err("parent task has not completed".into());
            }
            if prior.artifact_sha256.as_deref() != parent_artifact_sha256 {
                return Err("parent artifact hash does not match completed task".into());
            }
        } else if parent_artifact_sha256.is_some() {
            return Err("root task cannot claim a parent artifact".into());
        }
        let plaintext = serde_json::to_vec(payload).map_err(|e| e.to_string())?;
        let key: [u8; 32] = fresh();
        let nonce: [u8; 12] = fresh();
        let wrap_nonce: [u8; 12] = fresh();
        let entropy: [u8; 32] = fresh();
        let aad = format!("task:{id}:{owner}:{}", parent.unwrap_or(""));
        let ciphertext = cipher(&key)
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: &plaintext,
                    aad: aad.as_bytes(),
                },
            )
            .map_err(|_| "task encryption failed")?;
        let wrapped_key = cipher(&self.master)
            .encrypt(
                Nonce::from_slice(&wrap_nonce),
                Payload {
                    msg: &key,
                    aad: aad.as_bytes(),
                },
            )
            .map_err(|_| "task key wrapping failed")?;
        let mut checksum_input = Vec::new();
        checksum_input.extend_from_slice(b"hive-task-v1\0");
        checksum_input.extend_from_slice(&entropy);
        checksum_input.extend_from_slice(aad.as_bytes());
        checksum_input.extend_from_slice(&nonce);
        checksum_input.extend_from_slice(&ciphertext);
        let checksum = sha(&checksum_input);
        self.tasks.insert(
            id.into(),
            Task {
                owner: owner.into(),
                parent: parent.map(str::to_owned),
                parent_artifact_sha256: parent_artifact_sha256.map(str::to_owned),
                checksum: checksum.clone(),
                entropy,
                nonce,
                ciphertext,
                wrap_nonce,
                wrapped_key,
                state: TaskState::Sealed,
                artifact_sha256: None,
            },
        );
        Ok(checksum)
    }

    pub fn open_task(
        &mut self,
        id: &str,
        requester: &str,
        current_parent_hash: Option<&str>,
    ) -> Result<Value, String> {
        let task = self.tasks.get_mut(id).ok_or("unknown task")?;
        if task.owner != requester || task.state != TaskState::Sealed {
            return Err("task owner or state denied".into());
        }
        if task.parent_artifact_sha256.as_deref() != current_parent_hash {
            return Err("parent artifact changed before dispatch".into());
        }
        let aad = format!(
            "task:{id}:{requester}:{}",
            task.parent.as_deref().unwrap_or("")
        );
        let mut checksum_input = Vec::new();
        checksum_input.extend_from_slice(b"hive-task-v1\0");
        checksum_input.extend_from_slice(&task.entropy);
        checksum_input.extend_from_slice(aad.as_bytes());
        checksum_input.extend_from_slice(&task.nonce);
        checksum_input.extend_from_slice(&task.ciphertext);
        if sha(&checksum_input) != task.checksum {
            return Err("task snapshot checksum mismatch".into());
        }
        let key = cipher(&self.master)
            .decrypt(
                Nonce::from_slice(&task.wrap_nonce),
                Payload {
                    msg: &task.wrapped_key,
                    aad: aad.as_bytes(),
                },
            )
            .map_err(|_| "task key unwrap failed")?;
        let bytes = cipher(key.as_slice().try_into().map_err(|_| "bad task key")?)
            .decrypt(
                Nonce::from_slice(&task.nonce),
                Payload {
                    msg: &task.ciphertext,
                    aad: aad.as_bytes(),
                },
            )
            .map_err(|_| "task snapshot authentication failed")?;
        task.state = TaskState::Opened;
        serde_json::from_slice(&bytes).map_err(|e| e.to_string())
    }

    pub fn complete_task(
        &mut self,
        id: &str,
        owner: &str,
        artifact_sha256: &str,
    ) -> Result<(), String> {
        let task = self.tasks.get_mut(id).ok_or("unknown task")?;
        if task.owner != owner || task.state != TaskState::Opened || artifact_sha256.len() != 64 {
            return Err("task completion denied".into());
        }
        task.artifact_sha256 = Some(artifact_sha256.into());
        task.state = TaskState::Completed;
        Ok(())
    }

    pub fn task_record(&self, id: &str) -> Result<Value, String> {
        let task = self.tasks.get(id).ok_or("unknown task")?;
        Ok(serde_json::json!({
            "task_id": id, "owner": task.owner, "parent": task.parent,
            "checksum": task.checksum, "state": format!("{:?}", task.state),
            "artifact_sha256": task.artifact_sha256,
        }))
    }

    pub fn create_channel(
        &mut self,
        mind_approved: bool,
        source: &str,
        destination: &str,
        task_id: &str,
        ttl: Duration,
    ) -> Result<String, String> {
        if !mind_approved
            || source.is_empty()
            || destination.is_empty()
            || source == destination
            || !self.tasks.contains_key(task_id)
            || ttl.is_zero()
        {
            return Err("channel grant denied".into());
        }
        let grant_id = hex::encode(fresh::<12>());
        self.channels.insert(
            (
                source.into(),
                destination.into(),
                task_id.into(),
                grant_id.clone(),
            ),
            Channel {
                key: fresh(),
                expires_at: Instant::now() + ttl,
            },
        );
        Ok(grant_id)
    }

    fn channel(
        &self,
        source: &str,
        destination: &str,
        task_id: &str,
        grant_id: &str,
    ) -> Result<&Channel, String> {
        let grant = self
            .channels
            .get(&(
                source.into(),
                destination.into(),
                task_id.into(),
                grant_id.into(),
            ))
            .ok_or("channel grant missing")?;
        if Instant::now() >= grant.expires_at {
            return Err("channel grant expired".into());
        }
        Ok(grant)
    }

    pub fn seal_peer(
        &self,
        source: &str,
        destination: &str,
        task_id: &str,
        grant_id: &str,
        plaintext: &[u8],
    ) -> Result<Value, String> {
        let grant = self.channel(source, destination, task_id, grant_id)?;
        let nonce: [u8; 12] = fresh();
        let aad = format!("peer:{source}:{destination}:{task_id}:{grant_id}");
        let ciphertext = cipher(&grant.key)
            .encrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: plaintext,
                    aad: aad.as_bytes(),
                },
            )
            .map_err(|_| "peer encryption failed")?;
        Ok(
            serde_json::json!({"source": source, "destination": destination,
            "task_id": task_id, "grant_id": grant_id, "nonce": hex::encode(nonce),
            "ciphertext": hex::encode(ciphertext)}),
        )
    }

    pub fn open_peer(&self, envelope: &Value, requester: &str) -> Result<Vec<u8>, String> {
        let field = |name| {
            envelope
                .get(name)
                .and_then(Value::as_str)
                .ok_or(format!("missing {name}"))
        };
        let source = field("source")?;
        let destination = field("destination")?;
        let task_id = field("task_id")?;
        let grant_id = field("grant_id")?;
        if requester != destination {
            return Err("peer receiver denied".into());
        }
        let grant = self.channel(source, destination, task_id, grant_id)?;
        let nonce = hex::decode(field("nonce")?).map_err(|_| "bad peer nonce")?;
        let ciphertext = hex::decode(field("ciphertext")?).map_err(|_| "bad peer ciphertext")?;
        if nonce.len() != 12 {
            return Err("bad peer nonce length".into());
        }
        let aad = format!("peer:{source}:{destination}:{task_id}:{grant_id}");
        cipher(&grant.key)
            .decrypt(
                Nonce::from_slice(&nonce),
                Payload {
                    msg: &ciphertext,
                    aad: aad.as_bytes(),
                },
            )
            .map_err(|_| "peer message authentication failed".into())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn task_owner_dependency_and_parent_hash_are_enforced() {
        let mut c = Control::new(vec![]);
        c.seal_task("one", "a", None, None, &serde_json::json!({"x": 1}))
            .unwrap();
        assert!(c.open_task("one", "b", None).is_err());
        assert!(c
            .seal_task("two", "b", Some("one"), Some(&sha(b"one")), &Value::Null)
            .is_err());
        assert_eq!(c.open_task("one", "a", None).unwrap()["x"], 1);
        c.complete_task("one", "a", &sha(b"one")).unwrap();
        c.seal_task("two", "b", Some("one"), Some(&sha(b"one")), &Value::Null)
            .unwrap();
        assert!(c.open_task("two", "b", Some(&sha(b"changed"))).is_err());
        assert!(c.open_task("two", "b", Some(&sha(b"one"))).is_ok());
    }

    #[test]
    fn altered_snapshot_is_rejected_before_worker_dispatch() {
        let mut c = Control::new(vec![]);
        c.seal_task("one", "a", None, None, &serde_json::json!({"secret": "x"}))
            .unwrap();
        c.tasks.get_mut("one").unwrap().ciphertext[0] ^= 1;
        assert_eq!(
            c.open_task("one", "a", None).unwrap_err(),
            "task snapshot checksum mismatch"
        );
    }

    #[test]
    fn tools_and_peer_messages_require_scoped_grants() {
        let mut c = Control::new(vec![("stamp".into(), "run-artifact".into())]);
        assert!(c.approve_tool(false, "stamp", "run-artifact").is_err());
        assert!(c.approve_tool(true, "shell", "run-artifact").is_err());
        c.approve_tool(true, "stamp", "run-artifact").unwrap();
        c.seal_task("one", "a", None, None, &Value::Null).unwrap();
        assert!(c.seal_peer("a", "b", "one", "missing", b"secret").is_err());
        let id = c
            .create_channel(true, "a", "b", "one", Duration::from_secs(60))
            .unwrap();
        let envelope = c.seal_peer("a", "b", "one", &id, b"secret").unwrap();
        assert!(!envelope.to_string().contains("secret"));
        assert!(c.open_peer(&envelope, "c").is_err());
        assert_eq!(c.open_peer(&envelope, "b").unwrap(), b"secret");
        let mut tampered = envelope;
        tampered["ciphertext"] = Value::String("00".into());
        assert!(c.open_peer(&tampered, "b").is_err());
    }
}

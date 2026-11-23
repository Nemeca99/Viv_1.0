//! One Rust-owned SQLite transaction. Public PASS requires fresh verified readback.
use super::{
    contract::{self, Candidate, ZERO_HASH},
    policy::{self, hold, Rejection, Trust},
    receipt::{self, Receipt, ReceiptIdentity},
};
use rusqlite::{params, Connection, OpenFlags, OptionalExtension, TransactionBehavior};
use serde::{Deserialize, Serialize};
use std::{
    collections::BTreeSet,
    path::{Path, PathBuf},
    time::{Duration, SystemTime, UNIX_EPOCH},
};

const TABLES: &[(&str, &str)] = &[
    ("admissions", "CREATE TABLE admissions (id TEXT PRIMARY KEY NOT NULL, request_id TEXT NOT NULL UNIQUE, packet TEXT NOT NULL, receipt TEXT NOT NULL, generation INTEGER NOT NULL UNIQUE CHECK(generation>0))"),
    ("dispositions", "CREATE TABLE dispositions (request_id TEXT PRIMARY KEY NOT NULL, record TEXT NOT NULL)"),
    ("meta", "CREATE TABLE meta (id INTEGER PRIMARY KEY CHECK(id=1), policy TEXT NOT NULL, generation INTEGER NOT NULL CHECK(generation>=0), head TEXT NOT NULL)"),
    ("replay", "CREATE TABLE replay (issuer TEXT NOT NULL, nonce TEXT NOT NULL, sequence INTEGER NOT NULL CHECK(sequence>0), PRIMARY KEY(issuer,nonce), UNIQUE(issuer,sequence))"),
    ("requests", "CREATE TABLE requests (request_id TEXT PRIMARY KEY NOT NULL, packet_hash TEXT NOT NULL, candidate_hash TEXT NOT NULL, schema_id TEXT NOT NULL, action TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('PENDING','COMMITTED','REJECTED','HELD')), admission_id TEXT UNIQUE, receipt_hash TEXT, CHECK((state IN ('PENDING','REJECTED','HELD') AND admission_id IS NULL AND receipt_hash IS NULL) OR (state='COMMITTED' AND admission_id IS NOT NULL AND receipt_hash IS NOT NULL)))"),
];

#[derive(Clone, Debug, Serialize, Deserialize)]
pub struct AdmissionResult {
    pub state: String,
    pub reason: String,
    pub commit_status: String,
    pub admission: Option<Receipt>,
    pub authority_scope: String,
    pub os_isolation: String,
    pub production_antirollback: String,
}
impl AdmissionResult {
    fn rejected(error: Rejection, status: &str) -> Self {
        Self {
            state: error.state.into(),
            reason: error.reason.into(),
            commit_status: status.into(),
            admission: None,
            authority_scope: "fixture_only".into(),
            os_isolation: "HOLD_OS_ISOLATION_NOT_PROVEN".into(),
            production_antirollback: "HOLD_EXTERNAL_MONOTONIC_ANCHOR_NOT_PROVEN".into(),
        }
    }
    fn passed(receipt: Receipt, reason: &str) -> Self {
        let mut out = Self::rejected(hold(""), "COMMITTED");
        out.state = "PASS".into();
        out.reason = reason.into();
        out.admission = Some(receipt);
        out
    }
}
fn db_error<T: std::fmt::Display>(error: T) -> Rejection {
    #[cfg(test)]
    eprintln!("fixture database failure: {error}");
    #[cfg(not(test))]
    let _ = error;
    hold("DATABASE_ERROR")
}
// Present only in the test executable, never in the fixture host/API.
#[cfg(test)]
fn fault_point(name: &str) {
    if std::env::var("VIV_FIXTURE_TEST_KILL_POINT").ok().as_deref() == Some(name) {
        use std::io::Write;
        println!("FIXTURE_KILL_READY:{name}");
        std::io::stdout().flush().unwrap();
        loop {
            std::thread::park();
        }
    }
}
#[cfg(not(test))]
fn fault_point(_: &str) {}
fn clock() -> Result<u64, Rejection> {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|v| v.as_secs())
        .map_err(|_| hold("HOST_CLOCK"))
}

pub struct Host {
    path: PathBuf,
    trust: Trust,
    receipt_identity: ReceiptIdentity,
    #[cfg(test)]
    pub(crate) storage_fault: Option<&'static str>,
}
impl Host {
    fn current_clock(&self) -> Result<u64, Rejection> {
        #[cfg(test)]
        if self.storage_fault == Some("clock-unavailable") {
            return Err(hold("HOST_CLOCK"));
        }
        clock()
    }
    /// Called by trusted fixture bootstrap/host wiring, never from candidate IPC.
    pub fn attach(
        path: PathBuf,
        trust: Trust,
        receipt_identity: ReceiptIdentity,
    ) -> Result<Self, Rejection> {
        if receipt_identity.pin.public_key_sha256 == trust.capability.public_key_sha256
            || receipt_identity.pin.public_key_sha256 == trust.evidence.public_key_sha256
        {
            return Err(hold("HOST_IDENTITY_NOT_SEPARATE"));
        }
        let host = Self {
            path,
            trust,
            receipt_identity,
            #[cfg(test)]
            storage_fault: None,
        };
        let mut db = host.open(false)?;
        let txn = db.transaction().map_err(db_error)?;
        host.verify_all(&txn)?;
        drop(txn);
        Ok(host)
    }
    /// Management/bootstrap operation; not exported over the candidate interface.
    /// Refuses existing DBs. Controller must supply a new isolated proof path.
    pub fn initialize(path: &Path, trust: &Trust) -> Result<(), Rejection> {
        let reserved = std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(path)
            .map_err(db_error)?;
        drop(reserved);
        let mut db = Connection::open_with_flags(path, OpenFlags::SQLITE_OPEN_READ_WRITE)
            .map_err(db_error)?;
        db.execute_batch(
            "PRAGMA journal_mode=DELETE; PRAGMA synchronous=EXTRA; PRAGMA foreign_keys=ON;",
        )
        .map_err(db_error)?;
        let txn = db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_error)?;
        for (_, sql) in TABLES {
            txn.execute_batch(sql).map_err(db_error)?;
        }
        txn.execute(
            "INSERT INTO meta VALUES(1,?1,0,?2)",
            params![policy::policy_hash(trust), ZERO_HASH],
        )
        .map_err(db_error)?;
        txn.commit().map_err(db_error)
    }
    fn open(&self, write: bool) -> Result<Connection, Rejection> {
        #[cfg(test)]
        if !write && self.storage_fault == Some("readback-unavailable") {
            return Err(hold("INJECTED_READBACK_UNAVAILABLE"));
        }
        let flag = if write {
            OpenFlags::SQLITE_OPEN_READ_WRITE
        } else {
            OpenFlags::SQLITE_OPEN_READ_ONLY
        };
        let db = Connection::open_with_flags(&self.path, flag).map_err(db_error)?;
        db.busy_timeout(Duration::from_millis(250))
            .map_err(db_error)?;
        // Connection-local flags only; never switch an existing journal mode.
        db.execute_batch("PRAGMA synchronous=EXTRA; PRAGMA foreign_keys=ON;")
            .map_err(db_error)?;
        let mode: String = db
            .query_row("PRAGMA journal_mode", [], |r| r.get(0))
            .map_err(db_error)?;
        let sync: i64 = db
            .query_row("PRAGMA synchronous", [], |r| r.get(0))
            .map_err(db_error)?;
        let fk: i64 = db
            .query_row("PRAGMA foreign_keys", [], |r| r.get(0))
            .map_err(db_error)?;
        if mode != "delete" || sync != 3 || fk != 1 {
            return Err(hold("SQLITE_SETTINGS"));
        }
        #[cfg(test)]
        if write {
            match self.storage_fault {
                Some("full") => {
                    db.execute_batch("PRAGMA max_page_count=1;")
                        .map_err(db_error)?;
                }
                Some("readonly") => {
                    db.execute_batch("PRAGMA query_only=ON;")
                        .map_err(db_error)?;
                }
                _ => {}
            }
        }
        Ok(db)
    }
    fn verify_all(&self, db: &Connection) -> Result<Vec<(Candidate, Receipt)>, Rejection> {
        let integrity: String = db
            .query_row("PRAGMA integrity_check", [], |r| r.get(0))
            .map_err(db_error)?;
        if integrity != "ok" {
            return Err(hold("DATABASE_INTEGRITY"));
        }
        let mut schema = db
            .prepare(
                "SELECT name,sql FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' ORDER BY name",
            )
            .map_err(db_error)?;
        let actual = schema
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .map_err(db_error)?
            .collect::<Result<Vec<_>, _>>()
            .map_err(db_error)?;
        let expected: Vec<_> = TABLES
            .iter()
            .map(|(n, s)| (n.to_string(), s.to_string()))
            .collect();
        if actual != expected {
            return Err(hold("DATABASE_SCHEMA"));
        }
        let (policy_hash, generation, head): (String, u64, String) = db
            .query_row(
                "SELECT policy,generation,head FROM meta WHERE id=1",
                [],
                |r| Ok((r.get(0)?, r.get(1)?, r.get(2)?)),
            )
            .map_err(db_error)?;
        if policy_hash != policy::policy_hash(&self.trust) {
            return Err(hold("DATABASE_POLICY"));
        }
        let mut statement = db.prepare("SELECT id,request_id,packet,receipt,generation FROM admissions ORDER BY generation").map_err(db_error)?;
        let raw = statement
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, u64>(4)?,
                ))
            })
            .map_err(db_error)?
            .collect::<Result<Vec<_>, _>>()
            .map_err(db_error)?;
        let mut rows = Vec::new();
        let mut previous = ZERO_HASH.to_string();
        let mut replay = BTreeSet::new();
        let mut last_cap = 0;
        let mut last_evidence = 0;
        for (id, request, raw_packet, raw_receipt, stored_generation) in raw {
            let packet = contract::parse_packet(raw_packet.as_bytes())
                .map_err(|_| hold("STORED_PACKET_INVALID"))?;
            let receipt: Receipt =
                serde_json::from_str(&raw_receipt).map_err(|_| hold("STORED_RECEIPT_INVALID"))?;
            receipt::verify(&receipt, &self.receipt_identity.pin)?;
            policy::adjudicate(&packet, &self.trust, receipt.adjudicated_at)
                .map_err(|_| hold("STORED_EVIDENCE_INVALID"))?;
            let next = rows.len() as u64 + 1;
            if id != receipt::admission_id(&packet)
                || request != packet.request_id
                || receipt.admission_id != id
                || receipt.packet_sha256 != packet.hash()
                || receipt.candidate_sha256 != packet.candidate_sha256
                || receipt.policy_sha256 != policy_hash
                || receipt.previous_head != previous
                || receipt.generation != next
                || stored_generation != next
                || packet.expected_generation != next - 1
                || packet.expected_head_sha256 != previous
            {
                return Err(hold("STORED_RECEIPT_BINDING"));
            }
            if packet.authorization.sequence <= last_cap {
                return Err(hold("STORED_REPLAY"));
            }
            last_cap = packet.authorization.sequence;
            if !replay.insert((
                self.trust.capability.id.clone(),
                packet.nonce.clone(),
                last_cap,
            )) {
                return Err(hold("STORED_REPLAY"));
            }
            for (i, e) in packet.evidence.iter().enumerate() {
                if e.sequence <= last_evidence {
                    return Err(hold("STORED_REPLAY"));
                }
                last_evidence = e.sequence;
                if !replay.insert((
                    self.trust.evidence.id.clone(),
                    format!("{}:{i}", packet.nonce),
                    e.sequence,
                )) {
                    return Err(hold("STORED_REPLAY"));
                }
            }
            previous = receipt.hash();
            rows.push((packet, receipt));
        }
        if generation != rows.len() as u64 || head != previous {
            return Err(hold("STORED_HEAD"));
        }
        let mut cursors = db
            .prepare("SELECT issuer,nonce,sequence FROM replay")
            .map_err(db_error)?;
        let actual_replay = cursors
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, u64>(2)?,
                ))
            })
            .map_err(db_error)?
            .collect::<Result<BTreeSet<_>, _>>()
            .map_err(db_error)?;
        if replay != actual_replay {
            return Err(hold("STORED_REPLAY_CURSOR"));
        }
        let mut requests = db.prepare("SELECT request_id,packet_hash,candidate_hash,schema_id,action,state,admission_id,receipt_hash FROM requests").map_err(db_error)?;
        let recovery = requests
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, String>(2)?,
                    r.get::<_, String>(3)?,
                    r.get::<_, String>(4)?,
                    r.get::<_, String>(5)?,
                    r.get::<_, Option<String>>(6)?,
                    r.get::<_, Option<String>>(7)?,
                ))
            })
            .map_err(db_error)?
            .collect::<Result<Vec<_>, _>>()
            .map_err(db_error)?;
        let mut committed = 0;
        let mut negative = 0;
        for (
            request,
            packet_hash,
            candidate_hash,
            schema_id,
            action,
            state,
            admission_id,
            receipt_hash,
        ) in recovery
        {
            if !contract::valid_id(&request)
                || !contract::valid_hash(&packet_hash)
                || !contract::valid_hash(&candidate_hash)
                || schema_id != contract::SCHEMA
                || action != contract::ACTION
            {
                return Err(hold("RECOVERY_STRUCTURE"));
            }
            let admission = rows.iter().find(|(p, _)| p.request_id == request);
            match (state.as_str(), admission) {
                ("PENDING", None) if admission_id.is_none() && receipt_hash.is_none() => {}
                ("REJECTED" | "HELD", None) if admission_id.is_none() && receipt_hash.is_none() => {
                    let raw: String = db
                        .query_row(
                            "SELECT record FROM dispositions WHERE request_id=?1",
                            params![request],
                            |r| r.get(0),
                        )
                        .map_err(db_error)?;
                    let d: super::disposition::Disposition =
                        serde_json::from_str(&raw).map_err(|_| hold("DISPOSITION_SCHEMA"))?;
                    d.verify(&self.receipt_identity.pin)?;
                    if d.request_id != request
                        || d.packet_hash != packet_hash
                        || d.candidate_hash != candidate_hash
                        || d.policy_hash != policy_hash
                        || (state == "REJECTED" && d.state != "FAIL")
                        || (state == "HELD" && d.state != "HOLD")
                    {
                        return Err(hold("DISPOSITION_REQUEST_BINDING"));
                    }
                    negative += 1;
                }
                ("COMMITTED", Some((p, r)))
                    if packet_hash == p.hash()
                        && candidate_hash == p.candidate_sha256
                        && schema_id == p.schema
                        && action == p.action
                        && admission_id.as_deref() == Some(r.admission_id.as_str())
                        && receipt_hash == Some(r.hash()) =>
                {
                    committed += 1;
                }
                _ => return Err(hold("RECOVERY_INTEGRITY")),
            }
        }
        if committed != rows.len() {
            return Err(hold("RECOVERY_MISSING"));
        }
        let disposition_count: u64 = db
            .query_row("SELECT count(*) FROM dispositions", [], |r| r.get(0))
            .map_err(db_error)?;
        if disposition_count != negative {
            return Err(hold("DISPOSITION_ORPHAN"));
        }
        Ok(rows)
    }
    pub fn submit_candidate(&mut self, raw: &[u8]) -> AdmissionResult {
        let mut owns_pending = false;
        match self.submit_inner(raw, &mut owns_pending) {
            Ok(receipt) => {
                let result = self.query_request(&receipt.0, &receipt.1);
                if result.state != "PASS" {
                    return AdmissionResult::rejected(hold("POSTCOMMIT_READBACK"), "UNKNOWN");
                }
                fault_point("after_readback_before_response");
                result
            }
            Err((error, uncertain)) => {
                if owns_pending && !uncertain {
                    let persisted = (|| {
                        let p =
                            contract::parse_packet(raw).map_err(|_| hold("DISPOSITION_PACKET"))?;
                        self.persist_negative(&p, &error)?;
                        Ok::<_, Rejection>(self.query_request(&p.request_id, &p.candidate_sha256))
                    })();
                    return match persisted {
                        Ok(result) => result,
                        Err(e) => AdmissionResult::rejected(e, "UNKNOWN"),
                    };
                }
                AdmissionResult::rejected(
                    error,
                    if uncertain {
                        "UNKNOWN"
                    } else {
                        "NOT_COMMITTED"
                    },
                )
            }
        }
    }
    fn persist_negative(&self, p: &Candidate, error: &Rejection) -> Result<(), Rejection> {
        let d = super::disposition::Disposition::make(
            p,
            policy::policy_hash(&self.trust),
            error,
            self.current_clock()?,
            &self.receipt_identity,
        )?;
        let mut db = self.open(true)?;
        let txn = db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(db_error)?;
        self.verify_all(&txn)?;
        let state = if error.state == "FAIL" {
            "REJECTED"
        } else {
            "HELD"
        };
        let changed=txn.execute("UPDATE requests SET state=?1 WHERE request_id=?2 AND packet_hash=?3 AND candidate_hash=?4 AND state='PENDING'",
            params![state,p.request_id,p.hash(),p.candidate_sha256]).map_err(db_error)?;
        if changed != 1 {
            return Err(hold("DISPOSITION_COMPARE_AND_SET"));
        }
        fault_point("after_negative_state_update");
        txn.execute(
            "INSERT INTO dispositions VALUES(?1,?2)",
            params![
                p.request_id,
                serde_json::to_string(&d).map_err(|_| hold("DISPOSITION_SERIALIZATION"))?
            ],
        )
        .map_err(db_error)?;
        fault_point("after_negative_record_insert");
        txn.commit()
            .map_err(|_| hold("DISPOSITION_COMMIT_UNCERTAIN"))?;
        fault_point("after_negative_commit");
        Ok(())
    }
    fn submit_inner(
        &self,
        raw: &[u8],
        owns_pending: &mut bool,
    ) -> Result<(String, String), (Rejection, bool)> {
        let pre = |e| (e, false);
        let packet = contract::parse_packet(raw).map_err(|r| pre(policy::fail(r)))?;
        fault_point("before_pending");
        // Durable recovery binding is not admission or authorization. Never retry an existing request.
        let mut pending_db = self.open(true).map_err(pre)?;
        let pending = pending_db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|e| pre(db_error(e)))?;
        self.verify_all(&pending).map_err(pre)?;
        let existing: Option<(String, String)> = pending
            .query_row(
                "SELECT packet_hash,candidate_hash FROM requests WHERE request_id=?1",
                params![packet.request_id],
                |r| Ok((r.get(0)?, r.get(1)?)),
            )
            .optional()
            .map_err(|e| pre(db_error(e)))?;
        if let Some((hash, candidate)) = existing {
            return Err(pre(
                if hash == packet.hash() && candidate == packet.candidate_sha256 {
                    hold("QUERY_REQUIRED")
                } else {
                    policy::fail("REQUEST_ID_COLLISION")
                },
            ));
        }
        pending
            .execute(
                "INSERT INTO requests VALUES(?1,?2,?3,?4,?5,'PENDING',NULL,NULL)",
                params![
                    packet.request_id,
                    packet.hash(),
                    packet.candidate_sha256,
                    packet.schema,
                    packet.action
                ],
            )
            .map_err(|e| pre(db_error(e)))?;
        pending
            .commit()
            .map_err(|_| (hold("PENDING_COMMIT_UNCERTAIN"), true))?;
        *owns_pending = true;
        fault_point("after_pending");
        policy::adjudicate(&packet, &self.trust, self.current_clock().map_err(pre)?)
            .map_err(pre)?;
        fault_point("after_adjudication");
        let mut db = self.open(true).map_err(pre)?;
        let txn = db
            .transaction_with_behavior(TransactionBehavior::Immediate)
            .map_err(|e| pre(db_error(e)))?;
        let rows = self.verify_all(&txn).map_err(pre)?;
        let bound: i64=txn.query_row("SELECT COUNT(*) FROM requests WHERE request_id=?1 AND packet_hash=?2 AND candidate_hash=?3 AND schema_id=?4 AND action=?5 AND state='PENDING'",
            params![packet.request_id,packet.hash(),packet.candidate_sha256,packet.schema,packet.action],|r|r.get(0)).map_err(|e|pre(db_error(e)))?;
        if bound != 1 {
            return Err(pre(hold("RECOVERY_BINDING")));
        }
        let generation = rows.len() as u64;
        let head = rows
            .last()
            .map(|r| r.1.hash())
            .unwrap_or_else(|| ZERO_HASH.into());
        if rows
            .iter()
            .any(|r| r.0.request_id == packet.request_id || r.0.nonce == packet.nonce)
        {
            return Err(pre(hold("REQUEST_OR_NONCE_REPLAY")));
        }
        if packet.expected_generation != generation || packet.expected_head_sha256 != head {
            return Err(pre(hold("STALE_GENERATION_OR_HEAD")));
        }
        let cap_seq = rows.last().map(|r| r.0.authorization.sequence).unwrap_or(0);
        let mut evidence_seq = rows
            .last()
            .and_then(|r| r.0.evidence.last())
            .map(|e| e.sequence)
            .unwrap_or(0);
        if packet.authorization.sequence <= cap_seq {
            return Err(pre(hold("CAPABILITY_SEQUENCE_REPLAY")));
        }
        for e in &packet.evidence {
            if e.sequence <= evidence_seq {
                return Err(pre(hold("EVIDENCE_SEQUENCE_REPLAY")));
            }
            evidence_seq = e.sequence;
        }
        let now = self.current_clock().map_err(pre)?;
        policy::adjudicate(&packet, &self.trust, now).map_err(pre)?;
        let receipt = receipt::make(
            &packet,
            &policy::policy_hash(&self.trust),
            &head,
            generation + 1,
            now,
            &self.receipt_identity,
        )
        .map_err(pre)?;
        let packet_json = serde_json::to_string(&packet)
            .map_err(|_| pre(hold("REQUIRED_PACKET_SERIALIZATION")))?;
        let receipt_json = serde_json::to_string(&receipt)
            .map_err(|_| pre(hold("REQUIRED_RECEIPT_SERIALIZATION")))?;
        fault_point("before_admission_insert");
        txn.execute(
            "INSERT INTO admissions VALUES(?1,?2,?3,?4,?5)",
            params![
                receipt.admission_id,
                packet.request_id,
                packet_json,
                receipt_json,
                generation + 1
            ],
        )
        .map_err(|e| pre(db_error(e)))?;
        fault_point("after_admission_insert");
        txn.execute(
            "INSERT INTO replay VALUES(?1,?2,?3)",
            params![
                self.trust.capability.id,
                packet.nonce,
                packet.authorization.sequence
            ],
        )
        .map_err(|e| pre(db_error(e)))?;
        for (i, e) in packet.evidence.iter().enumerate() {
            txn.execute(
                "INSERT INTO replay VALUES(?1,?2,?3)",
                params![
                    self.trust.evidence.id,
                    format!("{}:{i}", packet.nonce),
                    e.sequence
                ],
            )
            .map_err(|e| pre(db_error(e)))?;
        }
        let changed = txn
            .execute(
                "UPDATE meta SET generation=?1,head=?2 WHERE id=1 AND generation=?3 AND head=?4",
                params![generation + 1, receipt.hash(), generation, head],
            )
            .map_err(|e| pre(db_error(e)))?;
        if changed != 1 {
            return Err(pre(hold("HEAD_COMPARE_AND_SET")));
        }
        fault_point("after_head_update");
        let recovered=txn.execute("UPDATE requests SET state='COMMITTED',admission_id=?1,receipt_hash=?2 WHERE request_id=?3 AND packet_hash=?4 AND state='PENDING'",
            params![receipt.admission_id,receipt.hash(),packet.request_id,packet.hash()]).map_err(|e|pre(db_error(e)))?;
        if recovered != 1 {
            return Err(pre(hold("RECOVERY_COMPARE_AND_SET")));
        }
        fault_point("after_recovery_update");
        policy::adjudicate(&packet, &self.trust, self.current_clock().map_err(pre)?)
            .map_err(pre)?;
        txn.commit().map_err(|_| (hold("COMMIT_UNCERTAIN"), true))?;
        fault_point("after_commit_before_readback");
        Ok((packet.request_id, packet.candidate_sha256))
    }
    pub fn query_request(&mut self, request: &str, candidate_hash: &str) -> AdmissionResult {
        let outcome = (|| {
            let mut db = self.open(false)?;
            let txn = db.transaction().map_err(db_error)?;
            let rows = self.verify_all(&txn)?;
            let recovery: Option<(String, String)> = txn
                .query_row(
                    "SELECT candidate_hash,state FROM requests WHERE request_id=?1",
                    params![request],
                    |r| Ok((r.get(0)?, r.get(1)?)),
                )
                .optional()
                .map_err(db_error)?;
            match recovery {
                None => return Err(hold("REQUEST_NOT_FOUND")),
                Some((hash, _)) if hash != candidate_hash => {
                    return Err(policy::fail("REQUEST_HASH_MISMATCH"))
                }
                Some((_, state)) if state == "PENDING" => {
                    return Err(hold("NOT_COMMITTED_OR_INTERRUPTED"))
                }
                Some((_, state)) if state == "REJECTED" || state == "HELD" => {
                    let raw: String = txn
                        .query_row(
                            "SELECT record FROM dispositions WHERE request_id=?1",
                            params![request],
                            |r| r.get(0),
                        )
                        .map_err(db_error)?;
                    let d: super::disposition::Disposition =
                        serde_json::from_str(&raw).map_err(|_| hold("DISPOSITION_SCHEMA"))?;
                    let mut result =
                        AdmissionResult::rejected(hold(""), "NOT_ADMITTED_DISPOSITION_DURABLE");
                    result.state = d.state;
                    result.reason = d.reason;
                    return Ok(result);
                }
                _ => {}
            }
            rows.into_iter()
                .find(|(p, _)| p.request_id == request && p.candidate_sha256 == candidate_hash)
                .map(|(_, r)| AdmissionResult::passed(r, "ALREADY_COMMITTED"))
                .ok_or_else(|| hold("REQUEST_NOT_FOUND"))
        })();
        match outcome {
            Ok(result) => result,
            Err(e) => AdmissionResult::rejected(e, "NO_ADMISSION_RETURNED"),
        }
    }
    pub fn read_admitted(&self, id: &str) -> Result<(Candidate, Receipt), Rejection> {
        let mut db = self.open(false)?;
        let txn = db.transaction().map_err(db_error)?;
        self.verify_all(&txn)?
            .into_iter()
            .find(|(_, r)| r.admission_id == id)
            .ok_or_else(|| hold("ADMISSION_NOT_FOUND"))
    }
}

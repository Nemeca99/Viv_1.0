//! Synthetic controller material is only compiled into the test harness.
use super::{contract::*, policy::*, receipt::ReceiptIdentity, store::Host};
use crate::federation_crypto::{generate_key_material, sign_protected};
use std::{
    path::PathBuf,
    time::{SystemTime, UNIX_EPOCH},
};

struct Fixture {
    path: PathBuf,
    trust: Trust,
    identity: ReceiptIdentity,
    cap: String,
    oracle: String,
}

#[test]
fn frozen_fact_canonical_vector() {
    let fact = Fact {
        object: "fixture:block-1".into(),
        predicate: "color".into(),
        value: "blue".into(),
    };
    assert_eq!(hex::encode(fact.canonical()),"00000000000000125649562f464958545552452f464143542f31000000000000000f666978747572653a626c6f636b2d310000000000000005636f6c6f720000000000000004626c7565");
    assert_eq!(
        fact.hash(),
        "106469726EC109A4215D0E8A312E503F5F633B54CC5062E0AE850030F580339F"
    );
}

#[test]
fn full_envelope_canonical_vector() {
    let f = Fixture::new();
    let mut p = f.packet("canonical-vector-v1");
    p.authorization.policy_sha256 = ZERO_HASH.into();
    p.authorization.issued_at = 1000;
    p.authorization.expires_at = 1300;
    p.authorization.signature_hex = "11".repeat(64);
    for e in &mut p.evidence {
        e.issued_at = 1000;
        e.expires_at = 1300;
        e.signature_hex = "22".repeat(64);
    }
    p.authorization.evidence_sha256 = evidence_hash(&p.evidence);
    assert_eq!(
        p.hash(),
        "B3E88BDB0FA245FA04F458CC402E0339D1D2473AC400FB26D46B94DBAE93DB86"
    );
    let vector = serde_json::json!({"scope":"encoding-only-invalid-signatures-no-authority","packet":p,"canonical_hex":hex::encode(p.canonical()),"sha256":p.hash()});
    let file = f.path.with_file_name("canonical-vector.json");
    use std::io::Write;
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&file)
        .unwrap()
        .write_all(&serde_json::to_vec_pretty(&vector).unwrap())
        .unwrap();
    let run=std::process::Command::new("C:/Users/nemec/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe")
        .args(["-c","import runpy,json,sys; m=runpy.run_path(sys.argv[1]); v=json.load(open(sys.argv[2])); b=m['candidate'](v['packet']); assert b.hex()==v['canonical_hex']; assert m['digest'](b)==v['sha256']; print(v['sha256'])"])
        .arg("L:/Continue/Viv/foundation/artifacts/auto/rust_durable_admission_fixture_v0/independent_verify.py").arg(&file).output().unwrap();
    assert!(
        run.status.success(),
        "{}",
        String::from_utf8_lossy(&run.stderr)
    );
    println!(
        "CANONICAL_VECTOR path={} sha256={}",
        file.display(),
        p.hash()
    );
}
impl Fixture {
    fn new() -> Self {
        static NEXT: std::sync::atomic::AtomicU64 = std::sync::atomic::AtomicU64::new(0);
        let root = PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("target")
            .join("durable_admission_fixtures");
        std::fs::create_dir_all(&root).unwrap();
        let path = root.join(format!(
            "test-{}-{}-{}",
            std::process::id(),
            SystemTime::now()
                .duration_since(UNIX_EPOCH)
                .unwrap()
                .as_nanos(),
            NEXT.fetch_add(1, std::sync::atomic::Ordering::Relaxed)
        ));
        std::fs::create_dir(&path).unwrap();
        let key = |id: &str| {
            let k = generate_key_material(id).unwrap();
            (
                IssuerPin {
                    id: id.into(),
                    public_key_hex: k.public_key_hex,
                    public_key_sha256: k.public_key_sha256,
                },
                k.protected_private_key_hex,
            )
        };
        let (cap_pin, cap) = key("fixture-capability");
        let (oracle_pin, oracle) = key("fixture-evidence");
        let (pin, protected_private_key_hex) = key("fixture-host");
        let out = Self {
            path: path.join("fixture.sqlite"),
            trust: Trust {
                capability: cap_pin,
                evidence: oracle_pin,
            },
            identity: ReceiptIdentity {
                pin,
                protected_private_key_hex,
            },
            cap,
            oracle,
        };
        Host::initialize(&out.path, &out.trust).unwrap();
        out
    }
    fn host(&self) -> Host {
        Host::attach(self.path.clone(), self.trust.clone(), self.identity.clone()).unwrap()
    }
    fn packet(&self, id: &str) -> Candidate {
        let now = SystemTime::now()
            .duration_since(UNIX_EPOCH)
            .unwrap()
            .as_secs();
        let payload = Fact {
            object: "fixture:block-1".into(),
            predicate: "color".into(),
            value: "blue".into(),
        };
        let provenance = Provenance {
            origin: "probabilistic_candidate".into(),
            producer: "fixture-python".into(),
            input_sha256: digest(b"synthetic"),
            source_ref: "fixture:input".into(),
        };
        let evidence = Evidence {
            schema: "viv_fixture_evidence_v1".into(),
            issuer_id: self.trust.evidence.id.clone(),
            role: "fixture_oracle".into(),
            universe: UNIVERSE.into(),
            fact: payload.clone(),
            sequence: 1,
            issued_at: now,
            expires_at: now + 300,
            signature_hex: String::new(),
        };
        let grant = Grant {
            schema: "viv_fixture_grant_v1".into(),
            issuer_id: self.trust.capability.id.clone(),
            role: "fixture_capability".into(),
            grant_id: format!("grant:{id}"),
            request_id: id.into(),
            nonce: format!("nonce:{id}"),
            action: ACTION.into(),
            universe: UNIVERSE.into(),
            namespace: NAMESPACE.into(),
            candidate_id: format!("candidate:{id}"),
            candidate_sha256: payload.hash(),
            provenance_sha256: provenance.hash(),
            evidence_sha256: String::new(),
            expected_generation: 0,
            expected_head_sha256: ZERO_HASH.into(),
            policy_sha256: policy_hash(&self.trust),
            sequence: 1,
            issued_at: now,
            expires_at: now + 300,
            signature_hex: String::new(),
        };
        let mut p = Candidate {
            schema: SCHEMA.into(),
            action: ACTION.into(),
            request_id: id.into(),
            nonce: grant.nonce.clone(),
            universe: UNIVERSE.into(),
            namespace: NAMESPACE.into(),
            candidate_id: grant.candidate_id.clone(),
            candidate_sha256: payload.hash(),
            payload,
            expected_generation: 0,
            expected_head_sha256: ZERO_HASH.into(),
            provenance_sha256: provenance.hash(),
            provenance,
            evidence: vec![evidence],
            authorization: grant,
        };
        self.sign(&mut p);
        p
    }
    fn sign(&self, p: &mut Candidate) {
        for e in &mut p.evidence {
            e.signature_hex =
                sign_protected(&self.trust.evidence.id, &self.oracle, &e.signing_bytes()).unwrap();
        }
        p.authorization.evidence_sha256 = evidence_hash(&p.evidence);
        p.authorization.signature_hex = sign_protected(
            &self.trust.capability.id,
            &self.cap,
            &p.authorization.signing_bytes(),
        )
        .unwrap();
    }
    fn counts(&self) -> (u64, u64, u64) {
        let db = rusqlite::Connection::open_with_flags(
            &self.path,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY,
        )
        .unwrap();
        db.query_row("SELECT (SELECT count(*) FROM admissions),(SELECT count(*) FROM requests),(SELECT generation FROM meta)",[],|r|Ok((r.get(0)?,r.get(1)?,r.get(2)?))).unwrap()
    }
    fn snapshot(&self) -> serde_json::Value {
        Self::snapshot_at(&self.path)
    }
    fn snapshot_at(path: &std::path::Path) -> serde_json::Value {
        let db =
            rusqlite::Connection::open_with_flags(path, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
                .unwrap();
        let (generation, head): (u64, String) = db
            .query_row("SELECT generation,head FROM meta", [], |r| {
                Ok((r.get(0)?, r.get(1)?))
            })
            .unwrap();
        let mut s = db
            .prepare("SELECT issuer,nonce,sequence FROM replay ORDER BY issuer,sequence")
            .unwrap();
        let replay = s
            .query_map([], |r| {
                Ok((
                    r.get::<_, String>(0)?,
                    r.get::<_, String>(1)?,
                    r.get::<_, u64>(2)?,
                ))
            })
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let mut s = db
            .prepare("SELECT request_id,state FROM requests ORDER BY request_id")
            .unwrap();
        let recovery = s
            .query_map([], |r| Ok((r.get::<_, String>(0)?, r.get::<_, String>(1)?)))
            .unwrap()
            .collect::<Result<Vec<_>, _>>()
            .unwrap();
        let admissions: u64 = db
            .query_row("SELECT count(*) FROM admissions", [], |r| r.get(0))
            .unwrap();
        serde_json::json!({"admissions":admissions,"generation":generation,"head":head,"replay":replay,"recovery":recovery})
    }
    fn observe(
        &self,
        case: &str,
        raw: &[u8],
        expected_state: &str,
        expected_reason: &str,
    ) -> super::store::AdmissionResult {
        let before = self.snapshot();
        let result = self.host().submit_candidate(raw);
        let after = self.snapshot();
        let receipt = serde_json::json!({"case_id":case,"expected":{"state":expected_state,"reason":expected_reason},"observed":result,
            "request_sha256":digest(raw),"before":before,"after":after,"fresh_process":"NOT_APPLICABLE_IN_PROCESS_CASE"});
        let path = self.path.with_file_name(format!("case-{case}.json"));
        use std::io::Write;
        std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .unwrap()
            .write_all(&serde_json::to_vec_pretty(&receipt).unwrap())
            .unwrap();
        println!(
            "CASE_RECEIPT path={} sha256={}",
            path.display(),
            digest(&std::fs::read(&path).unwrap())
        );
        assert_eq!(result.state, expected_state, "{case}: {result:?}");
        assert_eq!(result.reason, expected_reason, "{case}: {result:?}");
        result
    }
    fn record(&self, case: &str, record: serde_json::Value) {
        let path = self.path.with_file_name(format!("case-{case}.json"));
        use std::io::Write;
        std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .unwrap()
            .write_all(&serde_json::to_vec_pretty(&record).unwrap())
            .unwrap();
        println!(
            "CASE_RECEIPT path={} sha256={}",
            path.display(),
            digest(&std::fs::read(&path).unwrap())
        );
    }
}

#[test]
fn signed_admission_replay_and_durable_query() {
    let f = Fixture::new();
    let p = f.packet("positive");
    let raw = serde_json::to_vec(&p).unwrap();
    let result = f.observe("positive", &raw, "PASS", "ALREADY_COMMITTED");
    assert_eq!(result.state, "PASS", "{result:?}");
    assert_eq!(f.counts(), (1, 1, 1));
    f.observe("exact-replay", &raw, "HOLD", "QUERY_REQUIRED");
    assert_eq!(f.counts(), (1, 1, 1));
    let mut restarted = f.host();
    assert_eq!(
        restarted
            .query_request(&p.request_id, &p.candidate_sha256)
            .state,
        "PASS"
    );
    assert_eq!(
        restarted.query_request(&p.request_id, ZERO_HASH).reason,
        "REQUEST_HASH_MISMATCH"
    );
    let receipt = result.admission.unwrap();
    assert_eq!(restarted.read_admitted(&receipt.admission_id).unwrap().0, p);
}

#[test]
fn signed_false_fact_retains_rejected_disposition_without_admission() {
    let f = Fixture::new();
    let mut p = f.packet("false");
    p.payload.value = "red".into();
    p.candidate_sha256 = p.payload.hash();
    p.authorization.candidate_sha256 = p.candidate_sha256.clone();
    p.evidence[0].fact = p.payload.clone();
    f.sign(&mut p);
    let raw = serde_json::to_vec(&p).unwrap();
    let result = f.observe(
        "signed-false-fact",
        &raw,
        "FAIL",
        "FALSE_OR_UNSUPPORTED_FIXTURE_FACT",
    );
    assert_eq!(
        result.reason, "FALSE_OR_UNSUPPORTED_FIXTURE_FACT",
        "{result:?}"
    );
    assert_eq!(f.counts(), (0, 1, 0));
    let recovered = f.host().query_request(&p.request_id, &p.candidate_sha256);
    assert_eq!(recovered.reason, "FALSE_OR_UNSUPPORTED_FIXTURE_FACT");
    assert_eq!(recovered.state, "FAIL");
    assert_eq!(recovered.commit_status, "NOT_ADMITTED_DISPOSITION_DURABLE");
    assert_eq!(f.host().submit_candidate(&raw).reason, "QUERY_REQUIRED");
    assert_eq!(f.counts(), (0, 1, 0));
}

#[test]
fn negative_adjudication_board_preserves_authoritative_state() {
    for case in [
        "missing_evidence",
        "unknown_evidence",
        "unknown_capability",
        "altered_payload",
        "altered_provenance",
        "scope",
        "expired",
        "future",
        "stale_head",
        "wrong_candidate_grant",
        "wrong_action_grant",
        "wrong_universe",
        "policy_mismatch",
        "evidence_expired",
        "capability_bad_signature",
        "evidence_bad_signature",
    ] {
        let f = Fixture::new();
        let mut p = f.packet(case);
        let expected = match case {
            "missing_evidence" => {
                p.evidence.clear();
                f.sign(&mut p);
                "MISSING_EVIDENCE"
            }
            "unknown_evidence" => {
                p.evidence[0].issuer_id = "unknown".into();
                f.sign(&mut p);
                "UNKNOWN_EVIDENCE_ISSUER"
            }
            "unknown_capability" => {
                p.authorization.issuer_id = "unknown".into();
                "UNKNOWN_CAPABILITY_ISSUER"
            }
            "altered_payload" => {
                p.payload.value = "red".into();
                "CONTENT_HASH_MISMATCH"
            }
            "altered_provenance" => {
                p.provenance.producer = "other".into();
                "CONTENT_HASH_MISMATCH"
            }
            "scope" => {
                p.namespace = "other".into();
                "FIXTURE_SCOPE"
            }
            "expired" => {
                p.authorization.issued_at -= 301;
                p.authorization.expires_at -= 301;
                f.sign(&mut p);
                "ENVELOPE_TIME"
            }
            "future" => {
                p.authorization.issued_at += 301;
                p.authorization.expires_at += 301;
                f.sign(&mut p);
                "ENVELOPE_TIME"
            }
            "stale_head" => {
                p.expected_generation = 1;
                p.authorization.expected_generation = 1;
                f.sign(&mut p);
                "STALE_GENERATION_OR_HEAD"
            }
            "wrong_candidate_grant" => {
                p.authorization.candidate_id = "another".into();
                f.sign(&mut p);
                "GRANT_BINDING"
            }
            "wrong_action_grant" => {
                p.authorization.action = "another".into();
                f.sign(&mut p);
                "GRANT_BINDING"
            }
            "wrong_universe" => {
                p.universe = "another".into();
                "FIXTURE_SCOPE"
            }
            "policy_mismatch" => {
                p.authorization.policy_sha256 = ZERO_HASH.into();
                f.sign(&mut p);
                "POLICY_MISMATCH"
            }
            "evidence_expired" => {
                p.evidence[0].issued_at -= 301;
                p.evidence[0].expires_at -= 301;
                f.sign(&mut p);
                "ENVELOPE_TIME"
            }
            "capability_bad_signature" => {
                p.authorization.signature_hex = "00".repeat(64);
                "SIGNATURE_INVALID"
            }
            "evidence_bad_signature" => {
                p.evidence[0].signature_hex = "00".repeat(64);
                p.authorization.evidence_sha256 = evidence_hash(&p.evidence);
                p.authorization.signature_hex = sign_protected(
                    &f.trust.capability.id,
                    &f.cap,
                    &p.authorization.signing_bytes(),
                )
                .unwrap();
                "SIGNATURE_INVALID"
            }
            _ => unreachable!(),
        };
        let state = if [
            "altered_payload",
            "altered_provenance",
            "scope",
            "wrong_candidate_grant",
            "wrong_action_grant",
            "wrong_universe",
            "capability_bad_signature",
            "evidence_bad_signature",
        ]
        .contains(&case)
        {
            "FAIL"
        } else {
            "HOLD"
        };
        let result = f.observe(case, &serde_json::to_vec(&p).unwrap(), state, expected);
        assert_eq!(result.reason, expected, "{case}: {result:?}");
        assert_eq!(f.counts(), (0, 1, 0), "{case}");
        println!(
            "{case}: {} / {}; durable delta admissions=0 requests=1 generation=0",
            result.state, result.reason
        );
    }
}

#[test]
fn same_head_concurrency_and_request_collision() {
    let f = Fixture::new();
    let a = f.packet("race-a");
    let b = f.packet("race-b");
    let before = f.snapshot();
    let mut ha = f.host();
    let mut hb = f.host();
    let barrier = std::sync::Arc::new(std::sync::Barrier::new(2));
    let second = barrier.clone();
    let raw = serde_json::to_vec(&a).unwrap();
    let worker = std::thread::spawn(move || {
        barrier.wait();
        ha.submit_candidate(&raw)
    });
    second.wait();
    let rb = hb.submit_candidate(&serde_json::to_vec(&b).unwrap());
    let ra = worker.join().unwrap();
    assert_eq!(
        [&ra, &rb].iter().filter(|r| r.state == "PASS").count(),
        1,
        "{ra:?} {rb:?}"
    );
    assert_eq!(f.counts().0, 1);
    assert_eq!(f.counts().2, 1);
    f.record("same-head-race",serde_json::json!({"case_id":"same-head-race","expected":"exactly one PASS, other HOLD","observed":[ra,rb],"before":before,"after":f.snapshot(),"fresh_process":"two Host instances on concurrent threads"}));
    let mut changed = a.clone();
    changed.provenance.producer = "collision".into();
    f.observe(
        "request-collision",
        &serde_json::to_vec(&changed).unwrap(),
        "FAIL",
        "REQUEST_ID_COLLISION",
    );
}

#[test]
fn unrelated_query_cannot_resolve_pending_and_corruption_holds() {
    let f = Fixture::new();
    let mut pending = f.packet("pending");
    pending.evidence.clear();
    f.sign(&mut pending);
    assert_eq!(
        f.host()
            .submit_candidate(&serde_json::to_vec(&pending).unwrap())
            .state,
        "HOLD"
    );
    let p = f.packet("good");
    let good = f.host().submit_candidate(&serde_json::to_vec(&p).unwrap());
    assert_eq!(good.state, "PASS");
    let mut host = f.host();
    assert_eq!(
        host.query_request(&p.request_id, &p.candidate_sha256).state,
        "PASS"
    );
    assert_eq!(
        host.query_request(&pending.request_id, &pending.candidate_sha256)
            .reason,
        "MISSING_EVIDENCE"
    );
    // Intentionally mutate only this freshly allocated disposable DB as hostile same-user evidence.
    let db =
        rusqlite::Connection::open_with_flags(&f.path, rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE)
            .unwrap();
    db.execute(
        "UPDATE requests SET receipt_hash=?1 WHERE state='COMMITTED'",
        [ZERO_HASH],
    )
    .unwrap();
    drop(db);
    assert_eq!(
        host.query_request(&p.request_id, &p.candidate_sha256)
            .reason,
        "RECOVERY_INTEGRITY"
    );
    assert!(Host::attach(f.path.clone(), f.trust.clone(), f.identity.clone()).is_err());
}

#[test]
fn busy_database_and_receipt_failure_never_admit() {
    let f = Fixture::new();
    let p = f.packet("busy");
    let raw = serde_json::to_vec(&p).unwrap();
    let mut host = f.host();
    let before = f.snapshot();
    let db =
        rusqlite::Connection::open_with_flags(&f.path, rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE)
            .unwrap();
    db.execute_batch("BEGIN IMMEDIATE").unwrap();
    let locked = host.submit_candidate(&raw);
    assert_eq!(locked.reason, "DATABASE_ERROR");
    db.execute_batch("ROLLBACK").unwrap();
    drop(db);
    f.record("database-busy",serde_json::json!({"case_id":"database-busy","expected":{"state":"HOLD","reason":"DATABASE_ERROR"},"observed":locked,"before":before,"after":f.snapshot(),"fresh_process":"NOT_APPLICABLE"}));
    assert_eq!(f.counts(), (0, 0, 0));
    let mut bad_identity = f.identity.clone();
    bad_identity.protected_private_key_hex = "00".into();
    let mut broken = Host::attach(f.path.clone(), f.trust.clone(), bad_identity).unwrap();
    let before = f.snapshot();
    let failed = broken.submit_candidate(&raw);
    f.record("signing-failure",serde_json::json!({"case_id":"signing-failure","expected":{"state":"HOLD","reason":"DISPOSITION_SIGNING_FAILED","commit_status":"UNKNOWN"},"observed":failed,"before":before,"after":f.snapshot(),"fresh_process":"NOT_APPLICABLE"}));
    assert_eq!(failed.reason, "DISPOSITION_SIGNING_FAILED");
    assert_eq!(failed.commit_status, "UNKNOWN");
    assert_eq!(f.counts(), (0, 1, 0));
    assert_eq!(
        host.query_request(&p.request_id, &p.candidate_sha256)
            .reason,
        "NOT_COMMITTED_OR_INTERRUPTED"
    );
}

#[test]
fn nonce_and_sequence_replays_do_not_advance_head() {
    for kind in ["nonce", "capability_sequence", "evidence_sequence"] {
        let f = Fixture::new();
        let first = f.packet("first");
        let admitted = f
            .host()
            .submit_candidate(&serde_json::to_vec(&first).unwrap());
        assert_eq!(admitted.state, "PASS");
        let receipt = admitted.admission.unwrap();
        let mut p = f.packet(kind);
        p.expected_generation = 1;
        p.expected_head_sha256 = receipt.hash();
        p.authorization.expected_generation = 1;
        p.authorization.expected_head_sha256 = receipt.hash();
        p.authorization.sequence = 2;
        p.evidence[0].sequence = 2;
        let expected = match kind {
            "nonce" => {
                p.nonce = first.nonce.clone();
                p.authorization.nonce = p.nonce.clone();
                "REQUEST_OR_NONCE_REPLAY"
            }
            "capability_sequence" => {
                p.authorization.sequence = 1;
                "CAPABILITY_SEQUENCE_REPLAY"
            }
            _ => {
                p.evidence[0].sequence = 1;
                "EVIDENCE_SEQUENCE_REPLAY"
            }
        };
        f.sign(&mut p);
        let result = f.observe(kind, &serde_json::to_vec(&p).unwrap(), "HOLD", expected);
        assert_eq!(result.reason, expected, "{kind}: {result:?}");
        assert_eq!(f.counts(), (1, 2, 1));
        assert_eq!(
            f.host()
                .query_request(&first.request_id, &first.candidate_sha256)
                .admission
                .unwrap()
                .hash(),
            receipt.hash()
        );
    }
}

#[test]
fn malformed_and_injected_packets_do_not_create_recovery_rows() {
    let f = Fixture::new();
    let p = f.packet("wire");
    let raw = serde_json::to_string(&p).unwrap();
    let mut cases = vec![
        ("empty", Vec::new(), "PACKET_SIZE"),
        ("missing-fields", b"{}".to_vec(), "PACKET_SCHEMA"),
        (
            "trailing",
            format!("{raw} {{}}").into_bytes(),
            "PACKET_TRAILING",
        ),
        ("oversize", vec![b'x'; MAX_PACKET + 1], "PACKET_SIZE"),
        ("invalid-utf8", vec![0xff], "PACKET_SCHEMA"),
    ];
    for (name, field) in [
        ("verdict-injection", r#""verdict":"PASS""#),
        ("path-injection", r#""db_path":"other.sqlite""#),
        ("key-injection", r#""key":"attacker""#),
        ("duplicate-key", r#""schema":"duplicate""#),
    ] {
        cases.push((
            name,
            format!("{{{field},{}", &raw[1..]).into_bytes(),
            "PACKET_SCHEMA",
        ));
    }
    let mut oversized = p.clone();
    oversized.evidence = vec![p.evidence[0].clone(); MAX_EVIDENCE + 1];
    cases.push((
        "evidence-oversize",
        serde_json::to_vec(&oversized).unwrap(),
        "EVIDENCE_SIZE",
    ));
    let mut changed = p.clone();
    changed.action = "unsupported".into();
    cases.push((
        "unknown-action",
        serde_json::to_vec(&changed).unwrap(),
        "PACKET_SCHEMA",
    ));
    changed = p.clone();
    changed.schema = "unsupported".into();
    cases.push((
        "unknown-schema",
        serde_json::to_vec(&changed).unwrap(),
        "PACKET_SCHEMA",
    ));
    for (name, case, reason) in cases {
        f.observe(name, &case, "FAIL", reason);
        assert_eq!(f.counts(), (0, 0, 0));
    }
}

#[test]
fn corrupt_receipt_evidence_and_atomic_links_fail_closed() {
    for case in [
        "receipt",
        "evidence",
        "pending_with_admission",
        "committed_without_admission",
        "replay_cursor",
    ] {
        let f = Fixture::new();
        let p = f.packet(case);
        assert_eq!(
            f.host()
                .submit_candidate(&serde_json::to_vec(&p).unwrap())
                .state,
            "PASS"
        );
        let original = f.snapshot();
        let db = rusqlite::Connection::open_with_flags(
            &f.path,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE,
        )
        .unwrap();
        match case {
            "receipt" => {
                let raw: String = db
                    .query_row("SELECT receipt FROM admissions", [], |r| r.get(0))
                    .unwrap();
                let mut r: super::receipt::Receipt = serde_json::from_str(&raw).unwrap();
                r.signature_hex = "00".repeat(64);
                db.execute(
                    "UPDATE admissions SET receipt=?1",
                    [serde_json::to_string(&r).unwrap()],
                )
                .unwrap();
            }
            "evidence" => {
                let mut altered = p.clone();
                altered.evidence[0].fact.value = "red".into();
                db.execute(
                    "UPDATE admissions SET packet=?1",
                    [serde_json::to_string(&altered).unwrap()],
                )
                .unwrap();
            }
            "pending_with_admission" => {
                db.execute(
                    "UPDATE requests SET state='PENDING',admission_id=NULL,receipt_hash=NULL",
                    [],
                )
                .unwrap();
            }
            "replay_cursor" => {
                db.execute("DELETE FROM replay", []).unwrap();
            }
            _ => {
                db.execute("DELETE FROM admissions", []).unwrap();
            }
        }
        drop(db);
        let tampered = f.snapshot();
        let rejected = Host::attach(f.path.clone(), f.trust.clone(), f.identity.clone());
        assert!(rejected.is_err(), "corruption accepted: {case}");
        let error = rejected.err().unwrap();
        f.record(case,serde_json::json!({"case_id":format!("corrupt-{case}"),"expected":{"state":"HOLD"},"observed":{"state":error.state,"reason":error.reason},"before":tampered,"after":f.snapshot(),"before_deliberate_tampering":original,"mutation_origin":"test_controller_only","fresh_process":"new Host in existing process"}));
        println!("corruption {case}: HOLD on attach");
    }
}

#[test]
fn restored_valid_older_store_requires_external_rollback_anchor() {
    let f = Fixture::new();
    let backup = f.path.with_file_name("empty-parent.sqlite");
    // Preserve parent snapshot; restoration goes to a NEW path, never over original evidence.
    std::fs::copy(&f.path, &backup).unwrap();
    let p = f.packet("advance");
    let admitted = f.host().submit_candidate(&serde_json::to_vec(&p).unwrap());
    assert_eq!(admitted.state, "PASS");
    let expected_head = admitted.admission.unwrap().hash();
    let mut restored = Host::attach(backup.clone(), f.trust.clone(), f.identity.clone()).unwrap();
    let before = Fixture::snapshot_at(&backup);
    let result = restored.query_request(&p.request_id, &p.candidate_sha256);
    assert_eq!(result.reason, "REQUEST_NOT_FOUND");
    assert_eq!(
        result.production_antirollback,
        "HOLD_EXTERNAL_MONOTONIC_ANCHOR_NOT_PROVEN"
    );
    let db =
        rusqlite::Connection::open_with_flags(&backup, rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY)
            .unwrap();
    let actual_head: String = db
        .query_row("SELECT head FROM meta", [], |r| r.get(0))
        .unwrap();
    assert_ne!(actual_head, expected_head);
    f.record("rollback",serde_json::json!({"case_id":"rollback","expected":{"state":"HOLD","reason":"REQUEST_NOT_FOUND"},"observed":result,"before":before,"after":Fixture::snapshot_at(&backup),"controller_expected_head":expected_head,"restored_head":actual_head,"fresh_process":"new Host instance","production_antirollback":"HOLD_EXTERNAL_MONOTONIC_ANCHOR_NOT_PROVEN"}));
    println!("rollback: valid older store accepted structurally; controller frozen head detects mismatch; production antirollback remains HOLD");
}

#[derive(serde::Serialize, serde::Deserialize)]
struct WorkerInput {
    path: PathBuf,
    trust: Trust,
    identity: ReceiptIdentity,
    packet: Candidate,
}

#[test]
fn python_client_write_demonstrates_os_isolation_hold() {
    let f = Fixture::new();
    let p = f.packet("client-write");
    assert_eq!(
        f.host()
            .submit_candidate(&serde_json::to_vec(&p).unwrap())
            .state,
        "PASS"
    );
    let before = f.snapshot();
    let result=std::process::Command::new("C:/Users/nemec/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe")
        .args(["-c","import sqlite3,sys; c=sqlite3.connect(sys.argv[1]); c.execute('UPDATE meta SET head=?', ('0'*64,)); c.commit(); c.close(); print('DIRECT_CLIENT_WRITE_SUCCEEDED')"])
        .arg(&f.path).output().unwrap();
    assert!(result.status.success());
    assert!(Host::attach(f.path.clone(), f.trust.clone(), f.identity.clone()).is_err());
    f.record("python-direct-write",serde_json::json!({"case_id":"python-direct-write","expected":"client write succeeds; Rust HOLD; OS isolation unproven","observed":{"client_exit":result.status.code(),"rust_attach":"HOLD","os_isolation":"HOLD_OS_ISOLATION_NOT_PROVEN"},"before":before,"after":f.snapshot(),"mutation_origin":"explicit adversarial Python subprocess","fresh_process":true}));
    println!("Python direct disposable-DB write succeeded; subsequent Rust attach HOLD; HOLD_OS_ISOLATION_NOT_PROVEN remains");
}

#[test]
fn sqlite_full_and_readonly_errors_never_admit() {
    for mode in ["full", "readonly"] {
        let f = Fixture::new();
        let mut p = f.packet(mode);
        p.evidence = vec![p.evidence[0].clone(); 8];
        for (i, e) in p.evidence.iter_mut().enumerate() {
            e.sequence = i as u64 + 1;
        }
        f.sign(&mut p);
        let mut host = f.host();
        host.storage_fault = Some(mode);
        let before = f.snapshot();
        let r = host.submit_candidate(&serde_json::to_vec(&p).unwrap());
        f.record(mode,serde_json::json!({"case_id":mode,"expected":{"state":"HOLD","reason":"DATABASE_ERROR"},"observed":r,"before":before,"after":f.snapshot(),"request_sha256":digest(&serde_json::to_vec(&p).unwrap()),"fresh_process":"NOT_APPLICABLE","scope":"SQLite fault settings, not physical disk or OS ACL proof"}));
        assert_eq!(r.state, "HOLD", "{mode}: {r:?}");
        assert_eq!(r.reason, "DATABASE_ERROR", "{mode}: {r:?}");
        assert_eq!(f.counts().0, 0);
        assert_eq!(f.counts().2, 0);
        println!(
            "SQLite {mode}: HOLD DATABASE_ERROR; counts {:?}",
            f.counts()
        );
    }
}

#[test]
fn postcommit_readback_failure_returns_unknown_then_query_recovers() {
    let f = Fixture::new();
    let p = f.packet("readback-failure");
    let raw = serde_json::to_vec(&p).unwrap();
    let before = f.snapshot();
    let mut host = f.host();
    host.storage_fault = Some("readback-unavailable");
    let result = host.submit_candidate(&raw);
    assert_eq!(result.state, "HOLD");
    assert_eq!(result.reason, "POSTCOMMIT_READBACK");
    assert_eq!(result.commit_status, "UNKNOWN");
    assert_eq!(f.counts(), (1, 1, 1));
    let committed = f.snapshot();
    // Resolve exclusively through a new reader, never by mutation/retry.
    let recovered = f.host().query_request(&p.request_id, &p.candidate_sha256);
    assert_eq!(recovered.state, "PASS");
    assert_eq!(f.snapshot(), committed);
    f.record("postcommit-readback-failure",serde_json::json!({"case_id":"postcommit-readback-failure","expected":{"state":"HOLD","reason":"POSTCOMMIT_READBACK","commit_status":"UNKNOWN"},"observed":result,"before":before,"after":committed,"resolution":recovered,"after_resolution":f.snapshot(),"fresh_process":"new Host instance","fault":"cfg(test) read-only connection unavailable"}));
}

#[test]
fn held_request_does_not_block_fresh_authorized_work() {
    let f = Fixture::new();
    let mut old = f.packet("held-instance");
    old.evidence.clear();
    f.sign(&mut old);
    f.observe(
        "liveness-held",
        &serde_json::to_vec(&old).unwrap(),
        "HOLD",
        "MISSING_EVIDENCE",
    );
    let fresh = f.packet("fresh-evidence-instance");
    f.observe(
        "liveness-fresh",
        &serde_json::to_vec(&fresh).unwrap(),
        "PASS",
        "ALREADY_COMMITTED",
    );
    let before = f.snapshot();
    let old_result = f
        .host()
        .query_request(&old.request_id, &old.candidate_sha256);
    assert_eq!(old_result.reason, "MISSING_EVIDENCE");
    assert_eq!(f.snapshot(), before);
    f.observe(
        "liveness-old-not-retried",
        &serde_json::to_vec(&old).unwrap(),
        "HOLD",
        "QUERY_REQUIRED",
    );
}

#[test]
fn unavailable_clock_and_changed_trust_fail_closed() {
    let f = Fixture::new();
    let p = f.packet("clock-unavailable");
    let before = f.snapshot();
    let mut host = f.host();
    host.storage_fault = Some("clock-unavailable");
    let result = host.submit_candidate(&serde_json::to_vec(&p).unwrap());
    assert_eq!(result.state, "HOLD");
    assert_eq!(result.reason, "HOST_CLOCK");
    assert_eq!(f.counts(), (0, 1, 0));
    f.record("clock-unavailable",serde_json::json!({"case_id":"clock-unavailable","expected":{"state":"HOLD","reason":"HOST_CLOCK"},"observed":result,"before":before,"after":f.snapshot(),"fault":"test-only clock acquisition failure; system clock untouched","fresh_process":"NOT_APPLICABLE"}));
    let mut changed = f.trust.clone();
    changed.capability.id = "replacement-issuer".into();
    let before = f.snapshot();
    let outcome = Host::attach(f.path.clone(), changed, f.identity.clone());
    assert!(outcome.is_err());
    let error = outcome.err().unwrap();
    assert_eq!(error.reason, "DATABASE_POLICY");
    f.record("changed-trust",serde_json::json!({"case_id":"changed-trust","expected":{"state":"HOLD","reason":"DATABASE_POLICY"},"observed":{"state":error.state,"reason":error.reason},"before":before,"after":f.snapshot(),"fresh_process":"new Host instance","scope":"fixture trust pin replacement, not production revocation service"}));
}

#[test]
fn terminal_disposition_tampering_is_not_recoverable_truth() {
    for case in ["reason", "state", "orphan"] {
        let f = Fixture::new();
        let mut p = f.packet(case);
        p.evidence.clear();
        f.sign(&mut p);
        assert_eq!(
            f.host()
                .submit_candidate(&serde_json::to_vec(&p).unwrap())
                .reason,
            "MISSING_EVIDENCE"
        );
        let db = rusqlite::Connection::open_with_flags(
            &f.path,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE,
        )
        .unwrap();
        if case == "orphan" {
            db.execute("UPDATE requests SET state='PENDING'", [])
                .unwrap();
        } else {
            let raw: String = db
                .query_row("SELECT record FROM dispositions", [], |r| r.get(0))
                .unwrap();
            let mut d: super::disposition::Disposition = serde_json::from_str(&raw).unwrap();
            if case == "reason" {
                d.reason = "fabricated".into();
            } else {
                d.state = "FAIL".into();
            }
            db.execute(
                "UPDATE dispositions SET record=?1",
                [serde_json::to_string(&d).unwrap()],
            )
            .unwrap();
        }
        drop(db);
        let before = f.snapshot();
        let rejected = Host::attach(f.path.clone(), f.trust.clone(), f.identity.clone());
        assert!(rejected.is_err());
        let e = rejected.err().unwrap();
        f.record(&format!("terminal-tamper-{case}"),serde_json::json!({"case_id":format!("terminal-tamper-{case}"),"expected":{"state":"HOLD"},"observed":{"state":e.state,"reason":e.reason},"before":before,"after":f.snapshot(),"fresh_process":"new Host instance"}));
        assert_eq!(f.counts(), (0, 1, 0));
    }
}

#[test]
fn independent_python_admission_chain_verification() {
    let f = Fixture::new();
    let p = f.packet("independent");
    assert_eq!(
        f.host()
            .submit_candidate(&serde_json::to_vec(&p).unwrap())
            .state,
        "PASS"
    );
    let mut held = f.packet("independent-held");
    held.evidence.clear();
    f.sign(&mut held);
    assert_eq!(
        f.host()
            .submit_candidate(&serde_json::to_vec(&held).unwrap())
            .state,
        "HOLD"
    );
    let mut rejected = f.packet("independent-rejected");
    rejected.payload.value = "red".into();
    assert_eq!(
        f.host()
            .submit_candidate(&serde_json::to_vec(&rejected).unwrap())
            .state,
        "FAIL"
    );
    let pins = f.path.with_file_name("public-pins.json");
    let public = serde_json::json!({"trust":f.trust,"host":f.identity.pin});
    use std::io::Write;
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&pins)
        .unwrap()
        .write_all(&serde_json::to_vec(&public).unwrap())
        .unwrap();
    let run = || {
        std::process::Command::new("C:/Users/nemec/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe")
        .arg("L:/Continue/Viv/foundation/artifacts/auto/rust_durable_admission_fixture_v0/independent_verify.py").arg(&f.path).arg(&pins).output().unwrap()
    };
    let verified = run();
    assert!(
        verified.status.success(),
        "{}",
        String::from_utf8_lossy(&verified.stdout)
    );
    println!(
        "independent verifier: {}",
        String::from_utf8_lossy(&verified.stdout)
    );
    let db =
        rusqlite::Connection::open_with_flags(&f.path, rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE)
            .unwrap();
    db.execute("UPDATE meta SET head=?1", [ZERO_HASH]).unwrap();
    drop(db);
    assert!(!run().status.success());
}

#[test]
fn independent_verifier_rejects_each_protected_family() {
    use std::io::Write;
    let f = Fixture::new();
    let p = f.packet("verify-families");
    assert_eq!(
        f.host()
            .submit_candidate(&serde_json::to_vec(&p).unwrap())
            .state,
        "PASS"
    );
    let pins = f.path.with_file_name("public-pins.json");
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&pins)
        .unwrap()
        .write_all(
            &serde_json::to_vec(&serde_json::json!({"trust":f.trust,"host":f.identity.pin}))
                .unwrap(),
        )
        .unwrap();
    for family in [
        "candidate",
        "capability",
        "evidence",
        "receipt",
        "recovery",
        "replay",
        "schema",
    ] {
        let copy = f.path.with_file_name(format!("corrupt-{family}.sqlite"));
        assert!(!copy.exists());
        std::fs::copy(&f.path, &copy).unwrap();
        let db = rusqlite::Connection::open_with_flags(
            &copy,
            rusqlite::OpenFlags::SQLITE_OPEN_READ_WRITE,
        )
        .unwrap();
        match family {
            "candidate" | "capability" | "evidence" => {
                let mut bad = p.clone();
                match family {
                    "candidate" => bad.payload.value = "red".into(),
                    "capability" => bad.authorization.signature_hex = "00".repeat(64),
                    _ => bad.evidence[0].signature_hex = "00".repeat(64),
                };
                if family == "evidence" {
                    // Keep capability binding valid so the independent evidence signature branch is reached.
                    bad.authorization.evidence_sha256 = evidence_hash(&bad.evidence);
                    bad.authorization.signature_hex = sign_protected(
                        &f.trust.capability.id,
                        &f.cap,
                        &bad.authorization.signing_bytes(),
                    )
                    .unwrap();
                }
                db.execute(
                    "UPDATE admissions SET packet=?1",
                    [serde_json::to_string(&bad).unwrap()],
                )
                .unwrap();
            }
            "receipt" => {
                let raw: String = db
                    .query_row("SELECT receipt FROM admissions", [], |r| r.get(0))
                    .unwrap();
                let mut bad: super::receipt::Receipt = serde_json::from_str(&raw).unwrap();
                bad.signature_hex = "00".repeat(64);
                db.execute(
                    "UPDATE admissions SET receipt=?1",
                    [serde_json::to_string(&bad).unwrap()],
                )
                .unwrap();
            }
            "recovery" => {
                db.execute("UPDATE requests SET receipt_hash=?1", [ZERO_HASH])
                    .unwrap();
            }
            "replay" => {
                db.execute("DELETE FROM replay", []).unwrap();
            }
            _ => {
                db.execute("CREATE TABLE unrecognized (value TEXT)", [])
                    .unwrap();
            }
        }
        drop(db);
        let before = Fixture::snapshot_at(&copy);
        let result=std::process::Command::new("C:/Users/nemec/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe")
            .arg("L:/Continue/Viv/foundation/artifacts/auto/rust_durable_admission_fixture_v0/independent_verify.py").arg(&copy).arg(&pins).output().unwrap();
        assert!(
            !result.status.success(),
            "independent verifier accepted {family}"
        );
        let response: serde_json::Value = serde_json::from_slice(&result.stdout).unwrap();
        assert_eq!(response["state"], "HOLD");
        if ["capability", "evidence", "receipt"].contains(&family) {
            assert_eq!(response["reason"], "InvalidSignature");
        }
        f.record(&format!("independent-{family}"),serde_json::json!({"case_id":format!("independent-{family}"),"expected":{"state":"HOLD"},"observed":response,"before":before,"after":Fixture::snapshot_at(&copy),"fresh_process":{"exit":result.status.code(),"verifier":"independent_verify.py"}}));
        println!(
            "independent-family {family}: expected HOLD observed {}",
            response
        );
    }
}

#[test]
#[ignore = "explicit controller builds a separately bound ordinary host"]
fn ordinary_host_process_roundtrip() {
    use std::{
        io::Write,
        process::{Command, Stdio},
    };
    let f = Fixture::new();
    let root = f.path.parent().unwrap();
    let bootstrap = root.join("bootstrap.json");
    // Synthetic DPAPI-protected host key only; never include bootstrap in uploads.
    let config = serde_json::json!({"trust":f.trust,"receipt_identity":f.identity});
    std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(&bootstrap)
        .unwrap()
        .write_all(&serde_json::to_vec(&config).unwrap())
        .unwrap();
    let target = root.join("host-target");
    let build = Command::new("cargo")
        .args([
            "build",
            "--offline",
            "--manifest-path",
            "L:/Continue/Viv/security_core/Cargo.toml",
            "--bin",
            "durable_admission_fixture_host",
            "--features",
            "durable-admission-fixture",
        ])
        .env("CARGO_TARGET_DIR", &target)
        .env("VIV_DURABLE_FIXTURE_ROOT", root)
        .output()
        .unwrap();
    assert!(
        build.status.success(),
        "{}",
        String::from_utf8_lossy(&build.stderr)
    );
    let binary = target.join("debug/durable_admission_fixture_host.exe");
    let run = |lines: Vec<serde_json::Value>| {
        let mut child = Command::new(&binary)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .unwrap();
        {
            let mut input = child.stdin.take().unwrap();
            for line in lines {
                writeln!(input, "{}", line).unwrap();
            }
        }
        let output = child.wait_with_output().unwrap();
        assert!(
            output.status.success(),
            "{}",
            String::from_utf8_lossy(&output.stderr)
        );
        String::from_utf8(output.stdout)
            .unwrap()
            .lines()
            .map(|l| serde_json::from_str::<serde_json::Value>(l).unwrap())
            .collect::<Vec<_>>()
    };
    let p = f.packet("host-positive");
    let raw = serde_json::to_string(&p).unwrap();
    let first = run(vec![
        serde_json::json!({"op":"submit_candidate","canonical_packet_bytes":raw,"verdict":"PASS"}),
        serde_json::json!({"op":"submit_candidate","canonical_packet_bytes":raw}),
    ]);
    assert_eq!(first[0]["reason"], "IPC_SCHEMA");
    assert_eq!(first[1]["state"], "PASS");
    assert_eq!(f.counts(), (1, 1, 1));
    let aid = first[1]["admission"]["admission_id"].as_str().unwrap();
    let second = run(vec![
        serde_json::json!({"op":"query_request","request_id":p.request_id,"candidate_hash":p.candidate_sha256}),
        serde_json::json!({"op":"read_admitted","admission_id":aid}),
        serde_json::json!({"op":"submit_candidate","canonical_packet_bytes":raw}),
    ]);
    assert_eq!(second[0]["state"], "PASS");
    assert_eq!(second[1]["packet"]["request_id"], p.request_id);
    assert_eq!(second[2]["reason"], "QUERY_REQUIRED");
    assert_eq!(f.counts(), (1, 1, 1));
    let binary_hash = digest(&std::fs::read(&binary).unwrap());
    println!(
        "ORDINARY_HOST_PROOF root={} binary_sha256={} counts=1/1/1",
        root.display(),
        binary_hash
    );
}

#[test]
#[ignore = "controller-only subprocess; private synthetic material arrives via stdin"]
fn crash_worker() {
    use std::io::Read;
    let mut raw = String::new();
    std::io::stdin().read_to_string(&mut raw).unwrap();
    let input: WorkerInput = serde_json::from_str(&raw).unwrap();
    let mut host = Host::attach(input.path, input.trust, input.identity).unwrap();
    if std::env::var_os("VIV_FIXTURE_TEST_KILL_POINT").is_some() {
        let result = host.submit_candidate(&serde_json::to_vec(&input.packet).unwrap());
        panic!("kill point not reached: {}", result.reason);
    } else {
        let result = host.query_request(&input.packet.request_id, &input.packet.candidate_sha256);
        println!("FIXTURE_QUERY:{}", serde_json::to_string(&result).unwrap());
    }
}

#[test]
fn process_kill_board_reconstructs_durable_request_state() {
    use std::{
        io::{BufRead, BufReader, Write},
        process::{Command, Stdio},
        sync::mpsc,
        time::Duration,
    };
    for point in [
        "before_pending",
        "after_pending",
        "after_adjudication",
        "before_admission_insert",
        "after_admission_insert",
        "after_head_update",
        "after_recovery_update",
        "after_commit_before_readback",
        "after_readback_before_response",
        "after_negative_state_update",
        "after_negative_record_insert",
        "after_negative_commit",
        "after_negative_commit_fail",
    ] {
        let f = Fixture::new();
        let mut packet = f.packet(point);
        let before = f.snapshot();
        if point.contains("negative") {
            packet.evidence.clear();
            f.sign(&mut packet);
        }
        if point.ends_with("_fail") {
            packet.payload.value = "red".into();
        }
        let input = serde_json::to_vec(&WorkerInput {
            path: f.path.clone(),
            trust: f.trust.clone(),
            identity: f.identity.clone(),
            packet: packet.clone(),
        })
        .unwrap();
        let spawn = || {
            let mut c = Command::new(std::env::current_exe().unwrap());
            c.args([
                "--exact",
                "durable_admission::tests::crash_worker",
                "--ignored",
                "--nocapture",
            ])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
            c
        };
        let mut child = spawn()
            .env(
                "VIV_FIXTURE_TEST_KILL_POINT",
                point.strip_suffix("_fail").unwrap_or(point),
            )
            .spawn()
            .unwrap();
        child.stdin.take().unwrap().write_all(&input).unwrap();
        let stdout = child.stdout.take().unwrap();
        let (tx, rx) = mpsc::channel();
        let reader = std::thread::spawn(move || {
            for line in BufReader::new(stdout).lines() {
                let line = line.unwrap();
                if line.starts_with("FIXTURE_KILL_READY:") {
                    let _ = tx.send(line);
                    break;
                }
            }
        });
        let ready = rx.recv_timeout(Duration::from_secs(30));
        // Kill only the exact disposable worker process handle just spawned.
        child.kill().unwrap();
        let killed = child.wait().unwrap();
        reader.join().unwrap();
        assert!(
            ready.is_ok(),
            "{point}: worker failed to reach injection point"
        );
        assert!(!killed.success());
        let mut query = spawn().spawn().unwrap();
        query.stdin.take().unwrap().write_all(&input).unwrap();
        let output = query.wait_with_output().unwrap();
        assert!(
            output.status.success(),
            "{point}: {}",
            String::from_utf8_lossy(&output.stderr)
        );
        let stdout = String::from_utf8(output.stdout).unwrap();
        let raw = stdout
            .lines()
            .find_map(|s| s.strip_prefix("FIXTURE_QUERY:"))
            .expect("query response");
        let result: super::store::AdmissionResult = serde_json::from_str(raw).unwrap();
        let committed =
            point == "after_commit_before_readback" || point == "after_readback_before_response";
        let expected = if committed {
            "ALREADY_COMMITTED"
        } else if point == "before_pending" {
            "REQUEST_NOT_FOUND"
        } else if point == "after_negative_commit" {
            "MISSING_EVIDENCE"
        } else if point.ends_with("_fail") {
            "CONTENT_HASH_MISMATCH"
        } else {
            "NOT_COMMITTED_OR_INTERRUPTED"
        };
        assert_eq!(result.reason, expected, "{point}: {result:?}");
        if point.ends_with("_fail") {
            assert_eq!(result.state, "FAIL");
        }
        assert_eq!(
            f.counts(),
            (
                u64::from(committed),
                u64::from(point != "before_pending"),
                u64::from(committed)
            )
        );
        let record = serde_json::json!({"case_id":format!("crash-{point}"),"expected":{"state":if committed{"PASS"}else if point.ends_with("_fail"){"FAIL"}else{"HOLD"},"reason":expected},
            "observed":result,"request_sha256":digest(&serde_json::to_vec(&packet).unwrap()),"before":before,"after":f.snapshot(),
            "fresh_process":{"invoked_test":"durable_admission::tests::crash_worker","explicit_ignored":true,"query_exit":output.status.code(),"killed_exit":killed.code(),"checkpoint":ready.unwrap()},
            "controller_binary_sha256":digest(&std::fs::read(std::env::current_exe().unwrap()).unwrap())});
        let path = f.path.with_file_name(format!("case-crash-{point}.json"));
        std::fs::OpenOptions::new()
            .write(true)
            .create_new(true)
            .open(&path)
            .unwrap()
            .write_all(&serde_json::to_vec_pretty(&record).unwrap())
            .unwrap();
        println!(
            "CASE_RECEIPT path={} sha256={}",
            path.display(),
            digest(&std::fs::read(&path).unwrap())
        );
        println!(
            "process-kill {point}: {} / {}; counts {:?}",
            result.state,
            result.reason,
            f.counts()
        );
    }
}

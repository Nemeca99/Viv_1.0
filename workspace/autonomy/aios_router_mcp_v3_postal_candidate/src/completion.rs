//! Frozen Architect criteria and deterministic completion evidence. Model prose
//! is never a verification result. All persistent writes use Router's gates.
use crate::{Router,hex};
use rusqlite::{Connection,OptionalExtension,params};
use serde::{Deserialize,Serialize};
use serde_json::{Value,json};
use sha2::{Digest,Sha256};
use std::{collections::BTreeMap,io::Read,path::{Path,Component},process::{Command,Stdio},time::{Duration,Instant}};

const PROJECT:&str="/var/lib/aios-project";

#[derive(Debug,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Contract {
    pub version:u32,
    pub kind:String,
    #[serde(default)] pub artifacts:Vec<String>,
    #[serde(default)] pub checks:Vec<Check>,
    #[serde(default)] pub frozen_inputs:BTreeMap<String,String>,
}
#[derive(Debug,Serialize,Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Check { pub id:String,pub argv:Vec<String>,pub timeout_seconds:u64,#[serde(default)] pub inputs:Vec<String> }

pub(crate) fn parse(assignment:&str)->Result<Contract,String> {
    let lines=assignment.lines().filter_map(|l|l.trim().strip_prefix("Acceptance JSON:")).collect::<Vec<_>>();
    if lines.len()!=1{return Err("exactly_one_architect_acceptance_contract_required".into());}
    let contract:Contract=serde_json::from_str(lines[0]).map_err(|e|format!("invalid_acceptance_contract:{e}"))?;
    if contract.version!=1{return Err("unsupported_acceptance_version".into());}
    if contract.kind=="control_plane" {
        if !contract.artifacts.is_empty()||!contract.checks.is_empty()||!contract.frozen_inputs.is_empty(){return Err("control_contract_cannot_claim_code_verification".into());}
        return Ok(contract);
    }
    if contract.kind!="artifacts"||contract.artifacts.is_empty()||contract.artifacts.len()>16||contract.checks.is_empty()||contract.checks.len()>4 {
        return Err("artifact_contract_requires_artifacts_and_behavior_checks".into());
    }
    let mut unique=std::collections::BTreeSet::new();
    for p in &contract.artifacts {
        validate_path(p)?;
        if !unique.insert(p){return Err("duplicate_artifact".into());}
    }
    unique.clear();
    for check in &contract.checks {
        if check.id.is_empty()||check.id.len()>80||!unique.insert(&check.id)||check.argv.is_empty()||check.argv.len()>32||check.timeout_seconds==0||check.timeout_seconds>30 {
            return Err("invalid_acceptance_check".into());
        }
        let executable=&check.argv[0];
        if !(executable.starts_with("/usr/local/bin/")||executable.starts_with("/usr/bin/")||executable.starts_with("/bin/"))||executable.contains("..") {
            return Err("verification_executable_must_be_in_immutable_runtime".into());
        }
        if check.argv.iter().any(|s|s.contains('\0')||s.len()>4096){return Err("invalid_verification_argument".into());}
        if check.inputs.len()>16||(!check.argv.iter().any(|s|s=="-c")&&check.inputs.is_empty()){return Err("external_check_requires_frozen_verification_inputs".into());}
        for path in &check.inputs {validate_path(path)?;}
    }
    if contract.checks.iter().map(|c|c.timeout_seconds).sum::<u64>()>90{return Err("verification_budget_exceeds_ninety_seconds".into());}
    Ok(contract)
}

fn validate_path(raw:&str)->Result<(),String> {
    let p=Path::new(raw);
    if raw.is_empty()||raw.len()>512||raw.contains(['\\',':','\0'])||p.is_absolute()||p.components().any(|c|!matches!(c,Component::Normal(_))) {
        return Err("artifact_requires_project_relative_path".into());
    }
    Ok(())
}
fn file_hash(root:&Path,relative:&str)->Result<String,String> {
    validate_path(relative)?;
    let base=root.canonicalize().map_err(|e|format!("project_mount_unavailable:{e}"))?;
    let target=base.join(relative).canonicalize().map_err(|e|format!("artifact_unavailable:{relative}:{e}"))?;
    if !target.starts_with(&base){return Err("artifact_escapes_project_root".into());}
    let meta=target.metadata().map_err(|e|e.to_string())?;
    if !meta.is_file()||meta.len()>64*1024*1024{return Err("artifact_must_be_file_under_sixty_four_mib".into());}
    let mut file=std::fs::File::open(target).map_err(|e|e.to_string())?;
    let mut h=Sha256::new();let mut buf=[0u8;65536];
    loop{let n=file.read(&mut buf).map_err(|e|e.to_string())?;if n==0{break;}h.update(&buf[..n]);}
    Ok(hex(&h.finalize()))
}
fn hashes(root:&Path,contract:&Contract)->Result<BTreeMap<String,String>,String>{
    contract.artifacts.iter().map(|p|Ok((p.clone(),file_hash(root,p)?))).collect()
}
pub(crate) fn freeze(mut contract:Contract,root:&Path)->Result<Contract,String>{
    if !contract.frozen_inputs.is_empty(){return Err("frozen_input_hashes_are_owned_by_rust".into());}
    for check in &contract.checks {for input in &check.inputs {contract.frozen_inputs.insert(input.clone(),file_hash(root,input)?);}}
    Ok(contract)
}
fn inputs_current(root:&Path,contract:&Contract)->bool {
    contract.checks.iter().all(|c|c.argv.iter().any(|a|a=="-c")||!c.inputs.is_empty()) && contract.checks.iter().flat_map(|c|c.inputs.iter()).all(|p|contract.frozen_inputs.get(p).is_some_and(|h|file_hash(root,p).ok().as_ref()==Some(h)))
}
fn output<R:Read>(mut stream:R)->Value {
    let mut h=Sha256::new();let mut bytes=0u64;let mut excerpt=Vec::new();let mut buf=[0u8;8192];
    loop{match stream.read(&mut buf){Ok(0)=>break,Ok(n)=>{h.update(&buf[..n]);bytes+=n as u64;let remain=1000usize.saturating_sub(excerpt.len());excerpt.extend_from_slice(&buf[..n.min(remain)]);},Err(e)=>return json!({"error":e.to_string()})}}
    json!({"sha256":hex(&h.finalize()),"bytes":bytes,"excerpt":String::from_utf8_lossy(&excerpt),"truncated":bytes>1000})
}
fn run(root:&Path,check:&Check)->Result<Value,String> {
    let mut command=Command::new(&check.argv[0]);
    command.args(&check.argv[1..]).current_dir(root).env_clear().env("PATH","/usr/local/bin:/usr/bin:/bin").env("PYTHONDONTWRITEBYTECODE","1").env("TMPDIR","/tmp").env("HOME","/tmp").stdin(Stdio::null()).stdout(Stdio::piped()).stderr(Stdio::piped());
    #[cfg(unix)] {use std::os::unix::process::CommandExt;command.process_group(0);}
    let mut child=command.spawn().map_err(|e|format!("verification_spawn_failed:{}:{e}",check.id))?;
    let id=child.id();
    let out=child.stdout.take().ok_or("missing_stdout_pipe")?;let err=child.stderr.take().ok_or("missing_stderr_pipe")?;
    let stdout=std::thread::spawn(move||output(out));let stderr=std::thread::spawn(move||output(err));
    let start=Instant::now();let mut timed_out=false;
    let status=loop {
        if let Some(status)=child.try_wait().map_err(|e|e.to_string())?{break status;}
        if start.elapsed()>=Duration::from_secs(check.timeout_seconds){timed_out=true;let _=child.kill();break child.wait().map_err(|e|e.to_string())?;}
        std::thread::sleep(Duration::from_millis(10));
    };
    // Kill only this check's own process group, including children retaining its
    // pipes after parent exit. No host process or unrelated container is touched.
    #[cfg(unix)] unsafe {unsafe extern "C" {fn kill(pid:i32,sig:i32)->i32;} kill(-(id as i32),9);}
    let out=stdout.join().map_err(|_|"verification_stdout_reader_failed")?;
    let err=stderr.join().map_err(|_|"verification_stderr_reader_failed")?;
    Ok(json!({"id":check.id,"argv":check.argv,"exit_code":status.code(),"timed_out":timed_out,"passed":status.code()==Some(0)&&!timed_out&&out.get("error").is_none()&&err.get("error").is_none(),"stdout":out,"stderr":err}))
}

fn evaluate(root:&Path,contract:&Contract)->Value {
    if contract.kind=="control_plane"{return json!({"verified":true,"kind":"control_plane","artifacts":{},"checks":[]});}
    if !inputs_current(root,contract){return json!({"verified":false,"reason":"verification_input_changed"});}
    let before=match hashes(root,contract){Ok(h)=>h,Err(e)=>return json!({"verified":false,"reason":e})};
    let checks=contract.checks.iter().map(|check|run(root,check).unwrap_or_else(|e|json!({"id":check.id,"passed":false,"error":e}))).collect::<Vec<_>>();
    let after=match hashes(root,contract){Ok(h)=>h,Err(e)=>return json!({"verified":false,"checks":checks,"reason":e})};
    let unchanged=before==after && inputs_current(root,contract);
    json!({"verified":unchanged&&checks.iter().all(|v|v["passed"]==true),"kind":"artifacts","artifacts":after,"inputs_unchanged_during_checks":unchanged,"checks":checks})
}

pub(crate) fn schema(c:&Connection)->Result<(),String>{
    c.execute_batch("CREATE TABLE IF NOT EXISTS router_acceptance(task_id TEXT PRIMARY KEY,assignment_hash TEXT NOT NULL,contract_json TEXT NOT NULL,contract_sha256 TEXT NOT NULL,receipt_id TEXT NOT NULL);
      CREATE TABLE IF NOT EXISTS router_verification(id INTEGER PRIMARY KEY,task_id TEXT NOT NULL,contract_sha256 TEXT NOT NULL,result_json TEXT NOT NULL,result_sha256 TEXT NOT NULL,receipt_id TEXT NOT NULL UNIQUE);
      CREATE TRIGGER IF NOT EXISTS acceptance_no_update BEFORE UPDATE ON router_acceptance BEGIN SELECT RAISE(ABORT,'immutable acceptance contract'); END;
      CREATE TRIGGER IF NOT EXISTS acceptance_no_delete BEFORE DELETE ON router_acceptance BEGIN SELECT RAISE(ABORT,'immutable acceptance contract'); END;
      CREATE TRIGGER IF NOT EXISTS verification_no_update BEFORE UPDATE ON router_verification BEGIN SELECT RAISE(ABORT,'immutable verification evidence'); END;
      CREATE TRIGGER IF NOT EXISTS verification_no_delete BEFORE DELETE ON router_verification BEGIN SELECT RAISE(ABORT,'immutable verification evidence'); END;").map_err(|e|e.to_string())
}
pub(crate) fn install(c:&Connection,id:&str,assignment_hash:&str,contract:&Contract,receipt:&str)->Result<(),String>{
    let raw=serde_json::to_string(contract).map_err(|e|e.to_string())?;let hash=hex(&Sha256::digest(raw.as_bytes()));
    c.execute("INSERT OR IGNORE INTO router_acceptance VALUES(?1,?2,?3,?4,?5)",params![id,assignment_hash,raw,hash,receipt]).map_err(|e|e.to_string())?;
    let prior:(String,String)=c.query_row("SELECT assignment_hash,contract_sha256 FROM router_acceptance WHERE task_id=?1",[id],|r|Ok((r.get(0)?,r.get(1)?))).map_err(|e|e.to_string())?;
    if prior!=(assignment_hash.to_owned(),hash){return Err("acceptance_contract_conflict".into());}Ok(())
}
fn load(c:&Connection,id:&str)->Result<(Contract,String),String>{
    let (raw,hash):(String,String)=c.query_row("SELECT contract_json,contract_sha256 FROM router_acceptance WHERE task_id=?1",[id],|r|Ok((r.get(0)?,r.get(1)?))).optional().map_err(|_|"acceptance_contract_missing")?.ok_or("acceptance_contract_missing")?;
    if hex(&Sha256::digest(raw.as_bytes()))!=hash{return Err("acceptance_contract_hash_mismatch".into());}
    Ok((serde_json::from_str(&raw).map_err(|e|format!("stored_contract_invalid:{e}"))?,hash))
}
fn executable_hash()->Result<String,String>{
    let p=std::env::current_exe().map_err(|e|e.to_string())?;
    let bytes=std::fs::read(p).map_err(|e|e.to_string())?;Ok(hex(&Sha256::digest(bytes)))
}
/// Invoked only in a separate, read-only verification container. This mode has
/// no control DB/key/receipt write mounts and never starts an MCP server.
pub fn runner()->Result<Value,String>{
    let mut raw=String::new();std::io::stdin().take(65537).read_to_string(&mut raw).map_err(|e|e.to_string())?;
    if raw.len()>65536{return Err("verification_request_too_large".into());}
    let contract=parse(&format!("Acceptance JSON: {}",raw.trim()))?;
    let canonical=serde_json::to_string(&contract).map_err(|e|e.to_string())?;
    Ok(json!({"executor":"deterministic_rust_verifier_v1","executable_sha256":executable_hash()?,"contract_sha256":hex(&Sha256::digest(canonical.as_bytes())),"evidence":evaluate(Path::new(PROJECT),&contract)}))
}
pub(crate) fn verify_attested(c:&Connection,id:&str,receipt:&str,receipt_dir:&Path,root:&Path)->Result<Value,String>{
    let (contract,hash)=load(c,id)?;
    if contract.kind=="control_plane"{return verify(c,id,receipt,root);}
    let bytes=std::fs::read(receipt_dir.join(receipt)).map_err(|e|e.to_string())?;
    let attestation:Value=serde_json::from_slice(&bytes).map_err(|e|e.to_string())?;
    let proof=&attestation["verification"];
    if proof["executor"]!="deterministic_rust_verifier_v1"||proof["contract_sha256"]!=hash||proof["executable_sha256"]!=executable_hash()? {
        return Err("matching_rust_execution_receipt_required".into());
    }
    let mut result=proof["evidence"].clone();
    let empty=Vec::new();let observed=result["checks"].as_array().unwrap_or(&empty);
    let command_matches=observed.len()==contract.checks.len() && observed.iter().zip(contract.checks.iter()).all(|(r,c)|r["id"]==c.id&&r["argv"]==json!(c.argv)&&r["exit_code"]==0&&r["timed_out"]==false&&r["passed"]==true);
    let versions_current=inputs_current(root,&contract)&&hashes(root,&contract).ok().is_some_and(|h|json!(h)==result["artifacts"]);
    if !command_matches||!versions_current||result["inputs_unchanged_during_checks"]!=true {result["verified"]=json!(false);result["reason"]=json!("failed_or_stale_verification_evidence");}
    record(c,id,receipt,&hash,&result)
}
pub(crate) fn verify(c:&Connection,id:&str,receipt:&str,root:&Path)->Result<Value,String>{
    let (contract,hash)=load(c,id)?;let result=evaluate(root,&contract);
    record(c,id,receipt,&hash,&result)
}
fn record(c:&Connection,id:&str,receipt:&str,hash:&str,result:&Value)->Result<Value,String>{
    let raw=serde_json::to_string(&result).map_err(|e|e.to_string())?;let digest=hex(&Sha256::digest(raw.as_bytes()));
    c.execute("INSERT INTO router_verification(task_id,contract_sha256,result_json,result_sha256,receipt_id) VALUES(?1,?2,?3,?4,?5)",params![id,hash,raw,digest,receipt]).map_err(|e|e.to_string())?;
    Ok(json!({"evidence":result,"verification_sha256":digest,"contract_sha256":hash,"receipt_id":receipt}))
}
pub(crate) fn current(c:&Connection,id:&str,root:&Path)->Value{
    let (contract,hash)=match load(c,id){Ok(c)=>c,Err(e)=>return json!({"verified":false,"reason":e})};
    let latest=c.query_row("SELECT result_json,result_sha256,contract_sha256,receipt_id FROM router_verification WHERE task_id=?1 ORDER BY id DESC LIMIT 1",[id],|r|Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?,r.get::<_,String>(2)?,r.get::<_,String>(3)?)));
    let (raw,digest,stored_contract,receipt)=match latest{Ok(v)=>v,Err(_)=>return json!({"verified":false,"reason":"verification_missing"})};
    if stored_contract!=hash||hex(&Sha256::digest(raw.as_bytes()))!=digest{return json!({"verified":false,"reason":"verification_hash_mismatch"});}
    let result:Value=match serde_json::from_str(&raw){Ok(v)=>v,Err(_)=>return json!({"verified":false,"reason":"verification_invalid_json"})};
    if result["verified"]!=true{return json!({"verified":false,"reason":"acceptance_checks_failed","evidence":result});}
    let fresh=contract.kind=="control_plane" || (inputs_current(root,&contract)&&hashes(root,&contract).ok().is_some_and(|h|json!(h)==result["artifacts"]));
    json!({"verified":fresh,"kind":contract.kind,"reason":if fresh{"current_evidence"}else{"artifact_changed_after_verification"},"verification_sha256":digest,"receipt_id":receipt})
}

impl Router {
    pub fn verify_task(&self,session:&str,id:&str,ah:&str)->Result<Value,String>{
        let attempt=hex(&Sha256::digest(format!("{session}\n{id}\n{ah}").as_bytes()));
        self.guarded("tool:aios_router_verify_task",session,id,ah,&attempt,|receipt|{
            let c=self.readonly()?;let events=Self::events(&c)?;let state=Self::state(&events)?;let task=state.get(id).ok_or("unknown_task")?;
            if task.session_id!=session||task.assignment_hash!=ah||task.stopped{return Err("task_binding_mismatch".into());}
            let c=self.writable()?;verify_attested(&c,id,receipt,&self.receipt_dir,Path::new(PROJECT))
        })
    }
    pub fn acceptance_contract(&self,session:&str,id:&str,ah:&str)->Result<Value,String>{
        let c=self.readonly()?;let events=Self::events(&c)?;let state=Self::state(&events)?;let task=state.get(id).ok_or("unknown_task")?;
        if task.session_id!=session||task.assignment_hash!=ah{return Err("task_binding_mismatch".into());}
        let (contract,hash)=load(&c,id)?;Ok(json!({"contract":contract,"contract_sha256":hash,"assignment_hash":ah}))
    }
}
pub(crate) fn project_root()->&'static Path{Path::new(PROJECT)}

#[cfg(test)]
mod tests {
    use super::*;
    fn fixture()->std::path::PathBuf {
        let mut random=[0u8;8];getrandom::fill(&mut random).unwrap();
        let root=std::env::temp_dir().join(format!("completion-test-{}",hex(&random)));
        std::fs::create_dir(&root).unwrap();std::fs::write(root.join("artifact.txt"),"expected").unwrap();root
    }
    fn contract(script:&str)->Contract {
        let raw=json!({"version":1,"kind":"artifacts","artifacts":["artifact.txt"],"checks":[{"id":"behavior","argv":["/bin/sh","-c",script],"timeout_seconds":1}]}).to_string();
        parse(&format!("Architect assigned bounded verification\nAcceptance JSON: {raw}")).unwrap()
    }
    #[test]
    fn frozen_contract_required_and_scoped() {
        assert!(parse("model says done").is_err());
        assert!(parse("Acceptance JSON: {}\nAcceptance JSON: {}").is_err());
        assert!(parse("Acceptance JSON: {\"version\":1,\"kind\":\"artifacts\"}").is_err());
        assert!(validate_path("../outside").is_err());assert!(validate_path("C:\\file").is_err());
        assert!(parse("Acceptance JSON: {\"version\":1,\"kind\":\"control_plane\",\"artifacts\":[\"fake.py\"]}").is_err());
    }
    #[test]
    fn actual_behavior_and_artifact_changes_determine_completion() {
        let root=fixture();let contract=contract("test \"$(cat artifact.txt)\" = expected");
        let c=Connection::open_in_memory().unwrap();schema(&c).unwrap();
        install(&c,"task","assignment",&contract,"open-receipt").unwrap();
        let result=verify(&c,"task","real-process-receipt",&root).unwrap();
        assert_eq!(result["evidence"]["verified"],true);
        assert_eq!(result["evidence"]["checks"][0]["exit_code"],0);
        assert_eq!(current(&c,"task",&root)["verified"],true);
        std::fs::write(root.join("artifact.txt"),"changed after successful verification").unwrap();
        assert_eq!(current(&c,"task",&root)["verified"],false);
        assert_eq!(current(&c,"task",&root)["reason"],"artifact_changed_after_verification");
        let failed=verify(&c,"task","failed-process-receipt",&root).unwrap();
        assert_eq!(failed["evidence"]["verified"],false);
        assert_eq!(current(&c,"task",&root)["reason"],"acceptance_checks_failed");
        std::fs::write(root.join("artifact.txt"),"expected").unwrap();
        assert_eq!(current(&c,"task",&root)["verified"],false); // old pass cannot override newer failure
        assert_eq!(verify(&c,"task","fresh-reverification",&root).unwrap()["evidence"]["verified"],true);
        assert!(c.execute("DELETE FROM router_verification",[]).is_err());
        assert!(c.execute("UPDATE router_acceptance SET contract_json='{}'",[]).is_err());
        assert!(install(&c,"task","other-assignment",&contract,"bad-receipt").is_err());
    }
    #[test]
    fn positive_prose_and_zero_exit_cannot_hide_failures_or_mutations() {
        let root=fixture();
        let failed=evaluate(&root,&contract("echo 'PASS: everything works'; exit 7"));
        assert_eq!(failed["verified"],false);assert_eq!(failed["checks"][0]["exit_code"],7);
        let changed=evaluate(&root,&contract("printf altered > artifact.txt; exit 0"));
        assert_eq!(changed["verified"],false);assert_eq!(changed["inputs_unchanged_during_checks"],false);
        let timed=evaluate(&root,&contract("sleep 4"));
        assert_eq!(timed["verified"],false);assert_eq!(timed["checks"][0]["timed_out"],true);
    }
    #[test]
    fn checks_cannot_be_rewritten_to_manufacture_a_pass() {
        let root=fixture();std::fs::write(root.join("check.sh"),"test \"$(cat artifact.txt)\" = expected").unwrap();
        let raw=json!({"version":1,"kind":"artifacts","artifacts":["artifact.txt"],"checks":[{"id":"fixed-check","argv":["/bin/sh","check.sh"],"timeout_seconds":1,"inputs":["check.sh"]}]}).to_string();
        let frozen=freeze(parse(&format!("Acceptance JSON: {raw}")).unwrap(),&root).unwrap();
        assert_eq!(evaluate(&root,&frozen)["verified"],true);
        std::fs::write(root.join("check.sh"),"echo PASS; exit 0").unwrap();
        assert_eq!(evaluate(&root,&frozen)["verified"],false);
        assert_eq!(evaluate(&root,&frozen)["reason"],"verification_input_changed");
        assert!(freeze(frozen,&root).is_err());
    }
}

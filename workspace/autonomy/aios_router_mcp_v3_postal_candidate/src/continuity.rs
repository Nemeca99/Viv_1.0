//! Operational history, never accepted learned facts. Callers must obtain the
//! existing Body and PrivacyCore authority before opening a writable database.
use rusqlite::{params, Connection};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use crate::Router;

impl Router {
    fn continuity_path(&self) -> Result<std::path::PathBuf,String> {
        Ok(self.db_path.parent().ok_or("router_db_parent_missing")?.join("continuity.sqlite3"))
    }
    pub fn memory_checkpoint(&self, cp: Checkpoint) -> Result<serde_json::Value,String> {
        cp.validate()?;
        let host_target=std::path::Path::new(&self.privacy_target_path).with_file_name("continuity.sqlite3");
        // Windows paths must retain their spelling when evaluated inside Linux.
        let host_target=if self.privacy_target_path.contains('\\') {
            format!("{}\\continuity.sqlite3",self.privacy_target_path.rsplit_once('\\').ok_or("privacy_parent_missing")?.0)
        } else {host_target.to_string_lossy().into_owned()};
        let receipt=self.receipt_for("tool:aios_router_memory_checkpoint",&cp.session_id,&host_target)?;
        let binding:serde_json::Value=serde_json::from_slice(&std::fs::read(self.receipt_dir.join(&receipt.id)).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
        if binding["checkpoint_sha256"].as_str()!=Some(cp.sha256()?.as_str()) {
            return Err("checkpoint_authority_binding_mismatch".into());
        }
        let path=self.continuity_path()?;
        let mut c=Connection::open(path).map_err(|e|e.to_string())?;
        c.busy_timeout(std::time::Duration::from_secs(5)).map_err(|e|e.to_string())?;
        schema(&c)?;
        commit(&mut c,&cp,&receipt.id)
    }
    pub fn memory_stm(&self, session: &str) -> Result<serde_json::Value,String> {
        let path=self.continuity_path()?;
        if !path.is_file() {return Ok(serde_json::json!({"source":"stm","checkpoint":null}));}
        let c=Connection::open_with_flags(path,rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(|e|e.to_string())?;
        Ok(serde_json::json!({"source":"stm","checkpoint":latest_stm(&c,session)?}))
    }
    pub fn memory_checkpoint_read(&self,session:&str,id:&str)->Result<serde_json::Value,String> {
        use rusqlite::OptionalExtension;
        let path=self.continuity_path()?;
        if !path.is_file(){return Ok(serde_json::json!({"checkpoint":null}));}
        let c=Connection::open_with_flags(path,rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(|e|e.to_string())?;
        let cp=c.query_row("SELECT summary,stm,sha256,receipt_id FROM continuity_checkpoint WHERE session_id=?1 AND compaction_id=?2",params![session,id],|r| Ok(serde_json::json!({"summary":r.get::<_,String>(0)?,"stm":r.get::<_,String>(1)?,"sha256":r.get::<_,String>(2)?,"receipt_id":r.get::<_,String>(3)?}))).optional().map_err(|e|e.to_string())?;
        Ok(serde_json::json!({"checkpoint":cp}))
    }
    pub fn memory_working(&self, session: &str, context_id: &str, content: &str) -> Result<serde_json::Value,String> {
        if session.trim().is_empty() || session.len()>160 || context_id.is_empty() || context_id.len()>160 || content.len()>1024*1024 { return Err("invalid_working_context".into()); }
        let host=format!("{}\\continuity.sqlite3",self.privacy_target_path.rsplit_once('\\').ok_or("privacy_parent_missing")?.0);
        let receipt=self.receipt_for("tool:aios_router_memory_working",session,&host)?;
        let payload=serde_json::json!({"content":content,"context_id":context_id,"session_id":session});
        let hash=format!("{:x}",Sha256::digest(serde_json::to_vec(&payload).map_err(|e|e.to_string())?));
        let binding:serde_json::Value=serde_json::from_slice(&std::fs::read(self.receipt_dir.join(&receipt.id)).map_err(|e|e.to_string())?).map_err(|e|e.to_string())?;
        if binding["checkpoint_sha256"]!=hash {return Err("working_authority_binding_mismatch".into());}
        let mut c=Connection::open(self.continuity_path()?).map_err(|e|e.to_string())?;
        c.busy_timeout(std::time::Duration::from_secs(5)).map_err(|e|e.to_string())?;
        schema(&c)?;
        working_commit(&mut c,session,context_id,content,&hash,&receipt.id)
    }
    pub fn memory_retrieve(&self, session: &str, query: &str, limit: u32) -> Result<serde_json::Value,String> {
        if session.trim().is_empty() || query.trim().is_empty() || query.len()>512 {return Err("invalid_retrieval_request".into());}
        let path=self.continuity_path()?;
        if path.is_file() {
            let c=Connection::open_with_flags(path,rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(|e|e.to_string())?;
            // LTM survives new chats; STM remains scoped to its active session.
            let found=search(&c,"",query,limit)?;
            if found["matches"].as_array().is_some_and(|a|!a.is_empty()) {
                return Ok(serde_json::json!({"order":["ltm"],"result":found}));
            }
            if let Some(stm)=latest_stm(&c,session)? {
                if let Some(excerpt)=stm_excerpt(stm["stm"].as_str().unwrap_or(""),query) {
                    return Ok(serde_json::json!({"order":["ltm","stm"],"source":"stm","result":{"excerpt":excerpt,"context_id":stm["context_id"],"sha256":stm["sha256"],"receipt_id":stm["receipt_id"]}}));
                }
            }
        }
        let found=wikipedia(std::path::Path::new("/var/lib/aios-wikipedia"),query,limit)?;
        Ok(serde_json::json!({"order":["ltm","stm","wikipedia"],"source":"wikipedia","matches":found["matches"],"budget_exhausted":found["budget_exhausted"],"searched_databases":found["searched_databases"]}))
    }
}

fn stm_excerpt(stm:&str,query:&str)->Option<String> {
    // A question is not evidence for its own answer. Preserve all other working
    // context, including compaction summaries and completed tool results.
    let text=if let Ok(serde_json::Value::Array(mut messages))=serde_json::from_str::<serde_json::Value>(stm) {
        let latest=messages.iter().rposition(|m|m["type"]=="user"||m["role"]=="user"||m["info"]["role"]=="user");
        if let Some(i)=latest {messages.remove(i);}
        serde_json::to_string(&messages).ok()?
    }else{stm.to_owned()};
    let pos=text.to_lowercase().find(&query.to_lowercase())?;
    let mut start=pos.saturating_sub(600).min(text.len());
    let mut end=(start+3000).min(text.len());
    while !text.is_char_boundary(start){start-=1;}
    while !text.is_char_boundary(end){end-=1;}
    Some(text[start..end].to_owned())
}

/// Retain the real PrivacyCore decision, including its raw reason string. The
/// existing router gate is unchanged; continuity requires its own exact paths.
pub(crate) fn valid_privacy_decision(value:&serde_json::Value,target:&str)->bool {
    if value["schema"]!="continuity_privacy_decision_v1"
        || value["authority"]!="PrivacyCore.authorize_file_write"
        || value["target_path"]!=target || value["allowed"]!=true {return false;}
    let Some(paths)=value["checked_paths"].as_array() else {return false;};
    let expected=[target.to_owned(),format!("{target}-wal"),format!("{target}-shm"),format!("{target}-journal")];
    paths.len()==4 && paths.iter().zip(expected.iter()).all(|(p,e)|
        p["path"]==*e && p["raw"]["allowed"]==true && p["raw"]["reason"].is_string())
}

#[derive(Clone, Debug, Deserialize, Serialize)]
pub struct Checkpoint {
    pub session_id: String,
    pub compaction_id: String,
    pub summary: String,
    pub previous_assistant: String,
    pub previous_user: String,
}

impl Checkpoint {
    pub fn validate(&self) -> Result<(), String> {
        if self.session_id.trim().is_empty() || self.session_id.len() > 160
            || self.compaction_id.trim().is_empty() || self.compaction_id.len() > 160
            || self.summary.trim().is_empty()
        { return Err("invalid_checkpoint_identity_or_summary".into()); }
        if serde_json::to_vec(self).map_err(|e| e.to_string())?.len() > 1024 * 1024 {
            return Err("checkpoint_exceeds_one_mib".into());
        }
        Ok(())
    }
    pub fn sha256(&self) -> Result<String, String> {
        let bytes = serde_json::to_vec(self).map_err(|e| e.to_string())?;
        Ok(format!("{:x}", Sha256::digest(bytes)))
    }
    /// Preserve the exact summary and adjacent turns. No invented facts or
    /// additional model inference is required to recover the working context.
    pub fn stm(&self) -> String {
        format!("# Active context\n\n## Compaction summary\n{}\n\n## Previous assistant turn\n{}\n\n## Previous user turn\n{}\n", self.summary, self.previous_assistant, self.previous_user)
    }
}

pub(crate) fn schema(c: &Connection) -> Result<(), String> {
    c.execute_batch("PRAGMA synchronous=FULL;
      CREATE TABLE IF NOT EXISTS continuity_checkpoint(
        id INTEGER PRIMARY KEY, session_id TEXT NOT NULL, compaction_id TEXT NOT NULL,
        summary TEXT NOT NULL, previous_assistant TEXT NOT NULL, previous_user TEXT NOT NULL,
        stm TEXT NOT NULL, sha256 TEXT NOT NULL, receipt_id TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
        UNIQUE(session_id,compaction_id));
      CREATE VIRTUAL TABLE IF NOT EXISTS continuity_fts USING fts5(summary,previous_assistant,previous_user);
      CREATE TABLE IF NOT EXISTS continuity_working(id INTEGER PRIMARY KEY,session_id TEXT NOT NULL,context_id TEXT NOT NULL,stm TEXT NOT NULL,sha256 TEXT NOT NULL,receipt_id TEXT NOT NULL,UNIQUE(session_id,context_id));
      CREATE TRIGGER IF NOT EXISTS working_no_update BEFORE UPDATE ON continuity_working BEGIN SELECT RAISE(ABORT,'immutable working history'); END;
      CREATE TRIGGER IF NOT EXISTS working_no_delete BEFORE DELETE ON continuity_working BEGIN SELECT RAISE(ABORT,'immutable working history'); END;
      CREATE TRIGGER IF NOT EXISTS continuity_no_update BEFORE UPDATE ON continuity_checkpoint
        BEGIN SELECT RAISE(ABORT,'immutable continuity checkpoint'); END;
      CREATE TRIGGER IF NOT EXISTS continuity_no_delete BEFORE DELETE ON continuity_checkpoint
        BEGIN SELECT RAISE(ABORT,'immutable continuity checkpoint'); END;
      CREATE TRIGGER IF NOT EXISTS continuity_index AFTER INSERT ON continuity_checkpoint BEGIN
        INSERT INTO continuity_fts(rowid,summary,previous_assistant,previous_user)
        VALUES(new.id,new.summary,new.previous_assistant,new.previous_user); END;")
        .map_err(|e| e.to_string())
}

/// One transaction archives the summary and publishes its new STM. An exact
/// retry returns the original receipt; conflicting reuse fails without writes.
pub(crate) fn commit(c: &mut Connection, cp: &Checkpoint, receipt: &str) -> Result<serde_json::Value, String> {
    cp.validate()?;
    if receipt.trim().is_empty() { return Err("missing_authority_receipt".into()); }
    let digest = cp.sha256()?;
    let tx = c.transaction().map_err(|e|e.to_string())?;
    let existing = tx.query_row(
        "SELECT sha256,receipt_id FROM continuity_checkpoint WHERE session_id=?1 AND compaction_id=?2",
        params![cp.session_id,cp.compaction_id], |r| Ok((r.get::<_,String>(0)?,r.get::<_,String>(1)?)));
    match existing {
        Ok((hash, old_receipt)) => {
            if hash != digest { return Err("checkpoint_id_conflict".into()); }
            return Ok(serde_json::json!({"sha256":hash,"receipt_id":old_receipt,"replayed":true,"stm":cp.stm()}));
        },
        Err(rusqlite::Error::QueryReturnedNoRows) => {},
        Err(e) => return Err(e.to_string()),
    }
    tx.execute("INSERT INTO continuity_checkpoint(session_id,compaction_id,summary,previous_assistant,previous_user,stm,sha256,receipt_id) VALUES(?1,?2,?3,?4,?5,?6,?7,?8)",
        params![cp.session_id,cp.compaction_id,cp.summary,cp.previous_assistant,cp.previous_user,cp.stm(),digest,receipt]).map_err(|e|e.to_string())?;
    let id=tx.last_insert_rowid();
    tx.execute("INSERT INTO continuity_working(session_id,context_id,stm,sha256,receipt_id) VALUES(?1,?2,?3,?4,?5)",params![cp.session_id,format!("compact:{}",cp.compaction_id),cp.stm(),digest,receipt]).map_err(|e|e.to_string())?;
    tx.commit().map_err(|e|e.to_string())?;
    Ok(serde_json::json!({"id":id,"sha256":digest,"receipt_id":receipt,"replayed":false,"stm":cp.stm()}))
}

pub(crate) fn search(c: &Connection, session: &str, query: &str, limit: u32) -> Result<serde_json::Value,String> {
    if query.trim().is_empty() || query.len()>512 { return Err("invalid_search_query".into()); }
    let limit=limit.clamp(1,10);
    // Literal substring first (including paths and error codes), then quoted
    // FTS tokens. User text is never interpreted as SQL or an FTS expression.
    let mut exact=c.prepare("SELECT id,summary,sha256,receipt_id,session_id,compaction_id FROM continuity_checkpoint WHERE (?1='' OR session_id=?1) AND (instr(lower(summary),lower(?2))>0 OR instr(lower(previous_assistant),lower(?2))>0 OR instr(lower(previous_user),lower(?2))>0) ORDER BY id DESC LIMIT ?3").map_err(|e|e.to_string())?;
    let collect=|r:&rusqlite::Row<'_>| -> rusqlite::Result<serde_json::Value> {
        let summary=r.get::<_,String>(1)?;
        let excerpt=stm_excerpt(&summary,query).unwrap_or_else(||summary.chars().take(3000).collect());
        Ok(serde_json::json!({"id":r.get::<_,i64>(0)?,"summary":excerpt,"summary_is_excerpt":summary!=excerpt,"sha256":r.get::<_,String>(2)?,"receipt_id":r.get::<_,String>(3)?,"session_id":r.get::<_,String>(4)?,"compaction_id":r.get::<_,String>(5)?}))
    };
    let mut matches=exact.query_map(params![session,query,limit],collect).map_err(|e|e.to_string())?.collect::<Result<Vec<_>,_>>().map_err(|e|e.to_string())?;
    let mut method="literal";
    if matches.is_empty() {
        let tokens=query.split(|ch:char| !ch.is_alphanumeric()).filter(|t|!t.is_empty()).take(24).map(|t|format!("\"{t}\"" )).collect::<Vec<_>>().join(" AND ");
        if !tokens.is_empty() {
            let mut fts=c.prepare("SELECT c.id,c.summary,c.sha256,c.receipt_id,c.session_id,c.compaction_id FROM continuity_fts JOIN continuity_checkpoint c ON c.id=continuity_fts.rowid WHERE continuity_fts MATCH ?1 AND (?2='' OR c.session_id=?2) ORDER BY rank,c.id DESC LIMIT ?3").map_err(|e|e.to_string())?;
            matches=fts.query_map(params![tokens,session,limit],collect).map_err(|e|e.to_string())?.collect::<Result<Vec<_>,_>>().map_err(|e|e.to_string())?;
            method="fts";
        }
    }
    Ok(serde_json::json!({"source":"ltm","method":method,"matches":matches}))
}

pub(crate) fn latest_stm(c: &Connection, session: &str) -> Result<Option<serde_json::Value>,String> {
    use rusqlite::OptionalExtension;
    c.query_row("SELECT context_id,stm,sha256,receipt_id FROM continuity_working WHERE session_id=?1 ORDER BY id DESC LIMIT 1",[session],|r| Ok(serde_json::json!({"context_id":r.get::<_,String>(0)?,"stm":r.get::<_,String>(1)?,"sha256":r.get::<_,String>(2)?,"receipt_id":r.get::<_,String>(3)?})))
        .optional().map_err(|e|e.to_string())
}

fn working_commit(c:&mut Connection,session:&str,context_id:&str,content:&str,hash:&str,receipt:&str)->Result<serde_json::Value,String> {
    use rusqlite::OptionalExtension;
    let tx=c.transaction().map_err(|e|e.to_string())?;
    let old:Option<String>=tx.query_row("SELECT sha256 FROM continuity_working WHERE session_id=?1 AND context_id=?2",params![session,context_id],|r|r.get(0)).optional().map_err(|e|e.to_string())?;
    if let Some(old)=old {if old!=hash{return Err("working_id_conflict".into());}return Ok(serde_json::json!({"sha256":hash,"replayed":true}));}
    tx.execute("INSERT INTO continuity_working(session_id,context_id,stm,sha256,receipt_id) VALUES(?1,?2,?3,?4,?5)",params![session,context_id,content,hash,receipt]).map_err(|e|e.to_string())?;
    tx.commit().map_err(|e|e.to_string())?;
    Ok(serde_json::json!({"sha256":hash,"receipt_id":receipt,"replayed":false}))
}

/// Fixed source directory supplied by the server, never by model output.
/// Returns bounded article excerpts and provenance; never opens a writable DB.
pub(crate) fn wikipedia(root: &std::path::Path, query: &str, limit: u32) -> Result<serde_json::Value,String> {
    if query.trim().is_empty() || query.len()>512 { return Err("invalid_search_query".into()); }
    let mut paths=std::fs::read_dir(root).map_err(|e|e.to_string())?
        .filter_map(|e|e.ok().map(|v|v.path()))
        .filter(|p|p.file_name().and_then(|s|s.to_str()).is_some_and(|s|s.starts_with("wiki_") && s.ends_with(".sqlite3")))
        .collect::<Vec<_>>(); paths.sort();
    let mut matches=Vec::new();let mut exhausted=false;let mut searched=0usize;
    let start=std::time::Instant::now();
    for path in paths {
        if start.elapsed()>std::time::Duration::from_secs(8){exhausted=true;break;}
        if std::fs::symlink_metadata(&path).map_err(|e|e.to_string())?.file_type().is_symlink() { return Err("wikipedia_symlink_denied".into()); }
        let c=Connection::open_with_flags(&path,rusqlite::OpenFlags::SQLITE_OPEN_READ_ONLY).map_err(|e|e.to_string())?;
        c.busy_timeout(std::time::Duration::from_secs(2)).map_err(|e|e.to_string())?;
        let deadline=std::time::Instant::now()+std::time::Duration::from_secs(2);
        c.progress_handler(10000,Some(move||std::time::Instant::now()>deadline));
        searched+=1;
        let mut stmt=c.prepare("SELECT article_id,title,substr(summary,1,3000),batch_source,file_name FROM articles WHERE instr(lower(title),lower(?1))>0 ORDER BY article_id LIMIT ?2").map_err(|e|e.to_string())?;
        let rows=stmt.query_map(params![query,limit.clamp(1,10)],|r| Ok(serde_json::json!({"article_id":r.get::<_,i64>(0)?,"title":r.get::<_,String>(1)?,"excerpt":r.get::<_,String>(2)?,"batch_source":r.get::<_,String>(3)?,"file_name":r.get::<_,String>(4)?,"database":path.to_string_lossy()}))).map_err(|e|e.to_string())?;
        for row in rows {
            match row {
                Ok(row)=>matches.push(row),
                Err(error) if error.sqlite_error_code()==Some(rusqlite::ErrorCode::OperationInterrupted)=>{exhausted=true;break;},
                Err(error)=>return Err(error.to_string()),
            }
            if matches.len()>=limit.clamp(1,10) as usize {return Ok(serde_json::json!({"matches":matches,"budget_exhausted":exhausted,"searched_databases":searched}));}
        }
    }
    Ok(serde_json::json!({"matches":matches,"budget_exhausted":exhausted,"searched_databases":searched}))
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn archive_recover_retry_and_conflict() {
        let mut c=Connection::open_in_memory().unwrap(); schema(&c).unwrap();
        let mut cp=Checkpoint{session_id:"s1".into(),compaction_id:"c1".into(),summary:"Fixed exact error ERR_PATH at /project/foo.rs".into(),previous_assistant:"Changed foo; compilation passed".into(),previous_user:"Continue to the next task".into()};
        let first=commit(&mut c,&cp,"body-receipt").unwrap();
        assert!(first["stm"].as_str().unwrap().contains(&cp.previous_assistant));
        assert!(first["stm"].as_str().unwrap().contains(&cp.previous_user));
        assert_eq!(commit(&mut c,&cp,"retry-receipt").unwrap()["receipt_id"],"body-receipt");
        assert_eq!(search(&c,"s1","ERR_PATH",5).unwrap()["matches"].as_array().unwrap().len(),1);
        assert_eq!(search(&c,"s1","ERR_PATH",5).unwrap()["matches"][0]["compaction_id"],"c1");
        assert_eq!(search(&c,"s1","fixed error",5).unwrap()["method"],"fts");
        assert!(search(&c,"other","ERR_PATH",5).unwrap()["matches"].as_array().unwrap().is_empty());
        assert_eq!(search(&c,"","ERR_PATH",5).unwrap()["matches"][0]["session_id"],"s1");
        working_commit(&mut c,"s1","turn2","Current work changed: STM_ONLY_TOKEN","working-hash","body-working").unwrap();
        assert!(latest_stm(&c,"s1").unwrap().unwrap()["stm"].as_str().unwrap().contains("STM_ONLY_TOKEN"));
        assert!(search(&c,"","STM_ONLY_TOKEN",5).unwrap()["matches"].as_array().unwrap().is_empty());
        assert!(c.execute("DELETE FROM continuity_working",[]).is_err());
        assert!(stm_excerpt(r#"[{"type":"user","text":"SELF_QUESTION_ONLY"}]"#,"SELF_QUESTION_ONLY").is_none());
        assert!(stm_excerpt(r#"[{"type":"assistant","text":"verified previous result"},{"type":"user","text":"question"}]"#,"previous result").unwrap().contains("verified previous result"));
        let bounded=stm_excerpt(&("padding ".repeat(10000)+"EXACT_TARGET"),"EXACT_TARGET").unwrap();
        assert!(bounded.len()<=3000 && bounded.contains("EXACT_TARGET"));
        cp.summary="conflicting replacement".into();
        assert_eq!(commit(&mut c,&cp,"another-receipt").unwrap_err(),"checkpoint_id_conflict");
        assert!(c.execute("DELETE FROM continuity_checkpoint",[]).is_err());
        assert_eq!(c.query_row("SELECT count(*) FROM continuity_checkpoint",[],|r|r.get::<_,i64>(0)).unwrap(),1);
    }
    #[test]
    fn privacy_requires_exact_raw_allows_and_all_four_paths() {
        let target="L:\\LocalCoder\\workspace\\aios_rebuild\\memory\\aios_router\\continuity.sqlite3";
        let paths=[target.to_owned(),format!("{target}-wal"),format!("{target}-shm"),format!("{target}-journal")];
        let mut v=serde_json::json!({"schema":"continuity_privacy_decision_v1","authority":"PrivacyCore.authorize_file_write","target_path":target,"allowed":true,"checked_paths":paths.iter().map(|p|serde_json::json!({"path":p,"raw":{"allowed":true,"reason":""}})).collect::<Vec<_>>()});
        assert!(valid_privacy_decision(&v,target));
        v["checked_paths"][1]["raw"]["allowed"]=serde_json::json!(false);
        assert!(!valid_privacy_decision(&v,target));
        v["checked_paths"][1]["raw"]["allowed"]=serde_json::json!(true);
        v["checked_paths"][1]["path"]=serde_json::json!("wrong");
        assert!(!valid_privacy_decision(&v,target));
    }
}

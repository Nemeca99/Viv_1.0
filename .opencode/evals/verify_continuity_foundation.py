"""Audit real runtime results against the Architect's continuity requirements."""
import hashlib,json,pathlib,sqlite3,sys
ROOT=pathlib.Path('L:/LocalCoder')
sys.path.insert(0,str(ROOT/'workspace/autonomy/aios_router_mcp_v3_postal_candidate'))
from continuity_authority import canonical

def main():
    checks={}
    pointer=json.loads((ROOT/'.opencode/evals/continuity-final-opencode-verification.stdout.json').read_text(encoding='utf-8-sig'))
    assert pointer.get('error') is None,pointer
    path=pathlib.Path(pointer['evidence']); live=json.loads(path.read_text(encoding='utf-8'))
    checks['live_mcp_connected']=any(x['name']=='aios_router' and x['status']['status']=='connected' for x in live['mcp_after']['data'])
    checks['actual_tool_execution']=bool(live['completed_memory_retrievals'])
    retrieved=json.loads(live['completed_memory_retrievals'][-1]['state']['content'][0]['text'])
    checks['actual_ltm_tool_result']=retrieved.get('ok') is True and retrieved['result']['order']==['ltm'] and bool(retrieved['result']['result']['matches'])
    after=live['context_after']['data']
    compact=next(x for x in after if x['type']=='compaction')
    checks['actual_compaction_completed']=compact['status']=='completed'
    session=live['session']['data']['id']
    db=ROOT/'workspace/aios_rebuild/memory/aios_router/continuity.sqlite3'
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        row=dict(c.execute('SELECT * FROM continuity_checkpoint WHERE session_id=? AND sha256=?',(session,compact['metadata']['continuity_sha256'])).fetchone())
        cp={key:row[key] for key in ('session_id','compaction_id','summary','previous_assistant','previous_user')}
        checks['ltm_content_hash']=hashlib.sha256(canonical(cp)).hexdigest()==row['sha256']
        checks['native_stm_matches_archive']=compact['summary']==row['stm']
        messages=live['context_after_prompt']['data']
        assistant=next(m for m in reversed(messages) if m['type']=='assistant')
        user=next(m for m in reversed(messages) if m['type']=='user')
        saved_assistant=json.loads(row['previous_assistant'])
        # Compaction hooks use model messages (role/content); the public API
        # adds display metadata such as cost, snapshots and timestamps. Verify
        # the same message identity and full observable turn content.
        checks['previous_assistant_preserved']=saved_assistant['id']==assistant['id'] and saved_assistant.get('role',saved_assistant.get('type'))=='assistant' and saved_assistant['content']==assistant['content']
        checks['previous_user_preserved']=row['previous_user']==user['text']
        retrieved_hash=retrieved['result']['result']['matches'][0]['sha256']
        checks['retrieved_hash_exists_in_ltm']=c.execute('SELECT count(*) FROM continuity_checkpoint WHERE sha256=?',(retrieved_hash,)).fetchone()[0]==1
        checks['assistant_report_matches_tool_result']=retrieved_hash in json.dumps(assistant['content'])
        current=c.execute('SELECT stm FROM continuity_working WHERE session_id=? ORDER BY id DESC LIMIT 1',(session,)).fetchone()[0]
        checks['current_stm_persisted']=current==row['stm']
        triggers={x[0] for x in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        checks['immutable_sql_history']={'continuity_no_update','continuity_no_delete','working_no_update','working_no_delete'}.issubset(triggers)
    receipt=json.loads((ROOT/'.opencode/receipts'/row['receipt_id']).read_text(encoding='utf-8'))
    checks['actual_body_allow']=receipt['body_verdict']['allowed'] is True and receipt['body_verdict']['authority']=='deterministic_aios_body_rust'
    checks['actual_privacy_allows']=all(x['raw']['allowed'] is True for x in receipt['privacy_core']['checked_paths']) and len(receipt['privacy_core']['checked_paths'])==4
    checks['payload_bound_receipt']=receipt['checkpoint_sha256']==row['sha256']==compact['metadata']['continuity_sha256'] and receipt['session_id']==session
    tiers=json.loads((ROOT/'.opencode/evals/continuity-final-restart-tiers.json').read_text(encoding='utf-8'))
    for tier,order in [('ltm',['ltm']),('stm',['ltm','stm']),('wikipedia',['ltm','stm','wikipedia'])]:
        checks['restart_retrieval_'+tier]=tiers['checks'][tier]['order']==order
    config=json.loads((ROOT/'opencode.json').read_text(encoding='utf-8-sig'))
    checks['context_and_compaction_config']=config['providers']['lmstudio']['models']['omnicoder-2-9b']['limit']['context']==49152 and config['compaction']['buffer']=='10%' and config['compaction']['keep']['tokens']==10000
    checks['uncapped_agents']=all('steps' not in config['agents'][name] for name in ['build','drone_build','drone_read'])
    checks['no_hidden_continuation_ceiling']='MAX_AUTOMATIC_CONTINUATIONS' not in (ROOT/'.opencode/plugins/localcoder-drone-assignment-gate.ts').read_text(encoding='utf-8')
    checks['wikipedia_readonly_mount']='type=bind,source=/mnt/f/AI_Datasets/domain_dbs,target=/var/lib/aios-wikipedia,readonly' in config['mcp']['servers']['aios_router']['command']
    checks['hooks_enabled']=json.loads((ROOT/'.opencode/continuity.json').read_text(encoding='utf-8'))['enabled'] is True
    result={'result':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'live_evidence':str(path),'checkpoint_sha256':row['sha256'],'receipt_id':row['receipt_id'],'image':config['mcp']['servers']['aios_router']['command'][-1]}
    out=ROOT/'.opencode/evals/continuity-foundation-audit.json';out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result))
    return 0 if result['result']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())

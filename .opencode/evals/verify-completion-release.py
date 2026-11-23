"""Read-only audit of real completion authority and its retained evidence."""
import pathlib,json,sqlite3,hashlib
ROOT=pathlib.Path('L:/LocalCoder')
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8-sig'))
def main():
    live=read('.opencode/evals/opencode-completion-live-1794994843.json')
    native=read('.opencode/evals/completion-live-20261118T090631Z.json')
    wiki=read('.opencode/evals/completion-wikipedia-regression.json')
    finish=live['completion']['result']; summary=live['summary']['result'];task=summary['task_id']
    checks={'live_frontend_pass':live['result']=='PASS','native_negative_and_recovery_cases_pass':native['result']=='PASS',
            'rust_reported_completed':summary['state']=='completed' and summary['verification']['verified'] is True,
            'actual_process_exit_zero':finish['verification']['evidence']['checks'][0]['exit_code']==0,
            'readonly_behavior_check_executed':finish['verification']['evidence']['checks'][0]['id']=='behavior-and-readonly-scope',
            'artifact_versions_stable_during_checks':finish['verification']['evidence']['inputs_unchanged_during_checks'] is True,
            'wiki_positive_and_bounded_miss':wiki['result']=='PASS' and wiki['checks']['wikipedia']['result']['matches']!=[] and wiki['checks']['bounded_miss']['elapsed_seconds']<25}
    db=ROOT/'workspace/aios_rebuild/memory/aios_router/router.sqlite3'
    with sqlite3.connect(db.as_uri()+'?mode=ro',uri=True) as c:
        c.row_factory=sqlite3.Row
        contract_row=dict(c.execute('SELECT * FROM router_acceptance WHERE task_id=?',(task,)).fetchone())
        frozen=json.loads(contract_row['contract_json'])
        checks['contract_frozen_in_rust']=hashlib.sha256(contract_row['contract_json'].encode()).hexdigest()==contract_row['contract_sha256']
        checks['matches_assigned_criteria']=all(frozen[key]==live['contract'][key] for key in ('version','kind','artifacts','checks'))
        checks['declared_check_inputs_pinned']=all(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest for path,digest in frozen['frozen_inputs'].items()) and bool(frozen['frozen_inputs'])
        row=dict(c.execute('SELECT * FROM router_verification WHERE task_id=? ORDER BY id DESC LIMIT 1',(task,)).fetchone())
        result=json.loads(row['result_json'])
        checks['immutable_verification_hash']=hashlib.sha256(row['result_json'].encode()).hexdigest()==row['result_sha256']==summary['verification']['verification_sha256']
        checks['current_artifacts_match_proof']=all(hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest for path,digest in result['artifacts'].items())
        triggers={r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='trigger'")}
        checks['immutable_contract_and_verification_history']={'acceptance_no_update','acceptance_no_delete','verification_no_update','verification_no_delete'}.issubset(triggers)
        checks['lane_done_follows_verification']=c.execute("SELECT count(*) FROM router_event WHERE task=? AND kind='lane_done' AND receipt_id=?",(task,row['receipt_id'])).fetchone()[0]==1
    receipt=read('.opencode/receipts/'+row['receipt_id'])
    checks['actual_body_authority']=receipt['body_verdict']['allowed'] is True and receipt['body_verdict']['authority']=='deterministic_aios_body_rust'
    checks['actual_privacy_authority']=receipt['privacy_core']['allowed'] is True and len(receipt['privacy_core']['checked_paths'])==4 and all(v['raw_privacy_core']['allowed'] is True for v in receipt['privacy_core']['checked_paths'])
    checks['rust_executor_and_contract_bound']=receipt['verification']['executor']=='deterministic_rust_verifier_v1' and receipt['verification']['contract_sha256']==contract_row['contract_sha256'] and receipt['verification']['evidence']['verified'] is True
    cfg=read('opencode.json');command=cfg['mcp']['servers']['aios_router']['command']
    checks['project_mount_readonly']='type=bind,source=/mnt/l/LocalCoder,target=/var/lib/aios-project,readonly' in command
    checks['pinned_release']=command[-1]=='sha256:bc26b04fb32ffffb54749be70814711f3aa3a4a6da1b723b0cf9a321ce63731d'
    checks['frontend_hook_enabled']=read('.opencode/completion.json')['enabled'] is True
    audit={'result':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'task_id':task,'image':command[-1],
           'verification_sha256':row['result_sha256'],'body_receipt':row['receipt_id'],'live_evidence':'.opencode/evals/opencode-completion-live-1794994843.json','native_evidence':'.opencode/evals/completion-live-20261118T090631Z.json'}
    out=ROOT/'.opencode/evals/completion-release-audit.json';out.write_text(json.dumps(audit,indent=2),encoding='utf-8')
    print(json.dumps(audit));return 0 if audit['result']=='PASS' else 1
if __name__=='__main__':raise SystemExit(main())

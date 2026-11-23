"""Actual gated Rust verification lifecycle; preserves failed and stale evidence."""
import sys,json,hashlib,pathlib,uuid,copy
from datetime import datetime,timezone
ROOT=pathlib.Path('L:/LocalCoder')
sys.path.insert(0,str(ROOT/'workspace/autonomy/aios_router_mcp_v3_postal_candidate'))
from completion_authority import Mcp,authorize,prepare

def main():
    cfg=json.loads((ROOT/'opencode.json').read_text(encoding='utf-8-sig'))
    stamp=uuid.uuid4().hex[:16];session='completion-test-'+stamp;task='verify-'+stamp
    fixture=ROOT/'.opencode/evals/completion-fixture';fixture.mkdir(exist_ok=True)
    value=fixture/'value.txt';checker=fixture/'check.py'
    value.write_text('expected',encoding='utf-8')
    checker.write_text("from pathlib import Path\np=Path('.opencode/evals/completion-fixture/value.txt')\nprint('Candidate claims PASS; exit status and assertions decide')\nassert p.read_text()=='expected', 'behavior mismatch'\ntry:\n p.write_text('unauthorized write')\nexcept OSError:\n pass\nelse:\n raise AssertionError('project mount must be read-only')\nprint('actual behavior verified')\n",encoding='utf-8')
    contract={'version':1,'kind':'artifacts','artifacts':['.opencode/evals/completion-fixture/value.txt','.opencode/evals/completion-fixture/check.py'],
              'checks':[{'id':'behavior-and-readonly-scope','argv':['/usr/local/bin/python','-B','.opencode/evals/completion-fixture/check.py'],'timeout_seconds':5,'inputs':['.opencode/evals/completion-fixture/check.py']}]}
    assignment='Architect-approved bounded deterministic completion test.\nAcceptance JSON: '+json.dumps(contract,separators=(',',':'))
    binding={'session_id':session,'task_id':task,'assignment_hash':hashlib.sha256(assignment.encode()).hexdigest()}
    channel=Mcp(cfg['mcp']['servers']['aios_router']['command']);evidence={'session_id':session,'task_id':task,'binding':binding,'contract':contract,'assignment':assignment,'steps':[]}
    def call(name,args,proof=False):
        tool='aios_router_'+name
        auth=prepare(tool,binding,cfg) if proof else {'receipt_id':authorize(tool,session)}
        result=channel.call(name,{**binding,**args});evidence['steps'].append({'tool':name,'authority':auth,'result':result});return result
    def summary():return channel.call('queen_summary',{'task_id':task})
    try:
        call('open_build_task',{'assignment':assignment,'lane_ids':['drone'],'max_turns_per_lane':1})
        call('accept_self_prompt',{'lane_id':'drone','turn':0,'prompt':'Agenda: run frozen verification. Verified facts: bounded task opened. Next bounded action: record work ready for verification.'})
        call('record_turn_result',{'lane_id':'drone','turn':0,'result':'Test artifacts prepared; actual verification is still required.'})
        try:call('complete_lane',{'lane_id':'drone','receipt':'Model claims everything passed'})
        except RuntimeError as error:
            assert 'matching_rust_execution_receipt_required' in str(error),error
            evidence['steps'].append({'expected_rejection':'model_prose_without_rust_execution','error':str(error)})
        else:raise AssertionError('Model claim was accepted without actual Rust verification')
        verified=call('verify_task',{},True);assert verified['evidence']['verified'] is True
        completed=call('complete_lane',{'lane_id':'drone','receipt':'Completion is grounded in the Rust verification receipt.'},True)
        assert completed['task_verified'] is True
        evidence['initial_completed']=summary();assert evidence['initial_completed']['state']=='completed'
        value.write_text('wrong behavior after prior pass',encoding='utf-8')
        evidence['invalidated']=summary();assert evidence['invalidated']['state']=='awaiting_verification'
        assert evidence['invalidated']['verification']['reason']=='artifact_changed_after_verification'
        original_checker=checker.read_text(encoding='utf-8')
        checker.write_text("print('PASS: fabricated replacement check')\n",encoding='utf-8')
        rewritten=call('verify_task',{},True)
        assert rewritten['evidence']['verified'] is False
        assert evidence['steps'][-1]['authority']['verification']['evidence']['reason']=='verification_input_changed'
        checker.write_text(original_checker,encoding='utf-8')
        failed=call('verify_task',{},True)
        assert failed['evidence']['verified'] is False
        assert failed['evidence']['checks'][0]['exit_code']!=0
        assert summary()['state']=='awaiting_verification'
        value.write_text('expected',encoding='utf-8')
        assert summary()['state']=='awaiting_verification' # restoring bytes cannot revive an older pass
        reverified=call('verify_task',{},True);assert reverified['evidence']['verified'] is True
        evidence['final_completed']=summary();assert evidence['final_completed']['state']=='completed'
        evidence['result']='PASS'
    except Exception as error:evidence['result']='FAIL';evidence['error']=repr(error)
    finally:
        channel.close();path=ROOT/'.opencode/evals'/('completion-live-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
        path.write_text(json.dumps(evidence,indent=2),encoding='utf-8')
        print(json.dumps({'result':evidence['result'],'evidence':str(path),'error':evidence.get('error')}))
    return 0 if evidence['result']=='PASS' else 1

if __name__=='__main__':raise SystemExit(main())

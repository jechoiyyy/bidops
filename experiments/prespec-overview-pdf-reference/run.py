"""Run frozen page-reference inputs via BidOps' overview-purpose model client.

Run inside an explicitly configured BidOps ops container; never loads secrets
from files. Inputs/results are private, append-only run artifacts. Operational
review rows are not changed by this experiment.
"""
import json,hashlib,time,sys
from pathlib import Path
from uuid import uuid4
from datetime import datetime,UTC
from sqlalchemy import select,func
from app.core.db import SessionLocal
from app.core.models import AuditEvent
from app.core.model_client import build_prompt
from app.deep_review.models import PreSpecOverviewAttempt as A
from app.deep_review.services.prespec_overview import load_overview_policy
from app.deep_review.services.prespec_overview_runner import PreSpecOverviewRunner
from validate import validate,VALIDATOR_VERSION
root=Path(sys.argv[1]).resolve();policy=load_overview_policy(Path(__file__).with_name('policy.json'));assert policy
runner=PreSpecOverviewRunner(policy=policy)
binding,client=runner._resolve()
assert binding and client and not binding.deployable
assert binding.model_name=='qwen3.8:27b' and binding.model_digest=='22130167c4c20e20c7b71454612966ca8e8171e9b3cc8ab6ce8aa6cbfec79643'
run_id=str(uuid4());results=[];inputs=[]
def write(name,data):
 with (root/name).open('x') as f:json.dump(data,f,ensure_ascii=False,indent=2)
for row in json.loads((root/'input-manifest.json').read_text()):
 id=row['notice_id'];record=json.loads((root/f'{id}-input.json').read_text())
 assert hashlib.sha256((root/f'{id}.pdf').read_bytes()).hexdigest()==record['pdf_sha256']
 assert hashlib.sha256((root/f'{id}.hwp').read_bytes()).hexdigest()==record['source_sha256']
 prompt=build_prompt(policy.stage,record['model_input'],policy.document)
 inputs.append((record,hashlib.sha256(prompt.encode()).hexdigest()))
manifest={'validator_version':VALIDATOR_VERSION,'schema_version':'bidops.prespec-overview-page-run.v1','run_id':run_id,'quality_status':'unmeasured_reference','model':binding.model_name,'model_digest':binding.model_digest,'policy_digest':policy.digest,'prompt_version':binding.prompt_version,'created_at':datetime.now(UTC).isoformat(),'approval':'User explicitly requested Qwen overview generation with no length limit and PDF page references for the previously reviewed cohort.','input_count':len(inputs),'operational_review_rows_updated':False,'inputs':[{'notice_id':r['notice_id'],'prompt_sha256':h,'pdf_sha256':r['pdf_sha256'],'source_sha256':r['source_sha256']} for r,h in inputs]}
write('run-manifest.json',manifest)
def audit(id,status,metadata):
 with SessionLocal() as s:
  s.add(AuditEvent(actor_kind='system',claimed_name=None,action='prespec_overview.page_reference_run',aggregate_type='prespec_overview_reference',aggregate_id=run_id,safe_metadata={'notice_id':id,'status':status,'quality_status':'unmeasured_reference',**metadata}));s.commit()
try:
 for record,prompt_hash in inputs:
  id=record['notice_id'];started=time.monotonic()
  with SessionLocal() as s:
   assert s.scalar(select(func.count()).select_from(A).where(A.status.in_(['queued','running'])))==0
  audit(id,'started',{'prompt_sha256':prompt_hash,'policy_digest':policy.digest,'pdf_sha256':record['pdf_sha256'],'model_digest':binding.model_digest})
  print('started',id,flush=True)
  try:
   response=client.invoke(policy.stage,record['model_input'],policy.document)
   assert response.input_sha256==prompt_hash
   with SessionLocal() as s:
    sha=runner._store_raw_response(s,response.raw_response);s.commit()
   errors=validate(response.structured_output,record,policy.output_schema)
   write(f'{id}-output.json',response.structured_output)
   row={'notice_id':id,'status':'validation_failed' if errors else 'evidence_checks_passed','validation_errors':errors,'response_sha256':sha,'prompt_sha256':prompt_hash,'input_tokens':response.prompt_tokens,'output_tokens':response.output_tokens,'duration_seconds':round(time.monotonic()-started,3),'semantic_quality':'unmeasured_reference'}
  except KeyboardInterrupt:
   row={'notice_id':id,'status':'interrupted','reason_code':'operator_stopped_for_contract_review','duration_seconds':round(time.monotonic()-started,3)}
  except Exception as exc:
   row={'notice_id':id,'status':'failed','reason_code':getattr(exc,'code',type(exc).__name__),'duration_seconds':round(time.monotonic()-started,3)}
  write(f'{id}-outcome.json',row);results.append(row)
  audit(id,row['status'],{k:v for k,v in row.items() if k not in ['notice_id','status']})
  print(json.dumps(row),flush=True)
  if row['status']=='interrupted':break
finally:
 client.close()
 write('execution-results.json',{'run_id':run_id,'quality_status':'unmeasured_reference','results':results})

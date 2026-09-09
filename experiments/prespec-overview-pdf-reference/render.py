"""Render unmodified Qwen outputs with physical-PDF-page links, not chunk IDs."""
import json,sys,hashlib,html
from pathlib import Path
from validate import FACT_SECTIONS
root=Path(sys.argv[1]).resolve();out=Path(sys.argv[2]).resolve();out.mkdir(exist_ok=False,parents=True)
run=json.loads((root/'run-manifest.json').read_text());results=json.loads((root/'execution-results.json').read_text())
sections={'business_overview':'사업 개요','main_tasks':'주요 과업','budget_and_period':'사업 규모와 일정','important_conditions':'핵심 조건'}
lines=['# Qwen 사전규격 개요 검토 — PDF 페이지 근거','',f"모델: `{run['model']}` · 프롬프트: `{run['prompt_version']}` · `quality_status=unmeasured_reference`",'',
'글자수·줄수 제한 없이 Qwen이 실제 생성한 결과다. 사실 설명과 모델 검토 의견을 구분했다. 아래 PDF 페이지는 표지를 포함해 세는 변환 PDF의 실제 순번이며, 문서에 인쇄된 쪽수와 다를 수 있다. 원문 HWP/HWPX와 변환 PDF의 해시는 실행 manifest에 결속했다.','',
'원응답은 암호화 저장하고 기존 DB 개요 리뷰는 변경하지 않았다. 근거 검사 통과는 운영 품질 승인이나 최종 참여 판단을 의미하지 않는다. 아래 설명은 모델 출력이며 잘못된 내용이 확인되면 별도 검토 기록으로 표시하고 원응답을 고치지 않는다.','']
items=[]
for row in results['results']:
 id=row['notice_id'];record=json.loads((root/f'{id}-input.json').read_text())
 lines.extend([f"## {record['model_input']['title']}",'',f"내부 ID: {id} · 실행 상태: `{row['status']}`",'',f"[근거 PDF 열기]({root}/{id}.pdf) · 검토 페이지: "+', '.join(str(x) for x in record['selected_pages']),''])
 if not (root/f'{id}-output.json').exists():
  lines.extend(['모델 출력 없음. 실패 사유: `'+row.get('reason_code','unknown')+'`','']);continue
 output=json.loads((root/f'{id}-output.json').read_text())
 items.append({'notice_id':id,'title':record['model_input']['title'],'pdf_sha256':record['pdf_sha256'],'status':row['status'],'output':output})
 if row['validation_errors']:
  lines.extend(['**검증 실패 — 아래는 담당자 확인용 원출력이며 완료 결과가 아님.** 사유: '+', '.join(row['validation_errors']),''])
 evidence_pages=sorted({n for section in FACT_SECTIONS for fact in output.get(section,[]) for n in fact['evidence_pages']})
 for section in FACT_SECTIONS:
  lines.extend(['### '+sections[section],''])
  facts=output.get(section,[])
  if not facts:lines.extend(['모델이 확인된 사실을 기재하지 않았다. 아래 추가 확인 사항 참조.',''])
  for fact in facts:
   pages=sorted(set(fact['evidence_pages']))
   links=' · '.join(f"[PDF {n}페이지]({root}/{id}.pdf#page={n})" for n in pages)
   lines.extend([fact['text']+' '+links,''])
 for field,title in [('reviewer_analysis','검토 포인트 — Qwen 판단'),('unknowns','추가 확인 사항'),('input_limitations','입력·검토 한계')]:
  lines.extend(['### '+title,''])
  for text in output.get(field,[]):lines.extend(['- '+text])
  lines.append('')
 lines.extend(['### 근거 PDF 페이지',''])
 for n in evidence_pages:
  lines.append(f"- [PDF {n}페이지]({root}/{id}.pdf#page={n})")
 lines.append('')
lines.extend(['## 변환 및 검증 범위','',
'PDF는 저장소의 rhwp SVG 렌더와 Chromium 인쇄로 만든 참조 변환본이다. 한컴 원본과 동일한 페이지 배치를 보증하지 않는다. 인용 페이지는 함께 제공하는 PDF에서 확인해야 한다. 현재 운영 HWP/HWPX 구조의 page 필드(구역 순번)와 이번 pdf_page 필드(변환 PDF 실제 페이지)는 서로 대체하지 않는다.','',
'자동 검사는 스키마, 선택한 PDF 페이지 범위, 사실 문장의 숫자·영문 명칭이 표시한 원문 페이지에 있는지, 사업금액을 계약금액으로 잘못 표현했는지를 확인했다. 인용문은 모델이 재생성하지 않으며 근거 PDF를 직접 조회한다. 의미상 정확성·필수 내용의 완전성·회사 적합성은 이 검사만으로 보증하지 않는다.',''])
(out/'overview-6.md').write_text('\n'.join(lines))
(out/'overview-6.json').write_text(json.dumps({'schema_version':'bidops.prespec-overview-page-report.v1','quality_status':'unmeasured_reference','run_id':run['run_id'],'reviews':items},ensure_ascii=False,indent=2)+'\n')
(out/'execution-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
print(json.dumps({'rendered':len(items),'report':str(out/'overview-6.md')},ensure_ascii=False))

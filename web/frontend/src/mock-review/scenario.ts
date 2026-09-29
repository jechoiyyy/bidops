/** Reuse the approved fictional report and source; no operational data. */
import report from '../../../../docs/0922_deep-review-improvement/report.md?raw';
import input from '../../../../docs/0922_deep-review-improvement/report-source.md?raw';
export const title = '한빛시 민원 데이터 통합·분석 플랫폼 구축';
export type SourceId = string;
export const sources = [...input.matchAll(/^### (문서|회사) (\d+) — (.+)\n([\s\S]*?)(?=^#{2,3} |$(?![\s\S]))/gm)].map(m=>({id:`${m[1]} ${m[2]}`,location:`가상 ${m[1]} · ${m[3]}`,text:m[4].trim()}));
const ids = ['assessment','scope','fit','risk','evaluation','contract','actions','conditions'];
const questions = ['현재 자료로 어떻게 평가할 수 있는가?','무엇을 수행해야 하는가?','우리 회사가 조건을 충족하는가?','수행과 비용에서 무엇이 위험한가?','평가에서 무엇을 입증해야 하는가?','계약·경제성 조건은 어떤 부담을 주는가?','다음에 무엇을 확인하고 준비해야 하는가?','어떤 사실이 확인되면 판단이 바뀌는가?'];
export const answers = [...report.matchAll(/^## (\d+)\. (.+)\n([\s\S]*?)(?=^## \d+\.|$(?![\s\S]))/gm)].map((m,i)=>({id:ids[i],question:questions[i],headline:m[2],body:m[3].trim()}));
export const bundles = [
  { title:'사업 조건 이해', instruction:'제안요청서 전체를 읽고 과업·평가·계약 조건을 함께 설명하라. 조건과 예외를 보존하고 각 설명에 원문 근거를 연결하라.', sourceIds:sources.filter(s=>s.id.startsWith('문서')).map(s=>s.id), previous:[], answerIds:['scope','evaluation','contract'] },
  { title:'우리 회사에 대입', instruction:'사업 조건과 회사 자료를 대조하여 충족·부족·미확인을 구분하라. 인력·기술·일정·비용 영향을 함께 설명하고 자료 부재를 부적격으로 확정하지 말라.', sourceIds:sources.map(s=>s.id), previous:[0], answerIds:['fit','risk'] },
  { title:'판단과 행동 정리', instruction:'앞선 분석과 근거를 종합해 현재 평가, 확인할 행동, 판단이 바뀌는 조건을 작성하라. 새로운 사실을 만들거나 사람의 최종 결정을 대신하지 말라.', sourceIds:sources.map(s=>s.id), previous:[0,1], answerIds:['assessment','actions','conditions'] },
];
export const bundleOutput = (index: number) => answers.filter(a => bundles[index].answerIds.includes(a.id));
export const bundleInput = (index: number) => ({ instruction: bundles[index].instruction, questions: bundleOutput(index).map(a=>a.question), sources: sources.filter(s=>bundles[index].sourceIds.includes(s.id)), previous: bundles[index].previous.map(i=>({ stage:bundles[i].title, answers:bundleOutput(i) })) });

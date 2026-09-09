# PDF 페이지 근거를 갖는 Qwen 사전규격 개요 참조 실행

목표는 담당자가 사업의 목적·실제 과업·예산·기간·조건을 이해할 수 있는 개요다. 글자수와 줄수는 제한하지 않는다. 필요한 내용의 누락과 원문 근거의 정확성을 검토한다.

## 구현 범위

- `policy.json`: Qwen3.8:27B용 충분한 설명, 사실과 검토 의견의 분리, 페이지 근거 출력 계약.
- `validate.py`: strict 스키마, PDF 페이지 바인딩, 사실의 숫자·영문 명칭의 페이지 지지 확인, 사업금액을 계약금액으로 잘못 표기하는 문제 검사. 모델에게 인용문을 다시 복사시키지 않으며, 요약 글자수·줄수 제한 없음.
- `run.py`: 기존 overview 용도 ModelClient와 모델 identity/host/revision 검증을 사용. 고정 입력별 순차 호출, 원응답 암호화 저장, DB 감사 이벤트 기록. 결과는 `unmeasured_reference`이며 운영 개요 리뷰 행을 변경하지 않는다.
- `render.py`: 각 사실의 근거를 PDF 페이지 링크로 출력하며 내부 청크 식별자를 표시하지 않는다.
- `test_validate.py`: 틀린 페이지·숫자·영문 풀이·금액 역할 거절, 긴 설명·복수 페이지 참조 허용 검사.

이 실험은 운영 자동 파이프라인에 장착한 PDF 변환기가 아니다. HWP/HWPX 구역 번호를 PDF 페이지라고 해석하지 않기 위해 별도의 변환 PDF를 생성하고 개요 본문 페이지를 직접 확인한 입력을 사용한다. 운영 적용에는 변환본 불변 저장과 페이지 의미를 명시하는 구조 계약이 필요하다.

## 요약 프롬프트 v4 (모델 미호출)

`prespec-overview-page-review-reference-v4`는 세부 요구사항 나열을 업무 단위 요약으로 바꾼다. 사업 개요는 발주의 성격·문제·목적, 주요 과업은 관련 업무 묶음, 나머지 항목은 규모·일정·핵심 조건·검토 쟁점·확인 사항을 맡는다. 같은 사실은 주된 항목에 한 번만 배치하며 월별 예시 일정이나 일반 법령 목록을 옮겨 적지 않는다. 중요한 숫자·범위·제약과 PDF 페이지 근거는 유지한다. 글자수·줄수·항목 수에 강제 상한은 두지 않는다.

가상 개발 사업과 가상 감리 사업의 few-shot 두 개를 `prompt_output_contract`에 넣어 실제 `build_prompt` 요청에 포함시킨다. 예시는 담당자가 읽는 Markdown 소제목 형태이며, 질문별 작성 기준과 JSON 필드 매핑을 함께 제공한다. 실제 모델 응답과 저장 계약은 `bidops.prespec-overview-page-review.v3` JSON 그대로다. 예시의 업무·페이지·미확인 사항은 현재 공고에 복사하지 않도록 지시한다. 읽기 쉬운 정책 사본과 두 예시는 [prompt-v4.md](prompt-v4.md)에 있다.

이전 실행의 정책·입력·응답은 보존한다. 새 프롬프트의 요약 품질은 아직 실호출로 확인하지 않았다.

## 새 입력 계약

`input-manifest.json`은 실행할 `notice_id` 목록을 가진다. 건별 `<id>-input.json`에는 다음 필드가 필요하다.

- `notice_id`, `document_version_id`, `source_sha256`, `pdf_sha256`, `pdf_pages`, `selected_pages`.
- `model_input`: 문서 제목, 읽은 범위, 변환 한계, `blocks`.
- 각 model block: `block_key`, `ordinal`, `pdf_page`, `text`.
- private block manifest에는 페이지 원문 텍스트 해시와 시작 오프셋을 보존한다.
- `pdf_page`는 **해당 pdf_sha256에 결속된 PDF의 물리적 페이지 번호(표지 포함, 1부터)**다. 인쇄 쪽수나 HWPX 구역 번호가 아니다.
- 이번 실행에서는 한 청크가 한 PDF 페이지에 속한다. 여러 페이지 청크로 확장하면 단일 페이지를 임의로 택하지 말고 페이지별 텍스트 범위를 따로 보존해야 한다.

`<id>.hwp`는 이번 참조 실행의 고정 입력 파일명이며 실제 원문 형식은 HWP 또는 HWPX다. `<id>.pdf`는 그 원문에서 만든 참조 변환본이다. 출력 계약 `bidops.prespec-overview-page-review.v3`는 사실 항목마다 `evidence_pages: [3, 4]`를 붙인다. 근거 원문은 결속된 PDF 페이지에서 직접 조회한다. 별도 근거 ID나 인용문을 모델에게 생성·재연결시키지 않는다. PDF 실제 페이지와 설명을 연결하며, 설명 자체를 원문 발췌와 같게 만들 필요는 없다.

모델에는 파일 경로·저장소 키·자격증명 대신 선택한 페이지 본문과 인용 식별자만 전달한다.

## 실행

이미 승인된 모델 및 저장소 환경을 주입한 ops 실행 환경에서, 코드 디렉터리와 새 private 실행 디렉터리를 준비한다. 모델 원문·프롬프트·PDF·HWP/HWPX는 Git에 추가하지 않는다.

```bash
PYTHONPATH=/app/web/backend python /path/to/code/test_validate.py
PYTHONPATH=/app/web/backend python /path/to/code/run.py /path/to/frozen-run
PYTHONPATH=/app/web/backend python /path/to/code/render.py /path/to/frozen-run /path/to/new-report
```

운영 overview worker와 겹치지 않는 상태에서 실행한다. 기존 결과가 있는 실행 디렉터리는 재사용하지 않는다. 실행 중 policy와 입력은 변경하지 않는다. 모델 호출은 용도별 승인 설정을 그대로 사용하고 hosted fallback은 없다. 응답 토큰·입력 크기·시간의 자원 한도는 유지하며, 응답 잘림을 정상 출력으로 게시하지 않는다.

## 검증의 한계

근거 검사 통과는 의미 품질 통과가 아니다. 숫자가 같은 페이지에 있다고 해서 그 숫자의 역할까지 맞는 것은 아니다. 예를 들어 감리비와 대상사업 구축비를 구분했는지, 조건이 누락되거나 설명이 과장되지 않았는지는 출력 대조로 추가 확인한다. 회사의 역량·자격·실적과 최종 참여 판단은 확정하지 않는다.

이번 PDF는 저장소에 고정된 rhwp의 SVG 렌더와 Chromium 인쇄로 생성했다. 글꼴 폭 추정 등으로 한컴 원본의 페이지 배치와 다를 수 있으므로 **배포하는 변환 PDF 자체의 페이지**만 근거로 주장한다. 원본 렌더러와 동등한 변환 품질을 측정한 결과로 취급하지 않는다.

2026-09-07 저장/API 연결 이후의 새 실행은 backend의 `pdf-page-evidence.v2` 검증기를
공유하며 manifest에 validator_version을 남긴다. 프롬프트 v4와 출력 schema v3는 유지한다.
페이지 표기가 evidence_pages와 정확히 일치할 때만 사업 사실 검사와 분리한다.
이미 동결된 실행의 code·outcome·output은 바꾸지 않는다. 생성 후 아래 명령으로
해당 1건을 DB에 적재할 수 있다(추가 모델 호출 없음).

```bash
python -m app.deep_review.cli import-page-overview \
  --run-dir /absolute/frozen-run --notice-id 614 --actor jechoi
```

원래 실패한 실행을 적재하면 새 근거 검사 통과 여부와 관계없이 원실행 실패 상태를
보존한다. 이후 새 실행은 새 validator 결과를 기록하지만 참조 실행/품질 미측정은 유지한다.

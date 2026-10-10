# 가상회사 원본 승인

> 아래 최초 승인(2026-10-09T17:27:45+09:00)의 회사 원본 3개 해시는 같은 날 재발행으로 대체되었다(superseded). 현재 유효한 승인은 맨 아래 **재발행 재승인** 절이다. 최초 승인 기록은 이력으로 보존한다.

- 승인자: 현재 대화 사용자
- 승인 근거: “현재 초안 승인, 그리고 이어서 진행할 다음 작업은 뭐야?”
- 승인 기록 시각: 2026-10-09T17:27:45+09:00 (메시지 수신 후 기록 시각)
- 범위: 3사 합성 원본과 ontology v1을 데모 개발용 입력으로 동결. 실제 서버 적용·외부 모델 전송 승인은 포함하지 않음.
- 승인 요청 manifest와 현재 파일의 SHA-256을 모두 대조해 일치 확인.

| 파일 | 원본 바이트 SHA-256 |
|---|---|
| `docs/demo-fixtures/ontology.v1.json` | `cc821ae70b36d8e3aaed40b3f524b5be7209a491c4cf670cdff048ae4f5c27ef` |
| `docs/demo-fixtures/companies/demo-cloud-si.v1.json` | `58fe3ce03859d83a0c9327b7f90f1be3ce029bc7e5c62b9f3e4ba8bb0cf8339d` |
| `docs/demo-fixtures/companies/demo-data-ai.v1.json` | `b78fd0078615cd2ff9657484717c581aeacedeb9d66b6d2adde35a311f5c5eb2` |
| `docs/demo-fixtures/companies/demo-public-si.v1.json` | `6a2f6415f64cc5752fbb95efa01c61ac9662d7791054f783f14dc02d4728c3c7` |

- Ontology canonical SHA-256: `3775a3486e887d601b04bc5b073ff29f49f8dd2177ea3444f0d66f1b68a79411`
- 검증: docs/work/_runs/demo0203-20261009/step003-dry-run.log (3사 CLI exit0, errors=[]).
- 이 기록 시점에 실제 DB 등록·활성화는 수행하지 않음. 원본 JSON은 승인된 바이트 그대로 보존(이후 아래 재발행으로 대체).

## 재발행 재승인 (2026-10-09)

- 사유: DEMO-02 기능 최종 독립 리뷰 B2. 최초 승인본은 인력군(`staff_group`)·실적(`project`) value의 nullable key를 생략해 공통 계약 §3(`?`는 생략이 아니라 nullable, 모든 key 필수)과 어긋났다.
- 사용자 결정: 계약을 유지하고 원본에 null을 명시해 재발행(“원본에 null 명시”).
- 변경: 회사마다 `available`·`as_of`(인력군 2개)와 `amount_krw`·`started_on`·`ended_on`(실적 3개) key를 `null`로 추가(회사당 13개). 사실·인용·수치·노드 순서·JSON pointer·ontology는 불변이다. 재발행 전후 diff는 독립 리뷰어가 확인했다.
- 승인자: 현재 대화 사용자
- 승인 근거: 재승인 질문에 “재발행본 승인” 선택
- 승인 기록 시각: 2026-10-09T19:06:02+09:00 (응답 수신 후 기록 시각)
- 범위: 데모 개발용 입력으로 동결. 실제 서버 등록·활성화·외부 모델 전송 승인은 포함하지 않는다.
- 재승인 요청 manifest(`docs/work/_runs/demo0203-20261009/step003-reapproval-request.json`)와 현재 파일 SHA-256을 대조해 일치 확인.

| 파일 | 원본 바이트 SHA-256 | 이전 승인본 |
|---|---|---|
| `docs/demo-fixtures/ontology.v1.json` | `cc821ae70b36d8e3aaed40b3f524b5be7209a491c4cf670cdff048ae4f5c27ef` | 변경 없음 |
| `docs/demo-fixtures/companies/demo-cloud-si.v1.json` | `ae3a1ad324153e870f9ac29a75190950eeaee76921ba40d4d2f3e8b06cc74c41` | `58fe3ce03859d83a0c9327b7f90f1be3ce029bc7e5c62b9f3e4ba8bb0cf8339d` |
| `docs/demo-fixtures/companies/demo-data-ai.v1.json` | `19366eabe277bcc951c5a73e9ce0c96532aa745c4e53748b9dbb65af5558fdc2` | `b78fd0078615cd2ff9657484717c581aeacedeb9d66b6d2adde35a311f5c5eb2` |
| `docs/demo-fixtures/companies/demo-public-si.v1.json` | `7b83417b00124768336451f46e53233820655126a7ed112f0f440ea4ee514670` | `6a2f6415f64cc5752fbb95efa01c61ac9662d7791054f783f14dc02d4728c3c7` |

- 검증: `docs/work/_runs/demo0203-20261009/step003-reissue-dry-run.log` (엄격 validator로 3사 CLI dry-run exit0, errors=[]). 이전 승인본 바이트는 같은 validator에서 `source_invalid`(exit2)로 거부된다.
- 이 기록 시점에 실제 DB 등록·활성화는 수행하지 않음. 원본 JSON은 재승인된 바이트 그대로 보존.

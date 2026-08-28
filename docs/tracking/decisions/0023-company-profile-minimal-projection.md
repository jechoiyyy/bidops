# 회사 프로필 조회는 승인된 최소 projection만 제공

- 상태: 채택
- 일자: 2026-08-27

## 맥락

현재 profile snapshots API는 working-tree 상대 `source_ref`를, sections·unknowns API는 working tree 파일의 filesystem `source`, raw block·raw text, 파싱 예외 문자열을 응답에 넣을 수 있다. 사내망 사용자들이 같은 읽기 권한을 갖더라도 서버 배치 경로와 회사 프로필 전문이 일반 조회 API에 필요한 것은 아니다.

## 결정

사내 프로필 조회 API는 승인된 불변 profile version·digest에 묶인 구조화 항목과 `unknown`만 반환한다. 응답 schema는 `bidops.profile-projection.v1`로 명시한다.

filesystem source·source reference, source line, raw block, raw text, 원문 파싱 예외 문자열은 제외한다. 파싱·snapshot 실패는 내부 경로가 없는 안정 오류 코드로 바꾸고 fail closed한다. snapshot 목록에서도 `source_ref`를 제거하고 version, digest, source kind, created time만 제공한다. UI는 이 projection 외의 프로필 원문을 조회하거나 재구성하지 않는다.

## 대안

사내망 조회자 전체에게 프로필 전문을 허용하고 filesystem source만 숨기는 안은 필요 이상의 회사 정보를 범용 API 계약으로 고정하므로 기각했다.

현재 working tree parser 결과를 그대로 나두고 frontend만 raw field를 표시하지 않는 안은 API·log·향후 client 노출을 막지 못하므로 기각했다.

## 결과

기존 sections·unknowns route는 신규 projection contract로 교체하고 client를 함께 전환해야 한다. 전환 전에는 운영 조회에 사용하지 않는다. 회귀 검증은 response에 절대·상대 파일 경로, raw 프로필 일부, 원문 예외 문자열이 없고 version·digest·구조화 항목·`unknown`만 있는지 확인해야 한다.

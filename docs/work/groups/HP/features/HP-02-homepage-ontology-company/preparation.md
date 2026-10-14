# HP-02 준비 — 초안, 등록·활성화 전

실제 카드 근거와 분류·alias·concept ID 후보는 [vocabulary-candidates.md](vocabulary-candidates.md), 기계 판독 후보는 [ontology.candidates.draft.json](../../preparation/ontology.candidates.draft.json), 가상회사 설정은 [company.proposal.draft.json](../../preparation/company.proposal.draft.json). 실제 온톨로지 검증기와 NFKC 어휘 매퍼를 오프라인으로 통과했지만 사용자 승인·업무 적합 검증을 뜻하지 않는다. 관련어 묶음의 분리 여부를 먼저 결정한다. 파일 이름부터 초안이며 회사 파일은 등록 CLI 형식이 아니다.

회사 추천안은 가상 온웹서비스(hp-onweb), 18명·연매출18억원·2018년 설립·최근3년 홈페이지3건·최대2억원 실적이다. 전부 사용자 검토용 가상 수치다. 의도적 차이는 ISMS 미보유, 다국어 실적 없음, 상주 가용2명 제한이며 Oracle 경험과 직접생산확인 유효범위는 unknown/null이다. 마지막 둘을 미보유로 판정하지 않는다. 24시간 대응도 unknown이며 업무시간 대응만 가정했다. 등록 시 승인된 각 사실을 fictional_scenario source_refs와 별도 불변 버전에 연결해야 한다.

대안은 규모를 줄여 상주·실적 격차를 더 드러내거나, 규모를 키우되 자격·기술 격차만 남기는 것이다. 추천은 중간 규모 유지: 항상 전부 met 또는 gap인 데모를 피할 수 있다. 실제 공고 숫자에 맞춰 회사 사실을 사후 조정하지 않는다.

재생성 명령과 외부 파일 위치는 [준비 묶음](../../preparation/README.md). `coverage`는 후보가 나타난 카드 비율일 뿐 정확도·충족률이 아니다. 자격·계약은 카드 밖에 있을 수 있으므로 현재 사전의 카드 출현 0을 불필요로 자동 삭제하지 않는다. D1·D2 승인 후 source_refs가 있는 정식 fixture·스펙 작성, 현재 validator 재검증, 고정 hash, 격리 등록·활성화 순서로 진행한다. 이번에는 DB/MinIO/정책에 쓰지 않았다.

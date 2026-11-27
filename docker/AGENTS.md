# Docker 실행 구성

루트 지침과 `web/AGENTS.md`의 이미지·네트워크·검증 계약을 함께 따른다.

- Dockerfile과 Compose는 이 디렉터리에서 관리한다. 빌드 context는 저장소 루트이며 `.dockerignore`도 루트에 둔다.
- 모든 실행은 루트 Make 또는 `scripts/compose.sh`를 사용한다. 선택기가 저장소 루트 `--project-directory`를 지정하므로 상대 bind·env·secret 경로를 `../`로 바꾸지 않는다.
- dev/mock/prod project·port·volume을 분리한다. 운영 `bidops`와 데모 `bidops-local`은 개발 대상으로 쓰지 않는다.
- base는 내부망, edge는 웹 publish, prod는 서비스별 모델·G2B egress다. Luna/Slack은 명시적인 capability이며 profiles는 서비스 선택만 한다.
- 엔진 검토 스위치는 base에서 web·analysis-worker에 함께 전달한다. mock overlay는 참조 모드를 켜고, prod overlay는 두 서비스에 `BIDOPS_ENV=prod`를 고정해 엔진 검토의 `mock_reference` 기동을 차단한다.
- 앱 runtime amd64, 문서 worker native 플랫폼·network none 경계를 보존한다. 초기화·migration·배포·실제 전송은 별도 작업이다.
- 경로 변경은 선택기·COPY·문서·계약 검사를 함께 갱신한다. `make test-config`와 영향받는 runner 계약부터 확인하며 경로 이동만으로 전체 이미지를 재빌드하지 않는다.

# Docker 구성

저장소 루트에서 Make를 실행한다. `scripts/compose.sh`는 어느 디렉터리에서 호출해도 루트를 project directory로 지정한다. Compose의 `context: .`, bind mount, env, secret 상대 경로는 모두 저장소 루트 기준이다. `.dockerignore`도 루트에서 적용된다.

| 파일 | 책임 |
| --- | --- |
| `Dockerfile` | frontend 정적 빌드 + FastAPI/분석 runtime |
| `Document.Dockerfile` | native rhwp 문서 worker |
| `MinioInit.Dockerfile` | MinIO 초기화 도구 |
| `Ops.Dockerfile` | 명시적 백업·복구 도구 |
| `CodexRunner.Dockerfile` | 승인된 Luna 전용 runner, 소스는 `web/codex-runner/` |
| `docker-compose.yml` | 내부 애플리케이션·DB·객체 저장·worker |
| `docker-compose.edge.yml` | 공통 이미지·플랫폼·웹 publish |
| `docker-compose.prod.yml` | Mac 운영 이미지·모델·C-2 입력·G2B 설정 |
| `docker-compose.mock-reference.yml` | 모델 없는 참조 실행 |
| `docker-compose.luna.yml` | Luna runner의 제한된 인증·네트워크 |
| `docker-compose.slack-egress.yml` | web·Slack worker의 전용 env·egress |

개발은 base+edge, mock은 base+edge+mock, 운영은 base+edge+prod를 선택한다. Luna/Slack은 선택한 기본 env의 `BIDOPS_COMPOSE_FEATURES`로 추가한다. 파일을 수동으로 조합하거나 이 폴더에서 raw `docker compose`를 실행하지 않는다.

```bash
make config       # 구성 검증, 비밀값 출력 없음
make build        # 선택한 개발 이미지 빌드
make up           # 이미 만든 개발 컨테이너 시작
make status
make logs
make health
make test-config
```

초기화는 `make init`, 새 이미지 적용은 `make create`, migration은 `make migrate`로 명시한다. 기본은 `bidops-dev:18789`, mock은 `BIDOPS_ENV=mock`으로 `bidops-mock:18790`, 운영은 `BIDOPS_ENV=prod`로 기존 `bidops:18788`이다. 이번 파일 이동으로 project·volume 이름은 바뀌지 않으며 기존 데이터 연결을 유지한다. 운영 변경은 별도 승인 후 [운영 절차](../docs/operations.md)를 따른다.

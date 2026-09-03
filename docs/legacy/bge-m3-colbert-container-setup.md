# BGE-M3 ColBERT 완전 컨테이너형 환경 설정

> **보관본이다.** [ADR-0037](../tracking/decisions/0037-order-plan-c2-bm25-top300-qwen.md)이
> C-2 발주계획 선별을 `BM25 Top 300 + Qwen`으로 확정하면서 ColBERT 경로는 채택되지 않았다.
> 이 컨테이너 구성을 새로 만들지 않는다. 비교 실험 코드는 `experiments/order-plan-screening/`에 남아 있다.
> 원래 경로는 `docs/bge-m3-colbert-container-setup.md`였다.


작성 기준: 2026-08-28

배경 확인 세션: `01a043d2-9fe2-76f3-98e2-99b498a1e9af`

## 1. 목표

Ollama가 실행 중인 NVIDIA GPU 서버의 운영체제에는 Python, PyTorch, CUDA Toolkit, FlagEmbedding, Hugging Face 모델 또는 BidOps repository를 설치하지 않는다. 다음 항목을 하나의 `bge-m3-colbert` image에 포함해 build 머신에서 완성한 뒤 서버로 전달한다.

- Python과 고정 전이 의존성
- GPU용 PyTorch와 CUDA user-space runtime
- `FlagEmbedding==1.4.2`
- BidOps ColBERT 실행 코드
- 고정 revision의 `BAAI/bge-m3` 모델 가중치
- offline 합성 smoke script

서버에 필요한 소프트웨어는 아래 GPU container 실행 기반뿐이다.

- Docker Engine과 Docker Compose
- NVIDIA GPU driver
- NVIDIA Container Toolkit

NVIDIA GPU driver는 host kernel과 연결되므로 image 안으로 옮길 수 없다. 반면 CUDA Toolkit과 Python application stack은 image 안에 둘 수 있으며 host에는 CUDA Toolkit을 별도로 설치하지 않아도 된다. [NVIDIA Container Toolkit 설치 문서](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html), [Docker Compose GPU 공식 문서](https://docs.docker.com/compose/how-tos/gpu-support/)

## 2. image와 runtime data의 경계

“모두 컨테이너에 포함”은 실행 소프트웨어와 공개 모델 artifact를 image에 포함한다는 뜻이다. 회사자료와 실행 결과까지 image layer에 넣지는 않는다.

| 대상 | 위치 | 이유 |
|---|---|---|
| Python·PyTorch·CUDA runtime·FlagEmbedding | image | 서버 package 설치 제거, image digest로 고정 |
| `BAAI/bge-m3` 고정 snapshot | image | runtime 다운로드와 host model cache 제거 |
| `common.py`, `methods.py`, `run_methods.py` | image | 서버의 BidOps checkout 제거 |
| 회사 역량 승인본·methods config | runtime read-only mount | 회사자료를 image·registry·build cache에 넣지 않음 |
| 불변 run·population과 결과 | runtime read-write mount | 입력·결과 보존, 기존 run 덮어쓰기 금지 |
| API key·Hugging Face token | image에 없음 | 공개 모델이며 runtime network도 사용하지 않음 |

입력과 결과도 물리적으로는 서버 disk 또는 승인된 storage에 있어야 한다. 이는 package 설치가 아니라 보존 대상 데이터다. ephemeral container filesystem에만 결과를 두면 container 종료 시 사라지므로 금지한다.

## 3. dense와 ColBERT 구분

Ollama의 `bge-m3`와 이 image의 BGE-M3 ColBERT는 다른 실행 방법이다.

| 구분 | Ollama `bge-m3` | `bge-m3-colbert` image |
|---|---|---|
| 출력 | 입력당 dense vector 1개 | 입력 token별 vector 묶음 |
| 호출 경로 | Ollama `/api/embed` | `FlagEmbedding` 직접 실행 |
| BidOps 방법명 | `bge_m3_dense` | `bge_m3_colbert` |
| 점수 | dense cosine | token-level late-interaction |

Ollama 모델을 복사하거나 이름만 바꿔서는 ColBERT가 되지 않는다. BGE-M3의 multi-vector 출력은 `return_colbert_vecs=True` 경로로 생성한다. [FlagEmbedding BGE-M3 공식 예제](https://github.com/FlagOpen/FlagEmbedding/blob/master/research/BGE_M3/README.md), [BAAI/bge-m3 모델 카드](https://huggingface.co/BAAI/bge-m3)

## 4. 배포 흐름

```text
승인된 build 머신
  ├─ BidOps source checkout
  ├─ dependency lock
  ├─ PyTorch CUDA base image
  ├─ FlagEmbedding 설치
  ├─ BAAI/bge-m3 고정 revision 다운로드
  ├─ source·model·metadata 포함 image build
  └─ image digest 확정
          │
          ├─ 승인 registry push
          │     또는
          └─ docker save + archive SHA-256
                │
                ▼
NVIDIA GPU 서버
  ├─ image pull 또는 docker load
  ├─ 승인 입력 read-only mount
  ├─ 불변 run/result read-write mount
  ├─ network_mode: none
  └─ ColBERT job 실행 후 container 제거
```

모델 다운로드는 image build 때만 일어난다. GPU 서버의 runtime container에는 network가 없고 Hugging Face cache volume이나 repository bind mount도 없다.

## 5. 고정 실행 계약

현재 저장소의 기준은 다음과 같다.

| 항목 | 기준값 | 정본 |
|---|---|---|
| Python package | [`FlagEmbedding==1.4.2`](https://pypi.org/project/FlagEmbedding/1.4.2/) | `experiments/order-plan-screening/requirements-models.txt` |
| 모델 | `BAAI/bge-m3` | `experiments/order-plan-screening/config/methods.json` |
| 모델 revision | [`5617a9f61b028005a4858fdac845db406aefb181`](https://huggingface.co/BAAI/bge-m3/tree/5617a9f61b028005a4858fdac845db406aefb181) | `bge_m3_colbert.model_revision` |
| batch size | `12` | `bge_m3_colbert.batch_size` |
| max length | `512` | `bge_m3_colbert.max_length` |
| GPU device | `cuda:0` | 새 GPU methods config |
| precision | FP16 | 새 GPU methods config |
| 입력 | 승인 회사 역량 요약을 query, `title`을 passage로 사용 | 실험 계약 |
| 점수 | query token별 passage max-sim의 평균, capability 중 최댓값 | `BGEM3ColBERTAdapter` |

비교 실행 전에는 다음도 고정한다.

- PyTorch base image tag와 registry digest
- Python 전이 의존성 전체 lock과 package hash
- 완성 image의 registry digest 또는 offline archive SHA-256
- image label의 model name·revision
- NVIDIA driver, GPU, PyTorch, CUDA runtime
- methods config, population, company capability projection hash

현재 Git의 methods config는 CPU용 `device: "cpu"`, `use_fp16: false`다. GPU 실행은 기존 config와 과거 run을 수정하지 않고 새 승인 config와 새 run ID로 준비한다.

## 6. 구현 파일

다음 파일을 build branch에 추가한다.

```text
bidops/
├── containers/
│   └── bge-m3-colbert/
│       ├── Dockerfile
│       ├── Dockerfile.dockerignore
│       ├── download_model.py
│       ├── smoke_colbert.py
│       └── requirements.lock
└── docker-compose.t7.colbert.yml
```

회사 역량 파일, methods 승인본, raw, run, 결과, API key는 Docker build context 자체에서 제외한다. Dockerfile에서 `COPY`하지 않는 것만으로는 충분하지 않다. context에 들어간 파일은 builder로 전송되므로 Dockerfile 전용 allowlist를 사용한다. [Docker build context 공식 문서](https://docs.docker.com/build/concepts/context/)

### 6.1 Docker build context allowlist

`containers/bge-m3-colbert/Dockerfile.dockerignore`를 다음처럼 작성한다. Dockerfile과 같은 directory의 `<Dockerfile>.dockerignore`는 repository root의 `.dockerignore`보다 우선한다.

```dockerignore
**
!containers
!containers/bge-m3-colbert
!containers/bge-m3-colbert/Dockerfile
!containers/bge-m3-colbert/Dockerfile.dockerignore
!containers/bge-m3-colbert/download_model.py
!containers/bge-m3-colbert/smoke_colbert.py
!containers/bge-m3-colbert/requirements.lock
!experiments
!experiments/order-plan-screening
!experiments/order-plan-screening/scripts
!experiments/order-plan-screening/scripts/common.py
!experiments/order-plan-screening/scripts/methods.py
!experiments/order-plan-screening/scripts/run_methods.py
```

이 allowlist는 `.env`, `.git`, `.dryforge`, 회사 역량 원본, 승인 config, `data`, `reports`, raw, run, 결과가 build daemon이나 remote builder에 전달되는 것부터 막는다. ColBERT code가 다른 module을 새로 import하게 되면 directory 전체를 허용하지 말고 필요한 파일만 검토 후 한 줄씩 추가한다.

## 7. 1단계: build 머신에서 dependency lock 확정

최초 candidate 환경에서만 현재 `requirements-models.txt`의 `FlagEmbedding==1.4.2`를 설치해 호환성을 확인한다. 실제 image build에는 전이 의존성과 hash가 모두 고정된 `containers/bge-m3-colbert/requirements.lock`을 사용한다.

1. 승인할 digest-pinned PyTorch CUDA base image를 선택한다.
2. 그 image에서 `FlagEmbedding==1.4.2`와 전이 의존성을 설치한다.
3. model load와 ColBERT smoke를 통과시킨다.
4. dependency resolver로 exact version과 artifact hash가 있는 lock을 만든다.
5. 빈 build cache에서 `--require-hashes` 설치를 재검증한다.

사용 가능한 공식 image는 [PyTorch Docker Hub](https://hub.docker.com/r/pytorch/pytorch/tags)와 [PyTorch 설치 선택기](https://pytorch.org/get-started/locally/)에서 확인한다. `latest` tag는 사용하지 않는다.

## 8. 2단계: 모델 다운로드 script 작성

`containers/bge-m3-colbert/download_model.py`는 Docker build 중에만 실행한다. full commit SHA가 다른 snapshot을 받으면 build를 실패시킨다.

```python
import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download


MODEL_NAME = os.environ["BGE_MODEL_NAME"]
MODEL_REVISION = os.environ["BGE_MODEL_REVISION"]
HF_HUB_CACHE = os.environ["HF_HUB_CACHE"]

path = Path(
    snapshot_download(
        repo_id=MODEL_NAME,
        revision=MODEL_REVISION,
        cache_dir=HF_HUB_CACHE,
    )
).resolve()

if path.name != MODEL_REVISION:
    raise SystemExit("resolved model revision mismatch")

metadata = {
    "schema_version": "bidops.colbert-image-model.v1",
    "model_name": MODEL_NAME,
    "model_revision": MODEL_REVISION,
}
Path("/opt/bidops-colbert/model-metadata.json").write_text(
    json.dumps(metadata, sort_keys=True) + "\n",
    encoding="utf-8",
)
```

`snapshot_download()`은 `revision`에 full commit hash를 받을 수 있다. [Hugging Face download 공식 문서](https://huggingface.co/docs/huggingface_hub/guides/download)

## 9. 3단계: offline smoke script 작성

`containers/bge-m3-colbert/smoke_colbert.py`는 image 안의 cache만 사용한다. 실제 회사자료나 발주계획을 사용하지 않으며 입력 문구와 vector를 로그에 출력하지 않는다.

```python
import json
import math
import os
from pathlib import Path

import torch
from FlagEmbedding import BGEM3FlagModel
from huggingface_hub import snapshot_download


MODEL_NAME = os.environ["BGE_MODEL_NAME"]
MODEL_REVISION = os.environ["BGE_MODEL_REVISION"]

if not torch.cuda.is_available():
    raise SystemExit("cuda is not available")

model_path = Path(
    snapshot_download(
        repo_id=MODEL_NAME,
        revision=MODEL_REVISION,
        cache_dir=os.environ["HF_HUB_CACHE"],
        local_files_only=True,
    )
).resolve()
if model_path.name != MODEL_REVISION:
    raise SystemExit("cached model revision mismatch")

model = BGEM3FlagModel(
    str(model_path),
    use_fp16=True,
    devices=["cuda:0"],
)
output = model.encode(
    [
        "공공 정보화 시스템 구축 역량",
        "인공지능 기반 행정 데이터 분석 시스템 구축",
    ],
    batch_size=2,
    max_length=512,
    return_dense=False,
    return_sparse=False,
    return_colbert_vecs=True,
)

vectors = output["colbert_vecs"]
score = float((vectors[0] @ vectors[1].T).max(axis=1).mean())
if len(vectors) != 2 or not math.isfinite(score):
    raise SystemExit("invalid ColBERT smoke result")

print(
    json.dumps(
        {
            "status": "passed",
            "model_name": MODEL_NAME,
            "model_revision": MODEL_REVISION,
            "torch_version": torch.__version__,
            "cuda_runtime": torch.version.cuda,
            "gpu": torch.cuda.get_device_name(0),
            "item_count": len(vectors),
            "score_is_finite": True,
        },
        sort_keys=True,
    )
)
```

계산식은 현재 adapter의 `query_vector @ passage_vector.T → token별 max → mean`과 같다.

## 10. 4단계: 모델과 실행 코드를 포함한 Dockerfile 작성

`containers/bge-m3-colbert/Dockerfile` 예시는 다음과 같다.

```dockerfile
ARG PYTORCH_BASE_IMAGE
FROM ${PYTORCH_BASE_IMAGE}

ARG BIDOPS_UID=10001
ARG BIDOPS_GID=10001
ARG BGE_MODEL_NAME=BAAI/bge-m3
ARG BGE_MODEL_REVISION=5617a9f61b028005a4858fdac845db406aefb181

RUN test "${BIDOPS_UID}" -ne 0 \
    && install -d -o "${BIDOPS_UID}" -g "${BIDOPS_GID}" \
       /opt/bidops-colbert \
       /opt/huggingface/hub

COPY containers/bge-m3-colbert/requirements.lock /tmp/requirements.lock
RUN python -m pip install --no-cache-dir \
    --require-hashes \
    --requirement /tmp/requirements.lock

COPY containers/bge-m3-colbert/download_model.py \
     containers/bge-m3-colbert/smoke_colbert.py \
     /opt/bidops-colbert/

# 회사자료와 config는 복사하지 않는다. ColBERT 실행에 필요한 code만 복사한다.
COPY experiments/order-plan-screening/scripts/common.py \
     experiments/order-plan-screening/scripts/methods.py \
     experiments/order-plan-screening/scripts/run_methods.py \
     /opt/bidops-colbert/

ENV HOME=/tmp \
    HF_HOME=/opt/huggingface \
    HF_HUB_CACHE=/opt/huggingface/hub \
    HF_HUB_DISABLE_TELEMETRY=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TOKENIZERS_PARALLELISM=false \
    BGE_MODEL_NAME=${BGE_MODEL_NAME} \
    BGE_MODEL_REVISION=${BGE_MODEL_REVISION}

RUN python /opt/bidops-colbert/download_model.py \
    && test -f /opt/bidops-colbert/model-metadata.json \
    && chown -R "${BIDOPS_UID}:${BIDOPS_GID}" \
       /opt/bidops-colbert /opt/huggingface

ENV HF_HUB_OFFLINE=1

LABEL org.bidops.component="bge-m3-colbert" \
      org.bidops.model.name="${BGE_MODEL_NAME}" \
      org.bidops.model.revision="${BGE_MODEL_REVISION}"

USER ${BIDOPS_UID}:${BIDOPS_GID}
WORKDIR /work
ENTRYPOINT ["python", "/opt/bidops-colbert/run_methods.py"]
```

중요한 경계는 다음과 같다.

- 모델 download가 실패하면 image build도 실패한다.
- model cache는 `/opt/huggingface` image layer에 포함된다.
- runtime에는 cache volume을 mount하지 않는다.
- runtime은 `HF_HUB_OFFLINE=1`로 network lookup을 시도하지 않는다.
- 회사 역량, methods config, run data는 image에 포함하지 않는다.
- build log와 image metadata에 token 또는 build 머신 경로를 남기지 않는다.

## 11. 5단계: build 머신에서 image 생성

build 머신의 BidOps repository root에서 실행한다. base image는 반드시 registry digest까지 고정한다.

```bash
export BIDOPS_COLBERT_BASE_IMAGE='pytorch/pytorch:<검증한-tag>@sha256:<검증한-digest>'
export BIDOPS_COLBERT_IMAGE='registry.internal.example/bidops/bge-m3-colbert:20260828-1'

docker build --pull \
  --file containers/bge-m3-colbert/Dockerfile \
  --build-arg PYTORCH_BASE_IMAGE="$BIDOPS_COLBERT_BASE_IMAGE" \
  --build-arg BIDOPS_UID=10001 \
  --build-arg BIDOPS_GID=10001 \
  --build-arg BGE_MODEL_NAME=BAAI/bge-m3 \
  --build-arg BGE_MODEL_REVISION=5617a9f61b028005a4858fdac845db406aefb181 \
  --tag "$BIDOPS_COLBERT_IMAGE" \
  .
```

build 전에 `containers/bge-m3-colbert/Dockerfile.dockerignore`가 존재하는지 확인한다. root `.dockerignore`의 차단 목록에 기대지 않고 Dockerfile 전용 allowlist와 Dockerfile의 제한된 `COPY` 목록을 함께 유지한다.

## 12. 6단계: build 결과 정적 검증

GPU smoke 전에도 image에 고정된 metadata와 package를 확인한다.

```bash
docker image inspect "$BIDOPS_COLBERT_IMAGE" \
  --format '{{json .Config.Labels}}'

docker run --rm --entrypoint python "$BIDOPS_COLBERT_IMAGE" \
  -c 'import json; print(json.load(open("/opt/bidops-colbert/model-metadata.json")))'

docker run --rm --entrypoint python "$BIDOPS_COLBERT_IMAGE" \
  -c 'import importlib.metadata as m; print(m.version("FlagEmbedding"))'
```

다음을 확인한다.

- label과 `model-metadata.json`의 revision이 정확한 full commit SHA다.
- `FlagEmbedding` version이 `1.4.2`다.
- `/opt/bidops-colbert/run_methods.py`가 존재한다.
- image history에 secret, 회사자료, 승인 config가 없다.
- 완성 image ID를 build 기록에 남겼다.

GPU가 있는 build 머신이라면 offline smoke도 실행한다.

```bash
docker run --rm \
  --gpus device=0 \
  --network none \
  --read-only \
  --tmpfs /tmp:size=1g,mode=1777 \
  --entrypoint python \
  "$BIDOPS_COLBERT_IMAGE" \
  /opt/bidops-colbert/smoke_colbert.py
```

## 13. 7단계: image 전달

### 승인 registry 사용

```bash
docker push "$BIDOPS_COLBERT_IMAGE"
docker buildx imagetools inspect "$BIDOPS_COLBERT_IMAGE"
```

출력된 registry manifest digest를 배포 기록과 Compose의 `image`에 고정한다. tag만 배포 기준으로 사용하지 않는다.

### registry 없이 offline archive 사용

```bash
docker save "$BIDOPS_COLBERT_IMAGE" \
  | gzip > bge-m3-colbert-20260828-1.tar.gz

sha256sum bge-m3-colbert-20260828-1.tar.gz \
  > bge-m3-colbert-20260828-1.tar.gz.sha256
```

archive와 SHA-256 manifest를 승인된 전송 경로로 서버에 복사한다. 서버에서 검증한 뒤 load한다.

```bash
sha256sum --check bge-m3-colbert-20260828-1.tar.gz.sha256
gunzip --stdout bge-m3-colbert-20260828-1.tar.gz \
  | docker load
```

image archive에는 공개 모델이 포함되지만 회사자료나 secret은 없어야 한다.

## 14. 8단계: GPU 서버의 최소 사전 조건 확인

서버에서는 Python이나 CUDA Toolkit을 설치하지 않는다.

```bash
nvidia-smi
docker version
docker compose version

docker run --rm --gpus all \
  nvidia/cuda:12.6.3-base-ubuntu22.04 \
  nvidia-smi
```

GPU probe가 실패하면 application package가 아니라 host GPU runtime 경계를 고친다. NVIDIA driver와 Container Toolkit은 GPU container를 실행하기 위한 필수 host 구성이다. Compose reservation에는 `capabilities: [gpu]`가 필요하며 `count`와 `device_ids`를 함께 쓰지 않는다.

`nvidia-smi`의 CUDA 문자열만으로 image를 선택하지 않고 host driver와 image CUDA runtime의 호환 범위를 확인한다. [NVIDIA CUDA 호환성 문서](https://docs.nvidia.com/deploy/cuda-compatibility/minor-version-compatibility.html)

## 15. 9단계: 서버에 승인 입력과 결과 경로만 준비

서버에는 BidOps source checkout이나 model cache가 필요 없다. 승인 config와 run data를 보존할 두 경로만 준비한다.

```bash
test "$(id -u)" -ne 0
export BIDOPS_UID="$(id -u)"
export BIDOPS_GID="$(id -g)"
export BIDOPS_COLBERT_APPROVED_DIR='/srv/bidops-colbert/approved'
export BIDOPS_COLBERT_RUNS_DIR='/srv/bidops-colbert/runs'

test -d "$BIDOPS_COLBERT_APPROVED_DIR" \
  || install -d -m 0700 "$BIDOPS_COLBERT_APPROVED_DIR"
test -d "$BIDOPS_COLBERT_RUNS_DIR" \
  || install -d -m 0700 "$BIDOPS_COLBERT_RUNS_DIR"
test -w "$BIDOPS_COLBERT_RUNS_DIR"
```

다음 파일만 승인된 전송 절차로 배치한다.

```text
/srv/bidops-colbert/
├── approved/
│   ├── company-capabilities.json
│   └── methods-colbert-gpu.json
└── runs/
    └── <새-run-id>/
        ├── run.json
        ├── population.json
        └── results/
```

symlink, 경로 이탈, 기존 result 파일이 있는 run을 거부한다. 전송 전후 manifest SHA-256을 비교한다.

## 16. 10단계: GPU methods config와 run을 build 환경에서 준비

현재 CPU methods config를 수정하지 않는다. 승인 경로에 전체 schema를 유지한 새 GPU config를 만든다. 바뀌는 ColBERT 부분은 다음과 같다.

```json
{
  "bge_m3_colbert": {
    "model_name": "BAAI/bge-m3",
    "model_revision": "5617a9f61b028005a4858fdac845db406aefb181",
    "batch_size": 12,
    "max_length": 512,
    "use_fp16": true,
    "device": "cuda:0"
  }
}
```

위 JSON은 변경 부분을 설명한 fragment다. 실제 전달 파일은 전체 methods schema여야 한다.

이미 동결된 raw 모집단을 새 config와 결합해 새 run ID로 replay한다. `run.json`의 methods config hash와 company capability hash가 전달 파일과 처음부터 일치해야 한다. 기존 run, raw, 결과, 리뷰는 덮어쓰지 않는다.

## 17. 11단계: 서버용 Compose 작성

`docker-compose.t7.colbert.yml`에는 `build`, source mount, model cache mount가 없다. digest-pinned image와 승인 data mount만 사용한다.

```yaml
x-colbert-common: &colbert-common
  image: "${BIDOPS_COLBERT_IMAGE:?set a digest-pinned image}"
  restart: "no"
  user: "${BIDOPS_UID:?set a non-root uid}:${BIDOPS_GID:?set a non-root gid}"
  read_only: true
  network_mode: none
  environment:
    HOME: /tmp
    HF_HOME: /opt/huggingface
    HF_HUB_CACHE: /opt/huggingface/hub
    HF_HUB_OFFLINE: "1"
    HF_HUB_DISABLE_TELEMETRY: "1"
    BGE_MODEL_NAME: BAAI/bge-m3
    BGE_MODEL_REVISION: 5617a9f61b028005a4858fdac845db406aefb181
    CUDA_VISIBLE_DEVICES: "0"
  tmpfs:
    - /tmp:size=1g,mode=1777
  volumes:
    - type: bind
      source: "${BIDOPS_COLBERT_APPROVED_DIR:?set the approved input path}"
      target: /approved
      read_only: true
    - type: bind
      source: "${BIDOPS_COLBERT_RUNS_DIR:?set the immutable run path}"
      target: /runs
  deploy:
    resources:
      reservations:
        devices:
          - driver: nvidia
            device_ids: ["0"]
            capabilities: [gpu]

services:
  bge-m3-colbert-smoke:
    <<: *colbert-common
    profiles: ["colbert-smoke"]
    entrypoint: ["python", "/opt/bidops-colbert/smoke_colbert.py"]

  bge-m3-colbert:
    <<: *colbert-common
    profiles: ["colbert"]
    entrypoint: ["python", "/opt/bidops-colbert/run_methods.py"]
```

registry 배포라면 `BIDOPS_COLBERT_IMAGE`는 다음처럼 digest를 포함한다.

```bash
export BIDOPS_COLBERT_IMAGE='registry.internal.example/bidops/bge-m3-colbert@sha256:<manifest-digest>'
```

offline `docker load` 배포는 검증한 local image ID에 대응하는 tag를 사용하고 archive SHA-256과 image ID를 함께 기록한다. `pull_policy: never`가 필요한 air-gapped 운영은 별도 offline overlay에 명시한다.

## 18. 12단계: Qwen을 GPU memory에서 내리기

Ollama와 ColBERT가 같은 GPU를 동시에 사용하지 않도록 순차 실행한다. Ollama container를 정확히 확인한 뒤 Qwen만 내린다.

```bash
docker ps --format '{{.Names}}\t{{.Image}}\t{{.Status}}'

docker exec <확인한-ollama-container> \
  ollama stop qwen3.8:27b
```

`ollama stop`은 model file을 삭제하지 않는다. container 이름을 추정하거나 Ollama volume을 삭제하지 않는다.

## 19. 13단계: 서버에서 offline GPU smoke

```bash
COMPOSE_PROJECT_NAME=bidops-colbert \
docker compose \
  -f docker-compose.t7.colbert.yml \
  --profile colbert-smoke \
  config --quiet

COMPOSE_PROJECT_NAME=bidops-colbert \
docker compose \
  -f docker-compose.t7.colbert.yml \
  --profile colbert-smoke \
  run --rm --no-deps bge-m3-colbert-smoke
```

다음을 모두 확인한다.

- `model_revision`이 full commit SHA와 정확히 일치
- `FlagEmbedding` model load 성공
- `item_count`가 2
- `score_is_finite`가 true
- `cuda is not available` 오류 없음
- container network 없음
- host model cache와 repository mount 없음
- 종료 뒤 GPU memory 회수

## 20. 14단계: readiness와 실제 ColBERT 실행

먼저 모델 호출 없는 readiness를 실행한다.

```bash
export BIDOPS_COLBERT_RUN_ID='<새-run-id>'

COMPOSE_PROJECT_NAME=bidops-colbert \
docker compose \
  -f docker-compose.t7.colbert.yml \
  --profile colbert \
  run --rm --no-deps bge-m3-colbert \
  --run-dir "/runs/${BIDOPS_COLBERT_RUN_ID}" \
  --method bge_m3_colbert \
  --check-ready \
  --company-capabilities /approved/company-capabilities.json \
  --methods-config /approved/methods-colbert-gpu.json
```

성공 뒤 같은 명령에서 `--check-ready`만 제거해 실제 실행한다. 실행 전 `/runs/<run-id>/results/bge_m3_colbert.json`이 없어야 한다. 현재 writer는 기존 파일을 덮어쓰지 않고 실패해야 정상이다.

실행 기록에는 다음 metadata만 남긴다.

- run ID와 population hash
- company capability projection과 methods config hash
- model name과 revision
- base image digest, 완성 image digest 또는 archive SHA-256
- FlagEmbedding, PyTorch, CUDA runtime, driver, GPU
- device, precision, batch size, max length
- 시작·종료 시각, 성공·실패 수, 안전한 오류 코드

회사 역량 문구, 전체 title batch, vector, 내부 경로, 환경변수 전체, traceback을 일반 로그에 남기지 않는다.

## 21. 실패 처리

### GPU를 찾지 못함

host의 `nvidia-smi`와 CUDA probe를 먼저 확인한다. NVIDIA driver·Container Toolkit·Compose `device_ids`를 고친다. Python package를 host에 설치하거나 CPU로 자동 fallback하지 않는다.

### CUDA OOM

Qwen이 memory에 남아 있는지 확인한다. batch size를 줄여야 하면 새 methods config와 새 run ID를 만든다. 같은 run 도중 batch size나 FP16 설정을 변경해 이어서 실행하지 않는다.

### runtime에서 모델 다운로드 시도

image build 불완전으로 처리한다. runtime network나 Hugging Face cache volume을 추가하지 않는다. build 머신에서 정확한 revision을 image에 다시 포함하고 새 image digest로 smoke부터 반복한다.

### dependency 충돌

서버 container 안에서 `pip install`하지 않는다. build 머신에서 lock을 수정하고 새 image를 만든 뒤 정적 검증과 offline smoke를 다시 수행한다.

### 결과 쓰기 권한 오류

host의 run directory와 numeric UID/GID를 확인한다. `chmod 777`로 해결하지 않는다. 기존 run result를 삭제하거나 소유권을 root로 바꾸지 않는다.

### image metadata 불일치

tag를 신뢰해 진행하지 않는다. registry digest 또는 archive SHA-256, image label, model metadata, methods config revision 중 하나라도 다르면 실행을 중단한다.

## 22. 완료 체크리스트

- [ ] 서버 host에는 Python, PyTorch, CUDA Toolkit, FlagEmbedding을 설치하지 않았다.
- [ ] 서버에 BidOps repository와 Hugging Face model cache를 만들지 않았다.
- [ ] NVIDIA driver, Docker, Container Toolkit만 GPU runtime 기반으로 사용했다.
- [ ] Python dependency와 package hash를 lock했다.
- [ ] Dockerfile 전용 allowlist로 회사자료·secret을 build context에서 제외했다.
- [ ] 공개 BGE-M3 고정 snapshot을 image layer에 포함했다.
- [ ] ColBERT 실행 code와 smoke script를 image에 포함했다.
- [ ] 회사자료·승인 config·run data·secret을 image에 포함하지 않았다.
- [ ] 완성 image를 registry digest 또는 archive SHA-256으로 고정했다.
- [ ] runtime은 `network_mode: none`이고 host port가 없다.
- [ ] 승인 입력은 read-only, run/result는 제한된 read-write mount다.
- [ ] Qwen과 ColBERT를 동일 GPU에서 순차 실행한다.
- [ ] 합성 입력 offline smoke가 통과했다.
- [ ] 새 GPU config와 새 immutable run을 사용했다.
- [ ] readiness 뒤 실제 실행했다.
- [ ] CPU fallback, runtime package 설치, runtime model download를 허용하지 않았다.
- [ ] ColBERT와 사람 정답이 없으면 운영 방법 선정·활성화를 완료로 표시하지 않는다.

## 23. 후속: 상시 내부 API

현재 일회성 비교에는 self-contained job image가 가장 작은 변경이다. 향후 원격 상시 API가 필요하면 같은 image 원칙을 유지하되 별도 계약 변경으로 구현한다.

- image 안에 API code와 모델을 함께 포함
- `/health`, `/revision`, `/score`만 내부 network에 제공
- title과 승인 회사 역량 projection만 받는 strict schema
- 동시 실행 1, body·batch·timeout 제한
- 요청·응답 본문을 기록하지 않는 로그
- exact model revision과 image digest 불일치 시 fail closed
- BidOps HTTP adapter와 fake/live 분리 테스트

상시 API도 Ollama나 외부 모델의 자동 fallback으로 만들지 않는다.

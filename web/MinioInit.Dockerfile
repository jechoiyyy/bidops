# MinIO 초기화(minio-init) 이미지. Mac overlay(docker-compose.mac.yml)가 쓴다.
# 공식 minio/mc 이미지 대신 digest 고정 Chainguard mc 바이너리만 alpine에 담는다.
FROM cgr.dev/chainguard/minio-client@sha256:7a5387f27d1aa8fc11286acde9e024b7b1b77585e17c36378552eeafcccf2ba3 AS client
FROM alpine:3.22
COPY --from=client /usr/bin/mc /usr/bin/mc
RUN mc --version

"""Portfolio only: copy every object version of selected buckets from a source MinIO
(read-only use: list + get) into an empty, versioned portfolio MinIO and write the
source->target version mapping in the restore.sh mapping format:

    namespace/object_name<TAB>source_version_id<TAB>target_version_id<TAB>sha256

Versions are copied oldest first per object so the newest stays the newest. Each put is
checked against the bytes read (size, and MD5 against the single-part ETag). The script is
resumable: rows already in the mapping file are skipped. Delete markers are not copied
and are counted.

Runs inside the BidOps app image (minio SDK) on a container attached to both storage
networks. Credentials come from the environment only and are never printed:
SRC_ENDPOINT SRC_ACCESS_KEY SRC_SECRET_KEY DST_ENDPOINT DST_ACCESS_KEY DST_SECRET_KEY.

    python copy-objects.py --mapping /out/object-version-mapping.tsv bidops-source bidops-structure
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys

from minio import Minio

PART_SIZE = 512 * 1024 * 1024


def client(prefix: str) -> Minio:
    return Minio(os.environ[f"{prefix}_ENDPOINT"], access_key=os.environ[f"{prefix}_ACCESS_KEY"],
                 secret_key=os.environ[f"{prefix}_SECRET_KEY"], secure=False)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mapping", required=True)
    parser.add_argument("buckets", nargs="+")
    args = parser.parse_args()
    src, dst = client("SRC"), client("DST")
    done: set[tuple[str, str]] = set()
    if os.path.exists(args.mapping):
        with open(args.mapping, encoding="utf-8") as handle:
            for line in handle:
                key, source_vid, *_ = line.rstrip("\n").split("\t")
                done.add((key, source_vid))
    summary = {}
    with open(args.mapping, "a", encoding="utf-8") as out:
        for bucket in args.buckets:
            if not bucket.startswith("bidops-"):
                raise SystemExit("unexpected bucket name")
            namespace = bucket.removeprefix("bidops-")
            status = dst.get_bucket_versioning(bucket).status
            if status != "Enabled":
                raise SystemExit(f"target versioning is not enabled: {bucket}")
            versions = []
            markers = 0
            for item in src.list_objects(bucket, recursive=True, include_version=True):
                if item.is_delete_marker:
                    markers += 1
                    continue
                versions.append((item.object_name, item.last_modified, item.version_id))
            versions.sort(key=lambda v: (v[0], v[1]))
            copied = skipped = 0
            total_bytes = 0
            for name, _, version_id in versions:
                key = f"{namespace}/{name}"
                if (key, version_id) in done:
                    skipped += 1
                    continue
                response = src.get_object(bucket, name, version_id=version_id)
                try:
                    data = response.read()
                    content_type = response.headers.get("Content-Type") or "application/octet-stream"
                finally:
                    response.close()
                    response.release_conn()
                sha = hashlib.sha256(data).hexdigest()
                md5 = hashlib.md5(data).hexdigest()  # noqa: S324 - integrity check against ETag only
                # One PUT (no multipart) so the ETag is the MD5 of the bytes; app objects are <= 50 MiB.
                result = dst.put_object(bucket, name, io.BytesIO(data), len(data), content_type=content_type,
                                        part_size=PART_SIZE)
                target_vid = result.version_id
                if not target_vid:
                    raise SystemExit("target returned no version id")
                stat = dst.stat_object(bucket, name, version_id=target_vid)
                if stat.size != len(data) or (stat.etag or "").strip('"') != md5:
                    raise SystemExit("target object integrity check failed")
                out.write(f"{key}\t{version_id}\t{target_vid}\t{sha}\n")
                out.flush()
                copied += 1
                total_bytes += len(data)
                if copied % 200 == 0:
                    print(json.dumps({"bucket": bucket, "copied": copied, "of": len(versions)}), flush=True)
            summary[bucket] = {"versions": len(versions), "copied": copied, "skipped_already_mapped": skipped,
                               "delete_markers_not_copied": markers, "bytes_copied": total_bytes}
    print(json.dumps(summary), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

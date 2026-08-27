# HWPX conversion and HWP runtime provenance

- T2 authority upstream: https://github.com/jkf87/hwpx-skill.git
- Required authority commit: `96a2633f23a08f707679d7e212ebdc59948260e6`
- The required commit was acquired and checked out by hash before the T2
  implementation was reviewed. The local `hwpx.py` extractor is a stdlib
  implementation; no `rhwp` file is falsely attributed to this commit.
- HWP runtime provenance: `rhwp/rhwp.js` and `rhwp/rhwp_bg.wasm` are copied
  from https://github.com/DoHyun468/claw-hwp commit
  `583e327a4e1936d27061ba73086e83e538238a8e`.
- `rhwp_convert.mjs` is the local, deployment-only adapter around that runtime;
  its relative import is `./rhwp/rhwp.js` because the converter and runtime are
  kept in this vendor directory.
- The runtime's MIT notice is retained in `rhwp/LICENSE`. The T2 authority and
  third-party notices are retained in this directory, and exact bytes for every
  vendored file are listed in `SHA256SUMS` (the manifest excludes itself).

The processor invokes this runtime only with an internal temporary source path
inside a resource-limited child process. No user path, URL, shell string,
output path, credential, or proxy route is exposed to the child; deployment
must additionally place the worker in a network-disabled namespace.

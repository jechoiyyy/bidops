# HWPX conversion and native rhwp runtime provenance

- T2 authority upstream: https://github.com/jkf87/hwpx-skill.git
- Required authority commit: `96a2633f23a08f707679d7e212ebdc59948260e6`
- The required commit was acquired and checked out by hash before the T2
  implementation was reviewed. The local `hwpx.py` extractor is a stdlib
  implementation; no `rhwp` file is falsely attributed to this commit.
- Native CLI runtime: `rhwp/bin/rhwp` is copied unchanged from
  https://github.com/edwardkim/rhwp at commit
  `cac9b4f7cc743535cd7c00fe4f286abd67e7145b` (version output `rhwp v0.8.6`,
  based on tag `v0.8.6`). It was built with `cargo build --release` on Linux
  6.18.33.2-microsoft-standard-WSL2 x86_64 using rustc 1.98.1
  (`48a229cea 2026-09-01`) and cargo 1.98.1
  (`797e8a9bc 2026-08-05`). The copied linux x86_64 ELF has SHA-256
  `c82684971756d58ba7391cd08c38c93bb4280ab9ebf0e21c0936574a0084fc8c`
  and dynamically links only the platform loader, libc, libm, and libgcc_s.
- The native CLI's MIT notice is retained in `rhwp/LICENSE`. The T2 authority and
  third-party notices are retained in this directory, and exact bytes for every
  vendored file are listed in `SHA256SUMS` (the manifest excludes itself).

The processor invokes this runtime only with an internal temporary source path
inside a resource-limited child process. No user path, URL, shell string,
output path, credential, or proxy route is exposed to the child; deployment
must additionally place the worker in a network-disabled namespace.

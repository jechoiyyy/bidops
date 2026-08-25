# HWPX conversion runtime provenance

- Upstream: https://github.com/jkf87/hwpx-skill.git
- Required commit: `96a2633f23a08f707679d7e212ebdc59948260e6`
- Acquisition: commit was cloned and checked out by hash before vendoring.
- Runtime files copied: `rhwp_convert.mjs`, `rhwp/rhwp.js`, and
  `rhwp/rhwp_bg.wasm`.
- `rhwp_convert.mjs` has one deployment-only relative import adjustment
  (`./vendor/rhwp` → `./rhwp`) because this package keeps the converter and its
  runtime in the same vendor directory.
- The runtime's MIT notice is retained in `rhwp/LICENSE`; upstream's
  third-party notice is retained in `UPSTREAM_THIRD_PARTY_NOTICES.md`.

The processor invokes this runtime only with an internal temporary source path
inside a resource-limited child process.  No user path, URL, shell string,
output path, credential, or network capability is exposed to the child.

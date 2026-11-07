# Security policy

MaaLLMWiki publishes versioned catalog bundles from GitHub Releases. This policy covers the
integrity of those artifacts and of the supply chain that produces them — not the security of the
upstream projects the catalog describes.

## Supported versions

The newest published snapshot is the supported catalog version. Published snapshots are immutable:
a fix ships as a new `vX.Y.Z` snapshot, never by rewriting a tag or replacing an existing release
asset. There is no long-term-support branch.

## In scope

- A published bundle that does not match its `catalog-manifest.json`: file size/SHA-256 mismatch,
  extra or missing zip entries, or a manifest/wiki-revision inconsistency.
- Release assets that do not match `SHA256SUMS`, or a versioned bundle whose build-provenance
  attestation does not verify with
  `gh attestation verify maa-llm-wiki-catalog-vX.Y.Z.zip --repo Windsland52/MaaLLMWiki`.
- A catalog entry that points at the wrong or a mutable revision, a misclassified artifact, or a
  change to `sources/maa-framework/source-map.yaml` that bypassed human review.
- Supply-chain problems in this repository: workflow or action pinning, credential and token
  handling, publish-job integrity, release or tag manipulation.

## Out of scope

- Vulnerabilities in MaaFramework, the Go or Rust bindings, or any upstream project — report those
  upstream.
- Correctness disputes about upstream documentation content; use the catalog data error issue form.
- Availability, latency, rate limits, or GitHub platform incidents (see also
  `CATALOG-CONTRACT.md` §8.5 — no SLA).
- Runtime behaviour of a consumer's own application, or a consumer environment that can tamper with
  a file after you have verified it.

## Reporting a vulnerability privately

Use GitHub Security Advisories:
<https://github.com/Windsland52/MaaLLMWiki/security/advisories/new>.
Do **not** open a public issue for a suspected vulnerability.

Include enough detail to reproduce the discrepancy:

- the affected snapshot tag (for example `v0.1.17`) and the exact asset name you downloaded;
- the SHA-256 of the asset as downloaded (`sha256sum <asset>.zip`);
- the output of `sha256sum -c SHA256SUMS` and of
  `gh attestation verify <asset>.zip --repo Windsland52/MaaLLMWiki` (include the `gh` version), or
  the exact verification error;
- what you expected versus what you observed, with minimal reproduction steps;
- optionally the `wiki_revision` and `catalog_version` from the bundle's `catalog-manifest.json`.

Do not include secrets, access tokens, or personal data in a report.

## What to expect

- Acknowledgement, triage and fixes are best-effort; there is no SLA.
- A confirmed issue is corrected by publishing a new snapshot. Reporters are credited unless they
  ask to remain anonymous.
- Please allow a reasonable window for a fix before public disclosure.

## Related documents

- `CATALOG-CONTRACT.md` — what a snapshot guarantees, how to verify a bundle, checksums and
  provenance (§5), guarantees and their limits (§6), and known gaps (§8).
- `NOTICE`, `LICENSE`, `LICENSE-DATA` — licensing of the catalog and of quoted upstream excerpts.

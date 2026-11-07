# Pull request

## What and why

<!-- One or two sentences: what changes, and which fact/question it fixes. Link the issue or audit finding. -->

## Checklist

- [ ] I ran the required checks from `AGENTS.md`:
      `uv run maa-wiki-validate`, `uv run maa-wiki-generate-schemas` (then `git diff --check`),
      `uv run pytest`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run pyright`,
      `git diff --check`.
- [ ] I did **not** hand-edit `generated/`; it was produced by
      `uv run maa-wiki-sync-maafw-history` / `uv run maa-wiki-sync-bindings-history`.
- [ ] If I changed a Pydantic model, I regenerated `schemas/*.schema.json` with
      `uv run maa-wiki-generate-schemas` and committed the result.
- [ ] I did **not** hand-edit `sources/maa-framework/source-map.yaml` as part of a
      sync/automation change; if this PR changes it deliberately, the reason is explained above (the
      publish workflow refuses automated changes to it).
- [ ] I did **not** hand-edit `sources/maa-framework/machine-changes.yaml` or
      `sources/maa-framework/upstream-commits.yaml`; they come from the sync and
      `uv run maa-wiki-extract-changes`.
- [ ] Every new or changed source reference is pinned to a full 40-character commit SHA, never a
      branch or tag.
- [ ] Any quoted upstream text is a short excerpt with a link to the pinned source; no raw logs,
      dumps, screenshots, or unverified model-generated claims.

## Licence

Code contributions are accepted under the MIT License (`LICENSE`); catalog data contributions are
accepted under CC BY 4.0 (`LICENSE-DATA`). Upstream excerpts remain under their own licence
(`NOTICE`).

from __future__ import annotations

from datetime import date
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

COMMIT_PATTERN = r"^[0-9a-f]{40}$"
ID_PATTERN = r"^[a-z0-9]+(?:[.-][a-z0-9]+)*$"


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ArtifactKind(StrEnum):
    DOCUMENTATION = "documentation"
    DOCUMENTATION_ASSET = "documentation-asset"
    BINDING_API = "binding-api"
    SCHEMA = "schema"
    PUBLIC_API = "public-api"
    PACKAGE_MANIFEST = "package-manifest"


def _normalize_relative_path(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    candidate = PurePosixPath(normalized)
    if not normalized or candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("Source paths must be non-empty relative paths without parent traversal")
    return normalized


class SourceArtifact(StrictModel):
    path: str
    kind: ArtifactKind
    title: str = Field(min_length=1)
    summary: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _normalize_relative_path(value)


class SourceInventory(StrictModel):
    source_id: str = Field(pattern=ID_PATTERN)
    version: str = Field(min_length=1)
    revision: str = Field(pattern=COMMIT_PATTERN)
    artifacts: list[SourceArtifact] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_sorted_paths(self) -> SourceInventory:
        paths = [artifact.path for artifact in self.artifacts]
        if len(paths) != len(set(paths)):
            raise ValueError("Source inventory paths must be unique")
        if paths != sorted(paths):
            raise ValueError("Source inventory paths must be sorted")
        return self


class RepositoryRole(StrEnum):
    AUTHORITATIVE = "authoritative"
    MAINTAINER_GUIDANCE = "maintainer-guidance"


class RepositoryStatus(StrEnum):
    ACTIVE = "active"
    PLACEHOLDER = "placeholder"


class RepositorySource(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    role: RepositoryRole
    status: RepositoryStatus
    enabled: bool
    default_revision: str | None = Field(default=None, pattern=COMMIT_PATTERN)
    note: str | None = None

    @model_validator(mode="after")
    def validate_status(self) -> RepositorySource:
        if self.status is RepositoryStatus.ACTIVE:
            if not self.enabled or self.default_revision is None:
                raise ValueError("Active repositories must be enabled and pinned")
        elif self.enabled or self.default_revision is not None:
            raise ValueError("Placeholder repositories must be disabled and unpinned")
        return self


class RepositoryCatalog(StrictModel):
    repositories: list[RepositorySource] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_ids(self) -> RepositoryCatalog:
        ids = [repository.id for repository in self.repositories]
        if len(ids) != len(set(ids)):
            raise ValueError("Repository source IDs must be unique")
        return self


class ReleaseRecord(StrictModel):
    version: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    commit: str = Field(pattern=COMMIT_PATTERN)
    released_at: date


class PrereleaseRecord(StrictModel):
    version: str = Field(min_length=1)
    tag: str = Field(min_length=1)
    commit: str = Field(pattern=COMMIT_PATTERN)
    released_at: date
    included_in: str | None = None


class ReleaseCatalog(StrictModel):
    source_id: str = Field(pattern=ID_PATTERN)
    releases: list[ReleaseRecord] = Field(min_length=1)
    prereleases: list[PrereleaseRecord] = Field(default_factory=list[PrereleaseRecord])

    @model_validator(mode="after")
    def require_unique_versions(self) -> ReleaseCatalog:
        versions = [release.version for release in self.releases]
        if len(versions) != len(set(versions)):
            raise ValueError("Release versions must be unique")
        return self

    @model_validator(mode="after")
    def require_consistent_prereleases(self) -> ReleaseCatalog:
        stable_versions = {release.version for release in self.releases}
        stable_commits = {release.commit for release in self.releases}
        seen_versions: set[str] = set()
        seen_tags: set[str] = set()
        for prerelease in self.prereleases:
            if prerelease.version in stable_versions:
                raise ValueError(
                    f"Prerelease version collides with a stable release: {prerelease.version}"
                )
            if prerelease.commit in stable_commits:
                raise ValueError(
                    f"Prerelease tag points at a stable release commit: {prerelease.tag}"
                )
            if prerelease.version in seen_versions or prerelease.tag in seen_tags:
                raise ValueError(f"Duplicate prerelease entry: {prerelease.version}")
            seen_versions.add(prerelease.version)
            seen_tags.add(prerelease.tag)
            if prerelease.included_in is not None and prerelease.included_in not in stable_versions:
                raise ValueError(
                    f"Prerelease {prerelease.version} references unknown stable release: "
                    f"{prerelease.included_in}"
                )
        return self


class CompatibilityStatus(StrEnum):
    DECLARED = "declared"
    VERIFIED = "verified"
    UNKNOWN = "unknown"


class BindingCompatibility(StrictModel):
    source_id: str = Field(pattern=ID_PATTERN)
    binding_version: str = Field(min_length=1)
    binding_revision: str = Field(pattern=COMMIT_PATTERN)
    framework_version: str | None = None
    status: CompatibilityStatus
    evidence_paths: list[str] = Field(default_factory=list[str])
    note: str = Field(min_length=1)

    @field_validator("evidence_paths")
    @classmethod
    def validate_evidence_paths(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(path) for path in value]

    @model_validator(mode="after")
    def require_compatibility_evidence(self) -> BindingCompatibility:
        if self.status is CompatibilityStatus.UNKNOWN:
            if self.framework_version is not None:
                raise ValueError("Unknown compatibility cannot name a framework version")
        elif self.framework_version is None or not self.evidence_paths:
            raise ValueError("Declared or verified compatibility requires a version and evidence")
        return self


class BindingCompatibilityCatalog(StrictModel):
    bindings: list[BindingCompatibility] = Field(default_factory=list[BindingCompatibility])

    @model_validator(mode="after")
    def require_unique_binding_versions(self) -> BindingCompatibilityCatalog:
        keys = [(item.source_id, item.binding_version) for item in self.bindings]
        if len(keys) != len(set(keys)):
            raise ValueError("Binding compatibility entries must be unique")
        return self


class CatalogBundleFile(StrictModel):
    path: str
    size_bytes: int = Field(ge=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @field_validator("path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return _normalize_relative_path(value)


class CatalogBundleSource(StrictModel):
    source_id: str = Field(pattern=ID_PATTERN)
    version: str = Field(min_length=1)
    revision: str = Field(pattern=COMMIT_PATTERN)


class CatalogBundleManifest(StrictModel):
    api_version: Literal["maa-llm-wiki-catalog/v1"] = "maa-llm-wiki-catalog/v1"
    wiki_revision: str = Field(pattern=COMMIT_PATTERN)
    working_tree_clean: bool
    sources: list[CatalogBundleSource] = Field(min_length=1)
    files: list[CatalogBundleFile] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_sorted_content(self) -> CatalogBundleManifest:
        source_ids = [source.source_id for source in self.sources]
        if len(source_ids) != len(set(source_ids)):
            raise ValueError("Catalog bundle source IDs must be unique")
        paths = [file.path for file in self.files]
        if len(paths) != len(set(paths)):
            raise ValueError("Catalog bundle file paths must be unique")
        if paths != sorted(paths):
            raise ValueError("Catalog bundle file paths must be sorted")
        return self


class SemanticChange(StrictModel):
    topic_id: str = Field(pattern=ID_PATTERN)
    first_version: str = Field(min_length=1)
    revision: str = Field(pattern=COMMIT_PATTERN)
    description: str = Field(min_length=1)
    paths: list[str] = Field(min_length=1)

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(path) for path in value]


class SemanticChangeCatalog(StrictModel):
    source_id: str = Field(pattern=ID_PATTERN)
    changes: list[SemanticChange] = Field(default_factory=list[SemanticChange])


class SourceMapVariant(StrictModel):
    applies_to: str = Field(min_length=1)
    revision: str = Field(pattern=COMMIT_PATTERN)
    paths: list[str] = Field(min_length=1)
    symbols: list[str] = Field(default_factory=list[str])
    terms: list[str] = Field(min_length=1)

    @field_validator("paths")
    @classmethod
    def validate_paths(cls, value: list[str]) -> list[str]:
        return [_normalize_relative_path(path) for path in value]


class TopicSourceMap(StrictModel):
    id: str = Field(pattern=ID_PATTERN)
    source_id: str = Field(pattern=ID_PATTERN)
    variants: list[SourceMapVariant] = Field(min_length=1)


class SourceMap(StrictModel):
    topics: list[TopicSourceMap] = Field(min_length=1)

    @model_validator(mode="after")
    def require_unique_topics(self) -> SourceMap:
        ids = [topic.id for topic in self.topics]
        if len(ids) != len(set(ids)):
            raise ValueError("Source-map topic IDs must be unique")
        return self

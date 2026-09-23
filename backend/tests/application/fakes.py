from __future__ import annotations

from datetime import datetime, timezone

from core.application.models import Case, EvidenceFile, EvidenceKind, EvidenceMetadata
from core.application.ports import DomainInputs


FIXED_NOW = datetime(2026, 9, 10, 8, 0, tzinfo=timezone.utc)


class FixedIds:
    def __init__(self, *values: str) -> None:
        self._values = iter(values)

    def new_id(self) -> str:
        return next(self._values)


class FixedClock:
    def now(self) -> datetime:
        return FIXED_NOW


class MemoryCases:
    def __init__(self, *cases: Case) -> None:
        self.items = {case.id: case for case in cases}
        self.fail_save = False

    def save(self, case: Case) -> None:
        if self.fail_save:
            raise OSError("database unavailable")
        self.items[case.id] = case

    def get(self, case_id: str) -> Case | None:
        return self.items.get(case_id)


class MemoryWorkspaces:
    def __init__(self) -> None:
        self.created: list[str] = []
        self.discarded: list[str] = []

    def create(self, case_id: str) -> str:
        path = f"/workspaces/{case_id}"
        self.created.append(path)
        return path

    def discard(self, workspace_path: str) -> None:
        self.discarded.append(workspace_path)


class MemoryEvidence:
    def __init__(self, *evidence: EvidenceFile) -> None:
        self.items = {(item.case_id, item.id): item for item in evidence}

    def save(self, evidence: EvidenceFile) -> None:
        self.items[(evidence.case_id, evidence.id)] = evidence

    def get(self, case_id: str, evidence_id: str) -> EvidenceFile | None:
        return self.items.get((case_id, evidence_id))

    def find_by_source(self, case_id: str, canonical_path: str) -> EvidenceFile | None:
        return next(
            (
                item
                for item in self.items.values()
                if item.case_id == case_id and item.source_path == canonical_path
            ),
            None,
        )

    def list_for_case(self, case_id: str) -> list[EvidenceFile]:
        return [item for item in self.items.values() if item.case_id == case_id]


class StaticInspector:
    def __init__(self, kind: EvidenceKind = EvidenceKind.IBD) -> None:
        self.kind = kind

    def inspect(self, source_path: str) -> EvidenceMetadata:
        filename = source_path.rsplit("/", 1)[-1]
        return EvidenceMetadata(source_path, filename, 42, self.kind)


class MappingHasher:
    def __init__(self, values: dict[str, str]) -> None:
        self.values = values
        self.paths: list[str] = []

    def sha256(self, path: str) -> str:
        self.paths.append(path)
        return self.values[path]


class MemoryDomainRepository:
    def __init__(self, inputs: DomainInputs) -> None:
        self.inputs = inputs
        self.grouping = None
        self.correlation = None
        self.reconstruction = None
        self.reconciliation = None

    def inputs_for(self, case_id: str) -> DomainInputs:
        return self.inputs

    def save_grouping(self, case_id: str, result: object) -> None:
        self.grouping = result

    def load_grouping(self, case_id: str):
        return self.grouping

    def save_correlation(self, case_id: str, result: object) -> None:
        self.correlation = result

    def load_correlation(self, case_id: str):
        return self.correlation

    def save_reconstruction(self, case_id: str, result: object) -> None:
        self.reconstruction = result

    def load_reconstruction(self, case_id: str):
        return self.reconstruction

    def save_reconciliation(self, case_id: str, result: object) -> None:
        self.reconciliation = result

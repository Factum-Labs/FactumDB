from __future__ import annotations

import unittest

from core.application.errors import PrerequisiteError
from core.application.ports import DomainInputs
from core.application.use_cases.analysis import (
    CorrelateRecordsUseCase,
    GroupTransactionsUseCase,
    ReconcileRecordsUseCase,
    ReconstructStateUseCase,
)
from tests.application.fakes import MemoryDomainRepository
from tests.fixtures.datasets import ALL, DS02, Dataset
from tests.fixtures.inmemory import (
    InMemoryEventSource,
    InMemoryEvidenceContext,
    InMemoryPhysicalRecordSource,
    InMemorySchemaCatalog,
)


def repository(dataset: Dataset = DS02) -> MemoryDomainRepository:
    inputs = DomainInputs(
        InMemorySchemaCatalog(*dataset.schemas),
        InMemoryEventSource(dataset.events, dataset.markers),
        InMemoryPhysicalRecordSource(*dataset.physical),
        InMemoryEvidenceContext(
            inventory=dataset.inventory,
            integrity=dict(dataset.integrity),
            physical_tables=dataset.resolved_physical_tables,
        ),
    )
    return MemoryDomainRepository(inputs)


class DomainUseCaseTests(unittest.TestCase):
    def test_executes_and_persists_all_domain_stages(self) -> None:
        repo = repository()

        grouping = GroupTransactionsUseCase(repo).execute("case-1")
        correlation = CorrelateRecordsUseCase(repo).execute("case-1")
        reconstruction = ReconstructStateUseCase(repo).execute("case-1")
        reconciliation = ReconcileRecordsUseCase(repo).execute("case-1")

        self.assertIs(repo.grouping, grouping)
        self.assertIs(repo.correlation, correlation)
        self.assertIs(repo.reconstruction, reconstruction)
        self.assertIs(repo.reconciliation, reconciliation)
        self.assertGreater(len(grouping.transactions), 0)
        self.assertGreater(len(correlation.records), 0)
        self.assertGreater(len(reconstruction.histories), 0)
        self.assertGreater(len(reconciliation.rows), 0)

    def test_all_evaluation_datasets_cross_the_application_boundary(self) -> None:
        for dataset in ALL:
            with self.subTest(dataset=dataset.id):
                repo = repository(dataset)
                GroupTransactionsUseCase(repo).execute("case-1")
                CorrelateRecordsUseCase(repo).execute("case-1")
                ReconstructStateUseCase(repo).execute("case-1")
                result = ReconcileRecordsUseCase(repo).execute("case-1")
                self.assertIs(repo.reconciliation, result)

    def test_correlation_requires_grouping(self) -> None:
        with self.assertRaisesRegex(PrerequisiteError, "grouping"):
            CorrelateRecordsUseCase(repository()).execute("case-1")

    def test_reconstruction_requires_correlation(self) -> None:
        repo = repository()
        GroupTransactionsUseCase(repo).execute("case-1")
        with self.assertRaisesRegex(PrerequisiteError, "correlation"):
            ReconstructStateUseCase(repo).execute("case-1")

    def test_reconciliation_requires_reconstruction(self) -> None:
        repo = repository()
        GroupTransactionsUseCase(repo).execute("case-1")
        CorrelateRecordsUseCase(repo).execute("case-1")
        with self.assertRaisesRegex(PrerequisiteError, "reconstruction"):
            ReconcileRecordsUseCase(repo).execute("case-1")


if __name__ == "__main__":
    unittest.main()

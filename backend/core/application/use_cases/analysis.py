from __future__ import annotations

from core.application.errors import PrerequisiteError
from core.application.ports import DomainRepository
from core.domain.models.correlation import CorrelationResult
from core.domain.models.history import ReconstructionResult
from core.domain.models.reconciliation import ReconciliationResult
from core.domain.models.transactions import GroupingResult
from core.domain.services.record_correlation import RecordCorrelationService
from core.domain.services.record_reconciliation import ReconciliationService
from core.domain.services.state_reconstruction import StateReconstructionService
from core.domain.services.transaction_grouping import TransactionGroupingService


class GroupTransactionsUseCase:
    def __init__(self, repository: DomainRepository) -> None:
        self._repository = repository

    def execute(self, case_id: str) -> GroupingResult:
        inputs = self._repository.inputs_for(case_id)
        result = TransactionGroupingService(inputs.evidence).group(inputs.events)
        self._repository.save_grouping(case_id, result)
        return result


class CorrelateRecordsUseCase:
    def __init__(self, repository: DomainRepository) -> None:
        self._repository = repository

    def execute(self, case_id: str) -> CorrelationResult:
        grouping = self._repository.load_grouping(case_id)
        if grouping is None:
            raise PrerequisiteError("transaction grouping must complete before correlation")
        inputs = self._repository.inputs_for(case_id)
        result = RecordCorrelationService(
            inputs.schemas, inputs.physical, inputs.evidence
        ).correlate(grouping)
        self._repository.save_correlation(case_id, result)
        return result


class ReconstructStateUseCase:
    def __init__(self, repository: DomainRepository) -> None:
        self._repository = repository

    def execute(self, case_id: str) -> ReconstructionResult:
        grouping = self._repository.load_grouping(case_id)
        correlation = self._repository.load_correlation(case_id)
        if grouping is None:
            raise PrerequisiteError("transaction grouping must complete before reconstruction")
        if correlation is None:
            raise PrerequisiteError("record correlation must complete before reconstruction")
        inputs = self._repository.inputs_for(case_id)
        result = StateReconstructionService(
            inputs.schemas, inputs.physical, inputs.evidence
        ).reconstruct(grouping, correlation)
        self._repository.save_reconstruction(case_id, result)
        return result


class ReconcileRecordsUseCase:
    def __init__(self, repository: DomainRepository) -> None:
        self._repository = repository

    def execute(self, case_id: str) -> ReconciliationResult:
        grouping = self._repository.load_grouping(case_id)
        correlation = self._repository.load_correlation(case_id)
        reconstruction = self._repository.load_reconstruction(case_id)
        if grouping is None:
            raise PrerequisiteError("transaction grouping must complete before reconciliation")
        if correlation is None:
            raise PrerequisiteError("record correlation must complete before reconciliation")
        if reconstruction is None:
            raise PrerequisiteError("state reconstruction must complete before reconciliation")
        inputs = self._repository.inputs_for(case_id)
        result = ReconciliationService(
            inputs.schemas, inputs.physical, inputs.evidence
        ).reconcile(reconstruction, correlation, grouping.coverage)
        self._repository.save_reconciliation(case_id, result)
        return result

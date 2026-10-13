"""Application operations, imported only when their feature is requested."""

from importlib import import_module

_EXPORTS = {'CorrelateRecordsUseCase': 'core.application.use_cases.analysis',
 'GroupTransactionsUseCase': 'core.application.use_cases.analysis',
 'ReconcileRecordsUseCase': 'core.application.use_cases.analysis',
 'ReconstructStateUseCase': 'core.application.use_cases.analysis',
 'ToolRunAuditService': 'core.application.use_cases.audit',
 'CreateCaseUseCase': 'core.application.use_cases.cases',
 'RegisterEvidenceUseCase': 'core.application.use_cases.evidence',
 'VerifyEvidenceUseCase': 'core.application.use_cases.evidence',
 'DecodeBinaryLogsUseCase': 'core.application.use_cases.extraction',
 'ExtractPhysicalRowsUseCase': 'core.application.use_cases.extraction',
 'ExtractSchemaUseCase': 'core.application.use_cases.extraction',
 'NormalizeEvidenceUseCase': 'core.application.use_cases.extraction',
 'RunPageValidationUseCase': 'core.application.use_cases.extraction'}

__all__ = [
    "CorrelateRecordsUseCase",
    "CreateCaseUseCase",
    "DecodeBinaryLogsUseCase",
    "ExtractPhysicalRowsUseCase",
    "ExtractSchemaUseCase",
    "GroupTransactionsUseCase",
    "NormalizeEvidenceUseCase",
    "ReconcileRecordsUseCase",
    "ReconstructStateUseCase",
    "RegisterEvidenceUseCase",
    "RunPageValidationUseCase",
    "ToolRunAuditService",
    "VerifyEvidenceUseCase",
]


def __getattr__(name):
    module = _EXPORTS.get(name)
    if module is None:
        raise AttributeError(name)
    value = getattr(import_module(module), name)
    globals()[name] = value
    return value

# TODO(Chethana):
# Implement the SQLite case repository adapter that connects to
# `backend/core/application/ports/case_repository_port.py`.
#
# This adapter should implement `CaseRepositoryPort` and provide concrete
# SQLite-backed behavior for:
# - save(case: Case) -> None
# - find_by_id(case_id: str) -> Optional[Case]
#
# Keep SQLite-specific details in this adapter, and return/use the domain
# `Case` model so the application layer remains independent of persistence.
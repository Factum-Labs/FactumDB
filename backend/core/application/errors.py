"""Errors exposed by application use cases."""


class ApplicationError(Exception):
    """Base class for expected application-level failures."""


class NotFoundError(ApplicationError):
    pass


class ConflictError(ApplicationError):
    pass


class PrerequisiteError(ApplicationError):
    pass


class EvidenceIntegrityError(ApplicationError):
    pass

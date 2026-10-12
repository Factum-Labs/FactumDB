"""Bounded, controlled summaries: exception text is never a diagnostic record."""

from core.application.errors import (
    ApplicationError,
    ConflictError,
    NotFoundError,
    PrerequisiteError,
)


def safe_error(error: Exception) -> tuple[str, str]:
    # Only exact, application-authored messages may pass through the transport.
    # Never interpolate an exception, filename, payload, or tool output here.
    public_messages = {
        "Too many attempts. Try again in 30 seconds",
        "Incorrect username or password for this device account",
        "Incorrect password for this device account",
        "Sign in before using FactumDB",
        "Session locked. Enter your password to unlock.",
        "Passwords do not match",
        "Complete the analysis before exporting results.",
        "Refresh the export preview",
        "Case data changed; refresh the export preview",
        "Refresh the export preview before exporting",
        "Whole-workspace operations are unavailable in a shared workspace.",
    }
    summaries = (
        (NotFoundError, "The requested case or resource was not found."),
        (ConflictError, "This operation conflicts with the current case state."),
        (PrerequisiteError, "Complete the required preceding step before continuing."),
        (
            PermissionError,
            "Access or device verification was denied. Use the desktop app to verify your session.",
        ),
        (FileNotFoundError, "A required file or tool could not be found."),
        (FileExistsError, "The destination already exists. Choose a new file or folder."),
        (ValueError, "Invalid input. Check the supplied fields and settings."),
        (OSError, "A file or tool operation failed. Check access and tool settings."),
    )
    message = next(
        (text for kind, text in summaries if isinstance(error, kind)),
        "The operation failed. Check the selected evidence and tool settings.",
    )
    if (
        isinstance(error, (ApplicationError, PermissionError, ValueError))
        and str(error) in public_messages
    ):
        message = str(error)
    # Preserve familiar codes for known categories, without trusting custom class names.
    codes = {
        "NotFoundError",
        "ConflictError",
        "PrerequisiteError",
        "EvidenceIntegrityError",
        "AuthenticationError",
        "AuthenticationRequiredError",
        "InvalidPayloadError",
        "ApplicationNotConfiguredError",
        "RuntimeError",
        "ValueError",
        "TypeError",
        "OSError",
        "PermissionError",
        "FileNotFoundError",
        "FileExistsError",
        "TimeoutError",
        "JSONDecodeError",
    }
    name = type(error).__name__
    return (name if name in codes else "OPERATION_FAILED", message)

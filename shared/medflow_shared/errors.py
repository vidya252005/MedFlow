from __future__ import annotations


class MedFlowError(Exception):
    retryable = False
    code = "MEDFLOW_ERROR"

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        if code:
            self.code = code


class ValidationError(MedFlowError):
    retryable = False
    code = "INVALID_SCHEMA"


class DuplicateEventError(MedFlowError):
    retryable = False
    code = "DUPLICATE_EVENT"


class ModelTimeoutError(MedFlowError):
    retryable = True
    code = "MODEL_TIMEOUT"


class ModelUnavailableError(MedFlowError):
    retryable = True
    code = "MODEL_UNAVAILABLE"


class FeatureExtractionError(MedFlowError):
    retryable = False
    code = "FEATURE_EXTRACTION"


class PermanentProcessingError(MedFlowError):
    retryable = False
    code = "PERMANENT_FAILURE"


class TransientProcessingError(MedFlowError):
    retryable = True
    code = "TRANSIENT_FAILURE"


class ClockSkewError(ValidationError):
    code = "CLOCK_SKEW"


class UnsupportedEventError(ValidationError):
    code = "UNSUPPORTED_EVENT"

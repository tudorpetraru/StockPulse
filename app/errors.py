"""Common exception tuples used to avoid broad `except Exception` blocks."""

from __future__ import annotations

from sqlalchemy.exc import SQLAlchemyError

from app.services.providers.base import DataProviderError

ROUTE_RECOVERABLE_ERRORS = (
    DataProviderError,
    SQLAlchemyError,
    ValueError,
    TypeError,
    KeyError,
    RuntimeError,
    TimeoutError,
    ConnectionError,
    OSError,
)

SERVICE_RECOVERABLE_ERRORS = (
    DataProviderError,
    SQLAlchemyError,
    ValueError,
    TypeError,
    KeyError,
    RuntimeError,
    TimeoutError,
    ConnectionError,
    OSError,
)


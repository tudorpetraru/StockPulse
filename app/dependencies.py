from __future__ import annotations

from fastapi import Request

from app.services.cache_service import CacheService
from app.services.data_service import DataService
from app.services.prediction_service import PredictionService


def get_cache_service(request: Request) -> CacheService:
    return request.app.state.cache


def get_data_service(request: Request) -> DataService:
    return request.app.state.data_service


def get_prediction_service(request: Request) -> PredictionService:
    return request.app.state.prediction_service

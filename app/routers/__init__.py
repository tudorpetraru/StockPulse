from app.routers.dashboard import router as dashboard_router
from app.routers.news import router as news_router
from app.routers.portfolio import router as portfolio_router
from app.routers.predictions import router as predictions_router
from app.routers.screener import router as screener_router
from app.routers.ticker import router as ticker_router
from app.routers.watchlist import router as watchlist_router

__all__ = [
    "dashboard_router",
    "predictions_router",
    "screener_router",
    "ticker_router",
    "portfolio_router",
    "watchlist_router",
    "news_router",
]

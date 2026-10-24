"""Main router that includes all data hub sub-routers."""

from fastapi import APIRouter

from .alerts import router as alerts_router
from .bank_auctions import router as bank_auctions_router
from .calculations import router as calculations_router
from .circle_rates import router as circle_rates_router
from .developers import router as developers_router
from .market import router as market_router
from .neighbourhood import router as neighbourhood_router
from .projects import router as projects_router
from .registry import router as registry_router
from .rera import router as rera_router
from .scraper import router as scraper_router
from .watchlist import router as watchlist_router

router = APIRouter()

router.include_router(circle_rates_router)
router.include_router(rera_router)
router.include_router(projects_router)
router.include_router(developers_router)
router.include_router(market_router)
router.include_router(watchlist_router)
router.include_router(bank_auctions_router)
router.include_router(alerts_router)
router.include_router(calculations_router)
router.include_router(registry_router)
router.include_router(neighbourhood_router)
router.include_router(scraper_router)

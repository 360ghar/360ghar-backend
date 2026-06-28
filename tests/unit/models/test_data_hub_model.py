"""
Tests for app.models.data_hub module — BankAuction, CircleRate, RERA, etc.
"""


from app.models.data_hub import (
    AuctionAlert,
    BankAuction,
    BankRate,
    CircleRate,
    CourtAuction,
    GazetteNotification,
    JamabandiCache,
    NeighbourhoodScore,
    ReraComplaint,
    ReraProject,
    ScraperRun,
    ZoningData,
)


class TestBankAuctionModel:
    def test_tablename(self):
        assert BankAuction.__tablename__ == "bank_auctions"


class TestCircleRateModel:
    def test_tablename(self):
        assert CircleRate.__tablename__ == "circle_rates"


class TestCourtAuctionModel:
    def test_tablename(self):
        assert CourtAuction.__tablename__ == "court_auctions"


class TestGazetteModel:
    def test_tablename(self):
        assert GazetteNotification.__tablename__ == "gazette_notifications"


class TestJamabandiModel:
    def test_tablename(self):
        assert JamabandiCache.__tablename__ == "jamabandi_cache"


class TestRERAProjectModel:
    def test_tablename(self):
        assert ReraProject.__tablename__ == "rera_projects"


class TestRERAComplaintModel:
    def test_tablename(self):
        assert ReraComplaint.__tablename__ == "rera_complaints"


class TestZoningModel:
    def test_tablename(self):
        assert ZoningData.__tablename__ == "zoning_data"


class TestNeighbourhoodModel:
    def test_tablename(self):
        assert NeighbourhoodScore.__tablename__ == "neighbourhood_scores"


class TestBankRateModel:
    def test_tablename(self):
        assert BankRate.__tablename__ == "bank_rates"


class TestAuctionAlertModel:
    def test_tablename(self):
        assert AuctionAlert.__tablename__ == "auction_alerts"


class TestScraperRunModel:
    def test_tablename(self):
        assert ScraperRun.__tablename__ == "scraper_runs"

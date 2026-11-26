"""Initialize the dedicated Market Heatmap SQLite store."""
from database.market_heatmap_db import init_market_heatmap_db
from utils.logging import get_logger

logger = get_logger(__name__)


def initialize_market_heatmap(app=None):
    try:
        init_market_heatmap_db()
        logger.info("Market Heatmap SQLite database initialized")
    except Exception:
        logger.exception("Failed to initialize Market Heatmap SQLite database")
        raise

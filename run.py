import os
import logging
import warnings

import uvicorn

from dotenv import load_dotenv
load_dotenv()

# Suppress noisy third-party deprecation warnings (uvicorn/websockets)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    module=r"websockets\.legacy.*",
)
warnings.filterwarnings(
    "ignore",
    category=DeprecationWarning,
    message=r".*WebSocketServerProtocol is deprecated.*",
)

# Set up basic logging before uvicorn takes over
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

if __name__ == "__main__":
    port_str = os.getenv("PORT", "8000")

    logger.info(f"Starting Container - PORT: {port_str}")

    # Handle Railway's PORT environment variable properly
    try:
        port = int(port_str)
    except (ValueError, TypeError):
        logger.warning(f"Invalid PORT value '{port_str}', falling back to 8000")
        port = 8000

    environment = os.getenv("ENVIRONMENT", "development")
    reload = environment == "development"

    # Determine log level from DEBUG env var
    debug = os.getenv("DEBUG", "false").lower() in ("true", "1", "yes")
    log_level = "debug" if debug else "info"

    # Build uvicorn options with safe feature detection
    uvicorn_kwargs = {
        "host": "0.0.0.0",
        "port": port,
        "reload": reload,
        "log_level": log_level,
        "use_colors": True,
        # Keep workers=1 to avoid reload conflicts; uvicorn enforces it with reload anyway
        "workers": 1,
        # IMPORTANT: Don't let uvicorn override our logging config
        "log_config": None,
    }

    if reload:
        uvicorn_kwargs["reload_dirs"] = ["app"]

    # Prefer uvloop when available and not on Windows
    if os.name != "nt":
        try:
            import uvloop  # noqa: F401
            uvicorn_kwargs["loop"] = "uvloop"
        except Exception:
            logger.info("uvloop not available; using default asyncio loop")

    # Prefer httptools HTTP parser when available
    try:
        import httptools  # noqa: F401
        uvicorn_kwargs["http"] = "httptools"
    except Exception:
        logger.info("httptools not available; using default http implementation")

    # Import and setup logging BEFORE running uvicorn
    from app.core.logging import setup_logging
    setup_logging()

    logger.info(f"Starting uvicorn with log_level={log_level}, debug={debug}")

    # Configure uvicorn with better reload settings
    uvicorn.run("app.main:app", **uvicorn_kwargs)

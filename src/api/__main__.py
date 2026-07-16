"""Run the stats API: ``python -m src.api``."""

import uvicorn

from src.config import settings


def main() -> None:
    uvicorn.run(
        "src.api.app:app",
        host=settings.API_HOST,
        port=settings.API_PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()

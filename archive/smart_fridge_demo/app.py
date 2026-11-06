"""Compatibility entry point for existing ``uvicorn app:app`` scripts."""

from app.main import app


__all__ = ["app"]

"""Pydantic data models for CineplexBD Ticket Watcher."""

from __future__ import annotations
from pydantic import BaseModel


class APIEndpoint(BaseModel):
    """A discovered API endpoint (used by discovery module only)."""
    url: str
    method: str = "POST"
    headers: dict[str, str] = {}
    body: dict | list | None = None
    purpose: str = ""


class APIContract(BaseModel):
    """All discovered API endpoints (used by discovery module only)."""
    endpoints: dict[str, APIEndpoint] = {}
    discovered_at: str = ""

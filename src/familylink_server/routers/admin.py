"""Admin endpoints — protected, for operational management."""

from fastapi import APIRouter

router = APIRouter(prefix='/admin', tags=['admin'])

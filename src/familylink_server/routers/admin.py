"""Admin endpoints — protected, for operational management."""

import logging

from fastapi import APIRouter

logger = logging.getLogger(__name__)

router = APIRouter(prefix='/admin', tags=['admin'])

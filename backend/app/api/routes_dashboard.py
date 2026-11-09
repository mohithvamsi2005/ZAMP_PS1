"""Dashboard read-only APIs — Phase 7.
COUNTS ONLY FROM LIVE DATABASE RECORDS. Never canned, never cached here.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter
from pydantic import BaseModel

from app.services.run_store import get_dashboard_summary

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


class Totals(BaseModel):
    invoices: int
    runs: int
    completed_runs: int
    failed_runs: int
    pending_runs: int
    running_runs: int


class Decisions(BaseModel):
    APPROVE: int
    REVIEW: int
    REJECT: int


class ActivityDay(BaseModel):
    date: str
    submitted: int


class RecentRun(BaseModel):
    run_id: str
    invoice_id: Optional[int] = None
    invoice_number: Optional[str] = None
    vendor_name: Optional[str] = None
    po_reference: Optional[str] = None
    total_amount: Optional[str] = None
    currency: Optional[str] = None
    original_filename: Optional[str] = None
    status: Optional[str] = None
    decision: Optional[str] = None
    error_message: Optional[str] = None
    created_at: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    duration_seconds: Optional[float] = None


class DashboardSummary(BaseModel):
    totals: Totals
    decisions: Decisions
    decision_total: int
    approval_rate: Optional[float] = None
    review_queue: int
    avg_processing_seconds: Optional[float] = None
    activity_last_14_days: List[ActivityDay]
    recent_runs: List[RecentRun]
    latest_failed_runs: List[RecentRun]


@router.get("/summary", response_model=DashboardSummary,
            summary="Aggregated AP-pipeline metrics for the dashboard")
async def dashboard_summary():
    """Counts, decision distribution, 14-day ingest activity and recent runs.

    Every number is SQL-aggregated from the live database on each request;
    there is no cache and no fixture fallback — an empty database returns
    honest zeros.
    """
    return DashboardSummary(**get_dashboard_summary())

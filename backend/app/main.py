"""FastAPI application exposing the subscription detector over HTTP."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .detector import CsvFormatError, Subscription, Transaction, detect_subscriptions, parse_csv
from .pdf_parser import PdfParseError, PdfPasswordError, parse_pdf

MAX_UPLOAD_BYTES = 5 * 1024 * 1024
SAMPLE_CSV = Path(__file__).resolve().parent.parent / "sample_data" / "sample_transactions.csv"

app = FastAPI(title="Subscription Detector API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


class SubscriptionOut(BaseModel):
    merchant: str
    display_name: str
    cadence: str
    average_amount: float
    last_amount: float
    monthly_cost: float
    annual_cost: float
    occurrences: int
    first_charge: date
    last_charge: date
    next_expected: date
    confidence: float
    price_changed: bool
    likely_cancelled: bool


class Summary(BaseModel):
    transactions_analyzed: int
    subscriptions_found: int
    active_monthly_total: float
    active_annual_total: float


class AnalysisResponse(BaseModel):
    summary: Summary
    subscriptions: list[SubscriptionOut]


def _parse_csv_text(content: str) -> list[Transaction]:
    try:
        return parse_csv(content)
    except CsvFormatError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


def _analyze(transactions: list[Transaction]) -> AnalysisResponse:
    subs: list[Subscription] = detect_subscriptions(transactions)
    active = [s for s in subs if not s.likely_cancelled]
    monthly_total = round(sum(s.monthly_cost for s in active), 2)
    return AnalysisResponse(
        summary=Summary(
            transactions_analyzed=len(transactions),
            subscriptions_found=len(subs),
            active_monthly_total=monthly_total,
            active_annual_total=round(monthly_total * 12, 2),
        ),
        subscriptions=[SubscriptionOut(**s.__dict__) for s in subs],
    )


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/analyze", response_model=AnalysisResponse)
async def analyze(file: UploadFile = File(...), password: str | None = Form(None)) -> AnalysisResponse:
    """Analyze a bank statement: CSV, or PDF (optionally password-protected)."""
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="File too large (max 5 MB)")

    if raw.startswith(b"%PDF"):
        try:
            return _analyze(parse_pdf(raw, password))
        except PdfPasswordError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except PdfParseError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise HTTPException(status_code=422, detail="Upload a CSV (UTF-8) or PDF bank statement") from exc
    return _analyze(_parse_csv_text(content))


@app.get("/api/sample", response_model=AnalysisResponse)
def analyze_sample() -> AnalysisResponse:
    return _analyze(_parse_csv_text(SAMPLE_CSV.read_text(encoding="utf-8")))

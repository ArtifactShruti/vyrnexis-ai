"""Currency-aware reports over the tenant's recorded payments and refunds."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
import csv
from io import StringIO
import json

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select

from .database import get_db
from .models import CommerceFinding, CommerceRecord


ROLES = ("owner", "organization_admin", "business_analyst", "security_analyst")


def period(start, end):
    last = end or datetime.now(timezone.utc).date()
    first = start or last - timedelta(days=29)
    if first < date(1971, 1, 1) or last > date(9998, 12, 31) or last < first or (last - first).days > 365:
        raise HTTPException(422, "Select a UTC date range of up to 366 days")
    return first, last


def time_filter(column, start, end):
    return (column >= datetime.combine(start, time.min),
            column < datetime.combine(end + timedelta(days=1), time.min))


def rollup(db, org, start, end, currency):
    day = func.date(CommerceRecord.occurred_at)
    filters = [CommerceRecord.organization_id == org, *time_filter(CommerceRecord.occurred_at, start, end)]
    if currency:
        filters.append(CommerceRecord.currency == currency)
    groups = db.execute(select(day, CommerceRecord.currency, CommerceRecord.kind, func.count(),
                               func.sum(CommerceRecord.amount_minor)).where(*filters)
                        .group_by(day, CommerceRecord.currency, CommerceRecord.kind)).all()
    totals, buckets = {}, {}
    for recorded_day, code, kind, count, amount in groups:
        bucket = buckets.setdefault((str(recorded_day), code), {"date": str(recorded_day), "currency": code,
                                                                "payments": 0, "refunds": 0, "paid_minor": 0, "refunded_minor": 0})
        total = totals.setdefault(code, {"currency": code, "payments": 0, "refunds": 0, "paid_minor": 0, "refunded_minor": 0})
        count_key, amount_key = ("payments", "paid_minor") if kind == "payment" else ("refunds", "refunded_minor")
        for entry in (bucket, total):
            entry[count_key] += count
            entry[amount_key] += amount
    return totals, buckets, filters


def decimals(numerator, denominator):
    if not denominator:
        return None
    return str((Decimal(numerator) / Decimal(denominator)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def money_strings(item):
    return {key: str(value) if key.endswith("_minor") else value for key, value in item.items()}


def summarize(db, org, start, end, currency=None):
    current, daily, filters = rollup(db, org, start, end, currency)
    length = (end - start).days + 1
    prev_start, prev_end = start - timedelta(days=length), start - timedelta(days=1)
    previous, _, _ = rollup(db, org, prev_start, prev_end, currency)
    accounts = (select(CommerceRecord.currency.label("currency"), CommerceRecord.account.label("account"),
                       func.count().label("activity")).where(*filters, CommerceRecord.account != "")
                .group_by(CommerceRecord.currency, CommerceRecord.account).subquery())
    from sqlalchemy import case

    segment = case((accounts.c.activity == 1, "one_record"), (accounts.c.activity <= 4, "two_to_four"), else_="five_or_more")
    segments = db.execute(select(accounts.c.currency, segment, func.count()).group_by(accounts.c.currency, segment)).all()
    finding_rows = db.execute(select(CommerceRecord.currency, CommerceFinding.status, func.count()).join(
        CommerceFinding, (CommerceFinding.refund_id == CommerceRecord.id)
        & (CommerceFinding.organization_id == CommerceRecord.organization_id),
    ).where(*filters).group_by(CommerceRecord.currency, CommerceFinding.status)).all()
    summary = []
    for code in sorted(current.keys() | previous.keys()):
        zero = {"currency": code, "payments": 0, "refunds": 0, "paid_minor": 0, "refunded_minor": 0}
        item = current.get(code, zero)
        prior = previous.get(code, zero)
        summary.append(money_strings(item) | {
            "net_recorded_minor": str(item["paid_minor"] - item["refunded_minor"]),
            "average_payment_minor": decimals(item["paid_minor"], item["payments"]),
            "refund_count_per_100_payments": decimals(item["refunds"] * 100, item["payments"]),
            "refund_amount_per_100_paid": decimals(item["refunded_minor"] * 100, item["paid_minor"]),
            "previous": money_strings(prior),
        })
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat()},
        "comparison": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        "currency": currency, "summary": summary, "days": [money_strings(item) for _, item in sorted(daily.items())],
        "segments": [{"currency": code, "segment": label, "reported_accounts": count} for code, label, count in sorted(segments)],
        "finding_statuses": [{"currency": code, "status": status, "count": count} for code, status, count in sorted(finding_rows)],
        "limitations": [
            "Totals use recorded payment and refund observations in UTC and preserve their original currencies.",
            "Refund ratios compare records in the period. They do not match refunds to original payments.",
            "Customer activity uses reported account labels. Payment lifecycle, profitability, acquisition, and forecasts require additional data.",
        ],
    }


def build_business_router(require_roles, audit):
    router = APIRouter(prefix="/api/v1/business-intelligence")
    analyst = Depends(require_roles(*ROLES))

    @router.get("/report")
    def report(start: date | None = None, end: date | None = None,
               currency: str | None = Query(None, pattern=r"^[A-Z]{3}$"), db=Depends(get_db), user=analyst):
        first, last = period(start, end)
        return summarize(db, user.organization_id, first, last, currency)

    @router.get("/export")
    def export(start: date | None = None, end: date | None = None, format: str = Query("json", pattern="^(json|csv)$"),
               currency: str | None = Query(None, pattern=r"^[A-Z]{3}$"), db=Depends(get_db), user=analyst):
        first, last = period(start, end)
        snapshot = summarize(db, user.organization_id, first, last, currency)
        audit(db, user.organization_id, user.id, "business.report_exported", "business_intelligence",
              {"format": format, "start": first.isoformat(), "end": last.isoformat(), "currency": currency})
        db.commit()
        if format == "csv":
            output = StringIO()
            writer = csv.DictWriter(output, ("date", "currency", "payments", "refunds", "paid_minor", "refunded_minor"))
            writer.writeheader()
            for row in snapshot["days"]:
                currency_value = row["currency"]
                if not currency_value.isascii() or not currency_value.isalpha() or len(currency_value) != 3:
                    row = row | {"currency": "Unknown"}
                writer.writerow(row)
            body, mime = output.getvalue(), "text/csv"
        else:
            body, mime = json.dumps(snapshot, ensure_ascii=False), "application/json"
        return Response(body, media_type=mime, headers={
            "Content-Disposition": f"attachment; filename=business-{first.isoformat()}-{last.isoformat()}.{format}",
            "Cache-Control": "private, no-store",
        })

    return router

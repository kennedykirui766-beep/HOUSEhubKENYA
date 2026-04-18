import csv
import io
import os
import threading
import time
from datetime import datetime, timezone

from extensions import db
from models.models import House, MaintenanceRequest, Payment, SupportTicket, SystemSetting, User


SUPPORTED_DATASETS = ("summary", "finance", "occupancy", "maintenance")
_worker_started = False


def _parse_datasets(raw_value):
    datasets = []
    for item in (raw_value or "").split(","):
        clean = item.strip().lower()
        if clean in SUPPORTED_DATASETS and clean not in datasets:
            datasets.append(clean)
    return datasets


def _read_bool(key, default=False):
    fallback = "1" if default else "0"
    return SystemSetting.get(key, fallback) == "1"


def _read_int(key, default_value):
    raw = SystemSetting.get(key, str(default_value))
    try:
        return int(raw)
    except Exception:
        return default_value


def _read_format(key, default_value="csv"):
    raw = (SystemSetting.get(key, default_value) or "").strip().lower()
    if raw in ("csv", "xlsx", "both"):
        return raw
    return default_value


def _utc_now():
    return datetime.now(timezone.utc)


def _read_last_run():
    raw = (SystemSetting.get("report_schedule_last_run_at", "") or "").strip()
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except Exception:
        return None


def _is_due(now_utc, interval_minutes):
    last_run = _read_last_run()
    if last_run is None:
        return True
    elapsed = now_utc - last_run
    return elapsed.total_seconds() >= interval_minutes * 60


def _summary_rows():
    total_users = User.query.count()
    total_properties = House.query.count()
    total_transactions = Payment.query.count()
    occupied_properties = House.query.filter(House.available == False).count()
    vacant_properties = House.query.filter(House.available == True).count()
    occupancy_rate = round((occupied_properties / total_properties) * 100, 2) if total_properties else 0.0

    payments_paid = Payment.query.filter(
        (Payment.status.ilike("%paid%")) |
        (Payment.status.ilike("%success%")) |
        (Payment.status.ilike("%complete%"))
    ).all()
    paid_amount_total = round(sum(float(p.amount or 0) for p in payments_paid), 2)
    payments_pending_count = Payment.query.filter(Payment.status.ilike("%pending%")).count()
    payment_failures = Payment.query.filter(
        (Payment.status.ilike("%fail%")) | (Payment.status.ilike("%error%"))
    ).count()

    maintenance_total = MaintenanceRequest.query.count()
    maintenance_open = MaintenanceRequest.query.filter(MaintenanceRequest.status != "resolved").count()
    maintenance_resolved = MaintenanceRequest.query.filter(MaintenanceRequest.status == "resolved").count()

    support_total = SupportTicket.query.count()
    support_open = SupportTicket.query.filter(SupportTicket.status != "resolved").count()

    role_counts = {}
    for role_name in ("tenant", "landlord", "service", "admin"):
        role_counts[role_name] = User.query.filter(User.role == role_name).count()

    rows = [
        ["total_users", total_users],
        ["total_properties", total_properties],
        ["total_transactions", total_transactions],
        ["occupied_properties", occupied_properties],
        ["vacant_properties", vacant_properties],
        ["occupancy_rate", occupancy_rate],
        ["paid_amount_total", paid_amount_total],
        ["payments_pending_count", payments_pending_count],
        ["payment_failures", payment_failures],
        ["maintenance_total", maintenance_total],
        ["maintenance_open", maintenance_open],
        ["maintenance_resolved", maintenance_resolved],
        ["support_total", support_total],
        ["support_open", support_open],
        ["role_tenant", role_counts.get("tenant", 0)],
        ["role_landlord", role_counts.get("landlord", 0)],
        ["role_service", role_counts.get("service", 0)],
        ["role_admin", role_counts.get("admin", 0)],
    ]
    return ["metric", "value"], rows


def _finance_rows():
    payments = Payment.query.order_by(Payment.date.desc()).all()
    rows = []
    for p in payments:
        tenant_email = p.tenant.email if getattr(p, "tenant", None) else ""
        rows.append([
            p.id,
            p.tenant_id,
            tenant_email,
            p.house_id,
            float(p.amount or 0),
            p.payment_month or "",
            p.date.isoformat() if p.date else "",
            p.due_date.isoformat() if p.due_date else "",
            p.status or "",
            p.transaction_id or "",
        ])
    return ["id", "tenant_id", "tenant_email", "house_id", "amount", "payment_month", "date", "due_date", "status", "transaction_id"], rows


def _occupancy_rows():
    houses = House.query.order_by(House.id.desc()).all()
    rows = []
    for h in houses:
        rows.append([
            h.id,
            h.title or "",
            h.category or "",
            h.location or "",
            bool(h.available),
            h.owner_id,
            float(h.rent_amount or 0),
            h.bedrooms or 0,
            h.bathrooms or 0,
        ])
    return ["id", "title", "category", "location", "available", "owner_id", "rent_amount", "bedrooms", "bathrooms"], rows


def _maintenance_rows():
    requests = MaintenanceRequest.query.order_by(MaintenanceRequest.created_at.desc()).all()
    rows = []
    for r in requests:
        tenant_email = r.tenant.email if getattr(r, "tenant", None) else ""
        rows.append([
            r.id,
            r.tenant_id,
            tenant_email,
            r.house_id,
            r.issue or "",
            r.status or "",
            r.created_at.isoformat() if r.created_at else "",
            r.sla_due.isoformat() if r.sla_due else "",
        ])
    return ["id", "tenant_id", "tenant_email", "house_id", "issue", "status", "created_at", "sla_due"], rows


def _dataset_rows(dataset):
    if dataset == "summary":
        headers, rows = _summary_rows()
    elif dataset == "finance":
        headers, rows = _finance_rows()
    elif dataset == "occupancy":
        headers, rows = _occupancy_rows()
    elif dataset == "maintenance":
        headers, rows = _maintenance_rows()
    else:
        raise ValueError(f"Unsupported dataset: {dataset}")

    return headers, rows


def _dataset_to_csv(dataset):
    headers, rows = _dataset_rows(dataset)

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(headers)
    for row in rows:
        writer.writerow(row)
    return buf.getvalue(), len(rows)


def _dataset_to_xlsx_bytes(dataset):
    headers, rows = _dataset_rows(dataset)

    from openpyxl import Workbook

    wb = Workbook()
    ws = wb.active
    ws.title = dataset.capitalize()
    ws.append(headers)
    for row in rows:
        ws.append(row)

    xbuf = io.BytesIO()
    wb.save(xbuf)
    return xbuf.getvalue(), len(rows)


def run_scheduled_report_job(force=False):
    enabled = _read_bool("report_schedule_enabled", False)
    if not enabled and not force:
        return {"ran": False, "reason": "disabled", "files": []}

    interval_minutes = max(15, _read_int("report_schedule_interval_minutes", 1440))
    datasets = _parse_datasets(SystemSetting.get("report_schedule_datasets", "summary,finance,occupancy,maintenance"))
    output_format = _read_format("report_schedule_format", "csv")
    if not datasets:
        datasets = ["summary"]

    now_utc = _utc_now()
    if not force and not _is_due(now_utc, interval_minutes):
        return {"ran": False, "reason": "not_due", "files": []}

    reports_dir = os.path.join(os.getcwd(), "instance", "reports")
    os.makedirs(reports_dir, exist_ok=True)

    created_files = []
    counts = {}
    format_used = output_format
    ts = now_utc.strftime("%Y%m%d_%H%M%S")

    requested_formats = ["csv"]
    if output_format == "xlsx":
        requested_formats = ["xlsx"]
    elif output_format == "both":
        requested_formats = ["csv", "xlsx"]

    for dataset in datasets:
        row_count = 0
        for one_format in requested_formats:
            if one_format == "csv":
                csv_body, row_count = _dataset_to_csv(dataset)
                file_name = f"report_{dataset}_{ts}.csv"
                file_path = os.path.join(reports_dir, file_name)
                with open(file_path, "w", encoding="utf-8", newline="") as f:
                    f.write(csv_body)
                created_files.append(file_path)
            elif one_format == "xlsx":
                try:
                    xlsx_payload, row_count = _dataset_to_xlsx_bytes(dataset)
                    file_name = f"report_{dataset}_{ts}.xlsx"
                    file_path = os.path.join(reports_dir, file_name)
                    with open(file_path, "wb") as f:
                        f.write(xlsx_payload)
                    created_files.append(file_path)
                except Exception:
                    # Keep scheduler resilient: fall back to CSV if XLSX generation is unavailable.
                    format_used = "csv"
                    csv_body, row_count = _dataset_to_csv(dataset)
                    file_name = f"report_{dataset}_{ts}.csv"
                    file_path = os.path.join(reports_dir, file_name)
                    with open(file_path, "w", encoding="utf-8", newline="") as f:
                        f.write(csv_body)
                    created_files.append(file_path)

        counts[dataset] = row_count

    SystemSetting.set("report_schedule_last_run_at", now_utc.isoformat())
    SystemSetting.set("report_schedule_last_result", str({"format": format_used, "counts": counts, "files": len(created_files)}))

    return {
        "ran": True,
        "reason": "ok",
        "files": created_files,
        "counts": counts,
        "datasets": datasets,
        "format": format_used,
    }


def _worker_loop(app):
    with app.app_context():
        while True:
            try:
                run_scheduled_report_job(force=False)
            except Exception:
                app.logger.exception("Scheduled report job failed")
            time.sleep(60)


def start_scheduler(app):
    global _worker_started
    if _worker_started:
        return

    t = threading.Thread(target=_worker_loop, args=(app,), daemon=True)
    t.start()
    _worker_started = True
    app.logger.info("Report scheduler started")

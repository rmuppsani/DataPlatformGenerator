from __future__ import annotations

import csv
import io
import json
import os
import re
import shutil
import zipfile
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "target"
DASHBOARD = Path(__file__).resolve().parent
BRONZE = TARGET / "Bronze"
SILVER = TARGET / "Silver"
GOLD = TARGET / "Gold"
EVENTS: list[dict[str, Any]] = []


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def event(message: str, status: str = "completed", detail: str = "") -> None:
    EVENTS.insert(0, {"time": now(), "message": message, "status": status, "detail": detail})
    del EVENTS[12:]


def as_number(value: Any, default: float | None = None) -> float | None:
    if value is None or str(value).strip() == "":
        return default
    try:
        return float(str(value).replace(",", "").strip())
    except ValueError:
        return default


def parse_csv(data: bytes) -> list[dict[str, Any]]:
    text = data.decode("utf-8-sig")
    return [dict(row) for row in csv.DictReader(io.StringIO(text))]


def xlsx_value(cell: ET.Element, shared: list[str]) -> str:
    value = cell.find("{*}v")
    if value is None:
        inline = cell.find("{*}is/{*}t")
        return inline.text or "" if inline is not None else ""
    raw = value.text or ""
    return shared[int(raw)] if cell.attrib.get("t") == "s" else raw


def parse_xlsx(data: bytes) -> list[dict[str, Any]]:
    with zipfile.ZipFile(io.BytesIO(data)) as workbook:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in workbook.namelist():
            root = ET.fromstring(workbook.read("xl/sharedStrings.xml"))
            shared = ["".join(node.itertext()) for node in root.findall("{*}si")]
        sheet_name = "xl/worksheets/sheet1.xml"
        root = ET.fromstring(workbook.read(sheet_name))
        rows: list[list[str]] = []
        for row in root.findall("{*}sheetData/{*}row"):
            cells: dict[int, str] = {}
            for cell in row.findall("{*}c"):
                ref = cell.attrib.get("r", "A1")
                match = re.match(r"([A-Z]+)", ref)
                if not match:
                    continue
                index = 0
                for char in match.group(1):
                    index = index * 26 + ord(char) - 64
                cells[index - 1] = xlsx_value(cell, shared)
            rows.append([cells.get(i, "") for i in range(max(cells.keys(), default=-1) + 1)])
        if not rows:
            return []
        headers = rows[0]
        return [dict(zip(headers, row + [""] * (len(headers) - len(row)))) for row in rows[1:]]


def read_source(filename: str, data: bytes) -> list[dict[str, Any]]:
    suffix = Path(filename).suffix.lower()
    if suffix in {".xlsx", ".xlsm"}:
        return parse_xlsx(data)
    if suffix == ".json":
        loaded = json.loads(data.decode("utf-8"))
        return loaded if isinstance(loaded, list) else loaded.get("rows", [])
    return parse_csv(data)


def csv_bytes(rows: list[dict[str, Any]], columns: list[str]) -> bytes:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue().encode("utf-8")


def run_pipeline(filename: str, data: bytes) -> dict[str, Any]:
    BRONZE.mkdir(parents=True, exist_ok=True)
    SILVER.mkdir(parents=True, exist_ok=True)
    GOLD.mkdir(parents=True, exist_ok=True)
    event("Pipeline run started", "running", filename)
    source_rows = read_source(filename, data)
    bronze_name = Path(filename).name
    (BRONZE / bronze_name).write_bytes(data)
    event("Bronze layer loaded", "completed", f"{len(source_rows)} source records")

    seen: set[str] = set()
    cleaned: list[dict[str, Any]] = []
    duplicate_count = 0
    invalid_count = 0
    for row in source_rows:
        record = dict(row)
        order_id = str(record.get("Order_ID", "")).strip()
        if order_id and order_id in seen:
            duplicate_count += 1
            continue
        if order_id:
            seen.add(order_id)
        quantity = as_number(record.get("Quantity"))
        if quantity is None or quantity <= 0:
            invalid_count += 1
            continue
        unit_price = as_number(record.get("Unit_Price"), 0) or 0
        record["Order_ID"] = order_id
        record["Quantity"] = int(quantity) if quantity.is_integer() else quantity
        record["Unit_Price"] = unit_price
        record["Total_Sales"] = round(quantity * unit_price, 2)
        cleaned.append(record)

    columns = list(source_rows[0].keys()) if source_rows else []
    if "Total_Sales" not in columns:
        columns.append("Total_Sales")
    (SILVER / "cleaned_data.csv").write_bytes(csv_bytes(cleaned, columns))
    event("Silver layer validated", "completed", f"{len(cleaned)} records; {duplicate_count} duplicates and {invalid_count} invalid rows removed")

    grouped: dict[str, dict[str, Any]] = {}
    for row in cleaned:
        product = str(row.get("Product_Name", "")).strip()
        item = grouped.setdefault(product, {"Product_Name": product, "Total_Quantity": 0, "Total_Sales": 0})
        item["Total_Quantity"] += row["Quantity"]
        item["Total_Sales"] = round(item["Total_Sales"] + row["Total_Sales"], 2)
    summary = sorted(grouped.values(), key=lambda item: item["Total_Sales"], reverse=True)
    (GOLD / "product_sales_summary.csv").write_bytes(csv_bytes(summary, ["Product_Name", "Total_Quantity", "Total_Sales"]))
    event("Gold layer aggregated", "completed", f"{len(summary)} products summarized")
    event("Pipeline run completed", "completed", "All three layers are ready")
    return {"source_rows": len(source_rows), "silver_rows": len(cleaned), "duplicate_count": duplicate_count, "invalid_count": invalid_count, "products": len(summary)}


def read_csv_file(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def status_payload() -> dict[str, Any]:
    silver = read_csv_file(SILVER / "cleaned_data.csv")
    summary = read_csv_file(GOLD / "product_sales_summary.csv")
    total_sales = round(sum(as_number(row.get("Total_Sales"), 0) or 0 for row in silver), 2)
    bronze_files = [path for path in BRONZE.iterdir() if path.is_file()] if BRONZE.exists() else []
    current_bronze = max(bronze_files, key=lambda path: path.stat().st_mtime) if bronze_files else None
    bronze_rows = 0
    if current_bronze:
        try:
            bronze_rows = len(read_source(current_bronze.name, current_bronze.read_bytes()))
        except (OSError, ValueError, KeyError, zipfile.BadZipFile):
            bronze_rows = 0
    return {"layers": {"bronze": {"status": "ready" if current_bronze else "pending", "files": 1 if current_bronze else 0, "records": bronze_rows}, "silver": {"status": "ready" if silver else "pending", "files": 1 if silver else 0, "records": len(silver)}, "gold": {"status": "ready" if summary else "pending", "files": 1 if summary else 0, "records": len(summary)}}, "metrics": {"total_sales": total_sales, "clean_records": len(silver), "products": len(summary)}, "summary": summary, "preview": silver[:8], "events": EVENTS[:12]}


class DashboardHandler(BaseHTTPRequestHandler):
    def send_json(self, payload: dict[str, Any], code: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/status":
            self.send_json(status_payload())
            return
        if parsed.path == "/":
            path = DASHBOARD / "index.html"
        else:
            path = DASHBOARD / parsed.path.lstrip("/")
        if not path.is_file() or DASHBOARD not in path.resolve().parents:
            self.send_error(404)
            return
        content = path.read_bytes()
        content_type = "text/html; charset=utf-8" if path.suffix == ".html" else "text/css; charset=utf-8" if path.suffix == ".css" else "application/javascript; charset=utf-8"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def do_POST(self) -> None:
        if urlparse(self.path).path != "/api/run":
            self.send_error(404)
            return
        if self.command != "POST":
            self.send_error(405)
            return
        content_type = self.headers.get("Content-Type") or ""
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        print(f"POST received: {content_type} {length}", flush=True)
        filename, data = "", b""
        if content_type.startswith("multipart/form-data"):
            from email import policy
            from email.parser import BytesParser
            message = BytesParser(policy=policy.default).parsebytes(
                f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
            )
            for part in message.iter_attachments():
                if part.get_param("name", header="content-disposition") == "source":
                    filename = part.get_filename() or ""
                    data = part.get_payload(decode=True) or b""
                    break
        if not filename:
            source = next(BRONZE.glob("*.xlsx"), None)
            if source is None:
                self.send_json({"error": "Upload an .xlsx or .csv source file first."}, 400)
                return
            filename, data = source.name, source.read_bytes()
        try:
            result = run_pipeline(filename, data)
            self.send_json({"result": result, **status_payload()})
        except Exception as exc:
            event("Pipeline run failed", "failed", str(exc))
            self.send_json({"error": str(exc)}, 500)

    def log_message(self, *_: Any) -> None:
        return


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8001"))
    print(f"Dashboard running at http://localhost:{port}")
    ThreadingHTTPServer(("localhost", port), DashboardHandler).serve_forever()

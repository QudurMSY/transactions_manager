"""Big Ambitions transactions.csv izleme + Google Drive senkronizasyon scripti.

Yeni davranış:
- Drive üzerinde `big ambitions` adlı kök klasörü garanti edilir.
- Gün değerine göre 60 günlük dönem klasörleri (1-60, 61-120, ...) oluşturulur.
- transactions.csv değiştiğinde ilgili dönem klasörüne transactionsgun_<gun>.csv yüklenir.
- Her dönem klasöründe `main` adlı Google Sheet üretilir (görünür grafiklerle).
- Kök klasörde `main_total` adlı Google Sheet üretilir (görünür grafiklerle).
Bu script şunları yapar:
1) Big Ambitions süreci açık mı kontrol eder.
2) SaveGames altında en güncel sürüm + en güncel save klasörünü dinamik bulur.
3) transactions.csv değişince dosya yazımı bitsin diye kısa bekler.
4) CSV'den ilk veri satırının B sütunundaki (index=1) gün bilgisini okur.
5) Dosyayı transactionsgun_<gun>.csv adıyla Google Drive'a create/update eder.

Kimlik doğrulama:
- Yalnızca OAuth client JSON (`oauth_client_credentials.json` / `credentials.json`)
  desteklenir; kişisel Google hesabı (My Drive) ile çalışır.

Opsiyonel environment variable'lar:
- GOOGLE_CREDENTIALS_FILE
- GDRIVE_FOLDER_ID
- GOOGLE_TOKEN_FILE
- GAME_PROCESS_NAMES (varsayılan: Big Ambitions.exe,Big_Ambitions.exe,BigAmbitions.exe,UnityPlayer.exe)
"""

from __future__ import annotations

import argparse
import csv
import errno
import json
import os
import queue
import threading
import time
import tkinter as tk
import zipfile
from collections import defaultdict
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable, Optional
from tkinter import filedialog, messagebox
from xml.sax.saxutils import escape

import psutil
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.errors import HttpError
from googleapiclient.discovery import build
from googleapiclient.http import MediaInMemoryUpload
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

# NOTE:
# Bu uygulama hedef klasörü doğruladığı ve create/update yaptığı için
# tam Drive scope'u (`drive`) kullanır.
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
]


@dataclass
class Config:
    savegames_root: Path
    credentials_file: Path
    drive_folder_id: Optional[str]
    process_names: tuple[str, ...]
    poll_seconds: int = 15
    file_settle_seconds: int = 10


def normalize_drive_folder_id(raw_value: Optional[str]) -> Optional[str]:
    """Drive folder ID değerini normalize eder.

    - Boş/None -> None
    - URL verildiyse klasör ID'sini ayıklar
    - `.` gibi geçersiz placeholder değerleri temizler
    """
    if raw_value is None:
        return None

    value = raw_value.strip().strip('"').strip("'")
    if not value or value in {".", "./", "root"}:
        return None

    # Sık yapılan hatalar: placeholder/metin değeri doğrudan yapıştırılıyor.
    lowered = value.lower()
    if lowered in {"gdrive_folder_id", "drive_folder_id", "folder_id"}:
        return None
    if " " in value and "folder" in lowered and "id" in lowered:
        return None

    if "drive.google.com" in value and "/folders/" in value:
        value = value.split("/folders/", 1)[1].split("?", 1)[0].split("/", 1)[0].strip()

    return value or None


class DriveUploader:
    """OAuth (kişisel Google hesabı) ile Drive create/update."""

    def __init__(self, credentials_file: Path, folder_id: Optional[str] = None) -> None:
        self.folder_id = folder_id
        self.credentials_file = credentials_file
        credentials = self._load_credentials(credentials_file)
        self.service = build("drive", "v3", credentials=credentials, cache_discovery=False)
        self.sheets_service = build("sheets", "v4", credentials=credentials, cache_discovery=False)

    @staticmethod
    def _read_json(path: Path) -> dict:
        with path.open("r", encoding="utf-8") as f:
            return json.load(f)

    def _load_credentials(self, credentials_file: Path) -> Credentials:
        payload = self._read_json(credentials_file)

        oauth_config = payload.get("installed") or payload.get("web")
        if not oauth_config:
            raise RuntimeError(
                "Desteklenmeyen credentials dosyası. Yalnızca OAuth client JSON kullanın."
            )

        token_file = Path(os.getenv("GOOGLE_TOKEN_FILE", str(credentials_file.with_name("token.json"))))
        creds: Optional[Credentials] = None
        if token_file.exists():
            creds = Credentials.from_authorized_user_file(str(token_file), SCOPES)

        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                creds.refresh(Request())
            else:
                flow = InstalledAppFlow.from_client_secrets_file(str(credentials_file), SCOPES)
                creds = flow.run_local_server(port=0)
            token_file.write_text(creds.to_json(), encoding="utf-8")

        return creds

    def describe_target_folder(self) -> str:
        if not self.folder_id:
            return "Drive hedef klasör ID verilmedi (GDRIVE_FOLDER_ID boş)."

        try:
            meta = (
                self.service.files()
                .get(
                    fileId=self.folder_id,
                    fields="id,name,driveId,capabilities(canAddChildren)",
                    supportsAllDrives=True,
                )
                .execute()
            )
        except HttpError as exc:
            raise RuntimeError(explain_http_error(exc, self.folder_id)) from exc

        folder_name = meta.get("name", "(isimsiz)")
        drive_id = meta.get("driveId")
        can_add_children = meta.get("capabilities", {}).get("canAddChildren")
        if can_add_children is False:
            raise RuntimeError(
                "Drive klasörüne yazma yetkisi yok. Hesaba en az Editor yetkisi verin."
            )

        if not drive_id:
            return f"Doğrulandı: '{folder_name}' (My Drive klasörü)"

        return f"Doğrulandı: '{folder_name}' (driveId={drive_id})"

    @property
    def _list_kwargs(self) -> dict[str, object]:
        kwargs: dict[str, object] = {
            "spaces": "drive",
            "fields": "files(id, name)",
            "pageSize": 1,
            "supportsAllDrives": True,
            "includeItemsFromAllDrives": True,
        }
        if self.folder_id:
            kwargs["corpora"] = "allDrives"
        return kwargs

    def _find_existing_file_id(self, file_name: str) -> Optional[str]:
        return self._find_existing_file_id_in_parent(file_name, self.folder_id)

    def _find_existing_file_id_in_parent(self, file_name: str, parent_id: Optional[str]) -> Optional[str]:
        safe_name = file_name.replace("'", "\\'")
        query_parts = [f"name = '{safe_name}'", "trashed = false"]
        if parent_id:
            query_parts.append(f"'{parent_id}' in parents")
        query = " and ".join(query_parts)

        response = (
            self.service.files()
            .list(q=query, **self._list_kwargs)
            .execute()
        )
        files = response.get("files", [])
        return files[0]["id"] if files else None

    def ensure_folder(self, folder_name: str, parent_id: Optional[str]) -> str:
        existing_id = self._find_existing_file_id_in_parent(folder_name, parent_id)
        if existing_id:
            return existing_id

        metadata: dict[str, object] = {
            "name": folder_name,
            "mimeType": "application/vnd.google-apps.folder",
        }
        if parent_id:
            metadata["parents"] = [parent_id]

        created = (
            self.service.files()
            .create(body=metadata, fields="id", supportsAllDrives=True)
            .execute()
        )
        return created["id"]

    def upload_or_update_in_parent(
        self,
        file_bytes: bytes,
        file_name: str,
        mime_type: str,
        parent_id: Optional[str],
    ) -> str:
        existing_id = self._find_existing_file_id_in_parent(file_name, parent_id)
        media = MediaInMemoryUpload(file_bytes, mimetype=mime_type, resumable=False)

        if existing_id:
            self.service.files().update(
                fileId=existing_id,
                media_body=media,
                supportsAllDrives=True,
            ).execute()
            return f"Updated: {file_name} (id={existing_id})"

        metadata: dict[str, object] = {"name": file_name}
        if parent_id:
            metadata["parents"] = [parent_id]

        created = (
            self.service.files()
            .create(
                body=metadata,
                media_body=media,
                fields="id",
                supportsAllDrives=True,
            )
            .execute()
        )
        return f"Created: {file_name} (id={created.get('id')})"

    def upload_or_update(self, csv_bytes: bytes, drive_name: str) -> str:
        return self.upload_or_update_in_parent(csv_bytes, drive_name, "text/csv", self.folder_id)

    def replace_google_sheet_with_charts(
        self,
        file_name: str,
        parent_id: Optional[str],
        data_sheets: dict[str, dict[str, list[list[object]]]],
        charts: list[dict[str, object]],
    ) -> str:
        existing_id = self._find_existing_file_id_in_parent(file_name, parent_id)
        if existing_id:
            self.service.files().delete(fileId=existing_id, supportsAllDrives=True).execute()

        spreadsheet = self.sheets_service.spreadsheets().create(
            body={
                "properties": {"title": file_name},
                "sheets": [{"properties": {"title": name}} for name in data_sheets],
            },
            fields="spreadsheetId",
        ).execute()
        spreadsheet_id = spreadsheet["spreadsheetId"]

        if parent_id:
            file_meta = self.service.files().get(
                fileId=spreadsheet_id,
                fields="parents",
                supportsAllDrives=True,
            ).execute()
            current_parents = ",".join(file_meta.get("parents", []))
            self.service.files().update(
                fileId=spreadsheet_id,
                addParents=parent_id,
                removeParents=current_parents,
                fields="id",
                supportsAllDrives=True,
            ).execute()

        values_data = []
        for name, sheet_payload in data_sheets.items():
            values = [sheet_payload["headers"], *sheet_payload["rows"]]
            values_data.append({"range": f"'{name}'!A1", "values": values})

        self.sheets_service.spreadsheets().values().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={
                "valueInputOption": "RAW",
                "data": values_data,
            },
        ).execute()

        sheet_meta = self.sheets_service.spreadsheets().get(
            spreadsheetId=spreadsheet_id,
            fields="sheets(properties(sheetId,title))",
        ).execute()
        sheet_id_map = {
            item["properties"]["title"]: item["properties"]["sheetId"]
            for item in sheet_meta.get("sheets", [])
        }

        requests = []
        for idx, chart in enumerate(charts):
            chart_sheet = str(chart["sheet"])
            sheet_id = sheet_id_map[chart_sheet]
            rows = data_sheets[chart_sheet]["rows"]
            row_count = max(len(rows), 1)
            categories_col = int(chart["cats_col"]) - 1

            if chart["type"] in {"bar", "line"}:
                chart_type = "COLUMN" if chart["type"] == "bar" else "LINE"
                basic_series = []
                for val_col, _name in chart["series"]:
                    basic_series.append(
                        {
                            "series": {
                                "sourceRange": {
                                    "sources": [
                                        {
                                            "sheetId": sheet_id,
                                            "startRowIndex": 1,
                                            "endRowIndex": row_count + 1,
                                            "startColumnIndex": int(val_col) - 1,
                                            "endColumnIndex": int(val_col),
                                        }
                                    ]
                                }
                            },
                            "targetAxis": "LEFT_AXIS",
                        }
                    )

                spec = {
                    "title": str(chart["title"]),
                    "basicChart": {
                        "chartType": chart_type,
                        "legendPosition": "RIGHT_LEGEND",
                        "axis": [
                            {"position": "BOTTOM_AXIS", "title": data_sheets[chart_sheet]["headers"][categories_col]},
                            {"position": "LEFT_AXIS", "title": "Tutar"},
                        ],
                        "domains": [
                            {
                                "domain": {
                                    "sourceRange": {
                                        "sources": [
                                            {
                                                "sheetId": sheet_id,
                                                "startRowIndex": 1,
                                                "endRowIndex": row_count + 1,
                                                "startColumnIndex": categories_col,
                                                "endColumnIndex": categories_col + 1,
                                            }
                                        ]
                                    }
                                }
                            }
                        ],
                        "series": basic_series,
                        "headerCount": 1,
                    },
                }
            else:
                val_col, _name = chart["series"][0]
                spec = {
                    "title": str(chart["title"]),
                    "pieChart": {
                        "legendPosition": "RIGHT_LEGEND",
                        "domain": {
                            "sourceRange": {
                                "sources": [
                                    {
                                        "sheetId": sheet_id,
                                        "startRowIndex": 1,
                                        "endRowIndex": row_count + 1,
                                        "startColumnIndex": categories_col,
                                        "endColumnIndex": categories_col + 1,
                                    }
                                ]
                            }
                        },
                        "series": {
                            "sourceRange": {
                                "sources": [
                                    {
                                        "sheetId": sheet_id,
                                        "startRowIndex": 1,
                                        "endRowIndex": row_count + 1,
                                        "startColumnIndex": int(val_col) - 1,
                                        "endColumnIndex": int(val_col),
                                    }
                                ]
                            }
                        },
                    },
                }

            requests.append(
                {
                    "addChart": {
                        "chart": {
                            "spec": spec,
                            "position": {
                                "overlayPosition": {
                                    "anchorCell": {
                                        "sheetId": sheet_id,
                                        "rowIndex": 1 + (idx % 2) * 18,
                                        "columnIndex": 6 + (idx // 2) * 8,
                                    },
                                    "offsetXPixels": 0,
                                    "offsetYPixels": 0,
                                    "widthPixels": 640,
                                    "heightPixels": 360,
                                }
                            },
                        }
                    }
                }
            )

        self.sheets_service.spreadsheets().batchUpdate(
            spreadsheetId=spreadsheet_id,
            body={"requests": requests},
        ).execute()

        return f"Created: {file_name} (Google Sheets id={spreadsheet_id})"


def period_bounds(day: int) -> tuple[int, int]:
    start = ((day - 1) // 60) * 60 + 1
    end = start + 59
    return start, end


def period_label(day: int) -> str:
    start, end = period_bounds(day)
    return f"{start}-{end}"


def parse_transactions(csv_file: Path) -> list[tuple[int, str, float]]:
    rows: list[tuple[int, str, float]] = []
    with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) < 4:
                continue
            day_raw = row[1].strip()
            if not day_raw.isdigit():
                continue
            type_name = row[2].strip()
            if not type_name:
                continue

            amount_raw = row[3].strip()
            try:
                amount = parse_amount(amount_raw)
            except ValueError:
                continue

            rows.append((int(day_raw), type_name, amount))
    return rows


def parse_amount(raw: str) -> float:
    """Tutarları güvenli parse eder.

    Oyun çıktısında ondalık ayracı nokta olabildiği için (`765.487`) noktayı
    silmek büyük sapmaya yol açar. Bu fonksiyon hem nokta hem virgül içeren
    değerleri destekler.
    """
    value = raw.strip().replace(" ", "")
    if not value:
        raise ValueError("empty amount")

    if "," in value and "." in value:
        # Son görülen işaret ondalık ayracıdır, diğeri binlik ayracı sayılır.
        if value.rfind(",") > value.rfind("."):
            value = value.replace(".", "").replace(",", ".")
        else:
            value = value.replace(",", "")
    elif "," in value:
        value = value.replace(",", ".")

    return float(value)


def summarize_daily_metrics(transactions: list[tuple[int, str, float]]) -> list[tuple[int, float, float, float]]:
    grouped: dict[int, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for day, _type_name, amount in transactions:
        if amount >= 0:
            grouped[day]["income"] += amount
        else:
            grouped[day]["expense"] += abs(amount)

    rows: list[tuple[int, float, float, float]] = []
    for day in sorted(grouped):
        income = round(grouped[day]["income"], 2)
        expense = round(grouped[day]["expense"], 2)
        net = round(income - expense, 2)
        rows.append((day, income, expense, net))
    return rows


def summarize_period_metrics(transactions: list[tuple[int, str, float]]) -> list[tuple[str, float, float, float]]:
    grouped: dict[str, dict[str, float]] = defaultdict(lambda: {"income": 0.0, "expense": 0.0})
    for day, _type_name, amount in transactions:
        period = period_label(day)
        if amount >= 0:
            grouped[period]["income"] += amount
        else:
            grouped[period]["expense"] += abs(amount)

    def period_sort_key(label: str) -> int:
        return int(label.split("-", 1)[0])

    rows: list[tuple[str, float, float, float]] = []
    for period in sorted(grouped, key=period_sort_key):
        income = round(grouped[period]["income"], 2)
        expense = round(grouped[period]["expense"], 2)
        net = round(income - expense, 2)
        rows.append((period, income, expense, net))
    return rows


def summarize_type_totals(transactions: list[tuple[int, str, float]]) -> tuple[list[tuple[str, float]], list[tuple[str, float]]]:
    income_types: dict[str, float] = defaultdict(float)
    expense_types: dict[str, float] = defaultdict(float)
    for _day, type_name, amount in transactions:
        if amount >= 0:
            income_types[type_name] += amount
        else:
            expense_types[type_name] += abs(amount)

    income_rows = sorted(((k, round(v, 2)) for k, v in income_types.items()), key=lambda item: item[0])
    expense_rows = sorted(((k, round(v, 2)) for k, v in expense_types.items()), key=lambda item: item[0])
    return income_rows, expense_rows


def build_daily_sheet_payload(
    period: str,
    transactions: list[tuple[int, str, float]],
) -> tuple[dict[str, dict[str, list[list[object]]]], list[dict[str, object]]]:
    metrics_rows = [list(row) for row in summarize_daily_metrics(transactions)]
    income_rows, expense_rows = summarize_type_totals(transactions)

    if not metrics_rows:
        metrics_rows = [[0, 0.0, 0.0, 0.0]]
    if not income_rows:
        income_rows = [("KazancYok", 0.0)]
    if not expense_rows:
        expense_rows = [("HarcamaYok", 0.0)]

    data_sheets = {
        "ozet": {
            "headers": ["Gun", "Kazanc", "Harcama", "NetKazanc"],
            "rows": metrics_rows,
        },
        "turler": {
            "headers": ["KazancTuru", "KazancToplam", "HarcamaTuru", "HarcamaToplam"],
            "rows": [
                [income_rows[i][0] if i < len(income_rows) else "", income_rows[i][1] if i < len(income_rows) else "",
                 expense_rows[i][0] if i < len(expense_rows) else "", expense_rows[i][1] if i < len(expense_rows) else ""]
                for i in range(max(len(income_rows), len(expense_rows), 1))
            ],
        },
    }
    charts = [
        {"type": "bar", "title": f"{period} Kazanc-Harcama", "sheet": "ozet", "cats_col": 1, "series": [(2, "Kazanc"), (3, "Harcama")]},
        {"type": "line", "title": f"{period} Net Kazanc", "sheet": "ozet", "cats_col": 1, "series": [(4, "NetKazanc")]},
        {"type": "pie", "title": f"{period} Turlere Gore Kazanc", "sheet": "turler", "cats_col": 1, "series": [(2, "Kazanc")]},
        {"type": "pie", "title": f"{period} Turlere Gore Harcama", "sheet": "turler", "cats_col": 3, "series": [(4, "Harcama")]},
    ]
    return data_sheets, charts


def build_period_totals_sheet_payload(
    transactions: list[tuple[int, str, float]],
) -> tuple[dict[str, dict[str, list[list[object]]]], list[dict[str, object]]]:
    metrics_rows = [list(row) for row in summarize_period_metrics(transactions)]
    income_rows, expense_rows = summarize_type_totals(transactions)

    if not metrics_rows:
        metrics_rows = [["1-60", 0.0, 0.0, 0.0]]
    if not income_rows:
        income_rows = [("KazancYok", 0.0)]
    if not expense_rows:
        expense_rows = [("HarcamaYok", 0.0)]

    data_sheets = {
        "ozet": {
            "headers": ["Periyot", "Kazanc", "Harcama", "NetKazanc"],
            "rows": metrics_rows,
        },
        "turler": {
            "headers": ["KazancTuru", "KazancToplam", "HarcamaTuru", "HarcamaToplam"],
            "rows": [
                [income_rows[i][0] if i < len(income_rows) else "", income_rows[i][1] if i < len(income_rows) else "",
                 expense_rows[i][0] if i < len(expense_rows) else "", expense_rows[i][1] if i < len(expense_rows) else ""]
                for i in range(max(len(income_rows), len(expense_rows), 1))
            ],
        },
    }
    charts = [
        {"type": "bar", "title": "Periyot Bazli Kazanc-Harcama", "sheet": "ozet", "cats_col": 1, "series": [(2, "Kazanc"), (3, "Harcama")]},
        {"type": "line", "title": "Periyot Bazli Net Kazanc", "sheet": "ozet", "cats_col": 1, "series": [(4, "NetKazanc")]},
        {"type": "pie", "title": "Turlere Gore Kazanc", "sheet": "turler", "cats_col": 1, "series": [(2, "Kazanc")]},
        {"type": "pie", "title": "Turlere Gore Harcama", "sheet": "turler", "cats_col": 3, "series": [(4, "Harcama")]},
    ]
    return data_sheets, charts


def build_daily_summary_csv(period: str, transactions: list[tuple[int, str, float]]) -> bytes:
    metrics_rows = summarize_daily_metrics(transactions)
    income_rows, expense_rows = summarize_type_totals(transactions)

    lines: list[str] = [f"Periyot,{period}", ""]
    lines.append("[Veri] Gunluk Ozet")
    lines.append("Gun,Kazanc,Harcama,NetKazanc")
    for day, income, expense, net in metrics_rows:
        lines.append(f"{day},{income:.2f},{expense:.2f},{net:.2f}")

    lines.append("")
    lines.append("[Grafik] Sutun - Gunluk Kazanc/Harcama")
    lines.append("Gun,Kazanc,Harcama")
    for day, income, expense, _ in metrics_rows:
        lines.append(f"{day},{income:.2f},{expense:.2f}")

    lines.append("")
    lines.append("[Grafik] Cizgi - Gunluk Net")
    lines.append("Gun,NetKazanc")
    for day, _income, _expense, net in metrics_rows:
        lines.append(f"{day},{net:.2f}")

    lines.append("")
    lines.append("[Grafik] Pasta - Kazanc Turleri")
    lines.append("Tur,Tutar")
    for type_name, amount in income_rows:
        lines.append(f"{type_name},{amount:.2f}")

    lines.append("")
    lines.append("[Grafik] Pasta - Harcama Turleri")
    lines.append("Tur,Tutar")
    for type_name, amount in expense_rows:
        lines.append(f"{type_name},{amount:.2f}")

    return ("\n".join(lines) + "\n").encode("utf-8")


def build_period_totals_csv(transactions: list[tuple[int, str, float]]) -> bytes:
    metrics_rows = summarize_period_metrics(transactions)
    income_rows, expense_rows = summarize_type_totals(transactions)

    lines: list[str] = []
    lines.append("[Veri] Periyot Ozet")
    lines.append("Periyot,Kazanc,Harcama,NetKazanc")
    for period, income, expense, net in metrics_rows:
        lines.append(f"{period},{income:.2f},{expense:.2f},{net:.2f}")

    lines.append("")
    lines.append("[Grafik] Sutun - Periyot Bazli Kazanc/Harcama")
    lines.append("Periyot,Kazanc,Harcama")
    for period, income, expense, _ in metrics_rows:
        lines.append(f"{period},{income:.2f},{expense:.2f}")

    lines.append("")
    lines.append("[Grafik] Cizgi - Periyot Bazli Net")
    lines.append("Periyot,NetKazanc")
    for period, _income, _expense, net in metrics_rows:
        lines.append(f"{period},{net:.2f}")

    lines.append("")
    lines.append("[Grafik] Pasta - Toplam Kazanc Turleri")
    lines.append("Tur,Tutar")
    for type_name, amount in income_rows:
        lines.append(f"{type_name},{amount:.2f}")

    lines.append("")
    lines.append("[Grafik] Pasta - Toplam Harcama Turleri")
    lines.append("Tur,Tutar")
    for type_name, amount in expense_rows:
        lines.append(f"{type_name},{amount:.2f}")

    return ("\n".join(lines) + "\n").encode("utf-8")


def build_daily_summary_xlsx(period: str, transactions: list[tuple[int, str, float]]) -> bytes:
    data_sheets, charts = build_daily_sheet_payload(period, transactions)
    return build_xlsx_with_charts("gunluk_ozet", data_sheets, charts)


def build_period_totals_xlsx(transactions: list[tuple[int, str, float]]) -> bytes:
    data_sheets, charts = build_period_totals_sheet_payload(transactions)
    return build_xlsx_with_charts("period_ozet", data_sheets, charts)


def build_xlsx_with_charts(_sheet_name: str, data_sheets: dict[str, dict[str, list[list[object]]]], charts: list[dict[str, object]]) -> bytes:
    sheet_names = list(data_sheets.keys()) + ["grafikler"]
    sheet_xml_map = {
        name: _build_sheet_xml([spec["headers"]] + spec["rows"])
        for name, spec in data_sheets.items()
    }
    sheet_xml_map["grafikler"] = _build_chart_sheet_xml()

    workbook_sheets = []
    workbook_rels = []
    for idx, name in enumerate(sheet_names, start=1):
        workbook_sheets.append(f'<sheet name="{escape(name)}" sheetId="{idx}" r:id="rId{idx}"/>')
        workbook_rels.append(
            f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{idx}.xml"/>'
        )

    styles_rel_id = len(sheet_names) + 1
    workbook_rels.append(
        f'<Relationship Id="rId{styles_rel_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'
    )

    chart_sheet_index = len(sheet_names)
    chart_sheet_rels = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/drawing" Target="../drawings/drawing1.xml"/>'
        '</Relationships>'
    )

    drawing_xml = _build_drawing_xml(len(charts))
    drawing_rels = ['<?xml version="1.0" encoding="UTF-8" standalone="yes"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">']
    for idx in range(1, len(charts) + 1):
        drawing_rels.append(
            f'<Relationship Id="rId{idx}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/chart" Target="../charts/chart{idx}.xml"/>'
        )
    drawing_rels.append('</Relationships>')

    chart_xml_list = []
    for idx, chart in enumerate(charts, start=1):
        chart_xml_list.append(_build_chart_xml(idx, chart, data_sheets))

    content_types = [
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>',
        '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>',
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>',
        '<Override PartName="/docProps/app.xml" ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>',
    ]
    for idx in range(1, len(sheet_names) + 1):
        content_types.append(f'<Override PartName="/xl/worksheets/sheet{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>')
    content_types.append('<Override PartName="/xl/drawings/drawing1.xml" ContentType="application/vnd.openxmlformats-officedocument.drawing+xml"/>')
    for idx in range(1, len(charts) + 1):
        content_types.append(f'<Override PartName="/xl/charts/chart{idx}.xml" ContentType="application/vnd.openxmlformats-officedocument.drawingml.chart+xml"/>')
    content_types.append('</Types>')

    rels = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" Target="docProps/core.xml"/>
  <Relationship Id="rId3" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" Target="docProps/app.xml"/>
</Relationships>"""

    workbook = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f"<sheets>{''.join(workbook_sheets)}</sheets></workbook>"
    )

    workbook_rels_xml = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        f"{''.join(workbook_rels)}</Relationships>"
    )

    styles = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <fonts count="1"><font><sz val="11"/><name val="Calibri"/></font></fonts>
  <fills count="1"><fill><patternFill patternType="none"/></fill></fills>
  <borders count="1"><border/></borders>
  <cellStyleXfs count="1"><xf/></cellStyleXfs>
  <cellXfs count="1"><xf/></cellXfs>
</styleSheet>"""

    core = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/" xmlns:dcterms="http://purl.org/dc/terms/" xmlns:dcmitype="http://purl.org/dc/dcmitype/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <dc:title>Big Ambitions Summary</dc:title>
</cp:coreProperties>"""

    app = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">
  <Application>Python</Application>
</Properties>"""

    output = BytesIO()
    with zipfile.ZipFile(output, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", ''.join(content_types))
        archive.writestr("_rels/.rels", rels)
        archive.writestr("docProps/core.xml", core)
        archive.writestr("docProps/app.xml", app)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", workbook_rels_xml)
        archive.writestr("xl/styles.xml", styles)
        for idx, name in enumerate(sheet_names, start=1):
            archive.writestr(f"xl/worksheets/sheet{idx}.xml", sheet_xml_map[name])
        archive.writestr(f"xl/worksheets/_rels/sheet{chart_sheet_index}.xml.rels", chart_sheet_rels)
        archive.writestr("xl/drawings/drawing1.xml", drawing_xml)
        archive.writestr("xl/drawings/_rels/drawing1.xml.rels", ''.join(drawing_rels))
        for idx, chart_xml in enumerate(chart_xml_list, start=1):
            archive.writestr(f"xl/charts/chart{idx}.xml", chart_xml)
    return output.getvalue()


def _build_chart_sheet_xml() -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheetData/><drawing r:id="rId1"/></worksheet>'
    )


def _cell_range(sheet: str, col: int, start_row: int, end_row: int) -> str:
    col_letter = _column_letter(col)
    safe_sheet = sheet.replace("'", "''")
    return f"'{safe_sheet}'!${col_letter}${start_row}:${col_letter}${end_row}"


def _build_chart_xml(chart_index: int, chart: dict[str, object], data_sheets: dict[str, dict[str, list[list[object]]]]) -> str:
    chart_type = str(chart["type"])
    title = escape(str(chart["title"]))
    sheet = str(chart["sheet"])
    cats_col = int(chart["cats_col"])
    series = chart["series"]
    row_count = len(data_sheets[sheet]["rows"]) + 1
    start_row = 2
    end_row = max(row_count, 2)
    cat_range = _cell_range(sheet, cats_col, start_row, end_row)

    series_xml = []
    for idx, (val_col, name) in enumerate(series):
        val_range = _cell_range(sheet, int(val_col), start_row, end_row)
        series_xml.append(
            '<c:ser>'
            f'<c:idx val="{idx}"/><c:order val="{idx}"/>'
            f'<c:tx><c:v>{escape(str(name))}</c:v></c:tx>'
            f'<c:cat><c:strRef><c:f>{cat_range}</c:f></c:strRef></c:cat>'
            f'<c:val><c:numRef><c:f>{val_range}</c:f></c:numRef></c:val>'
            '</c:ser>'
        )

    if chart_type == "bar":
        plot = f'<c:barChart><c:barDir val="col"/><c:grouping val="clustered"/>{"".join(series_xml)}<c:axId val="1"/><c:axId val="2"/></c:barChart>'
        axes = '<c:catAx><c:axId val="1"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="b"/><c:tickLblPos val="nextTo"/><c:crossAx val="2"/><c:crosses val="autoZero"/></c:catAx><c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="l"/><c:majorGridlines/><c:tickLblPos val="nextTo"/><c:crossAx val="1"/><c:crosses val="autoZero"/></c:valAx>'
    elif chart_type == "line":
        plot = f'<c:lineChart><c:grouping val="standard"/>{"".join(series_xml)}<c:axId val="1"/><c:axId val="2"/></c:lineChart>'
        axes = '<c:catAx><c:axId val="1"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="b"/><c:tickLblPos val="nextTo"/><c:crossAx val="2"/><c:crosses val="autoZero"/></c:catAx><c:valAx><c:axId val="2"/><c:scaling><c:orientation val="minMax"/></c:scaling><c:axPos val="l"/><c:majorGridlines/><c:tickLblPos val="nextTo"/><c:crossAx val="1"/><c:crosses val="autoZero"/></c:valAx>'
    else:
        plot = f'<c:pieChart>{"".join(series_xml)}</c:pieChart>'
        axes = ''

    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<c:chartSpace xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        '<c:chart>'
        f'<c:title><c:tx><c:rich><a:bodyPr/><a:lstStyle/><a:p><a:r><a:rPr lang="en-US"/><a:t>{title}</a:t></a:r></a:p></c:rich></c:tx></c:title>'
        f'<c:plotArea><c:layout/>{plot}{axes}</c:plotArea>'
        '<c:legend><c:legendPos val="r"/></c:legend>'
        '</c:chart></c:chartSpace>'
    )


def _build_drawing_xml(chart_count: int) -> str:
    anchors = []
    positions = [(0,0),(8,0),(0,18),(8,18)]
    for idx in range(chart_count):
        col,row = positions[idx] if idx < len(positions) else (0, idx*16)
        anchors.append(
            '<xdr:twoCellAnchor>'
            f'<xdr:from><xdr:col>{col}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:from>'
            f'<xdr:to><xdr:col>{col+7}</xdr:col><xdr:colOff>0</xdr:colOff><xdr:row>{row+15}</xdr:row><xdr:rowOff>0</xdr:rowOff></xdr:to>'
            '<xdr:graphicFrame macro=""><xdr:nvGraphicFramePr><xdr:cNvPr id="{idv}" name="Chart {idv}"/><xdr:cNvGraphicFramePr/></xdr:nvGraphicFramePr><xdr:xfrm><a:off x="0" y="0"/><a:ext cx="0" cy="0"/></xdr:xfrm><a:graphic><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/chart"><c:chart xmlns:c="http://schemas.openxmlformats.org/drawingml/2006/chart" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" r:id="rId{idv}"/></a:graphicData></a:graphic></xdr:graphicFrame><xdr:clientData/>'
            '</xdr:twoCellAnchor>'.format(idv=idx+1)
        )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<xdr:wsDr xmlns:xdr="http://schemas.openxmlformats.org/drawingml/2006/spreadsheetDrawing" '
        'xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">'
        f"{''.join(anchors)}</xdr:wsDr>"
    )


def _build_sheet_xml(rows: list[list[object]]) -> str:
    row_xml: list[str] = []
    for row_idx, row_values in enumerate(rows, start=1):
        cells: list[str] = []
        for col_idx, value in enumerate(row_values, start=1):
            cell_ref = f"{_column_letter(col_idx)}{row_idx}"
            if isinstance(value, (int, float)):
                cells.append(f"<c r=\"{cell_ref}\"><v>{value}</v></c>")
            else:
                cells.append(
                    f"<c r=\"{cell_ref}\" t=\"inlineStr\"><is><t>{escape(str(value))}</t></is></c>"
                )
        row_xml.append(f"<row r=\"{row_idx}\">{''.join(cells)}</row>")

    return (
        "<?xml version=\"1.0\" encoding=\"UTF-8\" standalone=\"yes\"?>"
        "<worksheet xmlns=\"http://schemas.openxmlformats.org/spreadsheetml/2006/main\">"
        f"<sheetData>{''.join(row_xml)}</sheetData>"
        "</worksheet>"
    )


def _column_letter(index: int) -> str:
    label = ""
    current = index
    while current:
        current, rem = divmod(current - 1, 26)
        label = chr(65 + rem) + label
    return label


class TransactionsHandler(FileSystemEventHandler):
    """Sadece transactions.csv modified event'ini işler."""

    def __init__(
        self,
        uploader: DriveUploader,
        settle_seconds: int = 10,
        logger: Callable[[str], None] = print,
    ) -> None:
        self.uploader = uploader
        self.settle_seconds = settle_seconds
        self.logger = logger
        self._last_uploaded_day: Optional[str] = None
        self._last_uploaded_mtime: Optional[float] = None

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        changed_file = Path(event.src_path)
        if changed_file.name.lower() != "transactions.csv":
            return

        try:
            self.logger(f"[WATCHDOG] Değişim algılandı: {changed_file}")
            time.sleep(self.settle_seconds)

            # Aynı mtime için duplicate event'leri atla.
            file_mtime = changed_file.stat().st_mtime
            day_value = self._extract_day_from_csv(changed_file)
            if day_value is None:
                self.logger("[WARN] B sütunu (gün) okunamadı, upload atlandı.")
                return

            if self._last_uploaded_day == day_value and self._last_uploaded_mtime == file_mtime:
                self.logger("[INFO] Duplicate event atlandı.")
                return

            drive_name = f"transactionsgun_{day_value}.csv"
            csv_bytes = self._read_csv_bytes_with_retry(changed_file)
            day_number = int(day_value)
            period = period_label(day_number)

            root_folder_id = self.uploader.ensure_folder("big ambitions", self.uploader.folder_id)
            period_folder_id = self.uploader.ensure_folder(period, root_folder_id)

            result = self.uploader.upload_or_update_in_parent(
                csv_bytes,
                drive_name,
                "text/csv",
                period_folder_id,
            )
            self.logger(f"[DRIVE] {result}")

            transactions = parse_transactions(changed_file)
            period_start, period_end = period_bounds(day_number)
            in_period = [
                t for t in transactions if period_start <= t[0] <= period_end
            ]

            daily_data_sheets, daily_charts = build_daily_sheet_payload(period, in_period)
            daily_result = self.uploader.replace_google_sheet_with_charts(
                "main",
                period_folder_id,
                daily_data_sheets,
                daily_charts,
            )
            self.logger(f"[DRIVE] {daily_result}")

            total_data_sheets, total_charts = build_period_totals_sheet_payload(transactions)
            total_result = self.uploader.replace_google_sheet_with_charts(
                "main_total",
                root_folder_id,
                total_data_sheets,
                total_charts,
            )
            self.logger(f"[DRIVE] {total_result}")
            self._last_uploaded_day = day_value
            self._last_uploaded_mtime = file_mtime
        except HttpError as exc:
            self.logger(
                "[ERROR] transactions.csv işleme hatası: "
                f"{explain_http_error(exc, self.uploader.folder_id)}"
            )
        except Exception as exc:
            self.logger(f"[ERROR] transactions.csv işleme hatası: {exc}")

    @staticmethod
    def _extract_day_from_csv(csv_file: Path) -> Optional[str]:
        with csv_file.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.reader(f)
            first_row = next(reader, None)
            if not first_row:
                return None

            # Başlık yoksa ilk satırdan oku
            if len(first_row) > 1 and first_row[1].strip().isdigit():
                return first_row[1].strip()

            # Başlık varsa ilk veri satırından oku
            data_row = next(reader, None)
            if data_row and len(data_row) > 1:
                value = data_row[1].strip()
                return value or None

        return None

    @staticmethod
    def _read_csv_bytes_with_retry(source_file: Path) -> bytes:
        for attempt in range(1, 6):
            try:
                return source_file.read_bytes()
            except PermissionError as exc:
                if attempt == 5:
                    raise
                if getattr(exc, "winerror", None) != 32 and exc.errno != errno.EACCES:
                    raise
                time.sleep(0.4 * attempt)

        raise RuntimeError("transactions.csv okunamadı")


def is_game_running(process_names: tuple[str, ...]) -> bool:
    expected = {name.lower() for name in process_names}
    for proc in psutil.process_iter(attrs=["name"]):
        name = (proc.info.get("name") or "").lower()
        if name in expected:
            return True
    return False


def find_latest_save_folder(savegames_root: Path) -> Optional[Path]:
    if not savegames_root.exists():
        return None

    version_dirs = [p for p in savegames_root.iterdir() if p.is_dir()]
    if not version_dirs:
        return None

    latest_version = max(version_dirs, key=lambda p: p.stat().st_mtime)
    save_dirs = [p for p in latest_version.iterdir() if p.is_dir()]
    if not save_dirs:
        return None

    return max(save_dirs, key=lambda p: p.stat().st_mtime)


def build_default_config() -> Config:
    # Gereksinimde belirtildiği gibi home çözümleme.
    user_profile = os.environ.get("USERPROFILE")
    user_home = Path(user_profile) if user_profile else Path(os.path.expanduser("~"))

    savegames_root = (
        user_home
        / "AppData"
        / "LocalLow"
        / "Hovgaard Games"
        / "Big Ambitions"
        / "SaveGames"
    )

    script_dir = Path(__file__).resolve().parent
    credentials_default = script_dir / "oauth_client_credentials.json"
    if not credentials_default.exists():
        alt_default = script_dir / "credentials.json"
        if alt_default.exists():
            credentials_default = alt_default

    credentials_file = Path(os.getenv("GOOGLE_CREDENTIALS_FILE", str(credentials_default)))
    folder_id = normalize_drive_folder_id(os.getenv("GDRIVE_FOLDER_ID"))
    names = os.getenv("GAME_PROCESS_NAMES", "Big Ambitions.exe,Big_Ambitions.exe,BigAmbitions.exe,UnityPlayer.exe")
    process_names = tuple(n.strip() for n in names.split(",") if n.strip())

    return Config(
        savegames_root=savegames_root,
        credentials_file=credentials_file,
        drive_folder_id=folder_id,
        process_names=process_names,
    )


def preflight(config: Config) -> list[str]:
    errors: list[str] = []
    if os.name != "nt":
        errors.append("Bu script Windows path varsayımıyla yazıldı (os.name != 'nt').")
    if not config.savegames_root.exists():
        errors.append(f"SaveGames klasörü bulunamadı: {config.savegames_root}")
    if not config.credentials_file.exists():
        errors.append(
            f"Google credentials dosyası yok: {config.credentials_file} "
            "(oauth_client_credentials.json / credentials.json ekleyin veya GOOGLE_CREDENTIALS_FILE ayarlayın)"
        )
    if not config.process_names:
        errors.append("GAME_PROCESS_NAMES boş olamaz.")
    if config.drive_folder_id and len(config.drive_folder_id) < 10:
        errors.append(
            "Drive Folder ID geçersiz görünüyor. Yalnızca klasör ID'sini girin "
            "(örnek: 1AbCdEfGhIjKlMnOpQr). '.' veya kısa değerler kullanmayın."
        )
    return errors


def explain_http_error(
    exc: HttpError,
    folder_id: Optional[str] = None,
) -> str:
    body = getattr(exc, "content", b"")
    try:
        text = body.decode("utf-8", errors="replace")
    except Exception:
        text = str(body)

    folder_hint = folder_id if folder_id else "<boş>"
    if exc.resp is not None and exc.resp.status == 403 and "storageQuotaExceeded" in text:
        return (
            "Drive 403 storageQuotaExceeded: Kişisel Drive depolama kotanız dolu olabilir veya hedefe yazma izni yok. "
            f"Mevcut GDRIVE_FOLDER_ID={folder_hint}."
        )

    if exc.resp is not None and exc.resp.status == 404 and '"location": "fileId"' in text:
        return (
            "Drive 404 fileId notFound: Bu hata yalnızca 'ID yanlış' anlamına gelmez; "
            f"Mevcut GDRIVE_FOLDER_ID={folder_hint}. "
            "Kontrol edin: (1) URL'den gerçek klasör ID'si alındı mı, "
            "(2) Google hesabınızın bu klasöre erişimi var mı."
        )

    return f"HTTP {getattr(exc.resp, 'status', 'unknown')}: {text}"


def run_loop(config: Config, logger: Callable[[str], None] = print) -> None:
    uploader = DriveUploader(config.credentials_file, config.drive_folder_id)

    observer: Optional[Observer] = None
    watched_folder: Optional[Path] = None

    target_info = config.drive_folder_id if config.drive_folder_id else "<yok>"
    logger(f"[INFO] Drive hedef klasör ID: {target_info}")
    try:
        logger(f"[INFO] Drive hedef kontrolü: {uploader.describe_target_folder()}")
    except Exception as exc:
        logger(f"[ERROR] Drive hedef doğrulama hatası: {exc}")
        raise SystemExit(1)

    logger("[INFO] Otomasyon başladı. Oyun süreci izleniyor...")
    while True:
        try:
            running = is_game_running(config.process_names)
            if running:
                latest_folder = find_latest_save_folder(config.savegames_root)
                if latest_folder is None:
                    logger("[WARN] En güncel save klasörü bulunamadı.")
                else:
                    transactions = latest_folder / "transactions.csv"
                    if not transactions.exists():
                        logger(f"[WARN] transactions.csv yok: {transactions}")
                    elif observer is None:
                        handler = TransactionsHandler(uploader, config.file_settle_seconds, logger)
                        observer = Observer()
                        observer.schedule(handler, str(latest_folder), recursive=False)
                        observer.start()
                        watched_folder = latest_folder
                        logger(f"[INFO] İzleme başladı: {latest_folder}")
                    elif watched_folder != latest_folder:
                        observer.stop()
                        observer.join(timeout=5)
                        handler = TransactionsHandler(uploader, config.file_settle_seconds, logger)
                        observer = Observer()
                        observer.schedule(handler, str(latest_folder), recursive=False)
                        observer.start()
                        watched_folder = latest_folder
                        logger(f"[INFO] İzlenen klasör güncellendi: {latest_folder}")
            else:
                if observer is not None:
                    logger("[INFO] Oyun kapalı, izleme durduruldu.")
                    observer.stop()
                    observer.join(timeout=5)
                    observer = None
                    watched_folder = None

            time.sleep(config.poll_seconds)
        except KeyboardInterrupt:
            logger("[INFO] Çıkış sinyali alındı.")
            break
        except HttpError as exc:
            logger(
                "[ERROR] Ana döngü hatası: "
                f"{explain_http_error(exc, config.drive_folder_id)}"
            )
            time.sleep(config.poll_seconds)
        except Exception as exc:
            logger(f"[ERROR] Ana döngü hatası: {exc}")
            time.sleep(config.poll_seconds)

    if observer is not None:
        observer.stop()
        observer.join(timeout=5)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Big Ambitions -> Google Drive otomasyonu")
    parser.add_argument(
        "--doctor",
        action="store_true",
        help="Sadece kurulum/doğrulama kontrolü yap ve çık.",
    )
    parser.add_argument(
        "--no-gui",
        action="store_true",
        help="GUI açmadan doğrudan mevcut config ile çalıştır.",
    )
    return parser.parse_args()


def launch_config_gui(default_config: Config) -> None:
    """Kullanıcıdan ayarları alır ve izlemeyi GUI açık kalırken arka planda başlatır."""
    root = tk.Tk()
    root.title("Big Ambitions Drive Sync - Ayarlar")
    root.resizable(False, False)

    savegames_var = tk.StringVar(value=str(default_config.savegames_root))
    credentials_var = tk.StringVar(value=str(default_config.credentials_file))
    folder_id_var = tk.StringVar(value=default_config.drive_folder_id or "")
    process_var = tk.StringVar(value=",".join(default_config.process_names))
    poll_var = tk.StringVar(value=str(default_config.poll_seconds))
    settle_var = tk.StringVar(value=str(default_config.file_settle_seconds))
    status_var = tk.StringVar(value="Durum: Hazır")

    runner_thread: Optional[threading.Thread] = None

    log_queue: queue.Queue[str] = queue.Queue()

    def gui_logger(message: str) -> None:
        print(message)
        log_queue.put(message)

    def pump_logs() -> None:
        updated = False
        while True:
            try:
                message = log_queue.get_nowait()
            except queue.Empty:
                break

            updated = True
            if message.startswith("[ERROR]"):
                status_var.set(f"Durum: Hata - {message}")
            elif message.startswith("[WARN]"):
                status_var.set(f"Durum: Uyarı - {message}")
            else:
                status_var.set(f"Durum: {message}")

            log_text.configure(state="normal")
            log_text.insert("end", message + "\n")
            log_text.see("end")
            log_text.configure(state="disabled")

        if updated:
            root.update_idletasks()
        root.after(250, pump_logs)

    def browse_savegames() -> None:
        selected = filedialog.askdirectory(title="SaveGames klasörünü seç")
        if selected:
            savegames_var.set(selected)

    def browse_credentials_file() -> None:
        selected = filedialog.askopenfilename(
            title="OAuth credentials JSON seç",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if selected:
            credentials_var.set(selected)

    def on_start() -> None:
        nonlocal runner_thread
        try:
            poll_seconds = int(poll_var.get().strip())
            settle_seconds = int(settle_var.get().strip())
            if poll_seconds <= 0 or settle_seconds <= 0:
                raise ValueError("Süre değerleri 0'dan büyük olmalı")

            process_names = tuple(
                p.strip() for p in process_var.get().split(",") if p.strip()
            )
            cfg = Config(
                savegames_root=Path(savegames_var.get().strip()),
                credentials_file=Path(credentials_var.get().strip()),
                drive_folder_id=normalize_drive_folder_id(folder_id_var.get()),
                process_names=process_names,
                poll_seconds=poll_seconds,
                file_settle_seconds=settle_seconds,
            )

            errors = preflight(cfg)
            if errors:
                messagebox.showerror("Ayar Hatası", "\n".join(errors))
                return

            if runner_thread and runner_thread.is_alive():
                messagebox.showinfo("Bilgi", "İzleme zaten çalışıyor.")
                return

            runner_thread = threading.Thread(target=run_loop, args=(cfg, gui_logger), daemon=True)
            runner_thread.start()
            status_var.set("Durum: İzleme başladı (pencere açık kalır)")
            start_button.config(state="disabled")
            messagebox.showinfo(
                "Başlatıldı",
                "İzleme arka planda başladı. Bu pencere kapanmadı; durum takibi için açık kalabilir.",
            )
        except ValueError as exc:
            messagebox.showerror("Ayar Hatası", str(exc))

    def on_cancel() -> None:
        root.destroy()

    row = 0
    tk.Label(root, text="SaveGames klasörü").grid(row=row, column=0, sticky="w", padx=8, pady=6)
    tk.Entry(root, width=60, textvariable=savegames_var).grid(row=row, column=1, padx=8, pady=6)
    tk.Button(root, text="Seç", command=browse_savegames).grid(row=row, column=2, padx=8, pady=6)

    row += 1
    tk.Label(root, text="OAuth Credentials JSON").grid(row=row, column=0, sticky="w", padx=8, pady=6)
    tk.Entry(root, width=60, textvariable=credentials_var).grid(row=row, column=1, padx=8, pady=6)
    tk.Button(root, text="Seç", command=browse_credentials_file).grid(row=row, column=2, padx=8, pady=6)

    row += 1
    tk.Label(root, text="Drive Folder ID").grid(row=row, column=0, sticky="w", padx=8, pady=6)
    tk.Entry(root, width=60, textvariable=folder_id_var).grid(row=row, column=1, padx=8, pady=6)

    row += 1
    tk.Label(root, text="Process adları (virgülle)").grid(row=row, column=0, sticky="w", padx=8, pady=6)
    tk.Entry(root, width=60, textvariable=process_var).grid(row=row, column=1, padx=8, pady=6)

    row += 1
    tk.Label(root, text="Döngü bekleme sn").grid(row=row, column=0, sticky="w", padx=8, pady=6)
    tk.Entry(root, width=20, textvariable=poll_var).grid(row=row, column=1, sticky="w", padx=8, pady=6)

    row += 1
    tk.Label(root, text="Dosya yazım bekleme sn").grid(row=row, column=0, sticky="w", padx=8, pady=6)
    tk.Entry(root, width=20, textvariable=settle_var).grid(row=row, column=1, sticky="w", padx=8, pady=6)

    row += 1
    tk.Label(root, textvariable=status_var, fg="#0a5").grid(
        row=row, column=0, columnspan=3, sticky="w", padx=8, pady=6
    )


    row += 1
    tk.Label(root, text="Canlı log").grid(row=row, column=0, sticky="nw", padx=8, pady=6)
    log_text = tk.Text(root, width=82, height=10, state="disabled")
    log_text.grid(row=row, column=1, columnspan=2, padx=8, pady=6, sticky="w")

    row += 1
    start_button = tk.Button(root, text="Başlat", command=on_start, width=18)
    start_button.grid(row=row, column=1, sticky="w", padx=8, pady=12)
    tk.Button(root, text="Kapat", command=on_cancel, width=12).grid(
        row=row, column=1, sticky="e", padx=8, pady=12
    )

    root.after(250, pump_logs)
    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()


def main() -> None:
    args = parse_args()
    default_config = build_default_config()

    if args.no_gui:
        config = default_config
        errors = preflight(config)
        if errors:
            print("[PRECHECK] Hazır değil. Tespit edilen sorunlar:")
            for issue in errors:
                print(f"  - {issue}")
            raise SystemExit(1)

        print("[PRECHECK] Hazır: temel kontroller geçti.")
        if args.doctor:
            return

        run_loop(config)
        return

    launch_config_gui(default_config)


if __name__ == "__main__":
    main()

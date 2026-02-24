"""Big Ambitions transactions.csv izleme + Google Drive senkronizasyon scripti.

Yeni davranış:
- Drive üzerinde `big ambitions` adlı kök klasörü garanti edilir.
- Gün değerine göre 60 günlük dönem klasörleri (1-60, 61-120, ...) oluşturulur.
- transactions.csv değiştiğinde ilgili dönem klasörüne transactionsgun_<gun>.csv yüklenir.
- Her dönem klasöründe `main.xlsx` üretilir (Excel SUMIF formülleri ile tip bazlı toplam).
- Kök klasörde `main_total.xlsx` üretilir (tüm dönemlerin toplamı, yine Excel formülleri).
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
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional
from tkinter import filedialog, messagebox

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
SCOPES = ["https://www.googleapis.com/auth/drive"]


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
        safe_name = file_name.replace("'", "\\'")
        query_parts = [f"name = '{safe_name}'", "trashed = false"]
        if self.folder_id:
            query_parts.append(f"'{self.folder_id}' in parents")
        query = " and ".join(query_parts)

        response = (
            self.service.files()
            .list(q=query, **self._list_kwargs)
            .execute()
        )
        files = response.get("files", [])
        return files[0]["id"] if files else None

    def upload_or_update(self, csv_bytes: bytes, drive_name: str) -> str:
        existing_id = self._find_existing_file_id(drive_name)
        media = MediaInMemoryUpload(csv_bytes, mimetype="text/csv", resumable=False)

        if existing_id:
            self.service.files().update(
                fileId=existing_id,
                media_body=media,
                supportsAllDrives=True,
            ).execute()
            return f"Updated: {drive_name} (id={existing_id})"

        metadata = {"name": drive_name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]

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
        return f"Created: {drive_name} (id={created.get('id')})"


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
            result = self.uploader.upload_or_update(csv_bytes, drive_name)
            self.logger(f"[DRIVE] {result}")
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

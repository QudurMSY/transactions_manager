"""Big Ambitions transactions.csv izleme + Google Drive senkronizasyon scripti.

Bu script şunları yapar:
1) Big Ambitions süreci açık mı kontrol eder.
2) SaveGames altında en güncel sürüm + en güncel save klasörünü dinamik bulur.
3) transactions.csv değişince dosya yazımı bitsin diye kısa bekler.
4) CSV'den ilk veri satırının B sütunundaki (index=1) gün bilgisini okur.
5) Dosyayı transactionsgun_<gun>.csv adıyla Google Drive'a create/update eder.

Önemli:
- Service Account JSON dosyası varsayılan olarak script ile aynı klasörde
  service_account_credentials.json adıyla beklenir.

Opsiyonel environment variable'lar:
- SERVICE_ACCOUNT_FILE
- GDRIVE_FOLDER_ID
- GAME_PROCESS_NAMES (varsayılan: BigAmbitions.exe,UnityPlayer.exe)
"""

from __future__ import annotations

import argparse
import csv
import os
import shutil
import tempfile
import time
import tkinter as tk
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from tkinter import filedialog, messagebox

import psutil
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

SCOPES = ["https://www.googleapis.com/auth/drive.file"]


@dataclass
class Config:
    savegames_root: Path
    service_account_file: Path
    drive_folder_id: Optional[str]
    process_names: tuple[str, ...]
    poll_seconds: int = 15
    file_settle_seconds: int = 10


class DriveUploader:
    """Service Account ile Drive create/update."""

    def __init__(self, service_account_file: Path, folder_id: Optional[str] = None) -> None:
        self.folder_id = folder_id
        credentials = service_account.Credentials.from_service_account_file(
            str(service_account_file), scopes=SCOPES
        )
        self.service = build("drive", "v3", credentials=credentials, cache_discovery=False)

    def _find_existing_file_id(self, file_name: str) -> Optional[str]:
        safe_name = file_name.replace("'", "\\'")
        query_parts = [f"name = '{safe_name}'", "trashed = false"]
        if self.folder_id:
            query_parts.append(f"'{self.folder_id}' in parents")
        query = " and ".join(query_parts)

        response = (
            self.service.files()
            .list(q=query, spaces="drive", fields="files(id, name)", pageSize=1)
            .execute()
        )
        files = response.get("files", [])
        return files[0]["id"] if files else None

    def upload_or_update(self, local_file: Path, drive_name: str) -> str:
        media = MediaFileUpload(str(local_file), mimetype="text/csv", resumable=False)
        existing_id = self._find_existing_file_id(drive_name)

        if existing_id:
            self.service.files().update(fileId=existing_id, media_body=media).execute()
            return f"Updated: {drive_name} (id={existing_id})"

        metadata = {"name": drive_name}
        if self.folder_id:
            metadata["parents"] = [self.folder_id]

        created = self.service.files().create(body=metadata, media_body=media, fields="id").execute()
        return f"Created: {drive_name} (id={created.get('id')})"


class TransactionsHandler(FileSystemEventHandler):
    """Sadece transactions.csv modified event'ini işler."""

    def __init__(self, uploader: DriveUploader, settle_seconds: int = 10) -> None:
        self.uploader = uploader
        self.settle_seconds = settle_seconds
        self._last_uploaded_day: Optional[str] = None
        self._last_uploaded_mtime: Optional[float] = None

    def on_modified(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return

        changed_file = Path(event.src_path)
        if changed_file.name.lower() != "transactions.csv":
            return

        try:
            print(f"[WATCHDOG] Değişim algılandı: {changed_file}")
            time.sleep(self.settle_seconds)

            # Aynı mtime için duplicate event'leri atla.
            file_mtime = changed_file.stat().st_mtime
            day_value = self._extract_day_from_csv(changed_file)
            if day_value is None:
                print("[WARN] B sütunu (gün) okunamadı, upload atlandı.")
                return

            if self._last_uploaded_day == day_value and self._last_uploaded_mtime == file_mtime:
                print("[INFO] Duplicate event atlandı.")
                return

            drive_name = f"transactionsgun_{day_value}.csv"
            tmp_file = self._prepare_named_copy(changed_file, drive_name)
            try:
                result = self.uploader.upload_or_update(tmp_file, drive_name)
                print(f"[DRIVE] {result}")
                self._last_uploaded_day = day_value
                self._last_uploaded_mtime = file_mtime
            finally:
                tmp_file.unlink(missing_ok=True)
        except Exception as exc:
            print(f"[ERROR] transactions.csv işleme hatası: {exc}")

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
    def _prepare_named_copy(source_file: Path, target_name: str) -> Path:
        target_path = Path(tempfile.gettempdir()) / target_name
        shutil.copy2(source_file, target_path)
        return target_path


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
    service_account_file = Path(
        os.getenv("SERVICE_ACCOUNT_FILE", str(script_dir / "service_account_credentials.json"))
    )
    folder_id = os.getenv("GDRIVE_FOLDER_ID") or None
    names = os.getenv("GAME_PROCESS_NAMES", "BigAmbitions.exe,UnityPlayer.exe")
    process_names = tuple(n.strip() for n in names.split(",") if n.strip())

    return Config(
        savegames_root=savegames_root,
        service_account_file=service_account_file,
        drive_folder_id=folder_id,
        process_names=process_names,
    )


def preflight(config: Config) -> list[str]:
    errors: list[str] = []
    if os.name != "nt":
        errors.append("Bu script Windows path varsayımıyla yazıldı (os.name != 'nt').")
    if not config.savegames_root.exists():
        errors.append(f"SaveGames klasörü bulunamadı: {config.savegames_root}")
    if not config.service_account_file.exists():
        errors.append(
            f"Service account dosyası yok: {config.service_account_file} "
            "(service_account_credentials.json ekleyin veya SERVICE_ACCOUNT_FILE ayarlayın)"
        )
    if not config.process_names:
        errors.append("GAME_PROCESS_NAMES boş olamaz.")
    return errors


def run_loop(config: Config) -> None:
    uploader = DriveUploader(config.service_account_file, config.drive_folder_id)

    observer: Optional[Observer] = None
    watched_folder: Optional[Path] = None

    print("[INFO] Otomasyon başladı. Oyun süreci izleniyor...")
    while True:
        try:
            running = is_game_running(config.process_names)
            if running:
                latest_folder = find_latest_save_folder(config.savegames_root)
                if latest_folder is None:
                    print("[WARN] En güncel save klasörü bulunamadı.")
                else:
                    transactions = latest_folder / "transactions.csv"
                    if not transactions.exists():
                        print(f"[WARN] transactions.csv yok: {transactions}")
                    elif observer is None:
                        handler = TransactionsHandler(uploader, config.file_settle_seconds)
                        observer = Observer()
                        observer.schedule(handler, str(latest_folder), recursive=False)
                        observer.start()
                        watched_folder = latest_folder
                        print(f"[INFO] İzleme başladı: {latest_folder}")
                    elif watched_folder != latest_folder:
                        observer.stop()
                        observer.join(timeout=5)
                        handler = TransactionsHandler(uploader, config.file_settle_seconds)
                        observer = Observer()
                        observer.schedule(handler, str(latest_folder), recursive=False)
                        observer.start()
                        watched_folder = latest_folder
                        print(f"[INFO] İzlenen klasör güncellendi: {latest_folder}")
            else:
                if observer is not None:
                    print("[INFO] Oyun kapalı, izleme durduruldu.")
                    observer.stop()
                    observer.join(timeout=5)
                    observer = None
                    watched_folder = None

            time.sleep(config.poll_seconds)
        except KeyboardInterrupt:
            print("[INFO] Çıkış sinyali alındı.")
            break
        except Exception as exc:
            print(f"[ERROR] Ana döngü hatası: {exc}")
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


def launch_config_gui(default_config: Config) -> Optional[Config]:
    """Kullanıcıdan gerekli ayarları alır. İptal edilirse None döner."""
    result: dict[str, Config | None] = {"config": None}

    root = tk.Tk()
    root.title("Big Ambitions Drive Sync - Ayarlar")
    root.resizable(False, False)

    savegames_var = tk.StringVar(value=str(default_config.savegames_root))
    service_account_var = tk.StringVar(value=str(default_config.service_account_file))
    folder_id_var = tk.StringVar(value=default_config.drive_folder_id or "")
    process_var = tk.StringVar(value=",".join(default_config.process_names))
    poll_var = tk.StringVar(value=str(default_config.poll_seconds))
    settle_var = tk.StringVar(value=str(default_config.file_settle_seconds))

    def browse_savegames() -> None:
        selected = filedialog.askdirectory(title="SaveGames klasörünü seç")
        if selected:
            savegames_var.set(selected)

    def browse_service_account() -> None:
        selected = filedialog.askopenfilename(
            title="Service account JSON seç",
            filetypes=[("JSON files", "*.json"), ("All files", "*.*")],
        )
        if selected:
            service_account_var.set(selected)

    def on_start() -> None:
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
                service_account_file=Path(service_account_var.get().strip()),
                drive_folder_id=folder_id_var.get().strip() or None,
                process_names=process_names,
                poll_seconds=poll_seconds,
                file_settle_seconds=settle_seconds,
            )

            errors = preflight(cfg)
            if errors:
                messagebox.showerror("Ayar Hatası", "\n".join(errors))
                return

            result["config"] = cfg
            root.destroy()
        except ValueError as exc:
            messagebox.showerror("Ayar Hatası", str(exc))

    def on_cancel() -> None:
        root.destroy()

    row = 0
    tk.Label(root, text="SaveGames klasörü").grid(row=row, column=0, sticky="w", padx=8, pady=6)
    tk.Entry(root, width=60, textvariable=savegames_var).grid(row=row, column=1, padx=8, pady=6)
    tk.Button(root, text="Seç", command=browse_savegames).grid(row=row, column=2, padx=8, pady=6)

    row += 1
    tk.Label(root, text="Service Account JSON").grid(row=row, column=0, sticky="w", padx=8, pady=6)
    tk.Entry(root, width=60, textvariable=service_account_var).grid(row=row, column=1, padx=8, pady=6)
    tk.Button(root, text="Seç", command=browse_service_account).grid(row=row, column=2, padx=8, pady=6)

    row += 1
    tk.Label(root, text="Drive Folder ID (opsiyonel)").grid(row=row, column=0, sticky="w", padx=8, pady=6)
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
    tk.Button(root, text="Başlat", command=on_start, width=18).grid(row=row, column=1, sticky="w", padx=8, pady=12)
    tk.Button(root, text="İptal", command=on_cancel, width=12).grid(row=row, column=1, sticky="e", padx=8, pady=12)

    root.protocol("WM_DELETE_WINDOW", on_cancel)
    root.mainloop()
    built = result["config"]
    return built if isinstance(built, Config) else None


def main() -> None:
    args = parse_args()
    default_config = build_default_config()

    if args.no_gui:
        config = default_config
    else:
        config = launch_config_gui(default_config)
        if config is None:
            print("[INFO] Kullanıcı GUI üzerinden işlemi iptal etti.")
            return

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


if __name__ == "__main__":
    main()

# Big Ambitions Drive Sync

## Türkçe

Bu araç, Big Ambitions `transactions.csv` dosyasını izleyip Google Drive'da otomatik klasörler ve Excel raporları üretir.

### Klasör / rapor yapısı

Drive'da otomatik olarak:
- `big ambitions/` kök klasörü oluşturulur
- Gün değerine göre dönem klasörü açılır:
  - `1-60`, `61-120`, `121-180`, ...
- Her dönemde:
  - `transactionsgun_<gun>.csv`
  - `main.xlsx` (C sütunundaki type ve D sütunundaki value için Excel `SUMIF` özeti)
- Kökte:
  - `main_total.xlsx` (tüm dönemlerin toplam özeti)

> Hesaplamalar Python'da toplanmaz; Excel dosyaları içine formül olarak yazılır.

### Kurulum

```bash
pip install -r requirements.txt
```

### Çalıştırma

#### GUI ile (önerilen)
```bash
python big_ambitions_drive_sync.py
```

#### GUI olmadan
```bash
python big_ambitions_drive_sync.py --no-gui
```

#### Sadece ön kontrol
```bash
python big_ambitions_drive_sync.py --doctor --no-gui
```

### Gerekli dosya
- `service_account_credentials.json` (varsayılan olarak script ile aynı klasörde)
- veya `SERVICE_ACCOUNT_FILE` env ile farklı yol verilebilir.

### Notlar
- Oyun açıkken watcher aktif olur, kapanınca durur.
- Programı istediğin gün başlatıp durdurabilirsin; sadece var olan CSV dosyaları üzerinden rapor oluşturulur.
- Harcama tiplerini hardcode etmeye gerek yok; dosyalardan dinamik toplanır.

---

## English

This tool watches Big Ambitions `transactions.csv` and automatically creates Google Drive folders and Excel reports.

### Folder / report structure

On Drive, it automatically creates:
- a root folder: `big ambitions/`
- 60-day period folders by in-game day:
  - `1-60`, `61-120`, `121-180`, ...
- in each period folder:
  - `transactionsgun_<day>.csv`
  - `main.xlsx` (Excel `SUMIF` summary using type in column C and value in column D)
- in root:
  - `main_total.xlsx` (overall summary across all period folders)

> Calculations are not aggregated in Python; formulas are written into Excel files.

### Installation

```bash
pip install -r requirements.txt
```

### Run

#### With GUI (recommended)
```bash
python big_ambitions_drive_sync.py
```

#### Without GUI
```bash
python big_ambitions_drive_sync.py --no-gui
```

#### Pre-check only
```bash
python big_ambitions_drive_sync.py --doctor --no-gui
```

### Required file
- `service_account_credentials.json` (default: same folder as script)
- or set a custom path using `SERVICE_ACCOUNT_FILE` environment variable.

### Notes
- Watcher starts when the game process is running and stops when it closes.
- You can start/stop the program at any time; reports are built from existing CSV files only.
- Expense types are detected dynamically from data; no hardcoding required.

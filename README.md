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

### Service Account JSON nasıl hazırlanır? (Google Cloud temel anlatım)

Bu proje kullanıcı girişi (OAuth popup) açmaz. Bu yüzden bir **Service Account JSON key** gerekir.

1. **Google Cloud Console** aç: https://console.cloud.google.com/
2. Üstten bir **Project** seç veya yeni bir proje oluştur.
3. Sol menüden **APIs & Services > Library** bölümüne gir, **Google Drive API** ara ve **Enable** et.
4. Sol menüden **APIs & Services > Credentials** bölümüne gir.
5. **Create Credentials > Service account** seç.
6. Service account adı ver (ör. `big-ambitions-sync`) ve oluştur.
7. Oluşturduktan sonra service account içine gir, **Keys** sekmesinden:
   - **Add Key > Create new key > JSON**
   - JSON dosyasını indir.
8. İndirilen JSON'u proje klasörüne kopyala ve adını:
   - `service_account_credentials.json` yap
   - (veya farklı konum kullanacaksan `SERVICE_ACCOUNT_FILE` ortam değişkeni ayarla).

#### Drive erişim izni verme
Service account bir robot kullanıcıdır. Drive'da dosya yazabilmesi için izin gerekir:

- Drive'da kullanacağın klasörü aç.
- **Share / Paylaş** ile service account e-posta adresini ekle
  (JSON dosyasındaki `client_email`).
- En az **Editor** yetkisi ver.

> Eğer paylaşım yapılmazsa script API ile bağlansa bile hedef klasöre yazamayabilir.

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

### How to create the Service Account JSON (basic Google Cloud setup)

This project does not open an interactive OAuth login popup. It requires a **Service Account JSON key**.

1. Open **Google Cloud Console**: https://console.cloud.google.com/
2. Select a project (or create a new one).
3. Go to **APIs & Services > Library**, search for **Google Drive API**, and click **Enable**.
4. Go to **APIs & Services > Credentials**.
5. Click **Create Credentials > Service account**.
6. Give it a name (for example, `big-ambitions-sync`) and create it.
7. Open the created service account, then in **Keys** tab:
   - **Add Key > Create new key > JSON**
   - Download the JSON key file.
8. Put the downloaded file into this project folder and name it:
   - `service_account_credentials.json`
   - (or set `SERVICE_ACCOUNT_FILE` to a custom path).

#### Grant Drive access to the service account
A service account is a robot identity. It still needs permission to write into your Drive folder:

- Open the target folder in Google Drive.
- Click **Share** and add the service account email
  (`client_email` inside the JSON file).
- Grant at least **Editor** role.

> Without this sharing step, API auth may succeed but uploads to your target folder can fail.

### Notes
- Watcher starts when the game process is running and stops when it closes.
- You can start/stop the program at any time; reports are built from existing CSV files only.
- Expense types are detected dynamically from data; no hardcoding required.

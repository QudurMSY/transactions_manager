# Big Ambitions Drive Sync

Big Ambitions oyunundaki `transactions.csv` dosyasını izler, değişim oldukça dosyayı Google Drive'a yükler.

## Ne yapar?
- Oyun açıkken save klasörünü izler.
- `transactions.csv` değişince kısa süre bekler (dosya yazımı tamamlansın diye).
- CSV içinden gün (`day`) değerini okur.
- Dosyayı `transactionsgun_<gun>.csv` adıyla Drive'a yükler/günceller.

---

## Kurulum

```bash
pip install -r requirements.txt
```

---

## Google Cloud + Google Drive kurulumu (adım adım)

Bu uygulama **OAuth popup** açmaz; bunun yerine **Service Account JSON** kullanır.

### 1) Google Cloud projesi oluştur
1. https://console.cloud.google.com/ aç.
2. Sağ üstten mevcut bir proje seç veya **New Project** ile yeni bir proje oluştur.

### 2) Google Drive API'yi aç
1. Sol menü: **APIs & Services > Library**.
2. `Google Drive API` ara.
3. **Enable** tıkla.

### 3) Service Account oluştur
1. Sol menü: **APIs & Services > Credentials**.
2. **Create Credentials > Service account**.
3. Hesaba isim ver (ör. `big-ambitions-sync`) ve oluştur.

### 4) JSON key indir
1. Oluşturulan service account detayına gir.
2. **Keys** sekmesi.
3. **Add key > Create new key > JSON**.
4. İnen dosyayı projeye kopyala:
   - Varsayılan ad: `service_account_credentials.json`
   - veya farklı bir yol için `SERVICE_ACCOUNT_FILE` kullan.

### 5) Drive klasörü oluştur ve paylaş
> Önemli: Service Account'un kişisel “My Drive” kotası yoktur. Bu yüzden bir hedef klasör ID'si girmeniz gerekir.

1. Google Drive'da bir klasör aç/oluştur (ör. `BigAmbitionsSync`).
2. **Share / Paylaş** deyip service account e-postasını ekle:
   - JSON içindeki `client_email` alanı.
3. Yetkiyi en az **Editor** ver.
4. Klasör URL’sinden klasör ID’yi al:
   - `https://drive.google.com/drive/folders/<BURASI_FOLDER_ID>`

### 6) Uygulamaya Folder ID ver
Aşağıdakilerden biriyle verilebilir:
- GUI’de **Drive Folder ID** alanına yapıştır.
- veya ortam değişkeni:
  - Windows: `set GDRIVE_FOLDER_ID=...`
  - PowerShell: `$env:GDRIVE_FOLDER_ID="..."`

---

## Çalıştırma

### GUI ile (önerilen)
```bash
python big_ambitions_drive_sync.py
```

- Ayarları doldurup **Başlat** deyin.
- Uygulama artık **kendini kapatmaz/gizlemez**, pencere açık kalır.
- İzleme arka planda thread içinde devam eder.

### GUI olmadan
```bash
python big_ambitions_drive_sync.py --no-gui
```

### Sadece ön kontrol
```bash
python big_ambitions_drive_sync.py --doctor --no-gui
```

---

## Ortam değişkenleri
- `SERVICE_ACCOUNT_FILE`: JSON dosya yolu.
- `GDRIVE_FOLDER_ID`: Yükleme yapılacak Drive klasör ID’si (önerilen/zorunlu kullanım).
- `GAME_PROCESS_NAMES`: Virgülle ayrılmış process adları.

Örnek:
```bash
set SERVICE_ACCOUNT_FILE=C:\keys\service_account_credentials.json
set GDRIVE_FOLDER_ID=1AbCdEfGh...
set GAME_PROCESS_NAMES=BigAmbitions.exe,UnityPlayer.exe
python big_ambitions_drive_sync.py --no-gui
```

---

## Sık hata ve çözüm

### `HttpError 403 storageQuotaExceeded`
Sebep: Service Account ile My Drive root'a yazma denemesi.

Çözüm:
1. Drive’da bir klasör oluştur.
2. Service account e-postasına o klasörü paylaş (Editor).
3. Klasör ID’sini `GDRIVE_FOLDER_ID` olarak ver.

### `Geçici dosya silinemedi (WinError 32)`
Windows'ta dosya başka process tarafından kısa süreli kilitli olabilir. Script yeniden dener; çoğu durumda kritik değildir.

---

## Notlar
- Script Windows path yapısına göre yazılmıştır.
- Oyun süreci kapanınca izleme durur, açılınca tekrar başlar.
- Aynı dosya değişimi için duplicate event filtreleme yapılır.

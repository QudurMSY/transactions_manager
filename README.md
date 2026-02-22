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
> Önemli: Service Account'un kişisel “My Drive” kotası yoktur. **Hedef klasörün Shared Drive içinde olması gerekir**; kullanıcıların kişisel My Drive klasörleri genelde `storageQuotaExceeded` üretir.

1. Google Drive'da bir klasör aç/oluştur (ör. `BigAmbitionsSync`).
2. **Shared Drive** içinde klasör aç (önerilen) veya mevcut Shared Drive klasörü seç.
3. Service account e-postasını ekle:
   - JSON içindeki `client_email` alanı.
4. Yetkiyi en az **Content manager** (veya Manager) ver.
5. Klasör URL’sinden klasör ID’yi al:
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
set GAME_PROCESS_NAMES=Big Ambitions.exe,Big_Ambitions.exe,BigAmbitions.exe,UnityPlayer.exe
python big_ambitions_drive_sync.py --no-gui
```

---

## Sık hata ve çözüm


### Olası hata senaryoları (hızlı checklist)
1. `GDRIVE_FOLDER_ID` boş/yanlış (`.`, `root`, kısa değer, klasör adı girme)
2. Verilen ID erişilebilir değil (404 notFound)
3. Klasör kişisel My Drive'da (403 storageQuotaExceeded)
4. Service account e-postası klasöre/Shared Drive'a eklenmemiş
5. Yetki yetersiz (viewer/commenter ise upload yapılamaz)
6. Drive API projede kapalı
7. Yanlış service account JSON dosyası kullanılıyor
8. `transactions.csv` oyun tarafından kilitli (WinError 32 / EACCES)
9. CSV formatı bozuk, gün sütunu (B) okunamıyor
10. Oyun process adı farklı olduğu için izleme başlamıyor


### Log seviyeleri ne anlama geliyor?
- `[INFO]`: Normal durum bilgisi (izleme başlatıldı/durduruldu, duplicate event atlandı vb.).
- `[WATCHDOG]`: Dosya sistemi değişimi algılandı (`transactions.csv` update event'i geldi).
- `[DRIVE]`: Google Drive upload/update başarılı.
- `[WARN]`: Geçici/iyileştirilebilir durum (dosya kilidi, klasör bulunamaması, gün değeri okunamaması vb.).
- `[ERROR]`: İşlem hatası (Drive API veya beklenmeyen runtime hatası).

### `[ERROR] ... Drive 403 storageQuotaExceeded`
Sebep: Service Account hesabının kişisel **My Drive** depolama alanı yoktur. Hedef klasör kişisel My Drive altındaysa (ID doğru olsa bile) dosya oluşturma sırasında 403 gelebilir.

Çözüm (adım adım):
1. Google Drive'da bir **Shared Drive** içinde hedef klasör açın.
2. `service_account_credentials.json` içindeki `client_email` adresini Shared Drive'a **Content manager** veya **Manager** olarak ekleyin.
3. Klasör URL'sinden yalnızca ID'yi kopyalayın:
   - `https://drive.google.com/drive/folders/<BURASI_FOLDER_ID>`
4. Bu ID'yi uygulamaya verin:
   - GUI: **Drive Folder ID**
   - veya ortam değişkeni: `GDRIVE_FOLDER_ID=<BURASI_FOLDER_ID>`
5. Uygulama başlangıcında çıkan `Drive hedef kontrolü: Doğrulandı ...` satırını kontrol edin.

İpucu: `.`, `root`, kısa/eksik ID ya da klasör adı (ID yerine) kullanmayın.
Windows'ta `set GDRIVE_FOLDER_ID=...` sadece açtığınız mevcut CMD oturumunda geçerlidir; scripti başka yerden (ör. çift tık) başlatırsanız değişken taşınmayabilir.

### `WinError 32` (dosya kullanımda)
Bu hata/uyarı genelde Windows'ta oyun dosyayı o anda yazarken oluşur. Yeni sürümde temp dosya yerine bellekten upload yapıldığı için kilit kaynaklı yan etkiler azaldı, ancak kaynak `transactions.csv` kilitliyse script kısa aralıklarla tekrar dener.

### `HTTP 404: File not found: .` / `location: fileId`
Sebep: **Drive Folder ID** alanına geçersiz değer (ör. `.`, `GDRIVE_FOLDER_ID`, `Drive Folder ID`) girilmiştir veya URL yanlış kopyalanmıştır.

Not: ID doğru görünse bile, Service Account klasöre/Shared Drive'a ekli değilse Google Drive API bazen güvenlik nedeniyle yine `404 notFound` döndürebilir.
Aynı durum, klasöre eklediğiniz hesapla **farklı bir service account JSON** dosyası kullandığınızda da görülür (örn. benzer isimli ama başka `client_email`).

Çözüm:
1. Google Drive klasörünüzü açın.
2. URL'den yalnızca klasör ID kısmını alın:
   - `https://drive.google.com/drive/folders/<BURASI_FOLDER_ID>`
3. Uygulamadaki **Drive Folder ID** alanına yalnızca bu ID'yi girin.
4. Klasörün service account e-postası ile paylaşıldığını kontrol edin.

---

## Notlar
- Script Windows path yapısına göre yazılmıştır.
- Oyun süreci kapanınca izleme durur, açılınca tekrar başlar.
- Aynı dosya değişimi için duplicate event filtreleme yapılır.

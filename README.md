# Big Ambitions Drive Sync

Big Ambitions oyunundaki `transactions.csv` dosyasını izler, değişim oldukça dosyayı Google Drive'a yükler.

## Ne yapar?
- Oyun açıkken save klasörünü izler.
- `transactions.csv` değişince kısa süre bekler (dosya yazımı tamamlansın diye).
- CSV içinden gün (`day`) değerini okur.
- Dosyayı `transactionsgun_<gun>.csv` adıyla Drive'a yükler/günceller.

---

## 1) Kurulum

### 1.1 Python paketlerini yükle
```bash
pip install -r requirements.txt
```

### 1.2 Script dosyaları
Aynı klasörde şunlar olmalı:
- `big_ambitions_drive_sync.py`
- `requirements.txt`
- (birazdan oluşturacağınız) OAuth JSON dosyası

---

## 2) OAuth kurulumunu adım adım yap (kişisel Google hesabı)

> Bu proje artık **sadece kişisel Google hesabı + OAuth** destekler. Service Account kullanılmaz.

Aşağıdaki adımları sırayla yapın:

### 2.1 Google Cloud projesi oluştur
1. Tarayıcıdan `https://console.cloud.google.com/` açın.
2. Üstteki proje seçicisinden:
   - yeni proje oluşturun (**New Project**) veya
   - mevcut bir projeyi seçin.

### 2.2 Google Drive API’yi aç
1. Sol menü: **APIs & Services > Library**
2. Arama kutusuna `Google Drive API` yazın.
3. **Enable** (Etkinleştir) butonuna basın.

### 2.3 OAuth consent screen ayarla
1. Sol menü: **APIs & Services > OAuth consent screen**
2. User Type seçin:
   - kişisel hesap kullanıyorsanız genelde **External**
3. Gerekli alanları doldurun (App name, User support email, Developer contact email).
4. Kaydedin.

### 2.4 OAuth Client ID oluştur
1. Sol menü: **APIs & Services > Credentials**
2. **Create Credentials > OAuth client ID**
3. Application type: **Desktop app**
4. Bir isim verin (ör. `big-ambitions-desktop`)
5. Create deyin ve oluşan JSON’u indirin.

### 2.5 JSON dosyasını projeye koy
İndirdiğiniz dosyayı proje klasörüne kopyalayın ve şu isimlerden biriyle kullanın:
- `oauth_client_credentials.json` (**önerilen**)
- veya `credentials.json`

> Alternatif: Dosya başka klasördeyse `GOOGLE_CREDENTIALS_FILE` ile tam yol verebilirsiniz.

---

## 3) Drive klasörünü bağlama (folder ID alma) adım adım

Bu adım çok önemli. İsterseniz belirli bir klasöre, isterseniz Drive root’a yükleyebilirsiniz.

### Seçenek A — Belirli bir klasöre yükle (önerilen)
1. Google Drive’da bir klasör oluşturun (ör. `BigAmbitionsSync`).
2. Klasöre girin, tarayıcı adres çubuğunu kopyalayın.
3. URL örneği:
   - `https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQr...`
4. Buradaki `1AbCdEfGhIjKlMnOpQr...` kısmı **Folder ID**’dir.
5. Bu ID’yi GUI’de **Drive Folder ID** alanına yapıştırın
   - veya `GDRIVE_FOLDER_ID` env var olarak verin.

### Seçenek B — Drive root’a yükle
- `GDRIVE_FOLDER_ID` vermeyin (boş bırakın).
- Dosyalar hesabınızın ana Drive alanına gider.

---

## 4) İlk çalıştırma ve hesap doğrulama

İlk kez çalıştırdığınızda OAuth akışı devreye girer:

1. Scripti başlatın.
2. Tarayıcı açılır ve Google hesabı seçmeniz istenir.
3. Drive erişim iznini onaylayın.
4. Onay sonrası script klasöründe `token.json` oluşur.
5. Sonraki çalıştırmalarda tekrar giriş istemez (token geçerliyse).

---

## 5) Çalıştırma

### 5.1 GUI ile (kolay yöntem)
```bash
python big_ambitions_drive_sync.py
```

GUI’de doldurmanız gerekenler:
- **SaveGames klasörü**
- **OAuth Credentials JSON**
- **Drive Folder ID** (opsiyonel)
- Process adları (gerekirse)
- Alt bölümdeki **Canlı log** kutusunda `[INFO]/[WARN]/[ERROR]` mesajlarını anlık görebilirsiniz.

### 5.2 GUI olmadan
```bash
python big_ambitions_drive_sync.py --no-gui
```

### 5.3 Sadece kurulum kontrolü
```bash
python big_ambitions_drive_sync.py --doctor --no-gui
```

---

## 6) Ortam değişkenleri (Windows CMD / PowerShell)

### 6.1 Değişkenler
- `GOOGLE_CREDENTIALS_FILE`: OAuth client JSON dosya yolu
- `GOOGLE_TOKEN_FILE`: token dosya yolu (varsayılan: credentials dosyasının yanında `token.json`)
- `GDRIVE_FOLDER_ID`: hedef Drive klasör ID (opsiyonel)
- `GAME_PROCESS_NAMES`: virgülle process adları

### 6.2 Windows CMD örneği
```bat
set GOOGLE_CREDENTIALS_FILE=C:\keys\oauth_client_credentials.json
set GOOGLE_TOKEN_FILE=C:\keys\token.json
set GDRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQr
python big_ambitions_drive_sync.py --no-gui
```

### 6.3 PowerShell örneği
```powershell
$env:GOOGLE_CREDENTIALS_FILE="C:\keys\oauth_client_credentials.json"
$env:GOOGLE_TOKEN_FILE="C:\keys\token.json"
$env:GDRIVE_FOLDER_ID="1AbCdEfGhIjKlMnOpQr"
python big_ambitions_drive_sync.py --no-gui
```

---

## 7) Sık yapılan hatalar ve net çözümler

### Hata: `Google credentials dosyası yok`
**Sebep:** JSON yolu yanlış veya dosya yok.

**Çözüm:**
1. JSON dosyasının gerçekten var olduğunu kontrol edin.
2. `GOOGLE_CREDENTIALS_FILE` yolunu doğru girin.
3. Dosya adı `oauth_client_credentials.json` ise proje klasöründe olduğundan emin olun.

### Hata: `HTTP 404 fileId notFound`
**Sebep:** `GDRIVE_FOLDER_ID` yanlış, eksik, farklı hesaba ait veya erişiminiz yok.

**Çözüm:**
1. Klasörü Drive’da açın.
2. URL’den sadece `/folders/` sonrası ID’yi alın.
3. Doğru Google hesabıyla giriş yaptığınızdan emin olun.
4. Folder ID alanına klasör adını değil ID’yi yazın.

### Hata: `HTTP 403 storageQuotaExceeded`
**Sebep:** Drive kotası dolu olabilir.

**Çözüm:**
1. Google Drive depolama kullanımınızı kontrol edin.
2. Yer açın veya farklı hesapla deneyin.

### Hata: Tarayıcı açılmıyor / OAuth tamamlanmıyor
**Çözüm:**
1. Scripti normal kullanıcı haklarıyla tekrar başlatın.
2. Güvenlik duvarı/local browser kısıtlarını kontrol edin.
3. Gerekirse farklı varsayılan tarayıcı ile tekrar deneyin.

### Hata: `WinError 32`
**Sebep:** Oyun dosyayı o anda yazıyor (dosya kilidi).

**Çözüm:**
- Geçici bir durumdur; script zaten otomatik retry yapar.

---

## 8) Temiz başlangıç (reset) nasıl yapılır?
OAuth’u baştan kurmak isterseniz:
1. `token.json` dosyasını silin.
2. Scripti tekrar başlatın.
3. Tarayıcıdan hesabı yeniden seçip izin verin.

---

## Notlar
- Script Windows path yapısına göre yazılmıştır.
- Oyun kapanınca izleme durur, açılınca tekrar başlar.

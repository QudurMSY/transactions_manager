# Big Ambitions Drive Sync

Bu araç, Big Ambitions `transactions.csv` dosyasını izleyip Google Drive'da otomatik klasörler ve Excel raporları üretir.

## Yeni klasör/rapor yapısı

Drive'da otomatik olarak:
- `big ambitions/` kök klasörü oluşturulur
- Gün değerine göre dönem klasörü açılır:
  - `1-60`, `61-120`, `121-180`, ...
- Her dönemde:
  - `transactionsgun_<gun>.csv`
  - `main.xlsx` (C sütunundaki type ve D sütunundaki value için Excel SUMIF özeti)
- Kökte:
  - `main_total.xlsx` (tüm dönemlerin toplam özeti)

> Hesaplamalar Python'da toplanmaz; Excel dosyaları içine formül olarak yazılır.

## Kurulum

```bash
pip install -r requirements.txt
```

## Çalıştırma

### GUI ile (önerilen)
```bash
python big_ambitions_drive_sync.py
```

### GUI olmadan
```bash
python big_ambitions_drive_sync.py --no-gui
```

### Sadece ön kontrol
```bash
python big_ambitions_drive_sync.py --doctor --no-gui
```

## Gerekli dosya
- `service_account_credentials.json` (varsayılan olarak script ile aynı klasörde)
- veya `SERVICE_ACCOUNT_FILE` env ile farklı yol verilebilir.

## Notlar
- Oyun açıkken watcher aktif olur, kapanınca durur.
- Programı istediğin gün başlatıp durdurabilirsin; sadece var olan CSV dosyaları üzerinden rapor oluşturulur.
- Harcama tiplerini hardcode etmeye gerek yok; dosyalardan dinamik toplanır.

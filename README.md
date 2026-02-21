## Big Ambitions Drive Sync

Tak-çalıştır'a en yakın kurulum için:

1. Bu klasöre `service_account_credentials.json` koy.
2. Paketleri kur:
   ```bash
   pip install -r requirements.txt
   ```
3. Kontrol çalıştır:
   ```bash
   python big_ambitions_drive_sync.py --doctor --no-gui
   ```
4. GUI ile ayar girip başlat:
   ```bash
   python big_ambitions_drive_sync.py
   ```

Script açıldığında kullanıcı; Service Account JSON, Drive Folder ID, process isimleri
ve bekleme sürelerini GUI üzerinden girer. "Başlat" dedikten sonra otomatik izleme başlar.

5. (Opsiyonel) GUI olmadan environment/default ayarlarla başlat:
   ```bash
   python big_ambitions_drive_sync.py --no-gui
   ```

### Opsiyonel ayarlar
- `GDRIVE_FOLDER_ID`: Yüklenecek Drive klasörü
- `SERVICE_ACCOUNT_FILE`: Credential dosya yolu
- `GAME_PROCESS_NAMES`: Virgülle ayrılmış exe isimleri

Örnek:
```bash
set GDRIVE_FOLDER_ID=1abcDEF...
python big_ambitions_drive_sync.py
```

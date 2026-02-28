# Big Ambitions Drive Sync

Monitors the `transactions.csv` file in Big Ambitions and uploads it to Google Drive whenever it changes.

## What does it do?
- Watches the save folder while the game is running.
- Waits briefly when `transactions.csv` changes (so file writing can finish).
- Reads the day (`day`) value from the CSV.
- Uploads/updates the file to Drive as `transactionsgun_<day>.csv`.

---

## 1) Setup

### 1.1 Install Python packages
```bash
pip install -r requirements.txt
```

### 1.2 Script files
The following files should be in the same folder:
- `big_ambitions_drive_sync.py`
- `requirements.txt`
- the OAuth JSON file you will create shortly

---

## 2) Step-by-step OAuth setup (personal Google account)

> This project now supports **personal Google account + OAuth only**. Service Account is not used.

Follow the steps below in order:

### 2.1 Create a Google Cloud project
1. Open `https://console.cloud.google.com/` in your browser.
2. From the project selector at the top:
   - create a new project (**New Project**) or
   - select an existing project.

### 2.2 Enable Google Drive API
1. Left menu: **APIs & Services > Library**
2. Search for `Google Drive API`.
3. Click **Enable**.

### 2.3 Configure OAuth consent screen
1. Left menu: **APIs & Services > OAuth consent screen**
2. Select User Type:
   - if you use a personal account, this is usually **External**
3. Fill required fields (App name, User support email, Developer contact email).
4. Save.

### 2.4 Create OAuth Client ID
1. Left menu: **APIs & Services > Credentials**
2. **Create Credentials > OAuth client ID**
3. Application type: **Desktop app**
4. Give it a name (e.g. `big-ambitions-desktop`)
5. Click Create and download the generated JSON.

### 2.5 Put JSON file into the project
Copy the downloaded file into the project folder and use one of these names:
- `oauth_client_credentials.json` (**recommended**)
- or `credentials.json`

> Alternative: If the file is in another folder, you can provide its full path with `GOOGLE_CREDENTIALS_FILE`.

---

## 3) Connect Drive folder (how to get folder ID), step by step

This step is very important. You can upload either to a specific folder or to Drive root.

### Option A — Upload to a specific folder (recommended)
1. Create a folder in Google Drive (e.g. `BigAmbitionsSync`).
2. Open the folder and copy the browser address bar URL.
3. URL example:
   - `https://drive.google.com/drive/folders/1AbCdEfGhIjKlMnOpQr...`
4. The `1AbCdEfGhIjKlMnOpQr...` part is the **Folder ID**.
5. Paste this ID into **Drive Folder ID** in the GUI
   - or set it via `GDRIVE_FOLDER_ID` environment variable.

### Option B — Upload to Drive root
- Do not provide `GDRIVE_FOLDER_ID` (leave empty).
- Files will be uploaded to your account’s main Drive area.

---

## 4) First run and account authentication

When you run it for the first time, OAuth flow starts:

1. Start the script.
2. A browser opens and asks you to choose a Google account.
3. Approve Drive access permission.
4. After approval, `token.json` is created in the script folder.
5. On later runs, it won’t ask for login again (if token is valid).

---

## 5) Running

### 5.1 With GUI (easy method)
```bash
python big_ambitions_drive_sync.py
```

Fields you should fill in the GUI:
- **SaveGames folder**
- **OAuth Credentials JSON**
- **Drive Folder ID** (optional)
- Process names (if needed)
- You can see `[INFO]/[WARN]/[ERROR]` messages live in the **Live log** box at the bottom.

### 5.2 Without GUI
```bash
python big_ambitions_drive_sync.py --no-gui
```

### 5.3 Setup check only
```bash
python big_ambitions_drive_sync.py --doctor --no-gui
```

---

## 6) Environment variables (Windows CMD / PowerShell)

### 6.1 Variables
- `GOOGLE_CREDENTIALS_FILE`: OAuth client JSON file path
- `GOOGLE_TOKEN_FILE`: token file path (default: `token.json` next to credentials file)
- `GDRIVE_FOLDER_ID`: target Drive folder ID (optional)
- `GAME_PROCESS_NAMES`: process names separated by commas

### 6.2 Windows CMD example
```bat
set GOOGLE_CREDENTIALS_FILE=C:\keys\oauth_client_credentials.json
set GOOGLE_TOKEN_FILE=C:\keys\token.json
set GDRIVE_FOLDER_ID=1AbCdEfGhIjKlMnOpQr
python big_ambitions_drive_sync.py --no-gui
```

### 6.3 PowerShell example
```powershell
$env:GOOGLE_CREDENTIALS_FILE="C:\keys\oauth_client_credentials.json"
$env:GOOGLE_TOKEN_FILE="C:\keys\token.json"
$env:GDRIVE_FOLDER_ID="1AbCdEfGhIjKlMnOpQr"
python big_ambitions_drive_sync.py --no-gui
```


---

## 7) Common errors and clear fixes

### Error: `Google credentials dosyası yok`
**Cause:** JSON path is wrong or file does not exist.

**Solution:**
1. Check that the JSON file actually exists.
2. Enter `GOOGLE_CREDENTIALS_FILE` path correctly.
3. If file name is `oauth_client_credentials.json`, make sure it is in the project folder.

### Error: `HTTP 404 fileId notFound`
**Cause:** `GDRIVE_FOLDER_ID` is wrong, incomplete, belongs to another account, or you have no access.

**Solution:**
1. Open the folder in Drive.
2. Copy only the ID after `/folders/` from the URL.
3. Make sure you are logged in with the correct Google account.
4. In Folder ID field, enter the folder ID, not the folder name.

### Error: `HTTP 403 storageQuotaExceeded`
**Cause:** Drive quota may be full.

**Solution:**
1. Check your Google Drive storage usage.
2. Free up space or try with another account.

### Error: `HTTP 403 SERVICE_DISABLED` / `Google Sheets API has not been used ...`
**Cause:** Script uses both Drive and Sheets API. This error occurs if `Google Sheets API` is disabled or has never been enabled in the related Google Cloud project.

**Solution:**
1. Check the project number in the error message (e.g. `project=723495932964`).
2. In the same project, open this page and **Enable** `Google Sheets API`:
   - `https://console.developers.google.com/apis/api/sheets.googleapis.com/overview?project=<PROJECT_ID>`
3. If needed, also verify that **Google Drive API** is Enabled.
4. If API was just enabled, wait 2–5 minutes and run the script again.
5. If old auth/session conflicts exist, delete `token.json` and re-run OAuth login.

### Error: `RefreshError: invalid_scope`
**Cause:** Existing `token.json` was generated with old/incompatible scopes, or refresh token no longer matches valid scope set because OAuth client changed.

**Solution:**
1. Delete the `token.json` file used by the script.
   - Default path: `token.json` next to credentials file
   - If you use a custom path, check `GOOGLE_TOKEN_FILE` value.
2. Verify both **Google Drive API** and **Google Sheets API** are Enabled in Google Cloud project.
3. Run the script again and re-approve OAuth permission screen in browser.
4. If multiple Google accounts are open, make sure you authorize with the correct one.

> Note: Script is now updated to automatically fall back to full OAuth flow when `invalid_scope` happens.

### Error: `Erişim engellendi ... Hata 403: access_denied`
**Cause:** OAuth consent screen is most likely in **Testing** mode and the signing account is not in test users list.

**Solution (step-by-step checklist):**
1. Open the correct project in Google Cloud Console.
2. Go to **APIs & Services > OAuth consent screen**.
3. If app status is `Testing`, add the Gmail address that will sign in under **Test users**.
4. While running script, make sure you sign in with the same Gmail account (retry in incognito if needed).
5. To clear old session/permission conflicts, delete `token.json` and sign in again.
6. If you will open the app to wider users, complete OAuth verification and set app status to `In production`.

**Developer note:**
- In `Desktop app` OAuth client, redirect URI is not entered manually; Google client handles local redirect automatically.
- The most common issue across multiple Google accounts is that the wrong account is active in browser.

### Error: Browser does not open / OAuth does not complete
**Solution:**
1. Restart script with normal user privileges.
2. Check firewall/local browser restrictions.
3. If needed, try again with a different default browser.

### Error: `WinError 32`
**Cause:** The game is writing the file at that moment (file lock).

**Solution:**
- This is temporary; script already retries automatically.

---

## 8) How to do a clean start (reset)?
If you want to re-setup OAuth from scratch:
1. Delete `token.json`.
2. Restart the script.
3. Select account again in browser and grant permission.

---

## Notes
- Script is written according to Windows path structure.
- Monitoring stops when the game closes and starts again when it reopens.

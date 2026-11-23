# Direct Google Drive archival

The archive supervisor now prefers the Drive API when all three values exist:

- `C:\Users\nemec\.config\viv-google-drive\credentials.json` — OAuth desktop client secret
- `C:\Users\nemec\.config\viv-google-drive\token.json` — user OAuth refresh token
- `VIV_GOOGLE_DRIVE_FOLDER_ID` — destination folder ID

For scheduled-task use, you can instead put the destination folder ID in
`C:\Users\nemec\.config\viv-google-drive\folder_id.txt` so it is available
without relying on a transient PowerShell environment variable.

Until those values are present, the supervisor stays on the existing G: mount
path and never deletes a D:/F: buffer without a local hash-verified receipt.

Once configured, the API path uploads each run file with resumable uploads,
checks remote size and MD5, appends a receipt to
`autonomy/learning/google_drive_api_receipts.jsonl`, and only then removes the
D:/F: temporary copies.  No service-account credential is used; the intended
credential is the Architect's user OAuth grant.

PowerShell configuration (after placing the files):

```powershell
$env:VIV_GOOGLE_DRIVE_FOLDER_ID = '<folder-id>'
```

To create `token.json` interactively once:

```powershell
& 'L:\.venv\Scripts\python.exe' 'L:\LocalCoder\workspace\autonomy\authorize_google_drive.py'
```

Or run the complete setup wizard:

```powershell
& 'L:\LocalCoder\workspace\autonomy\setup_google_drive_api.ps1'
```

It asks for the OAuth client JSON and destination folder ID, launches the
browser authorization, validates the token, and restarts the scheduled archive
supervisor.

The scheduled archive supervisor inherits this environment only if it is
registered with that variable.  Prefer setting it as a user environment
variable before restarting the scheduled task.

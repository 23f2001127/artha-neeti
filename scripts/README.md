# scripts

Maintenance scripts, run by hand or on a schedule. The application never
imports them.

## `build_brand_assets.py`

Generates every logo derivative from `assets/brand/logo.png`:

- `assets/brand/`: transparent `mark.png`, `wordmark.png` and `lockup.png`,
  used by the PDF export and the README;
- `frontend/public/brand/`: favicons (16, 32 and `.ico`), the Apple touch
  icon, 192 and 512 pixel app icons, header images and the 1200×630
  social-preview image.

The dark background of the source is keyed out, and icons are placed on a navy
tile so they stay visible on light browser chrome.

```bash
python scripts/build_brand_assets.py
```

Rerun it after changing the source logo, and commit the outputs.

## `daily_ingest.ps1`

Resumes annual-report indexing once a day on Windows. The free embedding tier
allows about 1,000 chunks a day, and the indexer skips finished work, so a
daily run gets through a large batch unattended. Output is appended to
`logs/ingest_<date>.log`.

- Exit code 0: everything is indexed.
- Exit code 2: the daily quota was reached, which is normal.
- Anything else: an error.

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts\daily_ingest.ps1
```

To schedule it just after the quota resets (about 12:45 IST):

```powershell
$action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument '-NoProfile -ExecutionPolicy Bypass -File "<repo>\scripts\daily_ingest.ps1"'
$trigger  = New-ScheduledTaskTrigger -Daily -At 12:45PM
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 2)
Register-ScheduledTask -TaskName "ArthaNeeti-DailyFilingsIngest" -Action $action -Trigger $trigger -Settings $settings
```

To stop it, run `Disable-ScheduledTask -TaskName "ArthaNeeti-DailyFilingsIngest"`.

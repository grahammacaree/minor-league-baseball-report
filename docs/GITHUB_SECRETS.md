# GitHub secrets

The daily workflow needs the same two files the local run reads from
`~/.config/mlb-report/`, supplied as repository secrets.

## `MLB_REPORT_USER_JSON`

The contents of your `user.json` — the recipient list. Paste the file verbatim:

```json
{
  "recipients": [
    { "name": "Graham MacAree", "email": "hi@grahammacaree.com" }
  ],
  "send_when_quiet": false
}
```

The workflow validates this with `json.tool` before running, so a malformed
paste fails immediately with a clear error rather than midway through a send.

## `MLB_REPORT_USER_ENV`

The contents of your `.env`. **SMTP credentials only** — this is the one thing
worth being careful about here.

The file is uploaded verbatim into this repository's CI, so anything else living
in it goes too. If you keep one shared `.env` for several projects, or symlink
this one at another project's, then an unrelated API key ends up readable by
every workflow in this repository. Give this project its own file with these
five keys and nothing else:

```
SMTP_HOST=smtp.porkbun.com
SMTP_PORT=587
SMTP_USER=mlb-report@yourdomain.com
SMTP_PASSWORD=your-password
MAIL_FROM=mlb-report@yourdomain.com
```

## Setting them

Both are set from your machine, since neither the repository nor a workflow can
create its own secrets.

```bash
# Check what is actually in the env file before it leaves your laptop.
cut -d= -f1 ~/.config/mlb-report/.env

gh secret set MLB_REPORT_USER_JSON < ~/.config/mlb-report/user.json
gh secret set MLB_REPORT_USER_ENV < ~/.config/mlb-report/.env
```

Rotating an SMTP password means setting the secret again; nothing reads through
to your local file.

## Schedule

The workflow runs at 13:00 UTC daily, early morning on the west coast, by which
point even the late Pacific Coast League games have finished. It reports on the
previous day.

To test without waiting, run it manually with the dry-run box ticked:

```bash
gh workflow run daily-digest.yml -f dry_run=true
```

## State

The season's game logs are carried between runs as the `mlb-report-history`
artifact. Trends read from that accumulated store, so if it is ever lost the
digest still works but streaks and rolling splits flatten until it refills. The
artifact is uploaded even when a run fails, since the fetched logs are worth
keeping regardless of whether the email went out.

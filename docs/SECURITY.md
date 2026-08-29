# Security

This is a public repository that holds no secrets, runs a scheduled job with
SMTP credentials, and emails a list of people. That combination sets the whole
of the problem: the credentials must never reach the repository or its logs,
and the reader list must never reach anybody, including the other readers.

## What is sensitive

Two things, and they are sensitive for different reasons.

**The SMTP credentials** are a working mail account. They live in Actions
secrets and in `~/.config/mlb-report/.env` locally, and nowhere else. Losing
them means somebody else sending mail as you.

**The reader list** is other people's email addresses, given to you for one
purpose. Losing them is not dramatic, which is exactly why it is easy to do
carelessly. Most of the care in this project is spent here.

## Where addresses could escape, and why they do not

**Into a workflow log.** Logs on a public repository are readable by anyone,
so the run counts recipients rather than naming them, and an error about a
malformed entry gives its position in the list rather than quoting it. Actions
masks the values of secrets it holds, but what would be printed here is a
fragment extracted from inside a larger secret — one address out of a JSON
document — which is not a value it knows, and would appear in full.

**Into the mail itself.** Recipients are carried in the SMTP envelope and the
message is addressed to the sender, so no reader is shown the rest of the list.
Putting the list in a `To:` header would introduce every reader to every other,
in every digest, and to anyone a morning's email was forwarded to. The header
does no delivery work; the envelope passed to `sendmail` does.

**Into the repository.** `user.json` and `.env` live in the config home rather
than the working tree, and `.env` and `data/` are gitignored against strays.
Adding a reader therefore never touches a secret, and never touches a commit.

## Where credentials could escape, and why they do not

**Through a fork.** `ci.yml` is triggered by `pull_request`, not
`pull_request_target`, and requests no secrets. A stranger's branch runs in a
job that has nothing to steal. Only `daily-digest.yml` sees the credentials,
and it runs on a schedule or on manual dispatch, both of which require write
access.

**Through a dependency.** The daily job installs nothing: the digest uses the
standard library alone, which is why Playwright is confined to the twice-yearly
ranking capture. The two third-party actions are pinned to commit SHAs rather
than movable tags, one because it runs in the job holding the credentials and
one because it runs in a job that can write to the repository.

**Through a dispatch input.** Workflow inputs reach the shell through the
environment rather than being interpolated into the script, so a dispatched
value is an argument rather than more of the command. Dispatch already requires
write access, so this guards against a mistake rather than an intruder.

**Through the secret itself.** `MLB_REPORT_USER_ENV` uploads every line of
whatever file it is given. A shared or symlinked `.env` therefore hands
unrelated API keys to the repository along with the SMTP settings. Give it a
file containing only what the digest needs, and check it before setting it:

```bash
cut -d= -f1 ~/.config/mlb-report/.env
```

## What is deliberately public

The digest itself and everything behind it. Prospect rankings, game logs, park
factors and the play-by-play cache are all derived from public MLB endpoints,
so the run summary, the workflow logs and the `mlb-report-history` artifact can
all be read by anyone without anything being given away.

## Reporting something

Open an issue for anything that does not itself disclose a credential. For
anything that does, email the address on the commits in this repository rather
than filing it publicly.

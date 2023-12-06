# aws-profile-switch

`awsp`: switch AWS profiles from the terminal by typing a few letters, with recently used profiles first and `aws sso login` run only when the session actually needs it.

**Status: first working version (0.1.0).** Fuzzy matching, switching the profile in the current shell (bash and zsh), recent-first ordering and the SSO session check all work and are tested. The fish integration is written but has not been run yet. The SSO login path has been tested with a stand-in for the AWS CLI, not against a real IAM Identity Center login.

```text
$ awsp readonly
awsp: profile -> prod-readonly
$ echo $AWS_PROFILE
prod-readonly
```

## Install

```bash
pip install git+https://github.com/narayana006/aws-profile-switch
```

Python 3.10 or newer, no dependencies. Then load the shell integration (this is what lets `awsp` change the profile of the shell you are in):

```bash
# ~/.bashrc
eval "$(awsp --init bash)"

# ~/.zshrc
eval "$(awsp --init zsh)"

# ~/.config/fish/config.fish  (untested, see Limitations)
command awsp --init fish | source
```

SSO login needs the AWS CLI v2 (`aws`) on your `PATH`. Everything else works without it.

## Quick start with the example config

You can try it without touching your own `~/.aws`. From a clone of this repository, in zsh:

```bash
export AWS_CONFIG_FILE=$PWD/examples/config
export AWS_SHARED_CREDENTIALS_FILE=$PWD/examples/credentials
export AWSP_STATE_DIR=/tmp/awsp-demo/state
export AWSP_SSO_CACHE_DIR=/tmp/awsp-demo/sso
python examples/make_demo_token.py /tmp/awsp-demo/sso   # fake token so SSO profiles look logged in
eval "$(awsp --init zsh)"
```

The session below is real output from those example files (a made-up config and a fake token file; no AWS call is made at any point):

```text
$ awsp
   PROFILE        TYPE     SSO SESSION          LAST USED
   ci-deployer    keys     -                    never
   default        other    -                    never
   dev-admin      sso      valid (7h 59m left)  never
   prod-admin     sso      valid (7h 59m left)  never
   prod-audit     role     valid (7h 59m left)  never
   prod-readonly  sso      valid (7h 59m left)  never
   sandbox        process  -                    never
   staging-admin  sso      valid (7h 59m left)  never
$ awsp readonly
awsp: profile -> prod-readonly
$ echo $AWS_PROFILE
prod-readonly
$ awsp prod-a
awsp: 'prod-a' matches several profiles equally; type a little more:
  prod-admin
  prod-audit
$ awsp audit
awsp: profile -> prod-audit
$ awsp ci
awsp: profile -> ci-deployer
$ awsp prod-a
awsp: profile -> prod-audit
$ awsp
   PROFILE        TYPE     SSO SESSION          LAST USED
*  prod-audit     role     valid (7h 59m left)  0s ago
   ci-deployer    keys     -                    0s ago
   prod-readonly  sso      valid (7h 59m left)  2s ago
   default        other    -                    never
   dev-admin      sso      valid (7h 59m left)  never
   prod-admin     sso      valid (7h 59m left)  never
   sandbox        process  -                    never
   staging-admin  sso      valid (7h 59m left)  never
$ awsp --unset; echo ${AWS_PROFILE:-unset}
unset
```

Note the second `awsp prod-a`: the first time it was ambiguous, but after `prod-audit` had been used, recency broke the tie.

## Usage

| Command | What it does |
| --- | --- |
| `awsp` | List all profiles, most recently used first. `*` marks the current `AWS_PROFILE`. |
| `awsp QUERY` | Switch to the best match for `QUERY` and export `AWS_PROFILE` in this shell. |
| `awsp --list QUERY` (`-l`) | Show what `QUERY` matches, best first, without switching. |
| `awsp --unset` (`-u`) | Unset `AWS_PROFILE` in this shell. |
| `awsp --login QUERY` | Switch and run `aws sso login` even if the session looks valid. |
| `awsp --no-login QUERY` | Switch without ever running `aws sso login`. |
| `awsp --init bash\|zsh\|fish` | Print the shell integration. |

Exit status: `0` switched (or listed), `1` error or failed login, `2` no match or an ambiguous match.

### How matching works

Each word of the query must match the profile name, ignoring case. Matches are ranked:

1. the whole name (`prod-readonly`)
2. a prefix (`prod`)
3. the start of a word inside the name, after `-`, `_`, `.`, `/` or `:` (`readonly`)
4. any substring (`only`)
5. letters in order with gaps (`prdro`)

Within the same rank, the most recently used profile wins. If the best two candidates are in the same rank and neither has been used more recently than the other, `awsp` does not guess: it lists the candidates and exits with status 2. An exact name always wins.

### How the SSO check works

For a profile that uses IAM Identity Center (`sso_session` or the older `sso_start_url`), or a role profile whose `source_profile` chain leads to one, `awsp` looks at the token file that `aws sso login` writes under `~/.aws/sso/cache/`. It only reads the expiry fields.

| Token file | SSO SESSION column | Action on switch |
| --- | --- | --- |
| access token not yet expired | `valid (time left)` | none |
| access token expired, refresh token present and client registration not expired | `expired, refreshable` | none; the AWS CLI and SDKs renew it on next use |
| access token expired, nothing to refresh with | `expired` | runs `aws sso login --profile <sso profile>` |
| no token file | `not logged in` | runs `aws sso login --profile <sso profile>` |

If the login command fails, the profile is not switched. Profiles that do not use SSO never trigger a login.

Real output with the example config and an empty token cache (in this run `aws` was deliberately not on `PATH`, so no login was attempted):

```text
$ awsp --no-login dev
awsp: SSO session for 'dev-admin' is not logged in (login skipped)
awsp: profile -> dev-admin
$ awsp stag
awsp: SSO session for 'staging-admin' is not logged in; running aws sso login
awsp: the `aws` command was not found; install AWS CLI v2 to log in
awsp: aws sso login failed (exit 127); profile not switched
```

### Files and environment variables

| What | Default | Override |
| --- | --- | --- |
| AWS config (read only) | `~/.aws/config` | `AWS_CONFIG_FILE` |
| AWS credentials (read only, section names only) | `~/.aws/credentials` | `AWS_SHARED_CREDENTIALS_FILE` |
| SSO token cache (read only) | `~/.aws/sso/cache` | `AWSP_SSO_CACHE_DIR` |
| Last-used history (written) | `~/.local/state/aws-profile-switch/history.json` | `AWSP_STATE_DIR`, or `XDG_STATE_HOME` |

`awsp` never writes to your AWS files and never prints or stores keys or tokens. The history file contains profile names and timestamps only.

### Why a shell function is needed

A program cannot change the environment of the shell that launched it. `awsp --init` therefore defines a small shell function, also called `awsp`, that runs the real program and evaluates the single `export AWS_PROFILE=...` line it prints. Without the function, `awsp QUERY` prints that line and tells you the integration is not loaded.

## IAM permissions

None. `awsp` itself makes no AWS API calls; it reads local files. `aws sso login`, when it runs, opens the normal IAM Identity Center sign-in.

## Features

- [x] Fuzzy search over profiles in your AWS config
- [x] Exports the profile into the current shell
- [x] Runs SSO login only when the session has expired
- [x] Shows the last-used profiles first
- [ ] Works in bash, zsh and fish (bash and zsh work and are tested in real shells; the fish function is included but has not been run)

## Limitations

- The fish integration has not been executed, only written. Treat it as experimental and please report whether it works.
- The login step was tested with a fake `aws` executable. The decision of when to log in is tested thoroughly; an actual browser login through IAM Identity Center has not been exercised by the test suite.
- A token shown as `expired, refreshable` is left for the AWS CLI or SDK to renew. If that renewal is refused (for example the Identity Center session itself has ended), your next AWS command will fail and ask you to log in; run `awsp --login QUERY`.
- Only `AWS_PROFILE` is set. If access keys are exported in your shell (`AWS_ACCESS_KEY_ID`), the AWS CLI and SDKs use those keys in preference to the profile; `awsp` prints a note when it sees this but does not unset them.
- No interactive picker. An ambiguous query lists the candidates and asks you to type more.
- No tab completion yet.
- Expiry is only known for SSO. Profiles using `role_arn` on static keys, or `credential_process`, show `-`.

## Development

```bash
git clone https://github.com/narayana006/aws-profile-switch
cd aws-profile-switch
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest
```

Every test builds its AWS config, credentials file, token cache and history in a temporary directory and redirects `HOME`, so the suite never reads or writes your real `~/.aws`. Two tests load the integration in real bash and zsh processes and check that `AWS_PROFILE` changes in that shell.

## Contributing

Issues and pull requests are welcome. Reports from fish users and from unusual SSO setups are especially useful. Please replace account IDs and URLs before pasting config.

## Author

Built and maintained by [Narayana Vemburaj](https://github.com/narayana006).

## License

[MIT](LICENSE)

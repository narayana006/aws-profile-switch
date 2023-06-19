"""Command-line entry point for `awsp`."""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Callable, Mapping, Optional, Sequence

from . import __version__, fuzzy, history, profiles, shell, sso

EXIT_ERROR = 1
EXIT_NO_MATCH = 2

LoginRunner = Callable[[str], int]


def aws_sso_login(profile_name: str) -> int:
    """Run `aws sso login` for the profile. Its output goes to stderr so that
    stdout stays clean for the shell code the wrapper function evaluates."""
    try:
        return subprocess.call(["aws", "sso", "login", "--profile", profile_name], stdout=sys.stderr)
    except FileNotFoundError:
        print("awsp: the `aws` command was not found; install AWS CLI v2 to log in", file=sys.stderr)
        return 127


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="awsp",
        description="Switch AWS profiles with fuzzy search. Run with no arguments to list profiles.",
    )
    parser.add_argument("query", nargs="*", help="a few letters of the profile name")
    parser.add_argument("-l", "--list", action="store_true", help="list matching profiles instead of switching")
    parser.add_argument("-u", "--unset", action="store_true", help="clear AWS_PROFILE in the current shell")
    parser.add_argument("--login", action="store_true", help="always run `aws sso login` for SSO profiles")
    parser.add_argument("--no-login", action="store_true", help="never run `aws sso login`")
    parser.add_argument("--init", choices=shell.SHELLS, metavar="SHELL", help="print shell integration (bash, zsh, fish)")
    parser.add_argument("--emit", choices=shell.SHELLS, metavar="SHELL", help=argparse.SUPPRESS)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def humanize(seconds: float) -> str:
    seconds = int(abs(seconds))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h {seconds % 3600 // 60:02d}m"
    return f"{seconds // 86400}d"


def describe_token(status: Optional[sso.TokenStatus], now: datetime) -> str:
    if status is None:
        return "-"
    if status.state == sso.VALID:
        return f"valid ({humanize((status.expires_at - now).total_seconds())} left)"
    if status.state == sso.REFRESHABLE:
        return "expired, refreshable"
    if status.state == sso.EXPIRED:
        return "expired"
    return "not logged in"


def render_list(config, names, last_used, env, now) -> str:
    rows = [("", "PROFILE", "TYPE", "SSO SESSION", "LAST USED")]
    current = env.get("AWS_PROFILE")
    for name in names:
        _, status = sso.status_for(config, name, env, now)
        used = last_used.get(name)
        rows.append((
            "*" if name == current else "",
            name,
            config.profiles[name].kind,
            describe_token(status, now),
            f"{humanize(now.timestamp() - used)} ago" if used else "never",
        ))
    widths = [max(len(row[i]) for row in rows) for i in range(4)]
    lines = []
    for row in rows:
        cells = [row[0].ljust(1)] + [row[i].ljust(widths[i]) for i in range(1, 4)] + [row[4]]
        lines.append("  ".join(cells).rstrip())
    return "\n".join(lines) + "\n"


def main(
    argv: Optional[Sequence[str]] = None,
    *,
    env: Optional[Mapping[str, str]] = None,
    now: Optional[datetime] = None,
    login: LoginRunner = aws_sso_login,
    stdout=None,
    stderr=None,
) -> int:
    """Run awsp. `env`, `now` and `login` exist so tests can replace them."""
    args = build_parser().parse_args(argv)
    env = os.environ if env is None else env
    now = now or datetime.now(timezone.utc)
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    # With --emit, stdout is evaluated by the shell, so people-facing text goes to stderr.
    human = stderr if args.emit else stdout

    def say(message: str) -> None:
        print(f"awsp: {message}", file=stderr)

    if args.init:
        stdout.write(shell.init_script(args.init))
        return 0
    target_shell = args.emit or shell.detect(env)
    if args.unset:
        print(shell.unset_line(target_shell, "AWS_PROFILE"), file=stdout)
        if not args.emit:
            say(f'shell integration is not loaded, so nothing changed; run: eval "$(command awsp --init {target_shell})"')
        return 0

    try:
        config = profiles.load(env)
    except ValueError as exc:
        say(str(exc))
        return EXIT_ERROR
    if not config.profiles:
        say(f"no profiles found in {profiles.config_path(env)} or {profiles.credentials_path(env)}")
        return EXIT_ERROR

    last_used = history.load(env)
    query = " ".join(args.query)
    ranked = fuzzy.rank(query, config.profiles, last_used)

    if args.list or not query:
        if not ranked:
            say(f"no profile matches '{query}'")
            return EXIT_NO_MATCH
        if query:
            names = [name for name, _ in ranked]
        else:
            names = sorted(config.profiles, key=lambda n: (-last_used.get(n, 0.0), n))
        human.write(render_list(config, names, last_used, env, now))
        return 0

    chosen, tied = fuzzy.choose(ranked)
    if chosen is None:
        if not tied:
            say(f"no profile matches '{query}'")
        else:
            say(f"'{query}' matches several profiles equally; type a little more:")
            for name in tied:
                print(f"  {name}", file=stderr)
        return EXIT_NO_MATCH

    base, status = sso.status_for(config, chosen, env, now)
    if base is not None and not args.no_login and (args.login or status.needs_login):
        reason = "requested" if not status.needs_login else describe_token(status, now)
        say(f"SSO session for '{base.name}' is {reason}; running aws sso login")
        code = login(base.name)
        if code != 0:
            say(f"aws sso login failed (exit {code}); profile not switched")
            return EXIT_ERROR
    elif base is not None and status.needs_login:
        say(f"SSO session for '{base.name}' is {describe_token(status, now)} (login skipped)")
    elif status is not None and status.state == sso.REFRESHABLE:
        say("SSO access token has expired but can be refreshed without a login")

    history.record(env, chosen, now.timestamp())
    print(shell.export_line(target_shell, "AWS_PROFILE", chosen), file=stdout)
    say(f"profile -> {chosen}")
    if env.get("AWS_ACCESS_KEY_ID"):
        say("note: AWS_ACCESS_KEY_ID is set in this shell; the AWS CLI and SDKs use those keys before AWS_PROFILE")
    if not args.emit:
        say(f'shell integration is not loaded, so nothing changed; run: eval "$(command awsp --init {target_shell})"')
    return 0


if __name__ == "__main__":
    sys.exit(main())

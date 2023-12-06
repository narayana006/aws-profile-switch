import io
import shutil
import subprocess
import sys

import pytest

from aws_profile_switch import history
from aws_profile_switch.cli import EXIT_ERROR, EXIT_NO_MATCH, main

from conftest import NOW, write_token


class Login:
    """A fake `aws sso login` that records calls instead of running anything."""

    def __init__(self, code=0):
        self.code = code
        self.calls = []

    def __call__(self, profile_name):
        self.calls.append(profile_name)
        return self.code


def run(env, *argv, login=None):
    out, err = io.StringIO(), io.StringIO()
    login = login or Login()
    code = main(list(argv), env=env, now=NOW, login=login, stdout=out, stderr=err)
    return code, out.getvalue(), err.getvalue(), login


def test_switch_with_valid_session_does_not_login(env):
    write_token(env, "acme")
    code, out, err, login = run(env, "--emit", "zsh", "readonly")
    assert code == 0
    assert out == "export AWS_PROFILE=prod-readonly\n"
    assert "profile -> prod-readonly" in err
    assert login.calls == []
    assert history.load(env) == {"prod-readonly": NOW.timestamp()}


def test_expired_session_triggers_login(env):
    write_token(env, "acme", expires_in=-10)
    code, out, err, login = run(env, "--emit", "bash", "dev")
    assert code == 0
    assert login.calls == ["dev-admin"]
    assert "running aws sso login" in err
    assert out == "export AWS_PROFILE=dev-admin\n"


def test_missing_token_triggers_login_and_failed_login_blocks_switch(env):
    code, out, err, login = run(env, "--emit", "bash", "dev", login=Login(code=1))
    assert code == EXIT_ERROR
    assert login.calls == ["dev-admin"]
    assert out == ""
    assert "profile not switched" in err
    assert history.load(env) == {}


def test_role_profile_logs_in_through_its_sso_source(env):
    code, out, _, login = run(env, "--emit", "bash", "audit")
    assert code == 0
    assert login.calls == ["prod-readonly"]
    assert out == "export AWS_PROFILE=prod-audit\n"


def test_refreshable_token_skips_login(env):
    write_token(env, "acme", expires_in=-10, refreshable=True)
    code, _, err, login = run(env, "--emit", "bash", "dev")
    assert code == 0 and login.calls == []
    assert "can be refreshed" in err


def test_login_flags(env):
    write_token(env, "acme")
    _, _, _, login = run(env, "--emit", "bash", "--login", "dev")
    assert login.calls == ["dev-admin"]
    write_token(env, "acme", expires_in=-10)
    code, out, err, login = run(env, "--emit", "bash", "--no-login", "dev")
    assert code == 0 and login.calls == []
    assert "login skipped" in err
    assert out == "export AWS_PROFILE=dev-admin\n"


def test_non_sso_profile_never_logs_in(env):
    code, out, _, login = run(env, "--emit", "fish", "ci")
    assert code == 0 and login.calls == []
    assert out == "set -gx AWS_PROFILE 'ci-deployer'\n"


def test_ambiguous_query_lists_candidates_then_recency_decides(env):
    write_token(env, "acme")
    code, out, err, _ = run(env, "--emit", "bash", "prod-a")
    assert code == EXIT_NO_MATCH and out == ""
    assert "prod-admin" in err and "prod-audit" in err and "prod-readonly" not in err
    assert run(env, "--emit", "bash", "prod-audit")[0] == 0
    code, out, _, _ = run(env, "--emit", "bash", "prod-a")
    assert (code, out) == (0, "export AWS_PROFILE=prod-audit\n")


def test_no_match(env):
    code, out, err, _ = run(env, "--emit", "bash", "zzz")
    assert (code, out) == (EXIT_NO_MATCH, "")
    assert "no profile matches 'zzz'" in err


def test_list_orders_recent_first_and_marks_current(env):
    write_token(env, "acme", expires_in=7200)
    history.record(env, "sandbox", NOW.timestamp() - 120)
    history.record(env, "prod-admin", NOW.timestamp() - 30)
    code, out, _, _ = run({**env, "AWS_PROFILE": "sandbox"})
    assert code == 0
    lines = out.splitlines()
    assert lines[0].split() == ["PROFILE", "TYPE", "SSO", "SESSION", "LAST", "USED"]
    assert lines[1].startswith("   prod-admin") and "valid (2h 00m left)" in lines[1] and lines[1].endswith("30s ago")
    assert lines[2].startswith("*  sandbox") and lines[2].endswith("2m ago")
    assert [line.split()[0] for line in lines[3:]] == [
        "ci-deployer", "default", "dev-admin", "legacy-sso", "prod-audit", "prod-readonly",
    ]
    assert "not logged in" in next(line for line in lines if "legacy-sso" in line)


def test_list_with_query_filters_and_emit_mode_keeps_stdout_clean(env):
    code, out, _, _ = run(env, "--list", "prod")
    assert code == 0
    assert [line.split()[0] for line in out.splitlines()[1:]] == ["prod-admin", "prod-audit", "prod-readonly"]
    code, out, err, _ = run(env, "--emit", "bash", "prod", "--list")
    assert code == 0 and out == "" and "prod-admin" in err


def test_unset_and_missing_integration_hint(env):
    assert run(env, "--emit", "bash", "--unset")[1] == "unset AWS_PROFILE\n"
    assert run(env, "--emit", "fish", "--unset")[1] == "set -e AWS_PROFILE\n"
    code, out, err, _ = run(env, "ci")
    assert code == 0 and out == "export AWS_PROFILE=ci-deployer\n"
    assert 'eval "$(command awsp --init zsh)"' in err


def test_warns_when_static_keys_are_exported(env):
    _, _, err, _ = run({**env, "AWS_ACCESS_KEY_ID": "testing"}, "--emit", "bash", "ci")
    assert "AWS_ACCESS_KEY_ID is set" in err


def test_no_profiles_and_broken_config(env, tmp_path):
    empty = {"HOME": str(tmp_path / "nowhere")}
    code, _, err, _ = run(empty, "x")
    assert code == EXIT_ERROR and "no profiles found" in err
    open(env["AWS_CONFIG_FILE"], "w").write("this is not ini\n")
    code, _, err, _ = run(env, "x")
    assert code == EXIT_ERROR and "cannot parse" in err


@pytest.mark.parametrize("shell_name", ["bash", "zsh"])
def test_shell_function_sets_profile_in_a_real_shell(env, shell_name, tmp_path):
    """Load `awsp --init` in a real shell and check AWS_PROFILE changes in that shell."""
    if not shutil.which(shell_name):
        pytest.skip(f"{shell_name} not installed")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launcher = bin_dir / "awsp"
    launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m aws_profile_switch.cli "$@"\n')
    launcher.chmod(0o755)
    fake_aws = bin_dir / "aws"  # stands in for the AWS CLI; records how it was called
    fake_aws.write_text(f'#!/bin/sh\necho "$@" >> "{tmp_path}/aws-calls"\necho "fake login output"\n')
    fake_aws.chmod(0o755)
    script = """
eval "$(command awsp --init SHELLNAME)"
awsp ci || exit 10
echo "after-switch=$AWS_PROFILE"
awsp zzz; echo "no-match-status=$? still=$AWS_PROFILE"
awsp dev || exit 11
echo "after-sso=$AWS_PROFILE"
awsp --list prod | head -2 | tail -1
awsp --unset
echo "after-unset=${AWS_PROFILE:-none}"
""".replace("SHELLNAME", shell_name)
    flags = ["--norc", "--noprofile", "-c"] if shell_name == "bash" else ["-f", "-c"]
    shell_env = {**env, "PATH": f"{bin_dir}:/usr/bin:/bin"}
    done = subprocess.run([shell_name, *flags, script], env=shell_env, capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0] == "after-switch=ci-deployer"
    assert lines[1] == "no-match-status=2 still=ci-deployer"
    assert lines[2] == "after-sso=dev-admin"
    assert lines[3].split()[0] == "prod-admin"
    assert lines[4] == "after-unset=none"
    assert "fake login output" not in done.stdout  # login chatter must not be eval'd
    assert (tmp_path / "aws-calls").read_text() == "sso login --profile dev-admin\n"

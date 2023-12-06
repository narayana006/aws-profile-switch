from datetime import timedelta

from aws_profile_switch import fuzzy, history, profiles, shell, sso

from conftest import NOW, write_token


def test_profiles_from_config_and_credentials(env):
    config = profiles.load(env)
    assert sorted(config.profiles) == [
        "ci-deployer", "default", "dev-admin", "legacy-sso", "prod-admin", "prod-audit", "prod-readonly", "sandbox",
    ]
    assert set(config.sso_sessions) == {"acme"}
    kinds = {name: profile.kind for name, profile in config.profiles.items()}
    assert kinds["dev-admin"] == "sso"
    assert kinds["legacy-sso"] == "sso"
    assert kinds["prod-audit"] == "role"
    assert kinds["sandbox"] == "process"
    assert kinds["ci-deployer"] == "keys"
    assert kinds["default"] == "keys"
    assert config.profiles["dev-admin"].settings["region"] == "eu-west-1"


def test_missing_files_give_no_profiles(tmp_path):
    env = {"HOME": str(tmp_path)}
    assert profiles.load(env).profiles == {}
    assert profiles.config_path(env) == tmp_path / ".aws" / "config"


def test_sso_base_follows_source_profile(env):
    config = profiles.load(env)
    assert config.sso_base("prod-audit").name == "prod-readonly"
    assert config.sso_base("dev-admin").name == "dev-admin"
    assert config.sso_base("ci-deployer") is None
    assert config.sso_base("does-not-exist") is None


def test_score_classes_are_ordered():
    name = "acme-prod-readonly"
    assert fuzzy.score("acme-prod-readonly", name)[0] == fuzzy.EXACT
    assert fuzzy.score("ACME", name)[0] == fuzzy.PREFIX
    assert fuzzy.score("read", name)[0] == fuzzy.WORD_START
    assert fuzzy.score("only", name)[0] == fuzzy.SUBSTRING
    assert fuzzy.score("apr", name)[0] == fuzzy.SUBSEQUENCE
    assert fuzzy.score("xyz", name) is None
    assert fuzzy.score("prod read", name) is not None
    assert fuzzy.score("prod write", name) is None


def test_rank_prefers_better_class_then_recency():
    names = ["prod-admin", "prod-readonly", "dev-prod-mirror", "sandbox"]
    ranked = [name for name, _ in fuzzy.rank("prod", names, {})]
    assert ranked == ["prod-admin", "prod-readonly", "dev-prod-mirror"]
    ranked = [name for name, _ in fuzzy.rank("prod", names, {"prod-readonly": 50.0, "dev-prod-mirror": 99.0})]
    assert ranked == ["prod-readonly", "prod-admin", "dev-prod-mirror"]


def test_choose_handles_ties_exact_and_recency():
    names = ["prod", "prod-admin", "prod-readonly"]
    assert fuzzy.choose(fuzzy.rank("prod", names, {})) == ("prod", [])
    assert fuzzy.choose(fuzzy.rank("prod-", names, {})) == (None, ["prod-admin", "prod-readonly"])
    assert fuzzy.choose(fuzzy.rank("prod-", names, {"prod-readonly": 5.0})) == ("prod-readonly", [])
    assert fuzzy.choose(fuzzy.rank("read", names, {})) == ("prod-readonly", [])
    # "ro" is a plain substring of all three names, so nothing stands out.
    assert fuzzy.choose(fuzzy.rank("ro", names, {})) == (None, ["prod", "prod-admin", "prod-readonly"])
    assert fuzzy.choose(fuzzy.rank("zzz", names, {})) == (None, [])


def test_token_states(env):
    config = profiles.load(env)
    dev = config.profiles["dev-admin"]
    assert sso.token_status(dev, env, NOW).state == sso.MISSING
    path = write_token(env, "acme", expires_in=600)
    status = sso.token_status(dev, env, NOW)
    assert status.state == sso.VALID and not status.needs_login
    assert status.expires_at == NOW + timedelta(seconds=600)
    write_token(env, "acme", expires_in=-60)
    assert sso.token_status(dev, env, NOW).needs_login
    write_token(env, "acme", expires_in=-60, refreshable=True)
    status = sso.token_status(dev, env, NOW)
    assert status.state == sso.REFRESHABLE and not status.needs_login
    path.write_text("{corrupt")
    assert sso.token_status(dev, env, NOW).state == sso.MISSING


def test_legacy_profile_token_is_keyed_by_start_url(env):
    config = profiles.load(env)
    write_token(env, "https://legacy.awsapps.com/start")
    assert sso.token_status(config.profiles["legacy-sso"], env, NOW).state == sso.VALID
    assert sso.token_status(config.profiles["dev-admin"], env, NOW).state == sso.MISSING


def test_parse_time_formats():
    assert sso.parse_time("2030-01-01T12:00:00Z") == NOW
    assert sso.parse_time("2030-01-01T12:00:00UTC") == NOW
    assert sso.parse_time("2030-01-01T12:00:00") == NOW
    assert sso.parse_time("soon") is None
    assert sso.parse_time(None) is None


def test_history_roundtrip_and_corruption(env):
    assert history.load(env) == {}
    history.record(env, "dev-admin", 100.0)
    history.record(env, "prod-admin", 200.0)
    assert history.load(env) == {"dev-admin": 100.0, "prod-admin": 200.0}
    history.state_path(env).write_text("not json")
    assert history.load(env) == {}


def test_shell_lines():
    assert shell.export_line("bash", "AWS_PROFILE", "dev") == "export AWS_PROFILE=dev"
    assert shell.export_line("zsh", "AWS_PROFILE", "my profile") == "export AWS_PROFILE='my profile'"
    assert shell.export_line("fish", "AWS_PROFILE", "it's") == "set -gx AWS_PROFILE 'it\\'s'"
    assert shell.unset_line("fish", "AWS_PROFILE") == "set -e AWS_PROFILE"
    assert shell.unset_line("bash", "AWS_PROFILE") == "unset AWS_PROFILE"
    assert shell.detect({"SHELL": "/usr/bin/fish"}) == "fish"
    assert shell.detect({"SHELL": "/bin/tcsh"}) == "bash"

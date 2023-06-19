"""Shell code: the wrapper function that `awsp --init` prints, and the lines it evaluates.

A program cannot change the environment of the shell that started it, so the
real `awsp` executable prints shell code and a small shell function evaluates
it. Human-readable messages always go to stderr in that mode.
"""

from __future__ import annotations

import shlex

SHELLS = ("bash", "zsh", "fish")

_POSIX_INIT = """\
# aws-profile-switch shell integration for {shell}.
# Add to your shell startup file:  eval "$(command awsp --init {shell})"
awsp() {{
  case "${{1:-}}" in
    ""|-l|--list|-h|--help|--version|--init)
      command awsp "$@"
      return $?
      ;;
  esac
  local __awsp_code
  __awsp_code="$(command awsp --emit {shell} "$@")" || return $?
  eval "$__awsp_code"
}}
"""

_FISH_INIT = """\
# aws-profile-switch shell integration for fish.
# Add to ~/.config/fish/config.fish:  command awsp --init fish | source
function awsp
    switch "$argv[1]"
        case '' -l --list -h --help --version --init
            command awsp $argv
            return $status
    end
    set -l __awsp_code (command awsp --emit fish $argv)
    or return $status
    eval (string join ';' $__awsp_code)
end
"""


def init_script(shell: str) -> str:
    if shell == "fish":
        return _FISH_INIT
    return _POSIX_INIT.format(shell=shell)


def _fish_quote(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "\\'") + "'"


def export_line(shell: str, name: str, value: str) -> str:
    if shell == "fish":
        return f"set -gx {name} {_fish_quote(value)}"
    return f"export {name}={shlex.quote(value)}"


def unset_line(shell: str, name: str) -> str:
    if shell == "fish":
        return f"set -e {name}"
    return f"unset {name}"


def detect(env) -> str:
    name = (env.get("SHELL") or "").rsplit("/", 1)[-1]
    return name if name in SHELLS else "bash"

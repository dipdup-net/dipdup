"""This script (un)installs DipDup and its dependencies with pipx.

WARNING: No imports allowed here except stdlib! Otherwise, `curl | python` magic will break.
And no 3.12-only code too. Just to print nice colored "not supported" message instead of crashing.

Some functions are importable to use in `dipdup.cli`.
This script is also available as `dipdup-install` or `python -m dipdup.install`.
"""

import argparse
import os
import subprocess
import sys
from pathlib import Path
from shutil import which
from typing import Any
from typing import NoReturn
from typing import cast

GITHUB = 'https://github.com/dipdup-io/dipdup.git'
WHICH_CMDS = (
    'python3.12',
    'pipx',
    'dipdup',
    'pdm',
    'poetry',
    'pyvenv',
    'pyenv',
    'uv',
)
ENV_VARS = (
    'SHELL',
    'VIRTUAL_ENV',
    'PATH',
    'PYTHONPATH',
)

# NOTE: '\0' is to avoid truncating newlines by asyncclick
WELCOME_ASCII = (
    '\0'
    + r"""
        ____   _         ____              
       / __ \ (_)____   / __ \ __  __ ____ 
      / / / // // __ \ / / / // / / // __ \
     / /_/ // // /_/ // /_/ // /_/ // /_/ /
    /_____//_// .___//_____/ \__,_// .___/ 
             /_/                  /_/      
"""
)
EPILOG = (
    '\0'
    + """
Documentation:         https://dipdup.io/docs
GitHub:                https://github.com/dipdup-io/dipdup
Discord:               https://discord.gg/aG8XKuwsQd
"""
)


class Colors:
    """ANSI color codes"""

    BLUE = '\033[34m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    ENDC = '\033[0m'


def echo(msg: str, color: str = Colors.BLUE) -> None:
    print(color + f'=> {msg}' + Colors.ENDC)


def fail(msg: str) -> NoReturn:
    echo(msg, color=Colors.RED)
    sys.exit(1)


def done(msg: str) -> NoReturn:
    echo(msg, color=Colors.GREEN)
    sys.exit(0)


# NOTE: DipDup has `tabulate` dep, don't use this one elsewhere
# NOTE: Weird default is to match indentation in `EPILOG`.
def _tab(text: str, indent: int = 23) -> str:
    return text + ' ' * (indent - len(text))


class DipDupEnvironment:
    def __init__(self) -> None:
        self._os = os.uname().sysname
        self._arch = os.uname().machine
        self._commands: dict[str, str | None] = {}
        self._pipx_packages: set[str] = set()

    def refresh(self) -> None:
        for command in WHICH_CMDS:
            old, new = self._commands.get(command), which(command)
            if old == new:
                continue
            self._commands[command] = new

    def print(self) -> None:
        print()
        print(WELCOME_ASCII)
        print(EPILOG)
        print()

        print(_tab('OS:') + f'{self._os} ({self._arch})')
        print(_tab('Python:') + sys.version)
        print()

        for var in ENV_VARS:
            if var in os.environ:
                print(_tab(var + ':') + os.environ[var])
        print()

        for command, path in self._commands.items():
            print(_tab(f'{command}:') + (path or ''))
        print(_tab('pipx packages:') + ', '.join(self._pipx_packages))
        print()

    def refresh_pipx(self) -> None:
        """Get installed pipx packages"""
        self.ensure_pipx()
        pipx_packages_raw = self.run_cmd('pipx', 'list', '--short', capture_output=True).stdout
        self._pipx_packages = {p.split()[0].decode() for p in pipx_packages_raw.splitlines()}

    def prepare(self) -> None:
        # NOTE: Show warning if user is root
        if os.geteuid() == 0:
            echo('WARNING: Running as root, this is not generally recommended', Colors.YELLOW)

        # NOTE: Show warning if user is in virtualenv
        if sys.base_prefix != sys.prefix:
            echo('WARNING: Running in virtualenv, this script affects only current user', Colors.YELLOW)

        self.refresh()
        self.refresh_pipx()

    def run_cmd(self, cmd: str, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess[bytes]:
        """Run command safely (relatively lol)"""
        if (found_cmd := self._commands.get(cmd)) is None:
            fail(f'Command not found: {cmd}')
        args = (found_cmd, *tuple(a for a in args if a))
        print(Colors.YELLOW, f'$ {" ".join(args)}', Colors.ENDC)
        try:
            return subprocess.run(
                args,
                **kwargs,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            fail(f'{cmd} failed: {e.cmd} {e.returncode}')

    def ensure_pipx(self) -> None:
        if not sys.version.startswith('3.12'):
            fail('DipDup requires Python 3.12')

        """Ensure pipx is installed for current user"""
        if self._commands.get('pipx'):
            return

        echo('Installing pipx')
        if sys.base_prefix != sys.prefix:
            self.run_cmd('python3.12', '-m', 'pip', 'install', '-q', 'pipx')
        else:
            self.run_cmd('python3.12', '-m', 'pip', 'install', '--user', '-q', 'pipx')
        self.run_cmd('python3.12', '-m', 'pipx', 'ensurepath')
        pipx_path = str(Path.home() / '.local' / 'bin')
        os.environ['PATH'] = pipx_path + os.pathsep + os.environ['PATH']
        self._commands['pipx'] = which('pipx')


def install(
    quiet: bool,
    force: bool,
    version: str | None,
    ref: str | None,
    path: str | None,
    pre: bool = False,
    editable: bool = False,
    update: bool = False,
    with_pdm: bool = False,
    with_poetry: bool = False,
    with_uv: bool = False,
) -> None:
    """Install DipDup and its dependencies with pipx"""
    if ref and path:
        fail('Specify either ref or path, not both')

    env = DipDupEnvironment()
    env.prepare()
    if not quiet:
        env.print()

    pipx_packages = env._pipx_packages

    python_inter_pipx = cast(str, which('python3.12'))
    if 'pyenv' in python_inter_pipx:
        python_inter_pipx = (
            subprocess.run(
                ['pyenv', 'which', 'python3.12'],
                capture_output=True,
                text=True,
            )
            .stdout.strip()
            .split('\n')[0]
        )

    pipx_args = []
    if force:
        pipx_args.append('--force')
    if pre:
        pipx_args.append('--pip-args="--pre"')
    if editable:
        pipx_args.append('--editable')

    if 'dipdup' in pipx_packages and force:
        env.run_cmd('pipx', 'uninstall', 'dipdup')
        pipx_packages.remove('dipdup')

    if 'dipdup' in pipx_packages:
        if update:
            env.run_cmd('pipx', 'upgrade', '--python', python_inter_pipx, 'dipdup', *pipx_args)
    elif path:
        echo(f'Installing DipDup from `{path}`')
        env.run_cmd('pipx', 'install', '--python', python_inter_pipx, path, *pipx_args)
    elif ref:
        url = f'git+{GITHUB}@{ref}'
        echo(f'Installing DipDup from `{url}`')
        env.run_cmd('pipx', 'install', '--python', python_inter_pipx, url, *pipx_args)
    else:
        echo('Installing DipDup from PyPI')
        pkg = 'dipdup' if not version else f'dipdup=={version}'
        env.run_cmd('pipx', 'install', '--python', python_inter_pipx, pkg, *pipx_args)

    for pm, with_pm in (
        ('pdm', with_pdm),
        ('poetry', with_poetry),
        ('uv', with_uv),
    ):
        if pm in pipx_packages:
            if update:
                env.run_cmd('pipx', 'upgrade', '--python', python_inter_pipx, pm, *pipx_args)
        # NOTE: Installed from other sources; skip
        elif env._commands.get(pm):
            pass
        elif with_pm or force or quiet or ask(f'Install `{pm}`?', False):
            echo(f'Installing `{pm}`')
            env.run_cmd('pipx', 'install', '--python', python_inter_pipx, *pipx_args, pm)
            env._commands[pm] = which(pm)

    done(
        'Done! DipDup is ready to use.\n'
        'Run `dipdup new` to create a new project or `dipdup` to see all available commands.'
    )


def ask(question: str, default: bool) -> bool:
    """Ask user a yes/no question"""
    while True:
        answer = input(question + (' [Y/n] ' if default else ' [y/N] ')).lower().strip()
        if not answer:
            return default
        if answer in ('n', 'no'):
            return False
        if answer in ('y', 'yes'):
            return True


def uninstall(quiet: bool) -> NoReturn:
    """Uninstall DipDup and its dependencies with pipx"""
    env = DipDupEnvironment()
    env.prepare()
    if not quiet:
        env.print()

    package = 'dipdup'
    if package in env._pipx_packages:
        echo(f'Uninstalling {package}')
        env.run_cmd('pipx', 'uninstall', package)

    done('Done! DipDup is uninstalled.')


def cli() -> None:
    echo('Welcome to DipDup installer')

    parser = argparse.ArgumentParser()
    parser.add_argument('-q', '--quiet', action='store_true', help='Use default answers for all questions')
    parser.add_argument('-f', '--force', action='store_true', help='Force reinstall')
    parser.add_argument('-v', '--version', help='Install DipDup from a specific version')
    parser.add_argument('-r', '--ref', help='Install DipDup from a specific git ref')
    parser.add_argument('-p', '--path', help='Install DipDup from a local path')
    parser.add_argument('-u', '--uninstall', action='store_true', help='Uninstall DipDup')
    parser.add_argument('-U', '--update', action='store_true', help='Update DipDup')
    parser.add_argument('--pre', action='store_true', help='Include pre-release versions')
    parser.add_argument('-e', '--editable', action='store_true', help='Install DipDup in editable mode')
    parser.add_argument('--with-pdm', action='store_true', help='Install PDM')
    parser.add_argument('--with-poetry', action='store_true', help='Install Poetry')
    parser.add_argument('--with-uv', action='store_true', help='Install uv')
    args = parser.parse_args()

    if not args.quiet:
        sys.stdin = open('/dev/tty')  # noqa: PTH123

    if args.uninstall:
        uninstall(args.quiet)
    else:
        install(
            quiet=args.quiet,
            force=args.force,
            version=args.version.strip() if args.version else None,
            ref=args.ref.strip() if args.ref else None,
            path=args.path.strip() if args.path else None,
            pre=args.pre,
            editable=args.editable,
            update=args.update,
            with_pdm=args.with_pdm,
            with_poetry=args.with_poetry,
            with_uv=args.with_uv,
        )


if __name__ == '__main__':
    cli()

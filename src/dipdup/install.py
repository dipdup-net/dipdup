"""This script (un)installs DipDup and its dependencies with pipx.

WARNING: No imports allowed here except stdlib! Otherwise, `curl | python` magic will break.
And no 3.11-only code too. Just to print nice colored "not supported" message instead of crashing.

Some functions are importable to use in `dipdup.cli`.
This script is also available as `dipdup-install` or `python -m dipdup.install`.
"""
import argparse
import os
import subprocess
import sys
from shutil import which
from typing import cast
from typing import Any
from typing import Dict
from typing import NoReturn
from typing import Optional
from typing import Set

GITHUB = 'https://github.com/dipdup-io/dipdup.git'
WHICH_CMDS = (
    'python3',
    'pipx',
    'dipdup',
    'datamodel-codegen',
    'pdm',
    'pyvenv',
    'pyenv',
)

WELCOME_ASCII = r"""
        ____   _         ____              
       / __ \ (_)____   / __ \ __  __ ____ 
      / / / // // __ \ / / / // / / // __ \
     / /_/ // // /_/ // /_/ // /_/ // /_/ /
    /_____//_// .___//_____/ \__,_// .___/ 
             /_/                  /_/      
"""


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
def _tab(text: str, indent: int = 20) -> str:
    return text + ' ' * (indent - len(text))


class DipDupEnvironment:
    def __init__(self, quiet: bool = False) -> None:
        self._os = os.uname().sysname
        self._arch = os.uname().machine
        self._quiet = quiet
        self._commands: Dict[str, Optional[str]] = {}
        self._pipx_packages: Set[str] = set()

    def refresh(self) -> None:
        if not self._quiet and not self._commands:
            print(WELCOME_ASCII)
            print()
            print(_tab('OS:') + self._os)
            print(_tab('Arch:') + self._arch)
            print(_tab('Python:') + sys.version)
            print(_tab('PATH:') + os.environ['PATH'])
            print()

        for command in WHICH_CMDS:
            old, new = self._commands.get(command), which(command)
            if old == new:
                continue
            self._commands[command] = new
            self._quiet or print(_tab(f'{command}:') + (new or ''))

        print()

    def refresh_pipx(self) -> None:
        """Get installed pipx packages"""
        self.ensure_pipx()
        pipx_packages_raw = self.run_cmd('pipx', 'list', '--short', capture_output=True).stdout
        self._pipx_packages = {p.split()[0].decode() for p in pipx_packages_raw.splitlines()}
        self._quiet or print(_tab('pipx packages:') + ', '.join(self._pipx_packages) + '\n')

    def check(self) -> None:
        #if not sys.version.startswith('3.11'):
        #    fail('DipDup requires Python 3.11')

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
        args = (found_cmd,) + tuple(a for a in args if a)
        try:
            return subprocess.run(
                args,
                **kwargs,
                check=True,
            )
        except subprocess.CalledProcessError as e:
            self._quiet or fail(f'{cmd} failed: {e.cmd} {e.returncode}')
            raise

    def ensure_pipx(self) -> None:
        """Ensure pipx is installed for current user"""
        if self._commands.get('pipx'):
            return

        echo('Installing pipx')
        if sys.base_prefix != sys.prefix:
            self.run_cmd('python3', '-m', 'pip', 'install', '-q', 'pipx')
        else:
            self.run_cmd('python3', '-m', 'pip', 'install', '--user', '-q', 'pipx')
        self.run_cmd('python3', '-m', 'pipx', 'ensurepath')
        self._commands['pipx'] = which('pipx')


def install(
    quiet: bool,
    force: bool,
    ref: str | None,
    path: str | None,
) -> None:
    """Install DipDup and its dependencies with pipx"""
    if ref and path:
        fail('Specify either ref or path, not both')

    env = DipDupEnvironment()
    env.check()

    force_str = '--force' if force else ''
    pipx_packages = env._pipx_packages
    pipx_dipdup = 'dipdup' in pipx_packages
    pipx_datamodel_codegen = 'datamodel-code-generator' in pipx_packages
    pipx_pdm = 'pdm' in pipx_packages

    python_inter_pipx = cast(str, which('python3'))
    if 'pyenv' in python_inter_pipx:
        python_inter_pipx = subprocess.run(['pyenv', 'which', 'python3'], capture_output=True, text=True).stdout.strip().split('\n')[0]

    if pipx_dipdup:
        echo('Updating DipDup')
        env.run_cmd('pipx', 'upgrade', 'dipdup', force_str)
    else:
        if path:
            echo(f'Installing DipDup from `{path}`')
            env.run_cmd('pipx', 'install', '--python', python_inter_pipx, path, force_str)
        elif ref:
            echo(f'Installing DipDup from `{ref}`')
            env.run_cmd('pipx', 'install', '--python', python_inter_pipx, f'git+{GITHUB}@{ref}', force_str)
        else:
            echo('Installing DipDup from PyPI')
            env.run_cmd('pipx', 'install', '--python', python_inter_pipx, 'dipdup', force_str)

    if pipx_datamodel_codegen:
        env.run_cmd('pipx', 'upgrade', 'datamodel-code-generator', force_str)
    else:
        env.run_cmd('pipx', 'install', '--python', python_inter_pipx, 'datamodel-code-generator', force_str)

    if pipx_pdm:
        echo('Updating PDM')
        env.run_cmd('pipx', 'upgrade', 'pdm', force_str)
    else:
        echo('Installing PDM')
        env.run_cmd('pipx', 'install', '--python', python_inter_pipx, 'pdm', force_str)
        env._commands['pdm'] = which('pdm')
        pipx_pdm = True

    done(
        'Done! DipDup is ready to use.\nRun `dipdup new` to create a new project or `dipdup` to see all available'
        ' commands.'
    )


def uninstall(quiet: bool) -> NoReturn:
    """Uninstall DipDup and its dependencies with pipx"""
    env = DipDupEnvironment()
    env.check()

    pipx_packages = env._pipx_packages

    if 'dipdup' in pipx_packages:
        echo('Uninstalling DipDup')
        env.run_cmd('pipx', 'uninstall', 'dipdup')

    if 'datamodel-code-generator' in pipx_packages:
        echo('Uninstalling datamodel-code-generator')
        env.run_cmd('pipx', 'uninstall', 'datamodel-code-generator')

    if 'pdm' in pipx_packages:
        echo('Uninstalling pdm')
        env.run_cmd('pipx', 'uninstall', 'pdm')

    done('Done! DipDup is uninstalled.')


def cli() -> None:
    echo('Welcome to DipDup installer')

    parser = argparse.ArgumentParser()
    parser.add_argument('-q', '--quiet', action='store_true', help='Use default answers for all questions')
    parser.add_argument('-f', '--force', action='store_true', help='Force reinstall')
    parser.add_argument('-r', '--ref', help='Install DipDup from a specific git ref')
    parser.add_argument('-p', '--path', help='Install DipDup from a local path')
    parser.add_argument('-u', '--uninstall', action='store_true', help='Uninstall DipDup')
    args = parser.parse_args()

    if args.uninstall:
        uninstall(args.quiet)
    else:
        install(
            quiet=args.quiet,
            force=args.force,
            ref=args.ref.strip() if args.ref else None,
            path=args.path.strip() if args.path else None,
        )


if __name__ == '__main__':
    cli()

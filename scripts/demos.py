#!/usr/bin/env python3
import os
import subprocess
from pathlib import Path
from shutil import rmtree

import click

from dipdup.cli import green_echo
from dipdup.project import answers_from_replay
from dipdup.project import render_project

DEMO_PREFIX = 'demo_'
SRC_PATH = Path(__file__).parent.parent / 'src'
PROJECTS_PATH = SRC_PATH / 'dipdup' / 'projects'
DEFAULT_ENV = {
    **dict(os.environ),
    'POSTGRES_PASSWORD': '',
    'HASURA_SECRET': '',
    'DIPDUP_NO_SYMLINK': '1',
}


def _get_demos() -> dict[str, Path]:
    return {p.name: p for p in SRC_PATH.iterdir() if p.is_dir() and p.name.startswith(DEMO_PREFIX)}


def _get_projects() -> dict[str, Path]:
    return {p.name: p for p in PROJECTS_PATH.iterdir() if p.is_dir() and p.name.startswith(DEMO_PREFIX)}


def _render_demo(path: Path) -> None:
    package = path.name
    answers = answers_from_replay(path / 'replay.yaml')
    answers['package'] = package
    answers['template'] = package

    render_project(answers, force=True)

    Path(package).replace(f'src/{package}')


def _init_demo(path: Path) -> None:
    package = path.name
    package_path = Path(__file__).parent.parent / 'src' / package
    subprocess.run(
        ('dipdup', 'init', '--force'),
        cwd=package_path,
        check=True,
        env=DEFAULT_ENV,
    )


def _rm_demo(path: Path) -> None:
    rmtree(path, ignore_errors=True)
    rmtree(path.parent / 'src' / path.name, ignore_errors=True)


@click.group(help='Various tools to generate demo projects from templates. Read the script source!')
def main() -> None:
    pass


@main.command(help='Initialize rendered demo projects')
@click.argument('package', required=False)
def init(package: str | None) -> None:
    projects = {package: PROJECTS_PATH / package} if package else _get_projects()

    for package, path in projects.items():
        green_echo(f'=> Initializing `{package}`')
        _init_demo(path)


@main.command(help='Render demo projects from templates')
@click.argument('package', required=False)
def render(package: str | None) -> None:
    demos = {package: SRC_PATH / package} if package else _get_demos()
    projects = {package: PROJECTS_PATH / package} if package else _get_projects()

    for package, path in demos.items():
        green_echo(f'=> Removing `{package}`')
        _rm_demo(path)

    for package, path in projects.items():
        green_echo(f'=> Rendering `{package}`')
        _render_demo(path)


if __name__ == '__main__':
    main()

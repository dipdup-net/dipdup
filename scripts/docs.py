#!/usr/bin/env python3
#
# 🧙 Greetings, traveler!
#
# Why are you here?.. Wait, let me guess! You're a DipDup maintainer, something has broken in CI, and you have no idea how the docs are
# built, right? Good news: everything related to building, formatting and linting documentation is in this file. Bad news: we do everything
# with custom scripts, and it's DOOM on Nightmare. There are comments where possible tho. Read them carefully and you'll be fine.
#
# To run `build --serve` command you need to clone and install frontend from private `dipdup-io/interface` repo first.
#
import logging
import os
import re
import subprocess
import sys
import time
from collections import defaultdict
from collections.abc import Callable
from collections.abc import Iterator
from contextlib import ExitStack
from contextlib import contextmanager
from contextlib import suppress
from functools import partial
from pathlib import Path
from shutil import rmtree
from subprocess import Popen
from typing import Any
from typing import TypedDict

import click
import orjson
from watchdog.events import EVENT_TYPE_CREATED
from watchdog.events import EVENT_TYPE_DELETED
from watchdog.events import EVENT_TYPE_MODIFIED
from watchdog.events import EVENT_TYPE_MOVED
from watchdog.events import FileModifiedEvent
from watchdog.events import FileSystemEvent
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer
from watchdog.observers.api import BaseObserver

from dipdup import __version__
from dipdup.cli import green_echo
from dipdup.cli import red_echo
from dipdup.config import DipDupConfig
from dipdup.sys import set_up_logging

_version = __version__.split('+')[0]
_logger = logging.getLogger()
_logger.setLevel(logging.INFO)
_process: subprocess.Popen[Any] | None = None


class ReferencePage(TypedDict):
    title: str
    description: str
    h1: str
    md_path: str
    html_path: str


REFERENCE_MARKDOWNLINT_HINT = '<!-- markdownlint-disable first-line-h1 no-space-in-emphasis no-inline-html no-multiple-blanks no-duplicate-heading -->\n'
REFERENCE_STRIP_HEAD_LINES = 32
REFERENCE_STRIP_TAIL_LINES = 63
REFERENCE_HEADER_TEMPLATE = """---
title: "{title}"
description: "{description}"
---

# {h1}

"""
REFERENCES: tuple[ReferencePage, ...] = (
    ReferencePage(
        title='CLI',
        description='Command-line interface reference',
        h1='CLI reference',
        md_path='docs/7.references/1.cli.md',
        html_path='cli.html',
    ),
    ReferencePage(
        title='Config',
        description='Config file reference',
        h1='Config reference',
        md_path='docs/7.references/2.config.md',
        html_path='config.html',
    ),
    ReferencePage(
        title='Context (ctx)',
        description='Context reference',
        h1='Context reference',
        md_path='docs/7.references/3.context.md',
        html_path='context.html',
    ),
    ReferencePage(
        title='Models',
        description='Models reference',
        h1='Models reference',
        md_path='docs/7.references/4.models.md',
        html_path='models.html',
    ),
)


# {{ #include ../LICENSE }}
INCLUDE_REGEX = r'{{ #include ([^: ]*) }}'

# {{ #include ../LICENSE:5:20 }}
SLICE_INCLUDE_REGEX = r'{{ #include (.*):(.*):(.*) }}'

# {{ project.package }}
PROJECT_REGEX = r'{{ project.([a-zA-Z_0-9]*) }}'

# [DipDup](https://dipdup.io)
MD_LINK_REGEX = r'\[.*\]\(([0-9a-zA-Z\.\-\_\/\#\:\/\=\?]*)\)'

# ## Title
MD_HEADING_REGEX = r'\#\#* [\w ]*'

# NODE: Extract class name and subclasses in two groups; mind the classes without parents.
# class AbiDatasourceConfig(DatasourceConfig):
CLASS_REGEX = r'class ([a-zA-Z_0-9]*)[\(:]*(.*):'


IGNORED_MODEL_CLASSES = {
    'dipdup.models.BulkCreateQuery',
    'dipdup.models.BulkUpdateQuery',
    'dipdup.models.DeleteQuery',
    'dipdup.models.evm_node.EvmNodeHeadData',
    'dipdup.models.evm_node.EvmNodeHeadSubscription',
    'dipdup.models.evm_node.EvmNodeLogsSubscription',
    'dipdup.models.evm_node.EvmNodeSubscription',
    'dipdup.models.evm_node.EvmNodeSyncingData',
    'dipdup.models.evm_node.EvmNodeSyncingSubscription',
    'dipdup.models.evm_subsquid.BlockFieldSelection',
    'dipdup.models.evm_subsquid.FieldSelection',
    'dipdup.models.evm_subsquid.LogFieldSelection',
    'dipdup.models.evm_subsquid.LogRequest',
    'dipdup.models.evm_subsquid.Query',
    'dipdup.models.evm_subsquid.StateDiffFieldSelection',
    'dipdup.models.evm_subsquid.StateDiffRequest',
    'dipdup.models.evm_subsquid.TraceFieldSelection',
    'dipdup.models.evm_subsquid.TraceRequest',
    'dipdup.models.MessageType',
    'dipdup.models.QuerySet',
    'dipdup.models.RollbackMessage',
    'dipdup.models.substrate.HeadBlock',
    'dipdup.models.substrate.SubstrateEventDataDict',
    'dipdup.models.substrate_node.SubstrateNodeHeadSubscription',
    'dipdup.models.subsquid.AbstractSubsquidQuery',
    'dipdup.models.subsquid.SubsquidMessageType',
    'dipdup.models.starknet.StarknetSubscription',
    'dipdup.models.starknet_subsquid.Query',
    'dipdup.models.starknet_subsquid.TransactionFieldSelection',
    'dipdup.models.starknet_subsquid.EventRequest',
    'dipdup.models.starknet_subsquid.EventFieldSelection',
    'dipdup.models.starknet_subsquid.FieldSelection',
    'dipdup.models.starknet_subsquid.TransactionRequest',
    'dipdup.models.starknet_subsquid.BlockFieldSelection',
    'dipdup.models.tezos_tzkt.BigMapSubscription',
    'dipdup.models.tezos_tzkt.EventSubscription',
    'dipdup.models.tezos_tzkt.HeadSubscription',
    'dipdup.models.tezos_tzkt.OriginationSubscription',
    'dipdup.models.tezos_tzkt.SmartRollupCementSubscription',
    'dipdup.models.tezos_tzkt.SmartRollupExecuteSubscription',
    'dipdup.models.tezos_tzkt.TezosTzktMessageType',
    'dipdup.models.tezos_tzkt.TezosTzktSubscription',
    'dipdup.models.tezos_tzkt.TokenBalanceSubscription',
    'dipdup.models.tezos_tzkt.TokenTransferSubscription',
    'dipdup.models.tezos_tzkt.TransactionSubscription',
    'dipdup.models.UpdateQuery',
    'dipdup.models.VersionedTransaction',
}

TEXT_EXTENSIONS = (
    '.md',
    '.yml',
    '.yaml',
)
IMAGE_EXTENSIONS = (
    '.svg',
    '.png',
    '.jpg',
)

# NOTE: Global markdownlint ignore list. We have to duplicate H1's due to how our NextJS frontend works.
MARKDOWNLINT_IGNORE = (
    'line-length',
    'single-title',
    'single-h1',
)
MARKDOWNLINT_CMD = (
    'markdownlint',
    '-f',
    '--disable',
    *MARKDOWNLINT_IGNORE,
    '--',
    'docs',
)


# NOTE: As in Keep a Changelog spec
CHANGELOG_GROUP_ORDER = (
    'Added',
    'Fixed',
    'Changed',
    'Deprecated',
    'Removed',
    'Performance',
    'Security',
    'Other',
)


class ScriptObserver(FileSystemEventHandler):
    def on_modified(self, event: FileSystemEvent) -> None:
        _logger.info('script has been modified; restarting')
        if _process:
            _process.terminate()
        os.execl(sys.executable, sys.executable, *sys.argv)


class DocsBuilder(FileSystemEventHandler):
    def __init__(
        self,
        source: Path,
        destination: Path,
        callbacks: list[Callable[[str], str]] | None = None,
    ) -> None:
        self._source = source
        self._destination = destination
        self._callbacks = callbacks or []

    def on_rst_modified(self) -> None:
        subprocess.run(
            ('python3', 'scripts/docs.py', 'dump-references'),
            check=True,
        )

    def on_modified(
        self,
        event: FileSystemEvent,
        skip_rst: bool = False,
    ) -> None:
        src_file = Path(event.src_path).relative_to(self._source)  # type: ignore[arg-type]
        if src_file.is_dir() or 'html' in src_file.parts:
            return

        # NOTE: Sphinx autodoc reference; rebuild HTML
        if src_file.name.endswith('.rst'):
            if not skip_rst:
                self.on_rst_modified()
            return

        if event.event_type == EVENT_TYPE_DELETED:
            dst_file = (self._destination / src_file.relative_to(self._source)).resolve()
            dst_file.unlink(True)
            return

        if event.event_type not in (EVENT_TYPE_CREATED, EVENT_TYPE_MODIFIED, EVENT_TYPE_MOVED):
            return

        # NOTE: Vite doesn't like images in content directory; add '../public'
        destination = self._destination.parent.parent / 'public' if 'public' in src_file.parts else self._destination

        src_file = self._source / src_file
        dst_file = (destination / src_file.relative_to(self._source)).resolve()

        # NOTE: Make sure the destination directory exists
        dst_file.parent.mkdir(parents=True, exist_ok=True)

        _logger.info('`%s` has been %s; copying', src_file, event.event_type)

        try:
            if src_file.suffix in TEXT_EXTENSIONS:
                data = src_file.read_text()
                for callback in self._callbacks:
                    data = callback(data)
                dst_file.write_text(data)
            elif src_file.suffix in IMAGE_EXTENSIONS:
                dst_file.write_bytes(src_file.read_bytes())
            else:
                pass
        except Exception as e:
            _logger.error('Failed to copy %s: %s', src_file.name, e)


def create_include_callback(source: Path) -> Callable[[str], str]:
    def callback(data: str) -> str:
        def replacer(match: re.Match[str], slice: bool) -> str:
            # FIXME: Slices are not handled yet
            included_path = source / match.group(1).split(':')[0]
            included_file = included_path.read_text()
            _logger.info('including `%s`', included_path.relative_to(Path.cwd()))
            if slice:
                from_, to = match.group(2), match.group(3)
            else:
                return included_file

            from_, to = int(from_ or 0), int(to or len(included_file.split('\n')))
            return '\n'.join(included_file.split('\n')[from_:to])

        data = re.sub(INCLUDE_REGEX, partial(replacer, slice=False), data)
        return re.sub(SLICE_INCLUDE_REGEX, partial(replacer, slice=True), data)

    return callback


def create_project_callback() -> Callable[[str], str]:
    from dipdup.project import get_default_answers

    answers = get_default_answers()

    def callback(data: str) -> str:
        for match in re.finditer(PROJECT_REGEX, data):
            key = match.group(1)
            value = answers[key]  # type: ignore[literal-required]
            data = data.replace(match.group(0), str(value))
        return data

    return callback


@contextmanager
def observer(path: Path, handler: Any) -> Iterator[BaseObserver]:
    observer = Observer()
    observer.schedule(handler, path=str(path), recursive=True)
    observer.start()

    yield observer

    observer.stop()
    observer.join()


@contextmanager
def frontend(path: Path) -> Iterator[Popen[Any]]:
    global _process

    # NOTE: pnpm is important! Regular npm fails to resolve deps.
    _process = Popen(['pnpm', 'run', 'dev'], cwd=path)

    yield _process

    _process.terminate()
    _process = None


@click.group(help='Various tools to build and maintain DipDup documentation. Read the script source!')
def main() -> None:
    set_up_logging()


@main.command('build', help='Build and optionally serve docs')
@click.option(
    '--source',
    type=click.Path(exists=True, file_okay=False, dir_okay=True, resolve_path=True, path_type=Path),
    help='docs/ directory path to watch.',
    default='docs',
)
@click.option(
    '--destination',
    type=click.Path(file_okay=False, dir_okay=True, path_type=Path),
    help='content/ dirertory path to copy to.',
    default='../interface/content',
)
@click.option(
    '--watch',
    is_flag=True,
    help='Watch for changes.',
)
@click.option(
    '--serve',
    is_flag=True,
    help='Start frontend.',
)
def build(source: Path, destination: Path, watch: bool, serve: bool) -> None:
    green_echo('=> Building docs')
    rmtree(destination, ignore_errors=True)

    event_handler = DocsBuilder(
        source,
        destination,
        callbacks=[
            create_include_callback(source),
            create_project_callback(),
        ],
    )
    event_handler.on_rst_modified()
    for path in source.glob('**/*'):
        event_handler.on_modified(
            FileModifiedEvent(str(path)),
            skip_rst=True,
        )

    if not (watch or serve):
        return

    with ExitStack() as stack:
        stack.enter_context(observer(Path(__file__), ScriptObserver()))
        if watch:
            green_echo('=> Watching for changes')
            stack.enter_context(observer(source, event_handler))
        if serve:
            green_echo('=> Starting frontend')
            stack.enter_context(frontend(destination.parent.parent))

        stack.enter_context(suppress(KeyboardInterrupt))
        while True:
            time.sleep(1)


@main.command('check-links', help='Check relative links in docs')
@click.option(
    '--source',
    type=click.Path(exists=True, file_okay=False, dir_okay=True, resolve_path=True, path_type=Path),
    help='docs/ directory path to check.',
    default='docs',
)
@click.option('--http', is_flag=True, help='Check HTTP links too.')
def check_links(source: Path, http: bool) -> None:
    green_echo('=> Checking relative links')
    files, links, bad_paths, bad_anchors, bad_http = 0, 0, 0, 0, 0
    http_links: set[str] = set()

    for path in source.rglob('*.md'):
        _logger.info('checking file `%s`', path)
        files += 1
        data = path.read_text()
        for match in re.finditer(MD_LINK_REGEX, data):
            links += 1
            link = match.group(1)

            if link.startswith('http'):
                http_links.add(link)
                continue

            link, anchor = link.split('#') if '#' in link else (link, None)

            # NOTE: Vite doesn't like images in content directory; revert path hack
            if 'public' in link:
                link = link.replace('../../public', '../public')

            full_path = path.parent.joinpath(link)
            if not full_path.exists():
                logging.error('broken link: `%s`', full_path)
                bad_paths += 1
                continue

            if anchor:
                target = full_path.read_text() if link else data

                for match in re.finditer(MD_HEADING_REGEX, target):
                    header = match.group(0).lower().replace(' ', '-').strip('#-')
                    if header == anchor.lower():
                        break
                else:
                    logging.error('broken anchor: `%s#%s`', link, anchor)
                    bad_anchors += 1
                    continue

    if http:
        green_echo('=> Checking HTTP links')

        for i, link in enumerate(http_links):
            green_echo(f'{i+1}/{len(http_links)}: checking link `{link}`')
            try:
                res = subprocess.run(
                    ('curl', '-s', '-L', '-o', '/dev/null', '-w', '%{http_code}', link),
                    check=True,
                    capture_output=True,
                )
                status_code = int(res.stdout.decode().strip())
                if status_code != 200:
                    raise subprocess.CalledProcessError(status_code, 'curl')
            except subprocess.CalledProcessError:
                red_echo(f'broken http link: `{status_code}`')
                if 'subscan' in link:
                    print("Subscan is known to block curl, so it's probably fine.")
                bad_http += 1

    _logger.info('_' * 80)
    _logger.info('checked %d files and %d links:', files, links)
    _logger.info('paths: %d bad links, %d bad anchors', bad_paths, bad_anchors)
    _logger.info('http: %d bad links', bad_http)

    if bad_paths or bad_anchors or bad_http:
        red_echo('=> Fix broken links and try again')
        exit(1)


@main.command('dump-jsonschema', help='Dump config JSON schema to schema.json')
def dump_jsonschema() -> None:
    green_echo('=> Dumping JSON schema')

    schema_dict = DipDupConfig.json_schema()
    schema_path = Path(__file__).parent.parent / 'schemas' / 'dipdup-3.0.json'
    schema_path.write_bytes(orjson.dumps(schema_dict, option=orjson.OPT_INDENT_2))


@main.command('dump-references', help='Dump Sphinx references to ugly Markdown files')
def dump_references() -> None:
    green_echo('=> Dumping Sphinx references')

    def _compare(ref: str, ignore: set[str]) -> None:
        green_echo(f'=> Verifying that {ref} reference is up to date')
        ref_rst = Path(f'docs/{ref}.rst').read_text().splitlines()
        classes_in_ref = {line.split(' ')[2] for line in ref_rst if line.startswith('.. autoclass::')}
        classes_in_package = set()
        for file in Path(f'src/dipdup/{ref}').glob('*.py'):
            for match in re.finditer(CLASS_REGEX, file.read_text()):
                package_path = file.relative_to(f'src/dipdup/{ref}')
                if package_path == Path('__init__.py'):
                    package_path = package_path.parent
                if package_path == Path():
                    package_path_str = ''
                else:
                    package_path_str = '.' + package_path.with_suffix('').as_posix().replace('/', '.')
                # NOTE: Skip private modules and classes
                if '._' in package_path_str or 'ABC' in match.group(2):
                    continue
                classes_in_package.add(f'dipdup.{ref}{package_path_str}.{match.group(1)}')

        to_add = classes_in_package - classes_in_ref - ignore
        to_remove = classes_in_ref - classes_in_package - ignore

        if to_add or to_remove:
            red_echo(f'=> Reference is outdated! Update `docs/{ref}.rst` and try again.')
            red_echo(f'=> Add: {to_add}')
            red_echo(f'=> Remove: {to_remove}')
            exit(1)

    _compare('models', IGNORED_MODEL_CLASSES)

    green_echo('=> Building Sphinx docs')
    rmtree('docs/_build', ignore_errors=True)
    subprocess.run(
        args=('sphinx-build', '-M', 'html', '.', '_build'),
        cwd='docs',
        check=True,
    )

    green_echo('=> Converting to ugly Markdown files')
    for page in REFERENCES:
        to = Path(page['md_path'])
        from_ = Path(f"docs/_build/html/{page['html_path']}")

        # NOTE: Strip HTML boilerplate
        lines = from_.read_text().split('\n')
        out = '\n'.join(lines[REFERENCE_STRIP_HEAD_LINES:-REFERENCE_STRIP_TAIL_LINES]).strip(' \n')

        # - <dt class="sig sig-object py" id="dipdup.config.DipDupConfig">
        # + ## dipdup.config.DipDupConfig
        for match_ in re.finditer(r'<dt class="sig sig-object py" id="(.*)">', out):
            out = out.replace(match_.group(0), f'\n## {match_.group(1)}\n')

        # - <h1>Enums<a class="headerlink" href="#enums" title="Link to this heading">¶</a></h1>
        # + # Enums
        for match_ in re.finditer(
            r'<h(\d)>(.*)<a class="headerlink" href="#.*" title="Link to this heading">¶</a></h\d>', out
        ):
            level = int(match_.group(1))
            out = out.replace(match_.group(0), f'\n{"#" * level} {match_.group(2)}\n')

        # - <a class="headerlink" href="#dipdup.config.AbiDatasourceConfig" title="Link to this definition">¶</a>
        # + none
        out = re.sub(r'<a class="headerlink" href="#.*" title="Link to this definition">¶</a>', '', out)

        # - <a class="reference internal" href="#dipdup.config.HttpConfig" title="dipdup.config.HttpConfig">
        # + <a class="reference internal" href="#dipdupconfighttpconfig" title="dipdup.config.HttpConfig">
        for match_ in re.finditer(r'<a class="reference internal" href="#([^ ]*)" title="([^ ]*)"', out):
            anchor = match_.group(2).replace('.', '').lower()
            fixed_link = f'<a class="reference internal" href="#{anchor}" title="{match_.group(2)}" target="_self"'
            out = out.replace(match_.group(0), fixed_link)

        # - <a class="reference internal" href="config.html#dipdup.config.HttpConfig" title="dipdup.config.HttpConfig">
        # + <a class="reference internal" href="config#dipdupconfighttpconfig" title="dipdup.config.HttpConfig">
        for match_ in re.finditer(r'<a class="reference internal" href="([^"]*).html#([^"]*)" title="([^"]*)"', out):
            anchor = match_.group(3).replace('.', '').lower()
            fixed_link = f'<a class="reference internal" href="{match_.group(1)}#{anchor}" title="{match_.group(3)}" target="_self"'
            out = out.replace(match_.group(0), fixed_link)

        # - <dt class="field-even">Return type<span class="colon">:</span></dt>
        # + <dt class="field-even" style="color: var(--txt-primary);">Return type<span class="colon">:</span></dt>
        for match_ in re.finditer(r'<dt class="field-even">(.*)<span class="colon">:</span></dt>', out):
            out = out.replace(
                match_.group(0),
                f'<dt class="field-even" style="color: var(--txt-primary);">{match_.group(1)}<span class="colon">:</span></dt>',
            )

        # - <dt class="field-odd">Parameters<span class="colon">:</span></dt>
        # + <dt class="field-odd" style="color: var(--txt-primary);">Parameters<span class="colon">:</span></dt>
        for match_ in re.finditer(r'<dt class="field-odd">(.*)<span class="colon">:</span></dt>', out):
            out = out.replace(
                match_.group(0),
                f'<dt class="field-odd" style="color: var(--txt-primary);">{match_.group(1)}<span class="colon">:</span></dt>',
            )

        # - <section id="dipdup-config-env">
        out = re.sub(r'<section id=".*">', '', out)

        # NOTE: Remove empty "*args" generated for `kw_only` dataclasses
        if 'config' in page['md_path']:
            template = '<em class="sig-param"><span class="{}"><span class="pre">*</span></span><span class="{}"><span class="pre">args</span></span></em>, '
            for i, j in (
                ('n', 'n'),
                ('n', 'o'),
                ('o', 'n'),
                ('o', 'o'),
            ):
                out = out.replace(template.format(i, j), '')
            out = out.replace('<li><p><strong>args</strong> (<em>Any</em>)</p></li>', '')

        header = REFERENCE_HEADER_TEMPLATE.format(**page)
        to.write_text(header + REFERENCE_MARKDOWNLINT_HINT + out)


@main.command('markdownlint', help='Lint Markdown files')
def markdownlint() -> None:
    green_echo('=> Running markdownlint')
    try:
        subprocess.run(
            MARKDOWNLINT_CMD,
            check=True,
        )
    except subprocess.CalledProcessError:
        red_echo('=> Fix markdownlint errors and try again')
        exit(1)


# FIXME: It's a full-copilot script to fix the changelog once, quickly. Rewrite or remove it.
@main.command('merge-changelog', help='Print changelog grouped by minor versions')
def merge_changelog() -> None:
    changelog_path = Path('CHANGELOG.md')
    changelog = changelog_path.read_text().split('<!-- Links -->')[0].strip()

    changelog_tree: defaultdict[str, defaultdict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
    curr_version, curr_group = '', ''

    for line in changelog.split('\n'):
        line = line.strip()

        if line.startswith('## '):
            # FIXME: Remove after the first 8.0 release
            line = line.replace('## [Unreleased]', '## [8.0.0]')

            try:
                curr_version = line.split('[', 1)[1].split(']')[0]
            except IndexError:
                continue
            curr_version = '.'.join(curr_version.split('.')[:2])
        elif line.startswith('### '):
            curr_group = line[4:]
        elif line.startswith('- '):
            changelog_tree[curr_version][curr_group].append(line)

    for version in sorted(changelog_tree.keys()):
        major = int(version.split('.')[0])
        minor = int(version.split('.')[1])

        version_path = Path(f'docs/9.release-notes/_{version}_changelog.md')
        lines: list[str] = ['<!-- markdownlint-disable first-line-h1 -->']

        if minor:
            lines.append(f'## Changes since {major}.{minor - 1}\n')
        else:
            lines.append(f'## Changes since {major - 1}.x\n')

        for group in CHANGELOG_GROUP_ORDER:
            if not changelog_tree[version][group]:
                continue

            lines.append(f'### {group}\n')
            for line in sorted(changelog_tree[version][group]):
                lines.append(line)
            lines.append('')

        version_path.write_text('\n'.join(lines))


@main.command('dump-metrics', help='Dump Markdown table of Prometheus metrics')
def dump_metrics() -> None:
    green_echo('=> Dumping metrics table')
    metrics: list[tuple[str, str, str]] = []

    from dipdup.performance import _MetricManager as cls
    from dipdup.prometheus import Metric

    for attr in dir(cls):
        val = object.__getattribute__(cls, attr)
        if not isinstance(val, Metric):
            continue

        metrics.append((val._get_metric().name, val._get_metric().documentation, val.__class__.__name__))  # type: ignore[no-untyped-call]

    metrics = sorted(metrics, key=lambda x: x[0])

    lines = [
        '<!-- markdownlint-disable first-line-h1 -->',
        '| name | description | type |',
        '|-|-|-|',
        *(f'| {name} | {description} | {type_} |' for name, description, type_ in metrics),
        '',
    ]

    Path('docs/5.advanced/_metrics_table.md').write_text('\n'.join(lines))


@main.command('dump-demos', help='Dump Markdown table of available demo projects')
def dump_demos() -> None:
    from dipdup.project import TEMPLATES
    from dipdup.project import answers_from_replay

    green_echo('=> Dumping demos table')
    demos: list[tuple[str, str, str]] = []

    replays = Path('src/dipdup/projects').glob('**/replay.yaml')
    for replay_path in replays:
        replay = answers_from_replay(replay_path)
        package, description = replay['package'], replay['description']
        if package in TEMPLATES['evm']:
            network = 'EVM'
        elif package in TEMPLATES['tezos']:
            network = 'Tezos'
        elif package in TEMPLATES['starknet']:
            network = 'Starknet'
        else:
            network = ''
        demos.append((package, network, description))

    # NOTE: Sort by blockchain first, then by package name
    demos = sorted(demos, key=lambda x: (x[1], x[0]))

    lines = [
        '<!-- markdownlint-disable first-line-h1 -->',
        '| name | network | description | source |',
        '|-|-|-|-|',
        *(
            f'| {name} | {network} | {description} | [link](https://github.com/dipdup-io/dipdup/tree/{_version}/src/{name}) |'
            for name, network, description in demos
        ),
        '',
    ]

    Path('docs/8.examples/_demos_table.md').write_text('\n'.join(lines))

    # NOTE: Another fun script. Create a `launch.json` in the project root containing debug configurations for all demo projects.
    green_echo('=> Dumping `launch.json`')
    launch_json_path = Path('.vscode/launch.json')
    launch_json = {
        'version': '0.2.0',
        'configurations': [],
    }
    for name, _, _ in demos:
        for args in (
            ('run',),
            ('init',),
        ):
            launch_json['configurations'].append(  # type: ignore[attr-defined]
                {
                    'name': f'{name}: {" ".join(args)}',
                    'type': 'debugpy',
                    'request': 'launch',
                    'module': 'dipdup',
                    'args': ('-e', '.env', *args),
                    'console': 'integratedTerminal',
                    'cwd': '${workspaceFolder}/src/' + name,
                    'justMyCode': False,
                    'env': {
                        'DIPDUP_DEBUG': '1',
                        'DIPDUP_NO_SYMLINK': '1',
                    },
                }
            )
    launch_json_path.write_bytes(
        orjson.dumps(
            launch_json,
            option=orjson.OPT_INDENT_2,
        )
    )


@main.command('move-pages', help='Insert or remove pages in the ToC shifting page indexes')
@click.option(
    '--path',
    type=click.Path(exists=True, file_okay=False, dir_okay=True, resolve_path=True, path_type=Path),
    help='docs/ directory path to use.',
)
@click.option('--insert', type=int, help='Page index to insert')
@click.option('--pop', type=int, help='Page index to pop')
def move_pages(path: Path, insert: int, pop: int) -> None:
    files = list(path.glob('*.md'))
    if not files:
        red_echo('=> No pages found')
        exit(1)

    toc = {}
    for file in files:
        if not file.stem[0].isdigit():
            continue

        index = int(file.stem.split('.')[0])
        if index in toc:
            red_echo(f'=> Duplicate index {index}')
            exit(1)
        toc[index] = file

    if insert:
        for index in sorted(toc.keys(), reverse=True):
            if index < insert:
                break

            file = toc[index]
            new_name = path / f'{index + 1}.{file.name.split(".")[1]}.md'
            file.rename(new_name)
            toc[index + 1] = new_name

        new_file = path / f'{insert}.md'
        new_file.touch()
        toc[insert] = new_file

    if pop:
        if pop not in toc:
            red_echo(f'=> No page with index {pop}')
            exit(1)
        file = toc.pop(pop)
        file.rename(path / f'_{file.name}')

        for index in sorted(toc.keys()):
            if index > pop:
                file = toc.pop(index)
                new_name = path / f'{index - 1}.{file.name.split(".")[1]}.md'
                file.rename(new_name)
                toc[index - 1] = new_name


if __name__ == '__main__':
    main()

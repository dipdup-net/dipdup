import asyncio
import hashlib
import logging
import platform
from contextlib import suppress
from typing import TYPE_CHECKING

import sentry_sdk
import sentry_sdk.consts
import sentry_sdk.serializer
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from sentry_sdk.integrations.atexit import AtexitIntegration
from sentry_sdk.integrations.logging import LoggingIntegration

from dipdup import __version__
from dipdup import env
from dipdup.sys import fire_and_forget

HEARTBEAT_INTERVAL = 60 * 60 * 24

if TYPE_CHECKING:
    from sentry_sdk._types import Event

    from dipdup.config import SentryConfig

_logger = logging.getLogger(__name__)


async def _heartbeat() -> None:
    """Restart Sentry session every 24 hours"""
    with suppress(asyncio.CancelledError):
        while True:
            await asyncio.sleep(HEARTBEAT_INTERVAL)
            _logger.info('Reopening Sentry session')
            sentry_sdk.Hub.current.end_session()
            sentry_sdk.Hub.current.flush()
            sentry_sdk.Hub.current.start_session()


def extract_event(error: Exception) -> 'Event':
    """Extracts Sentry event from an exception"""
    exc_info = sentry_sdk.utils.exc_info_from_error(error)
    event, _ = sentry_sdk.utils.event_from_exception(exc_info)
    return sentry_sdk.serializer.serialize(event)  # type: ignore[arg-type,return-value]


def init_sentry(config: 'SentryConfig', package: str) -> None:
    dsn = config.dsn
    if dsn:
        _logger.info('Sentry is enabled: %s', dsn)

    if config.debug or env.DEBUG:
        level, event_level, attach_stacktrace = logging.DEBUG, logging.WARNING, True
    else:
        level, event_level, attach_stacktrace = logging.INFO, logging.ERROR, False

    integrations = [
        AioHttpIntegration(),
        LoggingIntegration(
            level=level,
            event_level=event_level,
        ),
        # NOTE: Suppresses `atexit` notification
        AtexitIntegration(lambda _, __: None),
    ]
    release = config.release or __version__
    environment = config.environment
    server_name = config.server_name

    if not environment:
        if env.DOCKER:
            environment = 'docker'
        elif env.TEST:
            environment = 'tests'
        elif env.CI:
            environment = 'gha'
        else:
            environment = 'local'

    if not server_name:
        server_name = platform.node()

    sentry_sdk.init(
        dsn=dsn,
        integrations=integrations,
        attach_stacktrace=attach_stacktrace,
        release=release,
        environment=environment,
        server_name=server_name,
        # NOTE: Increase __repr__ length limit
        max_value_length=sentry_sdk.consts.DEFAULT_MAX_VALUE_LENGTH * 10,
    )

    # NOTE: Setting session tags
    tags = {
        'python': platform.python_version(),
        'os': f'{platform.system().lower()}-{platform.machine()}',
        'version': __version__,
        'package': package,
        'release': release,
        'environment': environment,
        'server_name': server_name,
    }
    _logger.debug('Sentry tags: %s', ', '.join(f'{k}={v}' for k, v in tags.items()))
    for tag, value in tags.items():
        sentry_sdk.set_tag(f'dipdup.{tag}', value)

    # NOTE: User ID allows to track release adoption. It's sent on every session,
    # NOTE: but obfuscated below, so it's not a privacy issue. However, randomly
    # NOTE: generated Docker hostnames may spoil this metric.
    user_id = config.user_id
    if user_id is None:
        user_id = package + environment + server_name
        user_id = hashlib.sha256(user_id.encode()).hexdigest()[:8]
    _logger.debug('Sentry user_id: %s', user_id)

    sentry_sdk.set_user({'id': user_id})
    sentry_sdk.Hub.current.start_session()
    fire_and_forget(_heartbeat())

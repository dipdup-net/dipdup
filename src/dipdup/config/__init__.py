"""Config files parsing and processing

As you can see from the amount of code below, lots of things are going on here:

* Templating indexes and env variables (`<...>` and `${...}` syntax)
* Config initialization and validation
* Methods to generate paths for codegen
* And even importing contract types on demand

* YAML (de)serialization moved to `dipdup.yaml` module.

Dataclasses are used in this module instead of BaseModel for historical reasons, thus "...Mixin" classes to workaround the lack of proper
inheritance.
"""

from __future__ import annotations

import importlib
import inspect
import logging.config
import re
from abc import ABC
from abc import abstractmethod
from collections import defaultdict
from contextlib import suppress
from itertools import chain
from pathlib import Path
from types import NoneType
from typing import TYPE_CHECKING
from typing import Annotated
from typing import Any
from typing import Literal
from typing import TypeVar
from typing import cast
from urllib.parse import quote_plus

import orjson
from pydantic import BeforeValidator
from pydantic import ConfigDict
from pydantic import Field
from pydantic import TypeAdapter
from pydantic import ValidationError
from pydantic.dataclasses import dataclass
from pydantic.dataclasses import is_pydantic_dataclass
from pydantic_core import to_jsonable_python

from dipdup import __spec_version__
from dipdup import env
from dipdup.config._mixin import CallbackMixin
from dipdup.config._mixin import NameMixin
from dipdup.config._mixin import ParentMixin
from dipdup.exceptions import ConfigInitializationException
from dipdup.exceptions import ConfigurationError
from dipdup.exceptions import IndexAlreadyExistsError
from dipdup.models import ReindexingAction
from dipdup.models import ReindexingReason
from dipdup.models import SkipHistory
from dipdup.utils import pascal_to_snake
from dipdup.yaml import DipDupYAMLConfig

if TYPE_CHECKING:
    from collections.abc import Iterator

    from dipdup.subscriptions import Subscription

DEFAULT_POSTGRES_SCHEMA = 'public'
DEFAULT_POSTGRES_DATABASE = 'postgres'
DEFAULT_POSTGRES_USER = 'postgres'
DEFAULT_POSTGRES_PORT = 5432
DEFAULT_SQLITE_PATH = ':memory:'


def _valid_url(v: str, ws: bool) -> str:
    if not ws and not v.startswith(('http://', 'https://')):
        raise ConfigurationError(f'`{v}` is not a valid HTTP URL')
    if ws and not v.startswith(('ws://', 'wss://')):
        raise ConfigurationError(f'`{v}` is not a valid WebSocket URL')
    return v.rstrip('/')


_T = TypeVar('_T')
Alias = Annotated[_T, NoneType]

type Hex = Annotated[str, BeforeValidator(lambda v: hex(v) if isinstance(v, int) else v)]
type ToStr = Annotated[str | float, BeforeValidator(lambda v: str(v))]
type Url = Annotated[str, BeforeValidator(lambda v: _valid_url(v, ws=False))]
type WsUrl = Annotated[str, BeforeValidator(lambda v: _valid_url(v, ws=True))]


_logger = logging.getLogger(__name__)


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SqliteDatabaseConfig:
    """
    SQLite connection config

    :param kind: always 'sqlite'
    :param path: Path to .sqlite file, leave default for in-memory database (`:memory:`)
    :param immune_tables: List of tables to preserve during reindexing
    """

    kind: Literal['sqlite']
    path: str = DEFAULT_SQLITE_PATH
    immune_tables: set[str] = Field(default_factory=set)

    @property
    def schema_name(self) -> str:
        # NOTE: Used only as identifier in `dipdup_schema` dable, since Hasura integration is not supported for SQLite.
        return DEFAULT_POSTGRES_SCHEMA

    @property
    def connection_string(self) -> str:
        if self.path != DEFAULT_SQLITE_PATH:
            path = Path(self.path).resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            return f'{self.kind}:///{path}'

        return f'{self.kind}://{self.path}'

    @property
    def connection_timeout(self) -> int:
        # NOTE: Fail immediately
        return 1


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class PostgresDatabaseConfig:
    """Postgres database connection config

    :param kind: always 'postgres'
    :param host: Host
    :param port: Port
    :param user: User
    :param password: Password
    :param database: Database name
    :param schema_name: Schema name
    :param immune_tables: List of tables to preserve during reindexing
    :param connection_timeout: Connection timeout
    """

    kind: Literal['postgres']
    host: str
    user: str = DEFAULT_POSTGRES_USER
    database: str = DEFAULT_POSTGRES_DATABASE
    port: int = DEFAULT_POSTGRES_PORT
    schema_name: str = DEFAULT_POSTGRES_SCHEMA
    password: str = Field(default='', repr=False)
    immune_tables: set[str] = Field(default_factory=set)
    connection_timeout: int = 60

    def __post_init__(self) -> None:
        for table in self.immune_tables:
            if table.startswith('dipdup'):
                raise ConfigurationError("Tables with `dipdup` prefix can't be immune")

    @property
    def connection_string(self) -> str:
        # NOTE: `maxsize=1` is important! Concurrency will be broken otherwise.
        # NOTE: https://github.com/tortoise/tortoise-orm/issues/792
        connection_string = (
            f'{self.kind}://{self.user}:{quote_plus(self.password)}@{self.host}:{self.port}/{self.database}?maxsize=1'
        )
        if self.schema_name != DEFAULT_POSTGRES_SCHEMA:
            connection_string += f'&schema={self.schema_name}'
        return connection_string

    @property
    def hasura_connection_parameters(self) -> dict[str, Any]:
        return {
            'username': self.user,
            'password': self.password,
            'database': self.database,
            'host': self.host,
            'port': self.port,
        }


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class HttpConfig:
    """Advanced configuration of HTTP client

    :param retry_count: Number of retries after request failed before giving up
    :param retry_sleep: Sleep time between retries
    :param retry_multiplier: Multiplier for sleep time between retries
    :param ratelimit_rate: Number of requests per period ("drops" in leaky bucket)
    :param ratelimit_period: Time period for rate limiting in seconds
    :param ratelimit_sleep: Sleep time between requests when rate limit is reached
    :param connection_limit: Number of simultaneous connections
    :param connection_timeout: Connection timeout in seconds
    :param request_timeout: Request timeout in seconds
    :param batch_size: Number of items fetched in a single paginated request (when applicable)
    :param polling_interval: Interval between polling requests in seconds (when applicable)
    :param replay: Use cached HTTP responses instead of making real requests (dev only)
    :param replay_path: Use cached HTTP responses instead of making real requests (dev only)
    :param alias: Alias for this HTTP client (dev only)
    """

    retry_count: int | None = None
    retry_sleep: float | None = None
    retry_multiplier: float | None = None
    ratelimit_rate: int | None = None
    ratelimit_period: int | None = None
    ratelimit_sleep: float | None = None
    connection_limit: int | None = None
    connection_timeout: int | None = None
    request_timeout: int | None = None
    batch_size: int | None = None
    polling_interval: float | None = None
    replay: bool | None = None
    replay_path: str | Path | None = None
    alias: str | None = None


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class ResolvedHttpConfig:
    __doc__ = HttpConfig.__doc__

    retry_count: int = 10
    retry_sleep: float = 1.0
    retry_multiplier: float = 2.0
    ratelimit_rate: int = 0
    ratelimit_period: int = 0
    ratelimit_sleep: float = 0.0
    connection_limit: int = 100
    connection_timeout: int = 60
    request_timeout: int = 60
    batch_size: int = 10000
    polling_interval: float = 1.0
    replay: bool | None = None
    replay_path: str | Path | None = None
    alias: str | None = None

    @classmethod
    def create(
        cls,
        default: HttpConfig,
        user: HttpConfig | None,
    ) -> ResolvedHttpConfig:
        config = cls()
        # NOTE: Apply datasource defaults first
        for merge_config in (default, user):
            if merge_config is None:
                continue
            for k, v in merge_config.__dict__.items():
                if v is not None:
                    setattr(config, k, v)
        return config


class ContractConfig(ABC, NameMixin):
    """Contract config

    :param kind: Defined by child class
    :param typename: Alias for the typeclass directory
    """

    kind: str
    typename: str | None

    @property
    def module_name(self) -> str:
        return self.typename or self.name

    @property
    def module_path(self) -> Path:
        return Path(*self.module_name.split('.'))


class DatasourceConfig(ABC, NameMixin):
    """Base class for datasource configs

    :param kind: Defined by child class
    :param url: URL of the API
    :param http: HTTP connection tunables
    """

    kind: str
    url: str
    http: HttpConfig | None = None


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class HandlerConfig(CallbackMixin, ParentMixin['IndexConfig']):
    """Base class for index handlers

    :param callback: Callback name
    """

    def __post_init__(self) -> None:
        CallbackMixin.__post_init__(self)
        ParentMixin.__post_init__(self)


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class IndexTemplateConfig(NameMixin):
    """Index template config

    :param kind: always 'template'
    :param values: Values to be substituted in template (`<key>` -> `value`)
    :param first_level: Level to start indexing from
    :param last_level: Level to stop indexing at
    :param template: Template alias in `templates` section

    """

    kind = 'template'
    template: str
    values: dict[str, Any]
    first_level: int = 0
    last_level: int = 0


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class IndexConfig(ABC, NameMixin, ParentMixin['ResolvedIndexConfigU']):
    """Index config

    :param kind: Defined by child class
    :param datasources: Aliases of index datasources in `datasources` section
    """

    kind: str
    datasources: tuple[Alias[DatasourceConfig], ...]

    def __post_init__(self) -> None:
        NameMixin.__post_init__(self)
        ParentMixin.__post_init__(self)

        self._template_values: dict[str, str] = {}

    @abstractmethod
    def get_subscriptions(self) -> set[Subscription]: ...

    def hash(self) -> str:
        """Calculate hash to ensure config has not changed since last run."""
        import hashlib

        # FIXME: How to convert pydantic dataclass into dict without json.dumps? asdict is not recursive.
        config_json = orjson.dumps(self, default=to_jsonable_python)
        config_dict = orjson.loads(config_json)

        self.strip(config_dict)

        config_json = orjson.dumps(config_dict)
        return hashlib.sha256(config_json).hexdigest()

    @classmethod
    def strip(cls, config_dict: dict[str, Any]) -> None:
        """Strip config from tunables that are not needed for hash calculation."""
        for datasource in config_dict['datasources']:
            datasource.pop('http', None)
            datasource.pop('buffer_size', None)


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class HasuraConfig:
    """Config for the Hasura integration.

    :param url: URL of the Hasura instance.
    :param admin_secret: Admin secret of the Hasura instance.
    :param create_source: Whether source should be added to Hasura if missing.
    :param source: Hasura source for DipDup to configure, others will be left untouched.
    :param select_limit: Row limit for unauthenticated queries.
    :param allow_aggregations: Whether to allow aggregations in unauthenticated queries.
    :param allow_inconsistent_metadata: Whether to ignore errors when applying Hasura metadata.
    :param camel_case: Whether to use camelCase instead of default pascal_case for the field names.
    :param rest: Enable REST API both for autogenerated and custom queries.
    :param http: HTTP connection tunables
    :param hide_internal: Whether to make internal tables (prefixed with "dipdup") private.
    :param hide: List of table/view names to make private.
    """

    url: Url
    admin_secret: str | None = Field(default=None, repr=False)
    create_source: bool = False
    source: str = 'default'
    select_limit: int = 1000
    allow_aggregations: bool = True
    allow_inconsistent_metadata: bool = False
    camel_case: bool = False
    rest: bool = True
    http: HttpConfig | None = None
    hide_internal: bool = False
    hide: list[str] = Field(default_factory=list)

    @property
    def headers(self) -> dict[str, str]:
        """Headers to include with every request"""
        if self.admin_secret:
            return {'X-Hasura-Admin-Secret': self.admin_secret}
        return {}


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class JobConfig(NameMixin):
    """Job schedule config

    :param hook: Name of hook to run
    :param args: Arguments to pass to the hook
    :param crontab: Schedule with crontab syntax (`* * * * *`)
    :param interval: Schedule with interval in seconds
    :param daemon: Run hook as a daemon (never stops)
    """

    hook: Alias[HookConfig]
    args: dict[str, Any] = Field(default_factory=dict)
    crontab: str | None = None
    interval: int | None = None
    daemon: bool = False

    def __post_init__(self) -> None:
        schedules_enabled = sum(int(bool(x)) for x in (self.crontab, self.interval, self.daemon))
        if schedules_enabled > 1:
            raise ConfigurationError('Only one of `crontab`, `interval` of `daemon` can be specified')
        if not schedules_enabled:
            raise ConfigurationError('One of `crontab`, `interval` or `daemon` must be specified')

        NameMixin.__post_init__(self)


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SentryConfig:
    """Config for Sentry integration.

    :param dsn: DSN of the Sentry instance
    :param environment: Environment; if not set, guessed from docker/ci/gha/local.
    :param server_name: Server name; defaults to obfuscated hostname.
    :param release: Release version; defaults to DipDup package version.
    :param user_id: User ID; defaults to obfuscated package/environment.
    :param debug: Catch warning messages, increase verbosity.
    """

    dsn: str | None = None
    environment: str | None = None
    server_name: str | None = None
    release: str | None = None
    user_id: str | None = None
    debug: bool = False


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class PrometheusConfig:
    """Config for Prometheus integration.

    :param host: Host to bind to
    :param port: Port to bind to
    :param update_interval: Interval to update some metrics in seconds
    """

    host: str = '127.0.0.1'
    port: int = 8000
    update_interval: float = 1.0


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class HookConfig(CallbackMixin):
    """Hook config

    :param callback: Callback name
    :param args: Mapping of argument names and annotations (checked lazily when possible)
    :param atomic: Wrap hook in a single database transaction
    """

    args: dict[str, str] = Field(default_factory=dict)
    atomic: bool = False

    def iter_arguments(self) -> Iterator[tuple[str, str]]:
        yield 'ctx', 'HookContext'
        for name, annotation in self.args.items():
            yield name, annotation.split('.')[-1]

    def iter_imports(self, package: str) -> Iterator[tuple[str, str]]:
        yield 'dipdup.context', 'HookContext'
        for _, annotation in self.args.items():
            with suppress(ValueError):
                package, obj = annotation.rsplit('.', 1)
                yield package, obj


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class SystemHookConfig(HookConfig):
    __doc__ = HookConfig.__doc__


SYSTEM_HOOKS = {
    # NOTE: Fires on every run after datasources and schema are initialized.
    # NOTE: Default: nothing.
    'on_restart': SystemHookConfig(
        callback='on_restart',
    ),
    # NOTE: Fires on rollback which affects specific index and can't be processed unattended.
    # NOTE: Default: database rollback.
    'on_index_rollback': SystemHookConfig(
        callback='on_index_rollback',
        args={
            'index': 'dipdup.index.Index',
            'from_level': 'int',
            'to_level': 'int',
        },
    ),
    # NOTE: Fires when DipDup runs with empty schema, right after schema is initialized.
    # NOTE: Default: nothing.
    'on_reindex': SystemHookConfig(
        callback='on_reindex',
    ),
    # NOTE: Fires when all indexes reach REALTIME state.
    # NOTE: Default: nothing.
    'on_synchronized': SystemHookConfig(
        callback='on_synchronized',
    ),
}


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class ApiConfig:
    """Management API config

    :param host: Host to bind to
    :param port: Port to bind to
    """

    host: str = '127.0.0.1'
    port: int = 46339  # dial INDEX 😎


# NOTE: Should be the only place where extras are allowed
@dataclass(config=ConfigDict(extra='allow', defer_build=True), kw_only=True)
class AdvancedConfig:
    """This section allows users to tune some system-wide options, either experimental or unsuitable for generic configurations.

    :param reindex: Mapping of reindexing reasons and actions DipDup performs.
    :param scheduler: `apscheduler` scheduler config.
    :param postpone_jobs: Do not start job scheduler until all indexes reach the realtime state.
    :param early_realtime: Establish realtime connection and start collecting messages while sync is in progress (faster, but consumes more RAM).
    :param rollback_depth: A number of levels to keep for rollback.
    :param decimal_precision: Overwrite precision if it's not guessed correctly based on project models.
    :param unsafe_sqlite: Disable journaling and data integrity checks. Use only for testing.
    :param alt_operation_matcher: Use different algorithm to match Tezos operations (dev only)
    """

    reindex: dict[ReindexingReason, ReindexingAction] = Field(default_factory=dict)
    scheduler: dict[str, Any] | None = None
    postpone_jobs: bool = False
    early_realtime: bool = False
    rollback_depth: int | None = None
    decimal_precision: int | None = None
    unsafe_sqlite: bool = False
    alt_operation_matcher: bool = False


@dataclass(config=ConfigDict(extra='forbid', defer_build=True), kw_only=True)
class DipDupConfig:
    """DipDup project configuration file

    :param spec_version: Version of config specification, currently always `3.0`
    :param package: Name of indexer's Python package, existing or not
    :param datasources: Mapping of datasource aliases and datasource configs
    :param database: Database config
    :param contracts: Mapping of contract aliases and contract configs
    :param indexes: Mapping of index aliases and index configs
    :param templates: Mapping of template aliases and index templates
    :param jobs: Mapping of job aliases and job configs
    :param hooks: Mapping of hook aliases and hook configs
    :param hasura: Hasura integration config
    :param sentry: Sentry integration config
    :param prometheus: Prometheus integration config
    :param api: Management API config
    :param advanced: Advanced config
    :param custom: User-defined configuration to use in callbacks
    :param logging: Modify logging verbosity
    """

    spec_version: ToStr
    package: str
    datasources: dict[str, DatasourceConfigU] = Field(default_factory=dict)
    database: SqliteDatabaseConfig | PostgresDatabaseConfig = Field(
        default_factory=lambda *a, **kw: SqliteDatabaseConfig(kind='sqlite')
    )
    contracts: dict[str, ContractConfigU] = Field(default_factory=dict)
    indexes: dict[str, IndexConfigU] = Field(default_factory=dict)
    templates: dict[str, ResolvedIndexConfigU] = Field(default_factory=dict)
    jobs: dict[str, JobConfig] = Field(default_factory=dict)
    hooks: dict[str, HookConfig] = Field(default_factory=dict)
    hasura: HasuraConfig | None = None
    sentry: SentryConfig | None = None
    prometheus: PrometheusConfig | None = None
    api: ApiConfig | None = None
    advanced: AdvancedConfig = Field(default_factory=AdvancedConfig)
    custom: dict[str, Any] = Field(default_factory=dict)
    logging: dict[str, str | int] | str | int = 'INFO'

    def __post_init__(self) -> None:
        if self.package != pascal_to_snake(self.package):
            raise ConfigurationError('Python package name must be in snake_case.')

        self._paths: list[Path] = []
        self._environment: dict[str, str] = {}
        self._json = DipDupYAMLConfig()

    @property
    def schema_name(self) -> str:
        return self.database.schema_name

    @property
    def package_path(self) -> Path:
        return env.get_package_path(self.package)

    @classmethod
    def load(
        cls,
        paths: list[Path],
        environment: bool = True,
        raw: bool = False,
        unsafe: bool = False,
    ) -> DipDupConfig:
        config_json, config_environment = DipDupYAMLConfig.load(
            paths=paths,
            environment=environment,
            raw=raw,
            unsafe=unsafe,
        )

        try:
            # from pydantic.dataclasses import rebuild_dataclass
            # rebuild_dataclass(cls, force=True)

            config = TypeAdapter(cls).validate_python(config_json)
        except ConfigurationError:
            raise
        except ValidationError as e:
            msgs = []
            errors_by_path = defaultdict(list)
            for error in e.errors():
                loc = error['loc']
                index = 2 if isinstance(loc[-1], int) else 1
                path = '.'.join(str(e) for e in loc[:-index])
                errors_by_path[path].append(error)

            for path, errors in errors_by_path.items():
                fields = {error['loc'][-1] for error in errors}

                # NOTE: If `kind` or `type` don't match the expected value, skip this class; it's a wrong Union member.
                if 'kind' in fields or 'type' in fields:
                    continue

                for error in errors:
                    path = '.'.join(str(e) for e in error['loc'])
                    msgs.append(f'- {path}: {error["msg"]}')

            msg = 'Config validation failed:\n\n' + '\n'.join(msgs)
            raise ConfigurationError(msg) from e
        except Exception as e:
            raise ConfigurationError(str(e)) from e

        config._paths = paths
        config._json = config_json
        config._environment = config_environment
        return config

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        schema_dict = TypeAdapter(cls).json_schema()

        # NOTE: EVM addresses correctly parsed by Pydantic even if specified as integers
        fixed_anyof = [
            {'type': 'integer'},
            {'type': 'string'},
            {'type': 'null'},
        ]
        schema_dict['$defs']['EvmContractConfig']['properties']['address']['anyOf'] = fixed_anyof
        schema_dict['$defs']['EvmContractConfig']['properties']['abi']['anyOf'] = fixed_anyof
        schema_dict['$defs']['StarknetContractConfig']['properties']['address']['anyOf'] = fixed_anyof
        schema_dict['$defs']['StarknetContractConfig']['properties']['abi']['anyOf'] = fixed_anyof

        # NOTE: Environment configs don't have package/spec_version fields, but can't be loaded directly anyway.
        schema_dict['required'] = []

        # NOTE: `from_` fields should be passed without underscore
        fields_with_from = (
            schema_dict['$defs']['EvmTransactionsHandlerConfig']['properties'],
            schema_dict['$defs']['TezosTokenTransfersHandlerConfig']['properties'],
        )
        for fields in fields_with_from:
            fields['from'] = fields.pop('from_')

        # NOTE: Add description to the root schema; skipped by Pydantic for some reason
        schema_dict['description'] = cls.__doc__

        # NOTE: Extract param descriptions from the class docstrings and apply them to the schema
        param_regex = r':param ([a-zA-Z_0-9]*): ([^\n]*)'
        for def_dict in chain((schema_dict,), schema_dict['$defs'].values()):
            if 'properties' not in def_dict:
                continue
            param_descriptions = {}
            for match in re.finditer(param_regex, def_dict['description']):
                key, value = match.group(1), match.group(2)
                key = key if key != 'from_' else 'from'
                param_descriptions[key] = value
            def_dict['description'] = re.sub(param_regex, '', def_dict['description']).strip()
            for field_name, field_dict in def_dict['properties'].items():
                if field_name not in param_descriptions:
                    err = f'Missing `:param` description for `{def_dict["title"]}.{field_name}`'
                    raise ValueError(err)
                field_dict['title'] = field_name
                field_dict['description'] = param_descriptions[field_name]

                # NOTE: Don't duplicate single enum value in const fields
                if 'const' in field_dict:
                    field_dict.pop('enum', None)

        # NOTE: Fix root title as a final step
        schema_dict['title'] = 'DipDup'
        schema_dict['$schema'] = 'http://json-schema.org/draft-07/schema#'

        return schema_dict

    def get_contract(self, name: str) -> ContractConfig:
        try:
            return self.contracts[name]
        except KeyError as e:
            raise ConfigurationError(f'Contract `{name}` not found in `contracts` config section') from e

    def get_tezos_contract(self, name: str) -> TezosContractConfig:
        contract = self.get_contract(name)
        if not isinstance(contract, TezosContractConfig):
            raise ConfigurationError(f'Contract `{name}` is not a Tezos contract')
        return contract

    def get_evm_contract(self, name: str) -> EvmContractConfig:
        contract = self.get_contract(name)
        if not isinstance(contract, EvmContractConfig):
            raise ConfigurationError(f'Contract `{name}` is not an EVM contract')
        return contract

    def get_starknet_contract(self, name: str) -> StarknetContractConfig:
        contract = self.get_contract(name)
        if not isinstance(contract, StarknetContractConfig):
            raise ConfigurationError(f'Contract `{name}` is not an Starknet contract')
        return contract

    def get_datasource(self, name: str) -> DatasourceConfigU:
        try:
            return self.datasources[name]
        except KeyError as e:
            raise ConfigurationError(f'Datasource `{name}` not found in `datasources` config section') from e

    def get_index(self, name: str) -> IndexConfigU:
        try:
            return self.indexes[name]
        except KeyError as e:
            raise ConfigurationError(f'Index `{name}` not found in `indexes` config section') from e

    def get_template(self, name: str) -> ResolvedIndexConfigU:
        try:
            return self.templates[name]
        except KeyError as e:
            raise ConfigurationError(f'Template `{name}` not found in `templates` config section') from e

    def get_hook(self, name: str) -> HookConfig:
        try:
            return self.hooks[name]
        except KeyError as e:
            raise ConfigurationError(f'Hook `{name}` not found in `templates` config section') from e

    def get_tezos_tzkt_datasource(self, name: str) -> TezosTzktDatasourceConfig:
        datasource = self.get_datasource(name)
        if not isinstance(datasource, TezosTzktDatasourceConfig):
            raise ConfigurationError('`datasource` field must refer to TzKT datasource')
        return datasource

    def get_evm_subsquid_datasource(self, name: str) -> EvmSubsquidDatasourceConfig:
        datasource = self.get_datasource(name)
        if not isinstance(datasource, EvmSubsquidDatasourceConfig):
            raise ConfigurationError('`datasource` field must refer to Subsquid datasource')
        return datasource

    def get_evm_node_datasource(self, name: str) -> EvmNodeDatasourceConfig:
        datasource = self.get_datasource(name)
        if not isinstance(datasource, EvmNodeDatasourceConfig):
            raise ConfigurationError('`datasource` field must refer to TzKT datasource')
        return datasource

    def get_abi_etherscan_datasource(self, name: str) -> AbiEtherscanDatasourceConfig:
        datasource = self.get_datasource(name)
        if not isinstance(datasource, AbiEtherscanDatasourceConfig):
            raise ConfigurationError('`datasource` field must refer to Etherscan datasource')
        return datasource

    def set_up_logging(self) -> None:
        if isinstance(self.logging, dict):
            loglevels = {
                'dipdup': 'INFO',
                self.package: 'INFO',
                **self.logging,
            }
        else:
            loglevels = {
                'dipdup': self.logging,
                self.package: self.logging,
            }

        # NOTE: Environment variables have higher priority
        if env.DEBUG:
            loglevels['dipdup'] = 'DEBUG'
            loglevels[self.package] = 'DEBUG'

        for name, level in loglevels.items():
            try:
                if isinstance(level, str):
                    level = getattr(logging, level.upper())
                if not isinstance(level, int):
                    raise ValueError
            except (AttributeError, ValueError):
                raise ConfigurationError(f'Invalid logging level `{level}` for logger `{name}`') from None

            logging.getLogger(name).setLevel(level)

    def initialize(self) -> None:
        self._set_names()
        self._resolve_templates()
        self._resolve_aliases()
        self._validate()

    def dump(self) -> str:
        return DipDupYAMLConfig(
            **orjson.loads(
                orjson.dumps(
                    self,
                    default=to_jsonable_python,
                )
            )
        ).dump()

    def add_index(
        self,
        name: str,
        template: str,
        values: dict[str, Any],
        first_level: int = 0,
        last_level: int = 0,
    ) -> None:
        if name in self.indexes:
            raise IndexAlreadyExistsError(name)
        template_config = IndexTemplateConfig(
            template=template,
            values=values,
            first_level=first_level,
            last_level=last_level,
        )
        template_config._name = name
        self._resolve_template(template_config)
        index_config = cast(ResolvedIndexConfigU, self.indexes[name])
        self._resolve_index_links(index_config)
        index_config._name = name

    def _validate(self) -> None:
        # NOTE: Spec version
        if self.spec_version != __spec_version__:
            raise ConfigurationError(
                f'Incompatible spec version: expected {__spec_version__}, got {self.spec_version}. '
                'See https://dipdup.io/docs/config/spec_version'
            )

        # NOTE: Hasura and metadata interface
        if self.hasura:
            if isinstance(self.database, SqliteDatabaseConfig):
                raise ConfigurationError('SQLite database engine is not supported by Hasura')

        # NOTE: Hook names and callbacks
        for name, hook_config in self.hooks.items():
            if name != hook_config.callback:
                raise ConfigurationError(f'`{name}` hook name must be equal to `callback` value.')
            if name in SYSTEM_HOOKS:
                raise ConfigurationError(f'`{name}` hook name is reserved by system hook')

        # NOTE: Rollback depth euristics and validation
        rollback_depth = 0
        for name, datasource_config in self.datasources.items():
            try:
                rollback_depth = max(rollback_depth, datasource_config.rollback_depth or 0)  # type: ignore
            except AttributeError:
                continue

            if not isinstance(datasource_config, TezosTzktDatasourceConfig):
                continue
            if datasource_config.buffer_size and self.advanced.rollback_depth:
                raise ConfigurationError(
                    f'`{name}`: `buffer_size` option is incompatible with `advanced.rollback_depth`'
                )
        if self.advanced.rollback_depth is not None and rollback_depth > self.advanced.rollback_depth:
            raise ConfigurationError(
                '`advanced.rollback_depth` cannot be less than the maximum rollback depth of all index datasources'
            )
        self.advanced.rollback_depth = max(rollback_depth, self.advanced.rollback_depth or 0)

        if self.advanced.early_realtime:
            return

        # NOTE: Indexes that process only the current state imply early realtime.
        from dipdup.config.tezos_big_maps import TezosBigMapsIndexConfig
        from dipdup.config.tezos_token_balances import TezosTokenBalancesIndexConfig

        for name, index_config in self.indexes.items():
            is_big_maps = (
                isinstance(index_config, TezosBigMapsIndexConfig) and index_config.skip_history != SkipHistory.never
            )
            is_token_balances = isinstance(index_config, TezosTokenBalancesIndexConfig)
            if is_big_maps or is_token_balances:
                _logger.info('`%s` index is configured to skip history; implying `early_realtime` flag', name)
                self.advanced.early_realtime = True
                break

    def _resolve_template(self, template_config: IndexTemplateConfig) -> None:
        _logger.debug('Resolving index config `%s` from template `%s`', template_config.name, template_config.template)

        template = self.get_template(template_config.template)
        raw_template = orjson.dumps(template, default=to_jsonable_python).decode()
        for key, value in template_config.values.items():
            value_regex = r'<[ ]*' + key + r'[ ]*>'
            raw_template = re.sub(
                pattern=value_regex,
                repl=str(value),
                string=raw_template,
            )

        if missing_value := re.search(r'<*>', raw_template):
            raise ConfigurationError(
                f'`{template_config.name}` index config is missing required template value `{missing_value.group()}`'
            )

        json_template = orjson.loads(raw_template)
        new_index_config = template.__class__(**json_template)
        new_index_config._template_values = template_config.values
        new_index_config.parent = template
        new_index_config._name = template_config.name
        if not isinstance(new_index_config, TezosHeadIndexConfig):
            new_index_config.first_level |= template_config.first_level
            new_index_config.last_level |= template_config.last_level
        self.indexes[template_config.name] = new_index_config

    def _resolve_templates(self) -> None:
        for index_config in self.indexes.values():
            if isinstance(index_config, IndexTemplateConfig):
                self._resolve_template(index_config)

    def _resolve_aliases(self) -> None:
        for index_config in self.indexes.values():
            if isinstance(index_config, IndexTemplateConfig):
                raise ConfigInitializationException('Index templates must be resolved first')

            self._resolve_index_links(index_config)

        for job_config in self.jobs.values():
            if isinstance(job_config.hook, str):
                hook_config = self.get_hook(job_config.hook)
                if job_config.daemon and hook_config.atomic:
                    raise ConfigurationError('`HookConfig.atomic` and `JobConfig.daemon` flags are mutually exclusive')
                job_config.hook = hook_config

    def _resolve_index_links(self, index_config: ResolvedIndexConfigU) -> None:
        """Resolve contract and datasource configs by aliases.

        WARNING: str type checks are intentional! See `dipdup.config.patch_annotations`.
        """
        handler_config: HandlerConfig

        datasources = list(index_config.datasources)
        for i, datasource in enumerate(datasources):
            if isinstance(datasource, str):
                datasources[i] = self.get_datasource(datasource)  # type: ignore[assignment]
        index_config.datasources = tuple(datasources)  # type: ignore[assignment]

        if isinstance(index_config, TezosOperationsIndexConfig):
            if index_config.contracts is not None:
                for i, contract in enumerate(index_config.contracts):
                    if isinstance(contract, str):
                        index_config.contracts[i] = self.get_tezos_contract(contract)

            for handler_config in index_config.handlers:
                handler_config.parent = index_config
                for idx, pattern_config in enumerate(handler_config.pattern):
                    # NOTE: Untyped operations are named as `transaction_N` or `origination_N` based on their index
                    pattern_config._subgroup_index = idx

                    if isinstance(pattern_config, TezosOperationsHandlerTransactionPatternConfig):
                        if isinstance(pattern_config.destination, str):
                            pattern_config.destination = self.get_tezos_contract(pattern_config.destination)
                        if isinstance(pattern_config.source, str):
                            pattern_config.source = self.get_tezos_contract(pattern_config.source)

                    elif isinstance(pattern_config, TezosOperationsHandlerOriginationPatternConfig):
                        if isinstance(pattern_config.source, str):
                            pattern_config.source = self.get_tezos_contract(pattern_config.source)

                        if isinstance(pattern_config.originated_contract, str):
                            pattern_config.originated_contract = self.get_tezos_contract(
                                pattern_config.originated_contract
                            )

                    elif isinstance(pattern_config, TezosOperationsHandlerSmartRollupExecutePatternConfig):
                        if isinstance(pattern_config.destination, str):
                            pattern_config.destination = self.get_tezos_contract(pattern_config.destination)

                    elif isinstance(pattern_config, TezosOperationsHandlerSmartRollupCementPatternConfig):
                        if isinstance(pattern_config.destination, str):
                            pattern_config.destination = self.get_tezos_contract(pattern_config.destination)

        elif isinstance(index_config, TezosBigMapsIndexConfig):
            for handler_config in index_config.handlers:
                handler_config.parent = index_config
                if isinstance(handler_config.contract, str):
                    handler_config.contract = self.get_tezos_contract(handler_config.contract)

        elif isinstance(index_config, TezosHeadIndexConfig):
            index_config.handlers[0].parent = index_config

        elif isinstance(index_config, TezosTokenTransfersIndexConfig):
            for handler_config in index_config.handlers:
                handler_config.parent = index_config

                if isinstance(handler_config.contract, str):
                    handler_config.contract = self.get_tezos_contract(handler_config.contract)

                if isinstance(handler_config.from_, str):
                    handler_config.from_ = self.get_tezos_contract(handler_config.from_)

                if isinstance(handler_config.to, str):
                    handler_config.to = self.get_tezos_contract(handler_config.to)

        elif isinstance(index_config, TezosTokenBalancesIndexConfig):
            for handler_config in index_config.handlers:
                handler_config.parent = index_config

                if isinstance(handler_config.contract, str):
                    handler_config.contract = self.get_tezos_contract(handler_config.contract)

        elif isinstance(index_config, TezosOperationsUnfilteredIndexConfig):
            index_config.handlers[0].parent = index_config

        elif isinstance(index_config, TezosEventsIndexConfig):
            for handler_config in index_config.handlers:
                handler_config.parent = index_config

                if isinstance(handler_config.contract, str):
                    handler_config.contract = self.get_tezos_contract(handler_config.contract)

        elif isinstance(index_config, EvmEventsIndexConfig):
            for handler_config in index_config.handlers:
                handler_config.parent = index_config

                if isinstance(handler_config.contract, str):
                    handler_config.contract = self.get_evm_contract(handler_config.contract)

        elif isinstance(index_config, EvmTransactionsIndexConfig):
            for handler_config in index_config.handlers:
                handler_config.parent = index_config

                if isinstance(handler_config.to, str):
                    handler_config.to = self.get_evm_contract(handler_config.to)

                if isinstance(handler_config.from_, str):
                    handler_config.from_ = self.get_evm_contract(handler_config.from_)
        elif isinstance(index_config, StarknetEventsIndexConfig):
            for handler_config in index_config.handlers:
                handler_config.parent = index_config

                if isinstance(handler_config.contract, str):
                    handler_config.contract = self.get_starknet_contract(handler_config.contract)
        else:
            raise NotImplementedError(f'Index kind `{index_config.kind}` is not supported')

    def _set_names(self) -> None:
        named_config_sections = cast(
            tuple[dict[str, NameMixin], ...],
            (
                self.contracts,
                self.datasources,
                self.hooks,
                self.jobs,
                self.templates,
                self.indexes,
            ),
        )

        names: set[str] = set()
        for named_configs in named_config_sections:
            for name, config in named_configs.items():
                config._name = name
                if name in names:
                    _logger.warning('Alias `%s` used multiple times')
                else:
                    names.add(name)


"""
WARNING: A very dark magic ahead. Be extra careful when editing code below.
"""

# NOTE: Reimport to avoid circular imports
from dipdup.config.abi_etherscan import AbiEtherscanDatasourceConfig
from dipdup.config.coinbase import CoinbaseDatasourceConfig
from dipdup.config.evm import EvmContractConfig
from dipdup.config.evm_events import EvmEventsIndexConfig
from dipdup.config.evm_node import EvmNodeDatasourceConfig
from dipdup.config.evm_subsquid import EvmSubsquidDatasourceConfig
from dipdup.config.evm_transactions import EvmTransactionsIndexConfig
from dipdup.config.http import HttpDatasourceConfig
from dipdup.config.ipfs import IpfsDatasourceConfig
from dipdup.config.starknet import StarknetContractConfig
from dipdup.config.starknet_events import StarknetEventsIndexConfig
from dipdup.config.starknet_node import StarknetNodeDatasourceConfig
from dipdup.config.starknet_subsquid import StarknetSubsquidDatasourceConfig
from dipdup.config.tezos import TezosContractConfig
from dipdup.config.tezos_big_maps import TezosBigMapsIndexConfig
from dipdup.config.tezos_events import TezosEventsIndexConfig
from dipdup.config.tezos_head import TezosHeadIndexConfig
from dipdup.config.tezos_operations import TezosOperationsHandlerOriginationPatternConfig
from dipdup.config.tezos_operations import TezosOperationsHandlerSmartRollupCementPatternConfig
from dipdup.config.tezos_operations import TezosOperationsHandlerSmartRollupExecutePatternConfig
from dipdup.config.tezos_operations import TezosOperationsHandlerTransactionPatternConfig
from dipdup.config.tezos_operations import TezosOperationsIndexConfig
from dipdup.config.tezos_operations import TezosOperationsUnfilteredIndexConfig
from dipdup.config.tezos_token_balances import TezosTokenBalancesIndexConfig
from dipdup.config.tezos_token_transfers import TezosTokenTransfersIndexConfig
from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig
from dipdup.config.tzip_metadata import TzipMetadataDatasourceConfig

# NOTE: Unions for Pydantic config deserialization
ContractConfigU = EvmContractConfig | TezosContractConfig | StarknetContractConfig
DatasourceConfigU = (
    CoinbaseDatasourceConfig
    | AbiEtherscanDatasourceConfig
    | HttpDatasourceConfig
    | IpfsDatasourceConfig
    | EvmSubsquidDatasourceConfig
    | EvmNodeDatasourceConfig
    | TzipMetadataDatasourceConfig
    | TezosTzktDatasourceConfig
    | StarknetSubsquidDatasourceConfig
    | StarknetNodeDatasourceConfig
)
TezosIndexConfigU = (
    TezosBigMapsIndexConfig
    | TezosEventsIndexConfig
    | TezosHeadIndexConfig
    | TezosOperationsIndexConfig
    | TezosOperationsUnfilteredIndexConfig
    | TezosTokenTransfersIndexConfig
    | TezosTokenBalancesIndexConfig
)
EvmIndexConfigU = EvmEventsIndexConfig | EvmTransactionsIndexConfig
StarknetIndexConfigU = StarknetEventsIndexConfig

ResolvedIndexConfigU = TezosIndexConfigU | EvmIndexConfigU | StarknetIndexConfigU
IndexConfigU = ResolvedIndexConfigU | IndexTemplateConfig


def _patch_annotations() -> None:
    """Patch dataclass annotations in runtime to allow using aliases in config files.

    DipDup YAML config uses string aliases for contracts and datasources. During `DipDupConfig.load` these
    aliases are resolved to actual configs from corresponding sections and never become strings again.
    This hack allows to add `str` in Unions before loading config so we don't need to write `isinstance(...)`
    checks everywhere.
    """

    self = importlib.import_module(__name__)
    submodules = (
        *tuple(inspect.getmembers(self, inspect.ismodule)),
        (self.__name__, self),
    )

    for _, submodule in submodules:
        if not submodule.__name__.startswith('dipdup.config'):
            continue

        for attr in dir(submodule):
            value = getattr(submodule, attr)
            if not is_pydantic_dataclass(value) or 'Config' not in value.__name__:
                continue

            for name, annotation in value.__annotations__.items():
                # NOTE: All annotations must be strings for aliases to work
                if not isinstance(annotation, str):
                    raise RuntimeError(f'Add `from __future__ import annotations` to `{submodule.__name__}` module')

                # NOTE: Unwrap `Alias[...]` to 'str | ...' to allow using aliases in config files
                unwrapped = annotation

                while match := re.match(r'(.*)Alias\[(.*)', unwrapped):
                    before, body = match.groups()
                    body, after = body.split(']', 1)
                    unwrapped = f'{before}str | {body}{after}'

                if unwrapped != annotation:
                    value.__annotations__[name] = unwrapped
                    value.__pydantic_fields__[name].annotation = unwrapped  # type: ignore[assignment]
                    value.__dataclass_fields__[name].type = unwrapped


_patch_annotations()

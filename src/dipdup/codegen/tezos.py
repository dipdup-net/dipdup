"""Everything about Python code generation (`dipdup init`)

* TzKT JSONSchema processing
* Callback codegen with Jinja2 templates
* Types codegen with datamodel-codegen

For `dipdup new` templates processing see `dipdup.project` module.

Please, keep imports lazy to speed up startup.
"""

from pathlib import Path
from typing import Any
from typing import cast

import orjson

from dipdup.codegen import CodeGenerator
from dipdup.codegen import TypeClass
from dipdup.config import DipDupConfig
from dipdup.config.tezos import TezosContractConfig
from dipdup.config.tezos import is_contract_address
from dipdup.config.tezos import is_rollup_address
from dipdup.config.tezos_big_maps import TezosBigMapsIndexConfig
from dipdup.config.tezos_events import TezosEventsIndexConfig
from dipdup.config.tezos_events import TezosEventsUnknownEventHandlerConfig
from dipdup.config.tezos_operations import TezosOperationsHandlerOriginationPatternConfig as OriginationPatternConfig
from dipdup.config.tezos_operations import TezosOperationsHandlerPatternConfigU as PatternConfigU
from dipdup.config.tezos_operations import TezosOperationsHandlerTransactionPatternConfig as TransactionPatternConfig
from dipdup.config.tezos_operations import TezosOperationsIndexConfig
from dipdup.config.tezos_tzkt import TezosTzktDatasourceConfig
from dipdup.datasources import Datasource
from dipdup.datasources.tezos_tzkt import TezosTzktDatasource
from dipdup.datasources.tezos_tzkt import late_tzkt_initialization
from dipdup.exceptions import ConfigurationError
from dipdup.exceptions import FrameworkException
from dipdup.models.tezos import DEFAULT_ENTRYPOINT
from dipdup.package import DipDupPackage
from dipdup.utils import json_dumps
from dipdup.utils import pascal_to_snake
from dipdup.utils import snake_to_pascal
from dipdup.utils import write


def match_entrypoint_schema(entrypoint_name: str, entrypoint_schemas: list[dict[str, Any]]) -> dict[str, Any]:
    if entrypoint_name == DEFAULT_ENTRYPOINT and len(entrypoint_schemas) == 1:
        return entrypoint_schemas[0]['parameterSchema']  # type: ignore[no-any-return]
    return next(ep['parameterSchema'] for ep in entrypoint_schemas if ep['name'] == entrypoint_name)


def preprocess_storage_jsonschema(schema: dict[str, Any]) -> dict[str, Any]:
    """Preprocess `big_map` sections in JSONSchema.

    TzKT returns them as unions since before merging big map diffs there are just `int` pointers.
    We apply big map diffs to storage so there's no need to include `int` in type signature.
    """
    if not isinstance(schema, dict):
        return schema
    if 'oneOf' in schema:
        schema['oneOf'] = [preprocess_storage_jsonschema(sub_schema) for sub_schema in schema['oneOf']]

    if 'properties' in schema:
        return {
            **schema,
            'properties': {
                prop: preprocess_storage_jsonschema(sub_schema) for prop, sub_schema in schema['properties'].items()
            },
        }
    if 'items' in schema:
        return {
            **schema,
            'items': preprocess_storage_jsonschema(schema['items']),
        }
    if 'additionalProperties' in schema:
        return {
            **schema,
            'additionalProperties': preprocess_storage_jsonschema(schema['additionalProperties']),
        }
    if schema.get('$comment') == 'big_map':
        return cast(dict[str, Any], schema['oneOf'][1])
    return schema


class TezosCodeGenerator(CodeGenerator):
    """Generates package based on config, invoked from `init` CLI command"""

    kind = 'tezos'

    def __init__(
        self,
        config: DipDupConfig,
        package: DipDupPackage,
        datasources: dict[str, Datasource[Any]],
        include: set[str] | None = None,
    ) -> None:
        super().__init__(
            config=config,
            package=package,
            datasources=datasources,
            include=include,
        )
        self._contract_schemas: dict[str, dict[str, dict[str, Any]]] = {}
        self._rollup_schemas: dict[str, dict[str, Any]] = {}

    async def generate_abis(self) -> None:
        pass

    async def generate_schemas(self) -> None:
        """Fetch JSONSchemas for all contracts used in config"""
        self._cleanup_schemas()

        self._logger.info('Fetching contract schemas')
        await late_tzkt_initialization(
            config=self._config,
            datasources=self._datasources,
            reindex_fn=None,
        )

        unused_operation_templates = [
            t for t in self._config.templates.values() if isinstance(t, TezosOperationsIndexConfig)
        ]

        for index_config in self._config.indexes.values():
            if isinstance(index_config, TezosOperationsIndexConfig):
                await self._fetch_operation_index_schema(index_config)
                template = cast(TezosOperationsIndexConfig, index_config._parent)
                if template in unused_operation_templates:
                    unused_operation_templates.remove(template)
            elif isinstance(index_config, TezosBigMapsIndexConfig):
                await self._fetch_big_map_index_schema(index_config)
            elif isinstance(index_config, TezosEventsIndexConfig):
                await self._fetch_event_index_schema(index_config)
            else:
                pass

        # NOTE: Euristics for complex cases like templated `similar_to` factories.
        # NOTE: Try different contracts and datasources from config until one succeeds.
        for template_config in unused_operation_templates:
            self._logger.warning(
                'Unused operation template `%s`. Ignore this warning if it is used in a factory.', template_config.name
            )
            for datasource_name in template_config.datasources:
                if isinstance(datasource_name, str) and datasource_name in self._config.datasources:
                    datasource_config = self._config.get_tezos_tzkt_datasource(datasource_name)
                    template_config.datasources = (datasource_config,)
                    await self._fetch_operation_index_schema(template_config)
                else:
                    self._logger.info('Unresolved `datasource` field, trying to guess it.')
                    for possible_datasource_config in self._config.datasources.values():
                        if not isinstance(possible_datasource_config, TezosTzktDatasourceConfig):
                            continue
                        # NOTE: Do not modify config without necessity
                        template_config.datasources = (possible_datasource_config,)
                        template_config.contracts = [
                            c for c in self._config.contracts.values() if isinstance(c, TezosContractConfig)
                        ]
                        try:
                            await self._fetch_operation_index_schema(template_config)
                        except FrameworkException:
                            continue

    def get_typeclass_name(self, schema_path: Path) -> str:
        module_name = schema_path.stem
        if module_name == 'tezos_storage':
            class_name = f'{schema_path.parent.name}_storage'
        elif schema_path.parent.name == 'tezos_parameters':
            class_name = f'{module_name}_parameter'
        elif schema_path.parent.name == 'tezos_events':
            class_name = f'{module_name}_payload'
        else:
            class_name = module_name
        return snake_to_pascal(class_name)

    async def _generate_type(self, schema_path: Path, force: bool) -> None:
        markers = {
            'tezos_storage.json',
            'tezos_parameters',
            'tezos_events',
            'tezos_big_maps',
        }
        if not set(schema_path.parts).intersection(markers):
            return
        await super()._generate_type(schema_path, force)

    async def _get_schema(
        self,
        datasource_config: TezosTzktDatasourceConfig,
        contract_config: TezosContractConfig,
    ) -> dict[str, Any]:
        """Get contract JSONSchema from TzKT or from cache"""
        datasource = self._datasources[datasource_config.name]
        if not isinstance(datasource, TezosTzktDatasource):
            raise FrameworkException('`tzkt` datasource expected')

        if contract_config.address:
            address = contract_config.address
        elif contract_config.resolved_code_hash:
            address = await datasource.get_contract_address(contract_config.resolved_code_hash, 0)
        else:
            raise FrameworkException('No address or code hash provided, check earlier')

        if is_contract_address(address):
            schemas = self._contract_schemas
        elif is_rollup_address(address):
            schemas = self._rollup_schemas
        else:
            raise NotImplementedError

        name = datasource_config.name
        if name not in schemas:
            schemas[name] = {}
        if address not in schemas[name]:
            self._logger.info('Fetching schemas for contract `%s`', address)
            address_schemas_json = await datasource.get_jsonschemas(address)
            schemas[name][address] = address_schemas_json
        return schemas[name][address]

    async def _fetch_operation_pattern_schema(
        self,
        operation_pattern_config: PatternConfigU,
        datasource_config: TezosTzktDatasourceConfig,
    ) -> None:
        contract_config = operation_pattern_config.typed_contract
        if contract_config is None:
            return

        # NOTE: A very special case; unresolved `operation` template to spawn from factory indexes.
        if isinstance(contract_config, str) and contract_config in self._config.contracts:
            contract_config = self._config.get_tezos_contract(contract_config)

        elif isinstance(contract_config, str):
            self._logger.info('Unresolved `contract` field, trying to guess it.')
            for possible_contract_config in self._config.contracts.values():
                if not isinstance(possible_contract_config, TezosContractConfig):
                    continue

                if isinstance(operation_pattern_config, TransactionPatternConfig):
                    operation_pattern_config.destination = possible_contract_config
                elif isinstance(operation_pattern_config, OriginationPatternConfig):
                    operation_pattern_config.originated_contract = possible_contract_config
                try:
                    await self._fetch_operation_pattern_schema(
                        operation_pattern_config,
                        datasource_config=datasource_config,
                    )
                    break
                except FrameworkException:
                    self._logger.info("It's not `%s`", possible_contract_config.address)
                    continue

            return

        contract_schemas = await self._get_schema(datasource_config, contract_config)
        contract_schemas_path = self.schemas_dir / contract_config.module_name

        # NOTE: It's a rollup: entrypoint is always 'default', no storage
        if 'storageSchema' not in contract_schemas:
            contract_schemas = {
                'storageSchema': {'type': 'null'},
                'entrypoints': [
                    {
                        'parameterSchema': {**contract_schemas},
                    }
                ],
            }

        storage_schema_path = contract_schemas_path / 'tezos_storage.json'
        storage_schema = preprocess_storage_jsonschema(contract_schemas['storageSchema'])

        write(storage_schema_path, json_dumps(storage_schema))

        if not isinstance(operation_pattern_config, TransactionPatternConfig):
            return

        parameter_schemas_path = contract_schemas_path / 'tezos_parameters'
        entrypoint = cast(str, operation_pattern_config.entrypoint)

        try:
            entrypoint_schema = match_entrypoint_schema(
                entrypoint,
                contract_schemas['entrypoints'],
            )
        except StopIteration as e:
            raise ConfigurationError(f'Contract `{contract_config.address}` has no entrypoint `{entrypoint}`') from e
        entrypoint = entrypoint.replace('.', '_').lstrip('_')
        entrypoint_schema_path = parameter_schemas_path / f'{entrypoint}.json'
        written = write(entrypoint_schema_path, json_dumps(entrypoint_schema))
        if not written and contract_config.typename is not None:
            existing_schema = orjson.loads(entrypoint_schema_path.read_text())
            if entrypoint_schema != existing_schema:
                self._logger.warning(
                    'Contract `%s` falsely claims to be a `%s`', contract_config.address, contract_config.typename
                )

    async def _fetch_operation_index_schema(self, index_config: TezosOperationsIndexConfig) -> None:
        for handler_config in index_config.handlers:
            for operation_pattern_config in handler_config.pattern:
                await self._fetch_operation_pattern_schema(
                    operation_pattern_config,
                    index_config.datasources[0],
                )

    async def _fetch_big_map_index_schema(self, index_config: TezosBigMapsIndexConfig) -> None:
        for handler_config in index_config.handlers:
            contract_config = handler_config.contract

            contract_schemas = await self._get_schema(index_config.datasources[0], contract_config)

            contract_schemas_path = self.schemas_dir / contract_config.module_name
            big_map_schemas_path = contract_schemas_path / 'tezos_big_maps'

            try:
                big_map_schema = next(ep for ep in contract_schemas['bigMaps'] if ep['path'] == handler_config.path)
            except StopIteration as e:
                raise ConfigurationError(
                    f'Contract `{contract_config.address}` has no big map path `{handler_config.path}`'
                ) from e
            big_map_path = handler_config.path.replace('.', '_')
            big_map_key_schema = big_map_schema['keySchema']
            big_map_key_schema_path = big_map_schemas_path / f'{big_map_path}_key.json'
            write(
                big_map_key_schema_path,
                json_dumps(
                    big_map_key_schema,
                ),
            )

            big_map_value_schema = big_map_schema['valueSchema']
            big_map_value_schema_path = big_map_schemas_path / f'{big_map_path}_value.json'
            write(big_map_value_schema_path, json_dumps(big_map_value_schema))

    async def _fetch_event_index_schema(self, index_config: TezosEventsIndexConfig) -> None:
        for handler_config in index_config.handlers:
            if isinstance(handler_config, TezosEventsUnknownEventHandlerConfig):
                continue

            contract_config = handler_config.contract
            contract_schemas = await self._get_schema(
                index_config.random_datasource,
                contract_config,
            )
            contract_schemas_path = self.schemas_dir / contract_config.module_name
            event_schemas_path = contract_schemas_path / 'tezos_events'

            try:
                event_schema = next(ep for ep in contract_schemas['events'] if ep['tag'] == handler_config.tag)
            except StopIteration as e:
                raise ConfigurationError(
                    f'Contract `{contract_config.address}` has no event with tag `{handler_config.tag}`'
                ) from e

            event_tag = handler_config.tag.replace('.', '_')
            event_schema = event_schema['eventSchema']
            event_schema_path = event_schemas_path / f'{event_tag}.json'
            write(event_schema_path, json_dumps(event_schema))

    async def get_schemas(
        self,
        datasource: TezosTzktDatasource,
        contract_config: TezosContractConfig,
    ) -> dict[str, Any]:
        """Get contract JSONSchema from TzKT or from cache"""
        schemas: dict[str, Any] = {}

        if contract_config.address:
            address = contract_config.address
        elif contract_config.resolved_code_hash:
            address = await datasource.get_contract_address(contract_config.resolved_code_hash, 0)
        else:
            raise FrameworkException('No address or code hash provided, check earlier')

        if datasource.name not in schemas:
            schemas[datasource.name] = {}
        if address not in schemas[datasource.name]:
            self._logger.info('Fetching schemas for contract `%s`', address)
            address_schemas_json = await datasource.get_jsonschemas(address)
            schemas[datasource.name][address] = address_schemas_json
        return cast(dict[str, Any], schemas[datasource.name][address])


def get_storage_type(package: DipDupPackage, typename: str) -> TypeClass:
    cls_name = snake_to_pascal(typename) + 'Storage'
    return package.get_type(typename, 'tezos_storage', cls_name)


def get_parameter_type(package: DipDupPackage, typename: str, entrypoint: str) -> TypeClass:
    entrypoint = entrypoint.lstrip('_')
    module_name = f'tezos_parameters.{pascal_to_snake(entrypoint)}'
    cls_name = snake_to_pascal(entrypoint) + 'Parameter'
    return package.get_type(typename, module_name, cls_name)


def get_event_payload_type(package: DipDupPackage, typename: str, tag: str) -> TypeClass:
    tag = pascal_to_snake(tag.replace('.', '_'))
    module_name = f'tezos_events.{tag}'
    cls_name = snake_to_pascal(f'{tag}_payload')
    return package.get_type(typename, module_name, cls_name)


def get_big_map_key_type(package: DipDupPackage, typename: str, path: str) -> TypeClass:
    path = pascal_to_snake(path.replace('.', '_'))
    module_name = f'tezos_big_maps.{path}_key'
    cls_name = snake_to_pascal(path + '_key')
    return package.get_type(typename, module_name, cls_name)


def get_big_map_value_type(package: DipDupPackage, typename: str, path: str) -> TypeClass:
    path = pascal_to_snake(path.replace('.', '_'))
    module_name = f'tezos_big_maps.{path}_value'
    cls_name = snake_to_pascal(path + '_value')
    return package.get_type(typename, module_name, cls_name)

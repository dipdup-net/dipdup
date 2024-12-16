from pathlib import Path

from dipdup.codegen import CodeGenerator
from dipdup.config import HandlerConfig
from dipdup.config.starknet_events import StarknetEventsIndexConfig
from dipdup.utils import snake_to_pascal


class StarknetCodeGenerator(CodeGenerator):
    kind = 'starknet'

    # NOTE: For now ABIs need to be provided manually
    async def generate_abis(self) -> None: ...

    async def generate_schemas(self) -> None:
        from dipdup.abi.cairo import abi_to_jsonschemas

        self._cleanup_schemas()

        handler_config: HandlerConfig
        events: set[str] = set()

        for index_config in self._config.indexes.values():
            if isinstance(index_config, StarknetEventsIndexConfig):
                for handler_config in index_config.handlers:
                    events.add(handler_config.name)

        abi_to_jsonschemas(self._package, events)

    async def generate_hooks(self) -> None:
        pass

    async def generate_system_hooks(self) -> None:
        pass

    async def generate_handlers(self) -> None:
        pass

    def get_typeclass_name(self, schema_path: Path) -> str:
        module_name = schema_path.stem
        if schema_path.parent.name == 'starknet_events':
            class_name = f'{module_name}_payload'
        else:
            class_name = module_name
        return snake_to_pascal(class_name)

    async def _generate_type(self, schema_path: Path, force: bool) -> None:
        markers = {
            'starknet_events',
        }
        if not set(schema_path.parts).intersection(markers):
            return
        await super()._generate_type(schema_path, force)

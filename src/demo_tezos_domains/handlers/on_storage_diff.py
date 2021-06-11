import logging

import demo_tezos_domains.models as models
from demo_tezos_domains.types.name_registry.storage import NameRegistryStorage

_logger = logging.getLogger(__name__)


async def on_storage_diff(storage: NameRegistryStorage) -> None:
    for name, item in storage.store.records.items():  # type: ignore
        record_name = bytes.fromhex(name).decode()
        record_path = record_name.split('.')
        _logger.info('Processing `%s`', record_name)

        if len(record_path) != int(item.level):
            _logger.error('Invalid record `%s`: expected %s chunks, got %s', record_name, item.level, len(record_path))
            return

        if item.level == "1":
            await models.TLD.update_or_create(id=record_name, defaults=dict(owner=item.owner))
        else:
            if item.level == "2":
                await models.Domain.update_or_create(
                    id=record_name,
                    defaults=dict(
                        tld_id=record_path[-1],
                        owner=item.owner,
                        expiry=storage.store.expiry_map.get(item.expiry_key) if item.expiry_key else None,  # type: ignore
                        token_id=int(item.tzip12_token_id) if item.tzip12_token_id else None,
                    ),
                )

            await models.Record.update_or_create(id=record_name, defaults=dict(domain_id='.'.join(record_path[-2:]), address=item.address))

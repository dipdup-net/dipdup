# dipdup

[![PyPI version](https://badge.fury.io/py/dipdup.svg?)](https://badge.fury.io/py/dipdup)
[![Tests](https://github.com/dipdup-net/dipdup-py/workflows/Tests/badge.svg?)](https://github.com/baking-bad/dipdup/actions?query=workflow%3ATests)
[![Docker Build Status](https://img.shields.io/docker/cloud/build/bakingbad/dipdup)](https://hub.docker.com/r/bakingbad/dipdup)
[![Made With](https://img.shields.io/badge/made%20with-python-blue.svg?)](ttps://www.python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Python SDK for developing indexers of [Tezos](https://tezos.com/) smart contracts inspired by [The Graph](https://thegraph.com/).

## Installation

Python 3.7+ is required for dipdup to run.

```shell
$ pip install dupdup
```

## Creating indexer

### Write configuration file

Create a new YAML file and adapt the following example to your needs:

```yaml
spec_version: 0.0.1
package: dipdup_hic_et_nunc

database:
  path: db.sqlite3

contracts:
  HEN_objkts:
    network: mainnet
    address: KT1Hkg5qeNhfwpKW4fXvq7HGZB9z2EnmCCA9
  HEN_minter:
    network: mainnet
    address: KT1RJ6PbjHpwc3M5rw5s2Nbmefwbuwbdxton

datasources:
  tzkt_mainnet:
    tzkt:
      network: mainnet
      url: https://api.tzkt.io

indexes:
  operations_mainnet:
    operation:
      datasource: tzkt_mainnet
      contract: HEN_objkts
      first_block: 0
      handlers:

        - callback: on_mint
          pattern:
            - destination: HEN_objkts
              entrypoint: mint_OBJKT
            - destination: HEN_minter
              entrypoint: mint

        - callback: on_transfer
          pattern:
            - destination: HEN_minter
              entrypoint: transfer
```

### Initialize project structure

Run the following command replacing `config.yml` with path to YAML file you just created:

```shell
$ dipdup -c config.yml init
```

This command will create a new package with the following structure (some lines were omitted for readability):

```
dipdup_hic_et_nunc/
├── handlers
│   ├── on_mint.py
│   └── on_transfer.py
├── models.py
├── schemas
│   ├── KT1Hkg5qeNhfwpKW4fXvq7HGZB9z2EnmCCA9
│   │   └── parameter
│   │       └── mint_OBJKT.json
│   └── KT1RJ6PbjHpwc3M5rw5s2Nbmefwbuwbdxton
│       └── parameter
│           └── mint.json
└── types
    ├── KT1Hkg5qeNhfwpKW4fXvq7HGZB9z2EnmCCA9
    │   └── parameter
    │       └── mint_OBJKT.py
    └── KT1RJ6PbjHpwc3M5rw5s2Nbmefwbuwbdxton
        └── parameter
            └── mint.py
```

`schemas` directory is JSON schemas describing parameters of corresponding contract entrypoints. `types` are Pydantic dataclasses of these schemas. These two directories are autogenerated, you don't need to modify them. `models` and `handlers` modules will be discussed later.

### Define models

Dipdup uses [Tortoise](https://tortoise-orm.readthedocs.io/en/latest/) under the hood, fast asynchronous ORM supporting all major database engines. Check out [examples](https://tortoise-orm.readthedocs.io/en/latest/examples.html) to learn how to use is.

Now open `models.py` file in your project and define some models:
```python
from tortoise import Model, fields


class Address(Model):
    address = fields.CharField(58, pk=True)


class Token(Model):
    id = fields.IntField(pk=True)
    token_id = fields.IntField()
    token_info = fields.CharField(255)
    holder = fields.ForeignKeyField('models.Address', 'tokens')
    transaction = fields.ForeignKeyField('int_models.Transaction', 'tokens')
```
Pay attention to the optional `transaction` relation. It refers to internal Dipdup model and will be useful if you decide to implement rollback later.

### Write event handlers

Now take a look at `handlers` module generated by `init` command. When operation group matching `pattern` block of corresponding handler at config will arrive callback will be fired. This example will simply save minted Hic Et Nunc tokens and their owners to the database:

```python
from dipdup_hic_et_nunc.models import Address, Token
from dipdup_hic_et_nunc.types.KT1Hkg5qeNhfwpKW4fXvq7HGZB9z2EnmCCA9.parameter.mint_OBJKT import MintObjkt
from dipdup_hic_et_nunc.types.KT1RJ6PbjHpwc3M5rw5s2Nbmefwbuwbdxton.parameter.mint import Mint
from dipdup_dapps.models import HandlerContext


async def on_mint(
    mint_OBJKT: HandlerContext[MintObjkt],
    mint: HandlerContext[Mint]
) -> None:
    address, _ = await Address.get_or_create(address=mint.parameter.address)

    for _ in range(int(mint.parameter.amount)):
        token = Token(
            token_id=int(mint.parameter.token_id),
            token_info=mint.parameter.token_info[''],
            holder=address,
            transaction=mint.transaction,
        )
        await token.save()
```

### Run your dapp

Now everything is ready to run your indexer:
```shell
$ dipdup -c config.yml run
```

You can interrupt indexing at any moment, it will start from last processed block next time you run your app again.

Use `docker-compose.yml` included in this repo if you prefer to run dipdup in Docker:

```shell
$ docker-compose build
$ docker-compose up dipdup
```

## Contribution

To set up development environment you need to install [poetry](https://python-poetry.org/docs/#installation) package manager. Then run one of the following commands at project's root:
```shell
$ # install project dependencies
$ make install
$ # run linters
$ make lint
$ # run tests
$ make test cover
$ # run full CI pipeline
$ make
```

## Contact
* Telegram chat: [@baking_bad_chat](https://t.me/baking_bad_chat)
* Slack channel: [#baking-bad](https://tezos-dev.slack.com/archives/CV5NX7F2L)

## About
This project is maintained by [Baking Bad](https://baking-bad.org/) team.
Development is supported by [Tezos Foundation](https://tezos.foundation/).

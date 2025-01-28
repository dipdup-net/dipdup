# demo_tezos_nft_marketplace

NFT marketplace (hic at nunc)

## Installation

This project is based on [DipDup](https://dipdup.io), a framework for building featureful dapps.

You need a Linux/macOS system with Python 3.12 installed. To install DipDup with pipx or use our installer:

```shell
curl -Lsf https://dipdup.io/install.py | python3.12
```

See the [Installation](https://dipdup.io/docs/installation) page for all options.

## Usage

Run the indexer in memory:

```shell
dipdup run
```

Store data in SQLite database (defaults to /tmp, set `SQLITE_PATH` env variable):

```shell
dipdup -C sqlite run
```

Or spawn a Compose stack with PostgreSQL and Hasura:

```shell
make up
```

## Development setup

To set up the development environment:

```shell
make install
source .venv/bin/activate
```

Run `make all` to run full CI check or `make help` to see other available commands.
from enum import Enum


class TzipMetadataNetwork(Enum):
    """Tezos network enum for TZIP-16 metadata.

    :param mainnet: mainnet
    :param ghostnet: ghostnet
    :param nairobinet: nairobinet
    :param oxfordnet: oxfordnet
    :param parisnet: parisnet
    :param quebecnet: quebecnet
    """

    mainnet = 'mainnet'
    ghostnet = 'ghostnet'
    nairobinet = 'nairobinet'
    oxfordnet = 'oxfordnet'
    parisnet = 'parisnet'
    quebecnet = 'quebecnet'

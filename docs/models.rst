:orphan:

===============================================================================
Base classes
===============================================================================

.. autoclass:: dipdup.models.CachedModel
.. autoclass:: dipdup.models.Model

===============================================================================
Internal models
===============================================================================

.. autoclass:: dipdup.models.ContractMetadata
.. autoclass:: dipdup.models.Head
.. autoclass:: dipdup.models.TokenMetadata
.. autoclass:: dipdup.models.Contract
.. autoclass:: dipdup.models.ContractKind
.. autoclass:: dipdup.models.Index
.. autoclass:: dipdup.models.IndexStatus
.. autoclass:: dipdup.models.IndexType
.. autoclass:: dipdup.models.Schema
.. autoclass:: dipdup.models.ReindexingAction
.. autoclass:: dipdup.models.ReindexingReason
.. autoclass:: dipdup.models.SkipHistory
.. autoclass:: dipdup.models.Meta
.. autoclass:: dipdup.models.ModelUpdate
.. autoclass:: dipdup.models.ModelUpdateAction


===============================================================================
Datasource models
===============================================================================

-------------------------------------------------------------------------------
EVM
-------------------------------------------------------------------------------

.. autoclass:: dipdup.models.evm.EvmTransaction
.. autoclass:: dipdup.models.evm.EvmTransactionData
.. autoclass:: dipdup.models.evm.EvmEvent
.. autoclass:: dipdup.models.evm.EvmEventData

-------------------------------------------------------------------------------
Starknet
-------------------------------------------------------------------------------

.. autoclass:: dipdup.models.starknet.StarknetEvent
.. autoclass:: dipdup.models.starknet.StarknetEventData
.. autoclass:: dipdup.models.starknet.StarknetTransactionData

-------------------------------------------------------------------------------
Substrate
-------------------------------------------------------------------------------

.. autoclass:: dipdup.models.substrate.SubstrateEvent
.. autoclass:: dipdup.models.substrate.SubstrateEventData
.. autoclass:: dipdup.models.substrate.SubstrateHeadBlockData

-------------------------------------------------------------------------------
Tezos
-------------------------------------------------------------------------------

.. autoclass:: dipdup.models.tezos.TezosBigMapAction
.. autoclass:: dipdup.models.tezos.TezosBigMapData
.. autoclass:: dipdup.models.tezos.TezosBigMapDiff
.. autoclass:: dipdup.models.tezos.TezosBlockData
.. autoclass:: dipdup.models.tezos.TezosEvent
.. autoclass:: dipdup.models.tezos.TezosEventData
.. autoclass:: dipdup.models.tezos.TezosHeadBlockData
.. autoclass:: dipdup.models.tezos.TezosOperationData
.. autoclass:: dipdup.models.tezos.TezosOperationType
.. autoclass:: dipdup.models.tezos.TezosOrigination
.. autoclass:: dipdup.models.tezos.TezosQuoteData
.. autoclass:: dipdup.models.tezos.TezosSmartRollupCement
.. autoclass:: dipdup.models.tezos.TezosSmartRollupCommitment
.. autoclass:: dipdup.models.tezos.TezosSmartRollupExecute
.. autoclass:: dipdup.models.tezos.TezosTokenBalanceData
.. autoclass:: dipdup.models.tezos.TezosTokenStandard
.. autoclass:: dipdup.models.tezos.TezosTokenTransferData
.. autoclass:: dipdup.models.tezos.TezosTransaction
.. autoclass:: dipdup.models.tezos.TezosUnknownEvent

-------------------------------------------------------------------------------
Other
-------------------------------------------------------------------------------

.. autoclass:: dipdup.models.coinbase.CoinbaseCandleData
.. autoclass:: dipdup.models.coinbase.CoinbaseCandleInterval
.. autoclass:: dipdup.models.tzip_metadata.TzipMetadataNetwork
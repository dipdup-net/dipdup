import json
from os.path import dirname, join
from unittest import TestCase

from pytezos_dapps.datasources.tzkt.datasource import TzktDatasource
from pytezos_dapps.models import OperationData


class TzktDatasourceTest(TestCase):
    def test_convert_operation(self):
        with open(join(dirname(__file__), 'operations.json')) as file:
            operations_message = json.load(file)

        for operation_json in operations_message['data']:
            operation = TzktDatasource.convert_operation(operation_json)
            self.assertIsInstance(operation, OperationData)

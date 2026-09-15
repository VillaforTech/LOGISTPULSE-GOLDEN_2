import ast
from pathlib import Path
import unittest
from unittest.mock import MagicMock

class TransientError(Exception): pass
class BootstrapTests(unittest.TestCase):
    def bootstrap(self, service, connection):
        source=ast.parse(Path('services',service,'app.py').read_text())
        function=next(n for n in source.body if isinstance(n,ast.FunctionDef) and n.name=='bootstrap')
        namespace={'conn':connection,'psycopg':type('P',(),{'OperationalError':TransientError}),'time':MagicMock()}
        exec(compile(ast.Module(body=[function],type_ignores=[]), '<bootstrap>', 'exec'),namespace)
        return namespace['bootstrap']
    def test_seed_uses_cursor_and_commits(self):
        for service in ['inventory-api','logistics-api']:
            with self.subTest(service=service):
                c=MagicMock(); c.execute.return_value.fetchone.return_value=(0,)
                connect=MagicMock();connect.return_value.__enter__.return_value=c
                self.bootstrap(service,connect)()
                c.cursor.return_value.__enter__.return_value.executemany.assert_called_once()
                c.executemany.assert_not_called();c.commit.assert_called_once()
    def test_programming_errors_are_not_hidden(self):
        for service in ['inventory-api','logistics-api','fulfillment-api']:
            connect=MagicMock(side_effect=AttributeError('invalid API'))
            with self.assertRaises(AttributeError):self.bootstrap(service,connect)()
            self.assertEqual(connect.call_count,1)
    def test_transient_failure_exhaustion_stops_startup(self):
        for service in ['inventory-api','logistics-api','fulfillment-api']:
            connect=MagicMock(side_effect=TransientError())
            with self.assertRaises(RuntimeError):self.bootstrap(service,connect)()
    def test_existing_seed_is_not_duplicated(self):
        for service in ['inventory-api','logistics-api']:
            c=MagicMock();c.execute.return_value.fetchone.return_value=(4,)
            connect=MagicMock();connect.return_value.__enter__.return_value=c
            self.bootstrap(service,connect)()
            c.cursor.return_value.__enter__.return_value.executemany.assert_not_called();c.commit.assert_called_once()
if __name__=='__main__':unittest.main()

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy.exc import OperationalError

from sql_agent.intent_parser import IntentParser
from sql_agent.memory import SqlAgentMemoryRepository
from sql_agent.service import SqlAgentService
from sql_agent.sql_builder import SqlBuilder


class FailingEngine:
    def connect(self):
        raise OperationalError("SELECT 1", {}, RuntimeError("connection failed"))


class FailingConnector:
    def build_engine(self):
        return FailingEngine()


class ServiceDatabaseErrorTests(unittest.TestCase):
    def test_database_error_returns_sql_response_instead_of_raising(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            service = SqlAgentService(
                memory_repository=SqlAgentMemoryRepository(Path(temp_dir) / "memory.json"),
                database_connector=FailingConnector(),
                intent_parser=IntentParser(),
                sql_builder=SqlBuilder(),
            )

            response = service.ask_database("себестоимость товар с артикулом P084503")

        self.assertIn("SQL:", response)
        self.assertIn("FROM [DWH].[LLM].[cost] AS fact", response)
        self.assertIn("INNER JOIN [DWH].[LLM].[dimension_product] AS dim", response)
        self.assertIn("dim.[article] = 'P084503'", response)
        self.assertIn("Запрос не выполнен из-за ошибки подключения к SQL Server.", response)


if __name__ == "__main__":
    unittest.main()

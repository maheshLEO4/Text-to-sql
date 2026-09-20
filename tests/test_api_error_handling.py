import unittest
from unittest.mock import patch

from api.main import QueryRequest, pipeline_result_error_response, post_query, query_error_response
from generation.sql_generator import ModelRefusalError
from pipeline.pipeline_core import PipelineResult


class ApiErrorHandlingTests(unittest.TestCase):
    def test_model_refusal_is_a_client_error(self):
        error = query_error_response(ModelRefusalError("I cannot fulfill that request."))

        self.assertEqual(error.status_code, 400)
        self.assertIn("read-only SELECT", error.detail)

    def test_unexpected_pipeline_error_remains_server_error(self):
        error = query_error_response(RuntimeError("database unavailable"))

        self.assertEqual(error.status_code, 500)

    def test_guardrail_block_is_a_client_error(self):
        error = pipeline_result_error_response(PipelineResult(
            status="GUARDRAIL_BLOCKED",
            question="DROP TABLE products",
            guardrail_rejection_reason="Destructive SQL command detected: 'DROP TABLE'.",
        ))

        self.assertIsNotNone(error)
        self.assertEqual(error.status_code, 400)
        self.assertIn("Destructive queries are not permitted", error.detail)

    @patch("api.main.resolve_database_url", return_value="postgresql://example.test/db")
    @patch("api.main.run_pipeline")
    def test_post_query_does_not_record_blocked_query(self, run_pipeline_mock, _resolve_url_mock):
        run_pipeline_mock.return_value = PipelineResult(
            status="GUARDRAIL_BLOCKED",
            question="DELETE FROM products",
            guardrail_rejection_reason="Destructive SQL command detected: 'DELETE FROM'.",
        )

        with self.assertRaises(Exception) as raised:
            post_query(QueryRequest(question="DELETE FROM products"))

        self.assertEqual(raised.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
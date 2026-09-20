import unittest

from pipeline.pipeline_core import detect_destructive_request, run_pipeline


class PipelinePreflightTests(unittest.TestCase):
    def test_blocks_destructive_request_before_database_configuration(self):
        result = run_pipeline("DROP TABLE products;")

        self.assertEqual(result.status, "GUARDRAIL_BLOCKED")
        self.assertIn("DROP TABLE", result.guardrail_rejection_reason)

    def test_non_destructive_question_keeps_normal_configuration_path(self):
        self.assertIsNone(detect_destructive_request("Show me the products"))


if __name__ == "__main__":
    unittest.main()
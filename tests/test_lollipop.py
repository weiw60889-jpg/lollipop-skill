import importlib.util
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location("lollipop", Path(__file__).parents[1] / "scripts/lollipop.py")
lp = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lp)
IDENTIFIER = "00000000-0000-4000-8000-000000000000"


class ClientTests(unittest.TestCase):
    def sample(self):
        return {"status": "completed", "report_data": {"question_count": 1, "qa_reviews": [{"question_id": "q1", "question": "原题？", "reference_answer": "原文X%→Y%，保留'标点'。"}]}}

    def test_export_verbatim_and_count(self):
        text, count = lp.answers_markdown(self.sample(), IDENTIFIER)
        self.assertEqual(count, 1)
        self.assertIn("\n原文X%→Y%，保留'标点'。\n", text)

    def test_incomplete_export_does_not_replace_output(self):
        report = self.sample()
        report["report_data"]["qa_reviews"][0]["reference_answer"] = None
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "answers.md"
            output.write_text("original", encoding="utf-8")
            with patch.object(lp, "load_token", return_value="test"), patch.object(lp.LollipopClient, "get", return_value=report):
                self.assertEqual(lp.main(["answers", IDENTIFIER, "--output", str(output)]), 2)
            self.assertEqual(output.read_text(encoding="utf-8"), "original")

    def test_report_count_mismatch(self):
        report = self.sample()
        report["report_data"]["question_count"] = 2
        with self.assertRaises(lp.ClientError):
            lp.answers_markdown(report, IDENTIFIER)

    def test_host_validation(self):
        self.assertEqual(lp.report_id("https://lollipop.plus/report/" + IDENTIFIER), IDENTIFIER)
        for value in ("https://lollipop.plus.attacker.invalid/report/" + IDENTIFIER, "https://attacker.invalid/report/" + IDENTIFIER, "http://lollipop.plus/report/" + IDENTIFIER, "https://lollipop.plus@attacker.invalid/report/" + IDENTIFIER):
            with self.subTest(value=value), self.assertRaises(lp.ClientError):
                lp.report_id(value)

    def test_redirects_are_rejected(self):
        with self.assertRaises(lp.ClientError):
            lp.NoRedirects().redirect_request(None, None, 302, "", {}, "https://attacker.invalid")

    def test_non_readonly_endpoints_are_rejected(self):
        client = lp.LollipopClient("test")
        for path in ("https://attacker.invalid", "/api/payment/plans", "/api/reports/../../logout", "/api/history?next=bad"):
            with self.subTest(path=path), self.assertRaises(lp.ClientError):
                client.get(path)

    @unittest.skipUnless(lp.os.name == "nt", "Windows credential-store behavior")
    def test_windows_credential_is_encrypted_and_reusable(self):
        with tempfile.TemporaryDirectory() as folder, patch.dict(lp.os.environ, {"LOLLIPOP_AUTH_DIR": folder}):
            with patch.dict(lp.os.environ, {}, clear=True):
                lp.os.environ["LOLLIPOP_AUTH_DIR"] = folder
                lp.save_token("fake-test-token")
                raw = lp.auth_path().read_text(encoding="utf-8")
                self.assertNotIn("fake-test-token", raw)
                self.assertEqual(lp.load_token(), "fake-test-token")
                lp.remove_token()
                self.assertFalse(lp.auth_path().exists())


if __name__ == "__main__":
    unittest.main()

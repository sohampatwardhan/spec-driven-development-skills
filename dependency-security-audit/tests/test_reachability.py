"""Contract tests for conservative, evidence-based reachability loading."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
FIXTURES = Path(__file__).resolve().parent / "fixtures"
sys.path.insert(0, str(SCRIPTS))

from dependency_audit.models import Reachability  # noqa: E402
from dependency_audit.reachability import load_reachability  # noqa: E402


class ReachabilityLoaderTests(unittest.TestCase):
    """Verify positive evidence is retained and unsupported exclusions fail closed."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.result = load_reachability(FIXTURES / "reachability.json")

    def test_loads_reachable_and_proven_unreachable_annotations(self) -> None:
        reachable = self.result.lookup(
            "pkg:pypi/reachable@1.0.0", "OSV-REACH"
        )
        unreachable = self.result.lookup(
            "pkg:npm/unreachable@2.0.0", "GHSA-UNREACH"
        )

        self.assertEqual(reachable.state, Reachability.REACHABLE)
        self.assertEqual(reachable.methods, ("runtime_loading",))
        self.assertEqual(
            reachable.evidence, ("evidence/runtime-trace.json#event-42",)
        )
        self.assertEqual(unreachable.state, Reachability.UNREACHABLE)
        self.assertEqual(
            unreachable.evidence,
            ("evidence/bundle-manifest.json#excluded-components",),
        )

    def test_unsupported_or_evidence_free_unreachable_claims_become_unknown(self) -> None:
        unsupported = self.result.lookup(
            "pkg:cargo/unsupported@3.0.0", "CVE-UNSUPPORTED"
        )
        no_proof = self.result.lookup(
            "pkg:golang/no-proof@v1.0.0", "GO-NO-PROOF"
        )

        self.assertEqual(unsupported.state, Reachability.UNKNOWN)
        self.assertEqual(no_proof.state, Reachability.UNKNOWN)
        self.assertTrue(any("CVE-UNSUPPORTED" in item for item in self.result.diagnostics))
        self.assertTrue(any("GO-NO-PROOF" in item for item in self.result.diagnostics))

    def test_explicit_unknown_and_not_assessed_are_distinct(self) -> None:
        unknown = self.result.lookup(
            "pkg:pypi/unknown@1.0.0", "PYSEC-UNKNOWN"
        )
        not_assessed = self.result.lookup(
            "pkg:npm/not-assessed@1.0.0", "GHSA-NOT-ASSESSED"
        )

        self.assertEqual(unknown.state, Reachability.UNKNOWN)
        self.assertEqual(not_assessed.state, Reachability.NOT_ASSESSED)

    def test_reachable_evidence_wins_a_conflict_without_being_discarded(self) -> None:
        assessment = self.result.lookup(
            "pkg:pypi/conflict@1.0.0", "OSV-CONFLICT"
        )

        self.assertEqual(assessment.state, Reachability.REACHABLE)
        self.assertEqual(assessment.methods, ("direct_call",))
        self.assertEqual(
            assessment.evidence, ("evidence/runtime-trace.json#direct-call",)
        )
        self.assertTrue(any("OSV-CONFLICT" in item for item in self.result.diagnostics))

    def test_malformed_annotation_is_unknown_with_a_diagnostic(self) -> None:
        assessment = self.result.lookup(
            "pkg:pypi/malformed@1.0.0", "OSV-MALFORMED"
        )

        self.assertEqual(assessment.state, Reachability.UNKNOWN)
        self.assertTrue(any("OSV-MALFORMED" in item for item in self.result.diagnostics))

    def test_absent_annotation_is_not_assessed(self) -> None:
        result = load_reachability(None)

        self.assertTrue(result.available)
        self.assertEqual(
            result.lookup("pkg:pypi/missing@1.0.0", "OSV-MISSING").state,
            Reachability.NOT_ASSESSED,
        )

    def test_supplied_missing_or_malformed_file_fails_closed_to_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            malformed = root / "malformed.json"
            malformed.write_text("{not json", encoding="utf-8")

            missing_result = load_reachability(root / "missing.json")
            malformed_result = load_reachability(malformed)

        self.assertFalse(missing_result.available)
        self.assertFalse(malformed_result.available)
        self.assertEqual(
            missing_result.lookup("pkg:pypi/example@1", "OSV-1").state,
            Reachability.UNKNOWN,
        )
        self.assertEqual(
            malformed_result.lookup("pkg:pypi/example@1", "OSV-1").state,
            Reachability.UNKNOWN,
        )

    def test_duplicate_annotation_key_cannot_overwrite_reachable_evidence(self) -> None:
        raw_document = """{
          "schema_version": "1.0",
          "annotations": {
            "pkg:pypi/example@1|OSV-1": {
              "status": "reachable",
              "method": "direct_call",
              "evidence": ["evidence/runtime.json#call"],
              "producer": "runtime-tracer",
              "timestamp": "2026-08-08T12:00:00Z"
            },
            "pkg:pypi/example@1|OSV-1": {
              "status": "unreachable",
              "method": "call_graph_exclusion",
              "evidence": ["evidence/static.json#excluded"],
              "producer": "static-analyzer",
              "timestamp": "2026-08-08T12:01:00Z"
            }
          }
        }"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "duplicates.json"
            path.write_text(raw_document, encoding="utf-8")
            result = load_reachability(path)

        self.assertFalse(result.available)
        self.assertFalse(result.complete)
        self.assertEqual(
            result.lookup("pkg:pypi/example@1", "OSV-1").state,
            Reachability.UNKNOWN,
        )
        self.assertEqual(result.diagnostics, ("duplicate JSON object key rejected",))

    def test_accepts_schema_minor_versions_and_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compatible.json"
            path.write_text(
                """{
                  "schema_version": "1.1",
                  "future_document_field": {"ignored": true},
                  "annotations": {
                    "pkg:pypi/example@1|OSV-1": {
                      "status": "reachable",
                      "method": "execution_trace",
                      "evidence": ["evidence/trace.json#call"],
                      "producer": "runtime-tracer",
                      "timestamp": "2026-08-08T12:00:00Z",
                      "future_annotation_field": "ignored"
                    }
                  }
                }""",
                encoding="utf-8",
            )
            result = load_reachability(path)

        self.assertTrue(result.available)
        self.assertTrue(result.complete)
        self.assertEqual(
            result.lookup("pkg:pypi/example@1", "OSV-1").state,
            Reachability.REACHABLE,
        )

    def test_rejects_unsupported_or_nonparseable_schema_major(self) -> None:
        for schema_version in ("2.0", "v1", "1.x", ""):
            with self.subTest(schema_version=schema_version):
                with tempfile.TemporaryDirectory() as directory:
                    path = Path(directory) / "unsupported.json"
                    path.write_text(
                        json.dumps({
                            "schema_version": schema_version,
                            "annotations": {},
                        }),
                        encoding="utf-8",
                    )
                    result = load_reachability(path)

                self.assertFalse(result.available)
                self.assertFalse(result.complete)
                self.assertEqual(
                    result.lookup("pkg:pypi/example@1", "OSV-1").state,
                    Reachability.UNKNOWN,
                )

    def test_deep_unknown_field_fails_closed_without_recursion_escape(self) -> None:
        depth = 1_200
        raw_document = (
            '{"schema_version":"1","annotations":{},"future":'
            + "[" * depth
            + "0"
            + "]" * depth
            + "}"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "deep.json"
            path.write_text(raw_document, encoding="utf-8")
            result = load_reachability(path)

        self.assertFalse(result.available)
        self.assertFalse(result.complete)
        self.assertEqual(
            result.lookup("pkg:pypi/example@1", "OSV-1").state,
            Reachability.UNKNOWN,
        )
        self.assertEqual(
            result.diagnostics, ("reachability evidence exceeds nesting limit",)
        )

    def test_input_larger_than_one_mib_fails_closed_before_parsing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.json"
            path.write_bytes(b" " * (1024 * 1024 + 1))
            result = load_reachability(path)

        self.assertFalse(result.available)
        self.assertFalse(result.complete)
        self.assertEqual(
            result.lookup("pkg:pypi/example@1", "OSV-1").state,
            Reachability.UNKNOWN,
        )
        self.assertEqual(
            result.diagnostics,
            ("reachability evidence file exceeds 1 MiB limit",),
        )

    def test_bad_key_and_top_level_shape_are_rejected_without_crashing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "bad-shape.json"
            path.write_text(
                '{"schema_version":"1","annotations":{"missing-separator":{}}}',
                encoding="utf-8",
            )
            result = load_reachability(path)

        self.assertFalse(result.available)
        self.assertTrue(any("missing-separator" in item for item in result.diagnostics))


if __name__ == "__main__":
    unittest.main()

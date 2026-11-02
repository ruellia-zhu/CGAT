"""Regression coverage for generated, uploaded and legacy m8 directions."""
from __future__ import annotations

import configparser
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.core.issues import WgdiError
from app.wgdi.blast import for_wgdi
from app.wgdi.pipeline import Pipeline
from app.wgdi.project import GenomeInput, Project
from app.wgdi.runtime import Runtime


class BlastDirectionTests(unittest.TestCase):
    def setUp(self):
        base = ROOT / "build" / "bugfix_20261103" / "tests"
        base.mkdir(parents=True, exist_ok=True)
        self.project = Project(Path(tempfile.mkdtemp(dir=base)), self_compare=False,
                               genome_a=GenomeInput("A"), genome_b=GenomeInput("B"))
        self.project.prepare_dirs()
        self.a = self.project.prepared / "A.gff"
        self.b = self.project.prepared / "B.gff"
        self.a.write_text("chr1\ta1\t1\t300\t+\t1\tt1\n", encoding="utf-8")
        self.b.write_text("chr1\tb1\t1\t300\t+\t1\tt1\n", encoding="utf-8")
        self.source = self.project.work / "A-B.blastp.txt"
        self.target = self.project.work / "A-B.wgdi.blastp.txt"
        self.messages = []

    def row(self, q="b1", s="a1", bitscore=200):
        text = f"{q}\t{s}\t99\t80\t1\t0\t2\t81\t5\t84\t1e-30\t{bitscore}\n"
        self.source.write_text(text, encoding="utf-8")
        return text

    def prepare(self):
        return for_wgdi(self.source, self.a, self.b, self.target,
                        score=100, evalue=1e-5, log=self.messages.append)

    def test_reverse_preserves_source_and_swaps_coordinates(self):
        original = self.row()
        self.assertEqual(self.prepare(), self.target)
        self.assertEqual(self.source.read_text(), original)
        parts = self.target.read_text().split()
        self.assertEqual(parts[:2], ["a1", "b1"])
        self.assertEqual(parts[6:10], ["5", "84", "2", "81"])
        self.assertEqual(parts[10:], ["1e-30", "200"])

    def test_forward_keeps_original(self):
        self.row("a1", "b1")
        self.assertEqual(self.prepare(), self.source)
        self.assertFalse(self.target.exists())

    def test_forward_whitespace_and_comments_are_normalized(self):
        original = self.row("a1", "b1")
        self.source.write_text("# uploaded result\n" + original.replace("\t", " "))
        self.assertEqual(self.prepare(), self.target)
        self.assertEqual(self.target.read_text(), original)

    def test_importing_project_output_itself_preserves_resume(self):
        self.row()
        self.project.blast_input.source = "upload"
        self.project.blast_input.uploaded = str(self.source)
        pipeline = Pipeline(self.project, runtime=Runtime())
        self.assertTrue(pipeline.run_step("blast").ok)
        self.assertTrue(pipeline.run(only=["blast"])[0].skipped)

    def test_self_comparison_keeps_direction(self):
        self.b.write_text(self.a.read_text() + "chr1\ta2\t400\t700\t+\t2\tt2\n")
        self.a.write_text(self.b.read_text())
        self.row("a1", "a2")
        self.assertEqual(self.prepare(), self.source)

    def test_unknown_ids_are_actionable(self):
        self.row("unknown1", "unknown2")
        with self.assertRaisesRegex(WgdiError, "均不对应"):
            self.prepare()

    def test_score_failure_is_not_reported_as_id_mismatch(self):
        self.row(bitscore=20)
        with self.assertRaisesRegex(WgdiError, "阈值"):
            self.prepare()

    def test_empty_results(self):
        self.source.write_text("")
        with self.assertRaisesRegex(WgdiError, "没有比对记录"):
            self.prepare()

    def test_short_m8_rejected_before_wgdi(self):
        self.source.write_text("b1\ta1\t99\t80\t0\t0\n")
        with self.assertRaisesRegex(WgdiError, "12 列"):
            self.prepare()

    def test_non_numeric_score(self):
        self.row(bitscore="invalid")
        with self.assertRaisesRegex(WgdiError, "不是数字"):
            self.prepare()

    def test_non_numeric_evalue_even_on_low_score_row(self):
        self.source.write_text(self.row(bitscore=1).replace("1e-30", "invalid"))
        with self.assertRaisesRegex(WgdiError, "不是数字"):
            self.prepare()

    def test_later_steps_keep_correct_shared_conf(self):
        self.row()
        pipeline = Pipeline(self.project, runtime=Runtime(wgdi=Path("wgdi.exe")))
        for _ in range(2):
            conf = configparser.ConfigParser()
            conf.read(pipeline._ensure_conf(), encoding="utf-8")
            for section in ("dotplot", "collinearity", "blockinfo"):
                self.assertEqual(conf[section]["blast"], self.target.name)

    def test_uploaded_forward_result_keeps_direction(self):
        self.project.blast_input.source = "upload"
        self.row("a1", "b1")
        pipeline = Pipeline(self.project, runtime=Runtime(wgdi=Path("wgdi.exe")))
        conf = configparser.ConfigParser()
        conf.read(pipeline._ensure_conf(), encoding="utf-8")
        self.assertEqual(conf["blockinfo"]["blast"], self.source.name)

    def test_only_identical_self_hits_have_clear_message(self):
        self.b.write_text(self.a.read_text())
        self.row("a1", "a1")
        with self.assertRaisesRegex(WgdiError, "同名自身命中"):
            self.prepare()

    def test_rebuilt_when_source_changes(self):
        self.row()
        self.prepare()
        self.row(bitscore=300)
        self.assertTrue(self.prepare().read_text().endswith("\t300\n"))

    def test_all_three_wgdi_consumers_use_correct_direction(self):
        self.row()
        pipeline = Pipeline(self.project, runtime=Runtime(wgdi=Path("wgdi.exe")))
        for key, flag, section in (("dotplot", "-d", "dotplot"),
                                   ("collinearity", "-icl", "collinearity"),
                                   ("blockinfo", "-bi", "blockinfo")):
            def run(key, cmd, **kwargs):
                conf = configparser.ConfigParser()
                conf.read(self.project.work / cmd[-1], encoding="utf-8")
                self.assertEqual(conf[section]["blast"], self.target.name)
                for output in pipeline._outputs(key):
                    output.write_text("result")
                return 0
            with patch.object(pipeline, "_run", side_effect=run):
                pipeline._wgdi(key, flag)

    def test_wgdi_zero_exit_stop_is_failure_even_with_old_output(self):
        self.row()
        pipeline = Pipeline(self.project, runtime=Runtime(wgdi=Path("wgdi.exe")))
        pipeline._outputs("dotplot")[0].write_text("old")
        def run(*args, on_line, **kwargs):
            on_line("Stoped!")
            return 0
        with patch.object(pipeline, "_run", side_effect=run):
            result = pipeline.run(only=["dotplot"])[0]
        self.assertFalse(result.ok)
        self.assertEqual(self.project.step_state("dotplot"), "failed")

    def test_missing_wgdi_output_is_failure(self):
        self.row()
        pipeline = Pipeline(self.project, runtime=Runtime(wgdi=Path("wgdi.exe")))
        with patch.object(pipeline, "_run", return_value=0):
            with self.assertRaisesRegex(WgdiError, "未生成"):
                pipeline._wgdi("dotplot", "-d")


if __name__ == "__main__":
    unittest.main()

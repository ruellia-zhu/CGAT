"""Portable regressions for the 1.0.3 logic fixes; no external analysis data."""
import configparser
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from app.core.issues import WgdiError
from app.prep import build, gff3
from app.prep.extract import FastaReader
from app.prep.fai import index_fasta, needs_rewrap
from app.wgdi.pipeline import Pipeline
from app.wgdi.project import Project, GenomeInput
from app.wgdi.runtime import Runtime
from app.wgdi.cache import file_stamp
from app.wgdi.ks_inputs import merge_inputs, read_valid_ks
from app.wgdi import preview

BASE = ROOT / "build" / "bugfix_103_tests"
BASE.mkdir(parents=True, exist_ok=True)

def directory():
    return Path(tempfile.mkdtemp(dir=BASE))

def project():
    p = Project(directory(), self_compare=False, genome_a=GenomeInput("A"), genome_b=GenomeInput("B"), engine="diamond", threads=2)
    p.prepare_dirs()
    for prefix in ("A", "B"):
        (p.prepared / f"{prefix}.gff").write_text(f"chr1\t{prefix}1\t1\t9\t+\t1\tt1\n")
        (p.prepared / f"{prefix}.len").write_text("chr1\t100\t1\n")
        (p.prepared / f"{prefix}.wgdi.pep.fasta").write_text(f">{prefix}1\nMKK\n")
    return p

def complete(p, key):
    p.set_step(key, "done", signature=p.input_signature(key), output_stamps=[file_stamp(f) for f in p.outputs(key)])

def row(query="B1"):
    return f"{query}\tA1\t99\t3\t0\t0\t1\t3\t1\t3\t1e-30\t200\n"

class PreparationTests(unittest.TestCase):
    def test_coding_transcript_wins_over_long_noncoding(self):
        a=gff3.Transcript("coding","g1","chr1",1,99,"+",99,[(1,99)])
        b=gff3.Transcript("noncoding","g1","chr1",1,900,"+")
        choices,_=gff3.choose_longest({"a":a,"b":b})
        self.assertEqual(choices[0].transcript.tx_id,"coding")

    def test_annotation_order_and_multi_parent(self):
        d=directory()
        mrna="chr1\tx\tmRNA\t1\t30\t.\t+\t.\tID=t1;Parent=g1\nchr1\tx\tmRNA\t1\t30\t.\t+\t.\tID=t2;Parent=g1\n"
        cds="chr1\tx\tCDS\t1\t30\t.\t+\t0\tParent=t1,t2\n"
        for content in (mrna+cds,cds+mrna):
            (d/"ann.gff3").write_text(content)
            tx,_=gff3.read_annotation(d/"ann.gff3")
            self.assertEqual([(t.gene_id,t.start,t.cds_len) for t in tx.values()],[("g1",1,30)]*2)

    def test_cds_only_coordinates_begin_at_one(self):
        d=directory(); (d/"ann.gff3").write_text("chr1\tx\tCDS\t10\t30\t.\t+\t0\tParent=t1;gene_id=g1\n")
        tx,_=gff3.read_annotation(d/"ann.gff3")
        self.assertEqual((tx["t1"].start,tx["t1"].end),(10,30))

    def test_phase_on_both_strands(self):
        from app.prep.extract import reverse_complement
        for strand in ("+","-"):
            d=directory(); sequence="AATGAAATAG"
            if strand=="-": sequence=reverse_complement(sequence.encode()).decode()
            (d/"genome.fa").write_text(">chr1\n"+sequence+"\n")
            (d/"ann.gff3").write_text(f"chr1\tx\tmRNA\t1\t10\t.\t{strand}\t.\tID=t1;Parent=g1\nchr1\tx\tCDS\t1\t10\t.\t{strand}\t1\tParent=t1\n")
            out=build.prepare_auto(d/"genome.fa",d/"ann.gff3",d/"prepared","A",exclude=None)
            self.assertEqual(out.pep.read_text().splitlines()[1],"MK*")

    def test_phase_preserves_split_codon_across_exons(self):
        d=directory(); (d/"genome.fa").write_text(">chr1\nATGANNNNAATAG\n")
        (d/"ann.gff3").write_text("chr1\tx\tmRNA\t1\t13\t.\t+\t.\tID=t1;Parent=g1\nchr1\tx\tCDS\t1\t4\t.\t+\t0\tParent=t1\nchr1\tx\tCDS\t9\t13\t.\t+\t2\tParent=t1\n")
        out=build.prepare_auto(d/"genome.fa",d/"ann.gff3",d/"prepared","A",exclude=None)
        self.assertEqual(out.pep.read_text().splitlines()[1],"MK*")

    def test_ragged_fasta_is_rewrapped_before_extraction(self):
        d=directory(); (d/"genome.fa").write_bytes(b">chr1\nAAAAAA\nCC\nGGGGGG\nTT\n")
        recs,_=index_fasta(d/"genome.fa")
        self.assertTrue(needs_rewrap(recs)[0])
        with self.assertRaises(WgdiError): FastaReader(d/"genome.fa",recs)
        (d/"ann.gff3").write_text("chr1\tx\tmRNA\t9\t14\t.\t+\t.\tID=t1;Parent=g1\nchr1\tx\tCDS\t9\t14\t.\t+\t0\tParent=t1\n")
        out=build.prepare_auto(d/"genome.fa",d/"ann.gff3",d/"prepared","A",exclude=None)
        self.assertEqual(out.cds.read_text().splitlines()[1],"GGGGGG")

    def test_manual_filters_gff_and_protein_together(self):
        d=directory(); (d/"genome.len").write_text("chr1\t1000\t1\nscaffold1\t1000\t1\n")
        (d/"ann.gff3").write_text("chr1\tx\tmRNA\t1\t9\t.\t+\t.\tID=t1;Parent=g1\nscaffold1\tx\tmRNA\t1\t9\t.\t+\t.\tID=t2;Parent=g2\n")
        (d/"pep.fa").write_text(">t1\nMKK\n>t2\nMKT\n")
        out=build.prepare_manual(d/"genome.len",d/"ann.gff3",d/"pep.fa",None,d/"prepared","A")
        self.assertEqual(out.genes,1); self.assertNotIn("scaffold",out.gff.read_text()); self.assertNotIn("g2",out.pep.read_text())

    def test_manual_rejects_multiple_isoforms(self):
        d=directory(); (d/"genome.len").write_text("chr1\t1000\t1\n")
        (d/"ann.gff3").write_text("chr1\tx\tmRNA\t1\t9\t.\t+\t.\tID=t1;Parent=g1\nchr1\tx\tmRNA\t1\t12\t.\t+\t.\tID=t2;Parent=g1\n")
        (d/"pep.fa").write_text(">t1\nMKK\n>t2\nMKKT\n")
        with self.assertRaisesRegex(WgdiError,"多个转录本"):
            build.prepare_manual(d/"genome.len",d/"ann.gff3",d/"pep.fa",None,d/"prepared","A")

class StateAndCacheTests(unittest.TestCase):
    def setUp(self):
        self.p=project()
        self.pipe=Pipeline(self.p,runtime=Runtime(bins={k:Path(k+".exe") for k in ("diamond","blastp","makeblastdb")}))
        self.calls=[]
    def search(self,key,cmd,**kwargs):
        self.calls.append(cmd)
        path=Path(cmd[cmd.index("-o")+1] if "-o" in cmd else cmd[cmd.index("-out")+1])
        query=Path(cmd[cmd.index("-q")+1] if "-q" in cmd else cmd[cmd.index("-query")+1])
        ident=query.read_text().splitlines()[0][1:]
        path.write_text(row(ident))
        return 0
    def run_search(self):
        with patch.object(self.pipe,"_build_index",return_value=Path("db")),patch.object(self.pipe,"_run",side_effect=self.search):
            return self.pipe.run_step("blast")
    def test_same_search_reuses_only_completed_cache(self):
        self.assertTrue(self.run_search().ok); self.assertTrue(self.run_search().ok)
        self.assertEqual(len(self.calls),1)
    def test_engine_and_evalue_changes_recompute(self):
        self.run_search(); self.p.engine="blastp"; self.run_search()
        self.p.params=replace(self.p.params,evalue="1e-20"); self.run_search()
        self.assertEqual(len(self.calls),3)
    def test_input_change_recomputes_query(self):
        self.run_search(); (self.p.prepared/"B.wgdi.pep.fasta").write_text(">B2\nMKT\n")
        self.run_search(); self.assertEqual(len(self.calls),2)
        self.assertTrue(self.p.outputs("blast")[0].read_text().startswith("B2\t"))
    def test_failed_partial_chunk_is_retried(self):
        def fail(*args,**kwargs): self.search(*args,**kwargs); return 1
        with patch.object(self.pipe,"_build_index",return_value=Path("db")),patch.object(self.pipe,"_run",side_effect=fail):
            self.assertFalse(self.pipe.run_step("blast").ok)
        self.assertTrue(self.run_search().ok); self.assertEqual(len(self.calls),2)
    def test_filter_change_invalidates_done_steps(self):
        for k in ("blast","dotplot"):
            self.p.outputs(k)[0].write_text(row()); complete(self.p,k)
        self.p.params=replace(self.p.params,evalue="1e-20"); self.p.reconcile()
        self.assertEqual(self.p.step_state("blast"),"pending"); self.assertEqual(self.p.step_state("dotplot"),"pending")
    def test_missing_B_output_invalidates_prep(self):
        complete(self.p,"prep"); self.p.reconcile()
        self.assertEqual(self.p.step_state("prep"),"pending")
    def test_invalidated_preview_hides_old_file(self):
        self.p.outputs("dotplot")[0].write_bytes(b"old image"); self.p.reset_from("prep")
        self.assertIsNone(preview.build(self.p,"dotplot").image)
    def test_invalidated_upstream_cannot_be_used_by_single_step(self):
        self.p.outputs("blast")[0].write_text(row()); self.p.reset_from("prep")
        result=self.pipe.run_step("dotplot")
        self.assertFalse(result.ok); self.assertIn("请先完成",result.message)
    def test_pending_ks_not_consumed_by_blockinfo(self):
        self.p.outputs("ks")[0].write_text("old values"); self.p.reset_from("ks")
        c=configparser.ConfigParser(); c.read(self.pipe._ensure_conf(),encoding="utf-8")
        self.assertEqual(c["blockinfo"]["ks"],"none")
    def test_successful_output_preserved_in_history_on_rerun(self):
        self.run_search(); self.run_search()
        self.assertTrue(list((self.p.root/"history").rglob("*.blastp.txt")))
    def test_prefix_collision_rejected(self):
        self.p.genome_b.prefix="a"
        with self.assertRaisesRegex(WgdiError,"前缀相同"): self.p.validate()
    def test_merged_ks_files_are_single_valid_inputs(self):
        for g in self.p.genomes:
            (self.p.prepared/f"{g.prefix}.wgdi.cds.fasta").write_text(f">{g.prefix}1\nATGAAAAAA\n")
        c=configparser.ConfigParser(); c.read(self.pipe._ensure_conf(),encoding="utf-8")
        self.assertNotIn(";",c["ks"]["cds_file"])
        text=(self.p.work/c["ks"]["cds_file"]).read_text()
        self.assertIn(">A1",text); self.assertIn(">B1",text)
    def test_invalid_ks_rows_are_not_cache_hits(self):
        f=self.p.outputs("ks")[0]
        f.write_text("id1\tid2\tka_NG86\tks_NG86\tka_YN00\tks_YN00\nA1\tB1\n")
        self.assertEqual(read_valid_ks(f),{})
    def test_zero_valid_ks_rows_cannot_be_marked_done(self):
        self.pipe.runtime=Runtime(python=Path("python.exe"),wgdi=Path("wgdi.exe"),bins={k:Path(k) for k in ("muscle","yn00","perl","pal2nal")})
        for g in self.p.genomes:
            (self.p.prepared/f"{g.prefix}.wgdi.cds.fasta").write_text(f">{g.prefix}1\nATGAAAAAA\n")
        self.p.outputs("collinearity")[0].write_text("pairs")
        def run(key,cmd,**kwargs):
            c=configparser.ConfigParser(); c.read(self.p.work/cmd[-1],encoding="utf-8")
            Path(c["ks"]["ks_file"]).write_text("id1\tid2\tka_NG86\tks_NG86\tka_YN00\tks_YN00\n")
            return 0
        with patch.object(self.pipe,"_run",side_effect=run):
            result=self.pipe.run_step("ks")
        self.assertFalse(result.ok); self.assertEqual(self.p.step_state("ks"),"failed")
    def test_svg_only_export_actually_writes_svg(self):
        self.p.formats=["svg"]
        self.p.outputs("blockinfo")[0].write_text("id,chr1,chr2,block1,block2,length,pvalue\n1,chr1,chr1,1,1,1,0.01\n")
        result=self.pipe.run_step("circos")
        self.assertTrue(result.ok,result.message)
        self.assertTrue((self.p.results/"A-B.svg").exists()); self.assertFalse((self.p.results/"A-B.pdf").exists())

class UiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.app=QApplication.instance() or QApplication([])
    def panel(self):
        from app.ui.analysis import WizardPanel
        with patch("app.ui.analysis.default_projects_dir",return_value=BASE): return WizardPanel()
    def test_shared_score_and_evalue_are_synchronized(self):
        p=project(); panel=self.panel(); panel.set_project(p)
        panel.evalue.setText("1e-30"); panel._widgets["dotplot"]["score"].setValue(777)
        panel.apply_to(p)
        self.assertEqual((p.params.evalue,p.params.score),("1e-30",777))
    def test_labels_do_not_change_file_prefix(self):
        panel=self.panel(); panel.box_a.display.setText("species A"); panel.box_b.display.setText("species B")
        self.assertEqual(panel.box_a.to_input("A").prefix,"A"); self.assertEqual(panel.box_b.to_input("B").prefix,"B")
    def test_format_selection_is_persisted(self):
        p=project(); panel=self.panel(); panel.set_project(p)
        panel.fmt_pdf.setChecked(False); panel.fmt_png.setChecked(False); panel.apply_to(p)
        p.save(); self.assertEqual(Project.load(p.root).formats,["svg"])
    def test_open_project_restores_wizard(self):
        p=project(); p.save(); panel=self.panel(); panel.open_project(p.root)
        self.assertEqual(panel.project().root,p.root); self.assertEqual(panel.box_b.to_input("B").prefix,"B")
    def test_new_project_keeps_edited_settings(self):
        panel=self.panel(); d=directory()
        (d/"genome.fa").write_text(">chr1\nATGAAA\n"); (d/"ann.gff3").write_text("annotation")
        panel.dir_edit.setText(str(d)); panel.box_a.fields["genome"].setText(str(d/"genome.fa")); panel.box_a.fields["gff"].setText(str(d/"ann.gff3"))
        panel.only_chrom.setChecked(False); panel.evalue.setText("1e-30")
        p=panel.ensure_project()
        self.assertIsNotNone(p); self.assertFalse(p.filters.chromosomes_only); self.assertEqual(p.params.evalue,"1e-30")
    def test_nonfunctional_mafft_wrapper_is_not_available(self):
        from app.wgdi.runtime import usable_mafft
        exe=directory()/"mafft.bat"; exe.write_text("wrapper")
        with patch("app.wgdi.runtime._run",return_value="The system cannot execute the specified program."):
            self.assertFalse(usable_mafft(exe))
    def test_default_page_is_full_analysis(self):
        from PySide6.QtCore import QSettings
        from app.ui.main_window import MainWindow
        settings=QSettings(str(directory()/"ui.ini"),QSettings.IniFormat)
        with patch("app.ui.analysis.default_projects_dir",return_value=BASE),patch("app.ui.main_window.QSettings",return_value=settings),patch.object(MainWindow,"_load_demo"):
            window=MainWindow()
            self.assertEqual(window.page_switch.current(),0); self.assertEqual(window.panel_stack.currentIndex(),0)
            window.close()

if __name__=="__main__": unittest.main()

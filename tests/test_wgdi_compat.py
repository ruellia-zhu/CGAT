"""WGDI adapter regressions. Run with runtime/Scripts/python.exe."""
import configparser
import importlib.util
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
BASE=ROOT/"build"/"bugfix_103_compat_tests"
BASE.mkdir(parents=True,exist_ok=True)
os.environ["MPLBACKEND"]="Agg"
os.environ["MPLCONFIGDIR"]=str(BASE/"mpl")
from app.wgdi import runner
from app.wgdi.conf import render,GenomeFiles,WgdiParams
from app.wgdi.ks_inputs import read_valid_ks

@unittest.skipUnless(importlib.util.find_spec("wgdi"),"requires WGDI runtime")
class CompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp(dir=BASE))
        self.before=Path.cwd(); os.chdir(self.root)
        Path("A.cds").write_text(">A1\nATGAAAAAA\n>A2\nATGAAGAAG\n")
        Path("A.pep").write_text(">A1\nMKK\n>A2\nMKK\n")
        Path("A-A.collinearity.txt").write_text("# Alignment 1: score=100 pvalue=0.01 N=1 chr1&chr1 plus\nA1 1 A2 2 1\n")
        c=configparser.ConfigParser()
        c.read_string(render(GenomeFiles("A.gff","A.len","A.pep","A.cds"),GenomeFiles("A.gff","A.len","A.pep","A.cds"),"A-A","A","A",WgdiParams()))
        self.options=list(c["ks"].items())
    def tearDown(self): os.chdir(self.before)
    def test_failed_pairs_write_no_invalid_row_and_retry(self):
        from wgdi.ks import ks
        with patch.object(ks,"pair_kaks",return_value=None):
            with self.assertRaisesRegex(ValueError,"没有任何有效"):
                runner.run_ks(self.options)
        self.assertEqual(len(Path("A-A.ks").read_text().splitlines()),1)
        with Path("A-A.ks").open("a") as f: f.write("A1\tA2\n")
        with patch.object(ks,"pair_kaks",return_value=[0.1,0.2,0.1,0.3]) as pair:
            runner.run_ks(self.options)
            self.assertEqual(pair.call_count,1)
        self.assertEqual(len(read_valid_ks(Path("A-A.ks"))),1)
    def test_valid_pairs_are_reused(self):
        from wgdi.ks import ks
        Path("A-A.ks").write_text("id1\tid2\tka_NG86\tks_NG86\tka_YN00\tks_YN00\nA1\tA2\t0.1\t0.2\t0.1\t0.3\n")
        with patch.object(ks,"pair_kaks") as pair:
            runner.run_ks(self.options)
            pair.assert_not_called()
    def test_nonfinite_result_is_rejected(self):
        from wgdi.ks import ks
        with patch.object(ks,"pair_kaks",return_value=[0.1,float("inf"),0.1,0.2]):
            with self.assertRaisesRegex(ValueError,"没有任何有效"):
                runner.run_ks(self.options)
    def test_tool_exit_failure_cannot_produce_success(self):
        fake=self.root/"muscle.exe"; fake.write_bytes(b"fake")
        options=[(k,v) for k,v in self.options if k not in ("muscle_path","perl_path")]+[("muscle_path",str(fake)),("perl_path","perl.exe")]
        with patch("app.wgdi.runner.subprocess.run",side_effect=subprocess.CalledProcessError(1,[str(fake)])):
            with self.assertRaisesRegex(ValueError,"没有任何有效"):
                runner.run_ks(options)
    def test_tandem_switch_changes_retained_pairs(self):
        import pandas as pd
        import matplotlib.pyplot as plt
        import wgdi.block_ks as module
        Path("A.len").write_text("chr1\t1000\t100\n")
        pd.DataFrame([{"id":1,"chr1":"chr1","chr2":"chr1","length":2,"pvalue":0.001,
                       "block1":"1_2","block2":"2_3","ks":"0.2_0.3","ks_median":0.25,"start1":1,"start2":2,"end1":2,"end2":3}]).to_csv("A-A_block_information.csv",index=False)
        lengths=[]; original=plt.scatter
        def scatter(x,y,**kwargs):
            lengths.append(len(x)); return original(x,y,**kwargs)
        for enabled in (False,True):
            c=configparser.ConfigParser()
            c.read_string(render(GenomeFiles("A.gff","A.len"),GenomeFiles("A.gff","A.len"),"A-A","A","A",WgdiParams(bk_tandem=enabled,bk_block_length=1,bk_figsize="2,2")))
            with patch.object(module.plt,"scatter",side_effect=scatter),patch.object(module.plt,"savefig"),patch.object(module.plt,"show"):
                runner.run_blockks(list(c["blockks"].items()))
            plt.close("all")
        self.assertEqual(lengths,[0,2])

if __name__=="__main__": unittest.main()

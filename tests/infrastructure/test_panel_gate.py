import importlib.util
from pathlib import Path
import unittest
spec=importlib.util.spec_from_file_location('gate',Path('scripts/check-panel-evidence.py'))
gate=importlib.util.module_from_spec(spec);spec.loader.exec_module(gate)
class PanelGateTests(unittest.TestCase):
    def fixture(self):
        return {'measurementTarget':'grafana-render','requested':100,'observed':100,'lost':0,'errors':[], 'p95Ms':100, 'samples':[{'correlationId':str(i),'rendered':True,'correct':True,'quality':'FRESH','revision':i+1,'latencyMs':100} for i in range(100)]}
    def test_complete_evidence_passes(self):gate.verify(self.fixture())
    def test_partial_missing_and_loss_block(self):
        for change in [{'measurementTarget':'api'},{'coberturaParcialPanelPendiente':True},{'lost':1},{'observed':99},{'p95Ms':10}]:
            d=self.fixture();d.update(change)
            with self.assertRaises(AssertionError):gate.verify(d)
    def test_bad_samples_block(self):
        for change in [{'latencyMs':float('nan')},{'quality':'STALE'},{'correct':False},{'correlationId':'1'}]:
            d=self.fixture();d['samples'][0].update(change)
            with self.assertRaises(AssertionError):gate.verify(d)

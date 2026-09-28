"""Offline role input boundaries for the one-review factory."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from kojo.factory import instructions, stage_prompt

class FactoryTests(unittest.TestCase):
    def test_review_has_full_specs_but_no_prior_feedback(self):
        spec=SimpleNamespace(spec=lambda name,n:f'PUBLIC SPEC {n}')
        review=stage_prompt(spec,'review')
        for n in range(1,6): self.assertIn(f'PUBLIC SPEC {n}',review)
        self.assertNotIn('Feedback from',review)
        self.assertIn('Do not implement fixes',instructions(SimpleNamespace(python='/python'),'review'))

    def test_fix_requires_review_and_carries_it_exactly(self):
        spec=SimpleNamespace(spec=lambda name,n:f'PUBLIC SPEC {n}')
        with self.assertRaises(ValueError): stage_prompt(spec,'fix')
        feedback='Observed defect at line 42.\nReproduce with example.'
        self.assertTrue(stage_prompt(spec,'fix',feedback=feedback).endswith(feedback))

if __name__=='__main__': unittest.main()

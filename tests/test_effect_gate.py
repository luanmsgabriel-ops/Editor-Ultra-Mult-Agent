import copy
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from editorial_engine.effect_gate import audit, digest, load_unique

POLICY=Path(__file__).parent.parent / 'editorial_engine/effect_policy.json'

FIXTURE=Path(__file__).with_name('effect_gate_synthetic_fixture.json')

class Gates(unittest.TestCase):
    def setUp(self):
        self.tmp=TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name)
        self.run_files={}
        self.witness={}
        self.reports={}
        expected={'policy_sha256':digest(POLICY),'fixture_sha256':digest(FIXTURE)}
        pairs=load_unique(FIXTURE)['pairs']
        for name in ('reference','source','render','recipe'):
            p=root/name;p.write_text(name);self.run_files[name]=p
            expected[name+'_sha256']=digest(p)
        for eid,spec in load_unique(POLICY)['effects'].items():
            base={'effect_id':eid,'pair':pairs[eid],**expected,
                  'metrics':{k:l if l is not None else u for k,(l,u) in spec['requirements'].items()}}
            if 'anchor' in spec:base['anchor']=spec['anchor']
            report=copy.deepcopy(base)
            report.update(schema='ultra-effect-proof/1',authored_asset_hash_only=False)
            witness=root/(eid+'.json')
            witness.write_text(json.dumps({**base,'schema':'ultra-independent-witness/1'}))
            report['witness_sha256']=digest(witness)
            self.reports[eid]=report
            self.witness[eid]=witness
    def run_audit(self):
        return audit(POLICY,FIXTURE,self.run_files,self.reports,verifier_witnesses=self.witness)
    def metric(self,eid,metric,value):
        p=self.witness[eid]
        w=load_unique(p);w['metrics'][metric]=value
        p.write_text(json.dumps(w))
        self.reports[eid]['metrics'][metric]=value
        self.reports[eid]['witness_sha256']=digest(p)
    def expect(self,eid,status,issue):
        result=self.run_audit()
        self.assertEqual(result['status'],'changes_required')
        self.assertEqual(result['effects'][eid]['status'],status)
        self.assertIn(issue,result['effects'][eid]['issues'])
    def test_passing_mechanics_never_aesthetic_approval(self):
        result=self.run_audit()
        self.assertEqual(result['status'],'eligible_for_review')
        self.assertFalse(result['aesthetic_approved'])
    def test_missing_witness_fails_closed(self):
        eid='I03.projected_type';del self.witness[eid]
        self.expect(eid,'blocked','missing_independent_witness')
    def test_hash_registration_alone_fails_closed(self):
        eid='R02.glass_subtle';self.reports[eid]['authored_asset_hash_only']=True
        self.expect(eid,'blocked','alpha_or_asset_not_visual_proof')
    def test_flat_alpha_is_not_refraction(self):
        eid='R02.glass_subtle';self.metric(eid,'refraction_witness_mean_px',0.)
        self.expect(eid,'failed','out_of_bounds:refraction_witness_mean_px')
    def test_effect_at_wrong_phase(self):
        eid='R02.glass_warm_peak';self.metric(eid,'phase_error_frames',4)
        self.expect(eid,'failed','out_of_bounds:phase_error_frames')
    def test_missing_one_wide_band(self):
        eid='W03.text_hierarchy';self.metric(eid,'distinct_verified_glyph_bands',2)
        self.expect(eid,'failed','out_of_bounds:distinct_verified_glyph_bands')
    def test_no_hand_does_not_allow_chest_cluster_fallback(self):
        eid='C05.hand_clusters';self.metric(eid,'nonhand_anchor_count',2)
        self.expect(eid,'failed','out_of_bounds:nonhand_anchor_count')
    def test_glow_on_wrong_side(self):
        eid='C02.cool';self.metric(eid,'emitter_side_right',1)
        self.expect(eid,'failed','out_of_bounds:emitter_side_right')
    def test_witness_wrong_film(self):
        eid='R02.glass_subtle';self.run_files['render'].write_text('other')
        self.expect(eid,'blocked','witness_unbound:render_sha256')
    def test_bool_invalid_even_if_comparable(self):
        eid='W03.text_hierarchy';self.metric(eid,'arc_signed_curvature_matches',True)
        self.expect(eid,'blocked','missing_or_unverified_metric:arc_signed_curvature_matches')
    def test_nan_invalid(self):
        eid='R02.glass_subtle';self.metric(eid,'refraction_witness_mean_px',float('nan'))
        self.expect(eid,'blocked','missing_or_unverified_metric:refraction_witness_mean_px')
    def test_actual_disagrees_with_recipe(self):
        eid='C02.warm';self.reports[eid]['metrics']['target_local_glow_energy_ratio']=3.
        self.expect(eid,'blocked','missing_or_unverified_metric:target_local_glow_energy_ratio')
    def test_tampered_witness(self):
        eid='C02.warm';p=self.witness[eid];p.write_text(p.read_text()+'\n')
        self.expect(eid,'blocked','mismatch_independent_witness')
    def test_wrong_pair(self):
        eid='C02.cool';self.reports[eid]['pair']=[341,213]
        self.expect(eid,'blocked','wrong_marked_frame_pair')
    def test_unlisted_effect_is_not_approved(self):
        self.reports['invented_glitter']={}
        self.assertEqual(self.run_audit()['status'],'changes_required')

if __name__=='__main__': unittest.main()

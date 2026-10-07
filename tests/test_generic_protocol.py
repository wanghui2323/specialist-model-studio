from __future__ import annotations

import json
import unittest
from pathlib import Path
from copy import deepcopy

from model_harness.errors import ContractError
from model_harness.generic_protocol import execution_path_guide, execution_result_protocol, execution_spec_schema, validate_data_mapping, validate_execution_spec
from model_harness.isolated_execution import ExecutionBundle, OCIExecutor


def execution_spec():
    bundle = ExecutionBundle.create(
        files={'program.py': 'print("unseen objective")\n'},
        stages={stage: ['python', '/workspace/source/program.py', stage] for stage in ['qualify', 'train', 'evaluate', 'predict']},
        image='python@sha256:' + 'a' * 64,
    )
    return {'bundle': bundle.to_dict(), 'bundle_sha256': bundle.digest,
        'capability': {'objective': 'novel_geometric_constraint_prediction', 'input': {'format': 'arbitrary_coordinate_graph'}, 'output': 'score_and_layout'},
        'config': {'new_algorithm': {'regularizer': .3}},
        'data_mapping': [
            {'material_id': 'material-' + '1' * 24, 'inspection_sha256': 'b' * 64, 'split': 'train', 'csv_rows': {'start': 0, 'stop': 5}},
            {'material_id': 'material-' + '1' * 24, 'inspection_sha256': 'b' * 64, 'split': 'test', 'csv_rows': [5, 6]},
        ],
        'evaluation': {'primary_metric': 'constraint_violation', 'gates': {'constraint_violation': {'operator': 'lte', 'threshold': .2}}, 'minimum_test_samples': 2, 'test_unit': 'independent coordinate graph'},
        'artifacts': [{'path': 'model/custom.weights', 'role': 'model', 'export': True}],
        'inference': {'extensions': ['.xyzgraph'], 'max_bytes': 1024, 'schema': {'type': 'object'}},
        'description': 'An unknown model objective sharing the same generic protocol.'}


class GenericProtocolTests(unittest.TestCase):
    def test_unknown_business_objective_is_open_and_normalization_is_stable(self):
        raw = execution_spec()
        before = deepcopy(raw)
        normalized = validate_execution_spec(raw)
        self.assertEqual(normalized['capability'], raw['capability'])
        self.assertEqual(normalized['inference']['extensions'], ['.xyzgraph'])
        self.assertEqual(normalized['asset_ids'], [])
        self.assertEqual(validate_execution_spec(normalized), normalized)
        self.assertEqual(raw, before)
        raw['evaluation']['primary_metric'] = '验证/结构误差'
        raw['evaluation']['gates'] = {'验证/结构误差': {'operator': 'lte', 'threshold': .3}}
        self.assertEqual(validate_execution_spec(raw)['evaluation']['primary_metric'], '验证/结构误差')

    def test_discovery_schema_matches_open_capability_and_canonical_workflow(self):
        schema = execution_spec_schema()
        self.assertTrue(schema['properties']['capability']['additionalProperties'])
        self.assertNotIn('enum', schema['properties']['capability'])
        self.assertEqual(schema['properties']['bundle']['properties']['stages']['required'], ['qualify', 'train', 'evaluate', 'predict'])
        self.assertEqual(schema['x-protocol']['stage_outputs']['predict'], 'infer_result.json')
        try:
            import jsonschema
        except ImportError:
            return
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.validate(execution_spec(), schema)

    def test_discovery_documents_actual_workdir_without_rewriting_relative_argv(self):
        guide = execution_path_guide()
        schema = execution_spec_schema()
        self.assertEqual(guide['working_directory'], '/workspace/output')
        self.assertIn('empty', guide['working_directory_initial_state'])
        self.assertEqual(guide['source_argv_example'], ['python', '/workspace/source/run.py', 'qualify'])
        self.assertIn('/workspace/output/run.py', guide['relative_argv_policy'])
        self.assertEqual(schema['x-protocol']['working_directory'], guide['working_directory'])
        self.assertIn('/workspace/source/run.py', schema['properties']['bundle']['properties']['stages']['additionalProperties']['description'])
        raw = execution_spec()
        raw['bundle']['files'] = {'run.py': '# command-shape fixture, never executed\n'}
        raw['bundle']['stages']['qualify'] = ['python', 'run.py', 'qualify']
        raw.pop('bundle_sha256')
        original = ExecutionBundle.from_dict(raw['bundle'])
        normalized = validate_execution_spec(raw)
        self.assertEqual(normalized['bundle_sha256'], original.digest)
        self.assertEqual(normalized['bundle']['stages']['qualify'], ['python', 'run.py', 'qualify'])
        command = OCIExecutor._command('/fixture/docker', original, 'qualify', 'fixture', Path('/fixture/source'), Path('/fixture/input'), Path('/fixture/output'))
        self.assertEqual(command[command.index('--workdir') + 1], guide['working_directory'])
        self.assertEqual(command[-2:], ['run.py', 'qualify'])

    def test_stage_result_schemas_accept_examples_and_reject_observed_shape_errors(self):
        from jsonschema import Draft202012Validator
        protocol = execution_result_protocol()
        contracts = protocol['stage_result_contracts']
        for stage, contract in contracts.items():
            with self.subTest(stage=stage):
                Draft202012Validator.check_schema(contract['schema'])
                Draft202012Validator(contract['schema']).validate(contract['example'])
        Draft202012Validator(contracts['qualify']['schema']).validate(contracts['qualify']['failure_example'])
        bad = [
            ('qualify', {'valid': True, 'checks': {'model_reload': True}}),
            ('qualify', {'checks': contracts['qualify']['example']['checks']}),
            ('qualify', {'valid': True, 'checks': [{'name': 'model_reload', 'passed': True}]}),
            ('train', {**contracts['train']['example'], 'validation_candidates': {'candidate_a': {'best_selection': {'objective_error': .1}}}}),
            ('train', {**contracts['train']['example'], 'validation_candidates': {'candidate_a': {'objective_error': True}}}),
            ('evaluate', {'metrics': {'objective_error': None}, 'sample_count': 2}),
            ('predict', {'value': 1}),
            ('predict', {'prediction': 1, 'artifacts': [{'path': 'output.json'}]}),
        ]
        for stage, payload in bad:
            with self.subTest(stage=stage, payload=payload):
                self.assertFalse(Draft202012Validator(contracts[stage]['schema']).is_valid(payload))
        # Relationships to candidate keys, frozen gates and producing stages
        # remain runtime invariants; discovery must not claim schemas prove them.
        self.assertIn('existing key', ' '.join(contracts['train']['requirements']))
        self.assertIn('every exact key', ' '.join(contracts['evaluate']['requirements']))
        self.assertIn('not evidence', execution_result_protocol.__doc__)

    def test_artifact_stage_defaults_are_legacy_compatible_and_models_stay_train_only(self):
        old = execution_spec()
        normalized = validate_execution_spec(old)
        self.assertEqual(normalized['artifacts'], old['artifacts'])
        self.assertNotIn('stage', normalized['artifacts'][0])
        old['artifacts'].append({'path': 'named-report.json', 'role': 'report', 'export': True, 'stage': 'evaluate'})
        self.assertEqual(validate_execution_spec(old)['artifacts'][-1]['stage'], 'evaluate')
        schema = execution_spec_schema()['properties']['artifacts']['items']['properties']['stage']
        self.assertEqual(schema['enum'], ['train', 'evaluate'])
        self.assertEqual(schema['default'], 'train')
        for stage, role in [('predict', 'report'), ('qualify', 'report'), ('evaluate', 'model'), ('evaluate', 'checkpoint'), ('evaluate', 'weights')]:
            spec = execution_spec()
            spec['artifacts'][0].update(stage=stage, role=role)
            with self.subTest(stage=stage, role=role), self.assertRaises(ContractError):
                validate_execution_spec(spec)

    def test_bundle_digest_stages_and_pinned_image_are_enforced(self):
        raw = execution_spec()
        for mutation in [lambda spec: spec.update(bundle_sha256='0' * 64), lambda spec: spec['bundle']['stages'].pop('predict'), lambda spec: spec['bundle'].update(image='python:latest')]:
            value = deepcopy(raw); mutation(value)
            with self.assertRaises(ContractError):
                validate_execution_spec(value)

    def test_stage_budgets_are_discoverable_immutable_and_keep_legacy_specs_unchanged(self):
        old = validate_execution_spec(execution_spec())
        self.assertNotIn('stage_limits', old['bundle'])
        raw = execution_spec()
        raw['bundle']['limits'] = {'timeout_seconds': 180}
        raw['bundle']['stage_limits'] = {'qualify': {'timeout_seconds': 60}, 'predict': {'timeout_seconds': 30}}
        raw.pop('bundle_sha256', None)
        normalized = validate_execution_spec(raw)
        self.assertEqual(normalized['bundle']['stage_limits']['qualify']['timeout_seconds'], 60)
        self.assertEqual(normalized['bundle']['limits']['timeout_seconds'], 180)
        self.assertEqual(validate_execution_spec(normalized), normalized)
        schema = execution_spec_schema()['properties']['bundle']['properties']
        self.assertIn('not a total workflow budget', schema['limits']['description'])
        self.assertIn('stage_limits', schema)
        try:
            import jsonschema
        except ImportError:
            return
        jsonschema.validate(raw, execution_spec_schema())
        jsonschema.validate(normalized, execution_spec_schema())

    def test_metrics_are_named_finite_and_do_not_infer_sample_units(self):
        cases = [
            {'primary_metric': 'not_a_gate'}, {'minimum_test_samples': 0}, {'minimum_test_samples': True}, {'test_unit': ''},
            {'gates': {'constraint_violation': {'operator': 'exec', 'threshold': .2}}},
            {'gates': {'constraint_violation': {'operator': 'lte', 'threshold': float('nan')}}},
            {'gates': {'constraint_violation': {'operator': 'lte', 'threshold': True}}},
        ]
        for changes in cases:
            with self.subTest(changes=changes):
                raw = execution_spec(); raw['evaluation'].update(changes)
                with self.assertRaises(ContractError):
                    validate_execution_spec(raw)

    def test_untrusted_json_and_export_paths_have_bounds(self):
        for change in [lambda spec: spec.update(secret_env={'TOKEN': 'no'}), lambda spec: spec['artifacts'][0].update(path='../outside'), lambda spec: spec['artifacts'][0].update(export='yes'), lambda spec: spec['inference'].update(extensions=['*']), lambda spec: spec['inference'].update(max_bytes=26 * 1024 * 1024), lambda spec: spec.update(config={'x': object()})]:
            raw = execution_spec(); change(raw)
            with self.assertRaises(ContractError):
                validate_execution_spec(raw)
        raw = execution_spec(); raw['asset_ids'] = [{}]
        with self.assertRaises(ContractError):
            validate_execution_spec(raw)
        raw = execution_spec(); raw['asset_ids'] = ['asset-' + 'c' * 24]
        self.assertEqual(validate_execution_spec(raw)['asset_ids'], raw['asset_ids'])

    def test_explicit_mapping_normalizes_prefixes_and_indices(self):
        raw = execution_spec()['data_mapping']
        raw[0].pop('csv_rows'); raw[0]['member_prefixes'] = ['train']
        raw[1]['csv_rows'] = [6, 5]
        normalized = validate_data_mapping(raw)
        self.assertEqual(normalized[0]['member_prefixes'], ['train/'])
        self.assertEqual(normalized[1]['csv_rows'], [5, 6])
        self.assertEqual(validate_data_mapping(normalized), normalized)

    def test_mapping_rejects_identity_ambiguity_traversal_and_bad_rows(self):
        changes = [lambda item: item.update(split='all'), lambda item: item.update(inspection_sha256='not-a-digest'), lambda item: item.update(material_id='../material'), lambda item: item.update(csv_rows=[0, 0]), lambda item: item.update(csv_rows=[-1]), lambda item: item.update(csv_rows=[True]), lambda item: item.update(csv_rows={'start': 1, 'stop': 1}), lambda item: item.update(member_paths=['a.csv']), lambda item: item.update(csv_rows=None)]
        for change in changes:
            raw = execution_spec()['data_mapping']; change(raw[0])
            with self.subTest(mapping=raw), self.assertRaises(ContractError):
                validate_data_mapping(raw)
        raw = execution_spec()['data_mapping']; raw[0].pop('csv_rows'); raw[0]['member_paths'] = ['../escape']
        with self.assertRaises(ContractError):
            validate_data_mapping(raw)
        with self.assertRaises(ContractError):
            validate_data_mapping(execution_spec()['data_mapping'][:1])


if __name__ == '__main__':
    unittest.main()

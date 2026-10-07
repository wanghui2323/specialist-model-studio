from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

from model_harness.errors import ContractError
from model_harness.evidence import InferenceCheck
from model_harness.generic_io_schema import validate_input_file, validate_output_result, validate_schema_definition
from model_harness.generic_protocol import execution_spec_schema, validate_execution_spec
from model_harness.io_utils import read_json, write_json
from model_harness.plugin_api import RunExecutionContext
from tests import test_generic_recipe as fixtures
from tests import test_generic_delivery as delivery
from tests.test_generic_protocol import execution_spec


class GenericSchemaTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)

    def test_declaration_rejects_invalid_schema_and_external_references_without_network(self):
        schemas = [
            {'type': 'unsupported-json-type'}, {'required': 'not-an-array'},
            {'$ref': 'https://example.invalid/private.json'}, {'$ref': 'file:///private/data'},
            {'$dynamicRef': 'another.json#/$defs/value'},
            {'$defs': {'unused': {'$ref': 'https://example.invalid/schema'}}},
            {'$ref': '#/missing'}, {'$schema': 'https://example.invalid/dialect'},
            {'$schema': ['invalid']}, {'$recursiveRef': '#'},
            {'$ref': '#/custom', 'custom': {'$ref': 'file:///private/schema'}},
            {'$ref': '#/allOf/-1', 'allOf': [{'type': 'number'}]},
            {'$ref': '#/$defs/~2', '$defs': {'~2': {}}},
        ]
        with patch('socket.socket', side_effect=AssertionError('schema must not use the network')):
            for schema in schemas:
                for field in ('schema', 'output_schema'):
                    raw = execution_spec(); raw['inference'][field] = schema
                    with self.subTest(schema=schema, field=field), self.assertRaises(ContractError):
                        validate_execution_spec(raw)

    def test_local_pointer_definitions_and_dynamic_pointer_are_checked_offline(self):
        schema = {'$defs': {'count': {'type': 'integer', 'minimum': 1}}, 'type': 'object',
            'required': ['count'], 'additionalProperties': False, 'properties': {'count': {'$ref': '#/$defs/count'}}}
        path = self.root / 'input.json'; write_json(path, {'count': 2})
        with patch('socket.socket', side_effect=AssertionError('no network')):
            for ref_keyword in ('$ref', '$dynamicRef'):
                current = deepcopy(schema)
                current['properties']['count'] = {ref_keyword: '#/$defs/count'}
                result = validate_input_file(path, {'schema': current, 'max_bytes': 1024})
                self.assertEqual(result, {'status': 'passed', 'scope': 'host_json', 'schema_declared': True})
            write_json(path, {'count': 0})
            with self.assertRaisesRegex(ContractError, 'minimum'):
                validate_input_file(path, {'schema': schema, 'max_bytes': 1024})

    def test_literal_reference_shaped_business_data_does_not_become_a_schema_reference(self):
        expected = {'$ref': 'https://example.invalid/just-user-data'}
        schema = {'type': 'object', 'const': expected, 'examples': [expected]}
        validate_schema_definition(schema)
        path = self.root / 'input.json'; write_json(path, expected)
        self.assertEqual(validate_input_file(path, {'schema': schema, 'max_bytes': 1024})['status'], 'passed')

    def test_input_structure_failures_do_not_echo_customer_values_or_property_names(self):
        secret = 'PRIVATE_CUSTOMER_VALUE_339129'
        path = self.root / 'input.json'; write_json(path, {secret: secret})
        with self.assertRaises(ContractError) as found:
            validate_input_file(path, {'schema': {'type': 'object', 'additionalProperties': False}, 'max_bytes': 2048})
        self.assertNotIn(secret, str(found.exception))
        self.assertLess(len(str(found.exception)), 160)
        for payload in (b'not JSON secret payload', b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":Infinity}', b'\xff'):
            path.write_bytes(payload)
            with self.subTest(payload=payload), self.assertRaisesRegex(ContractError, 'valid UTF-8 JSON'):
                validate_input_file(path, {'schema': {}, 'max_bytes': 2048})
        path.write_text('"too many bytes"')
        with self.assertRaisesRegex(ContractError, 'byte limit'):
            validate_input_file(path, {'schema': {}, 'max_bytes': 1})

    def test_text_is_one_utf8_string_and_other_formats_are_never_guessed(self):
        schema = {'type': 'string', 'minLength': 2, 'maxLength': 5}
        path = self.root / 'input.txt'; path.write_text('你好')
        self.assertEqual(validate_input_file(path, {'schema': schema, 'max_bytes': 1024})['scope'], 'host_utf8_text')
        with self.assertRaisesRegex(ContractError, 'type'):
            validate_input_file(path, {'schema': {'type': 'array'}, 'max_bytes': 1024})
        path.write_bytes(b'\xff')
        with self.assertRaisesRegex(ContractError, 'UTF-8 text'):
            validate_input_file(path, {'schema': schema, 'max_bytes': 1024})
        for extension in ('.csv', '.wav', '.png', '.custom'):
            opaque = self.root / ('opaque' + extension)
            with patch.object(Path, 'open', side_effect=AssertionError('opaque inputs must not be host-decoded')):
                result = validate_input_file(opaque, {'schema': {'type': 'array'}, 'max_bytes': 1024})
            self.assertEqual(result['status'], 'worker_validation_required')
            self.assertTrue(result['schema_declared'])

    def test_omitted_schemas_remain_unverified_and_output_targets_the_complete_envelope(self):
        self.assertEqual(validate_input_file(self.root / 'unread.json', {})['status'], 'not_declared')
        self.assertEqual(validate_output_result({'prediction': 3}, {})['status'], 'not_declared')
        schema = {'type': 'object', 'required': ['prediction'], 'additionalProperties': False,
            'properties': {'prediction': {'type': 'integer'}, 'artifacts': {'type': 'array', 'items': {'type': 'string'}}}}
        self.assertEqual(validate_output_result({'prediction': 3, 'artifacts': ['output.wav']}, {'output_schema': schema})['scope'], 'host_infer_result_envelope')
        for result in ({'prediction': 'private-value'}, {'artifacts': []}, {'prediction': 3, 'unexpected': True}):
            with self.subTest(result=result), self.assertRaises(ContractError):
                validate_output_result(result, {'output_schema': schema})
        with self.assertRaisesRegex(ContractError, 'type'):
            validate_output_result({'prediction': 3}, {'output_schema': {'type': 'integer'}})

    def test_recursive_unresolvable_and_oversized_schemas_fail_with_bounded_errors(self):
        with self.assertRaises(ContractError) as found:
            validate_output_result({'prediction': 1}, {'output_schema': {'$ref': '#'}})
        self.assertLess(len(str(found.exception)), 160)
        with self.assertRaisesRegex(ContractError, 'size limit'):
            validate_schema_definition({'description': 'x' * (128 * 1024)})
        definition = execution_spec_schema()['properties']['inference']['properties']
        self.assertIn('COMPLETE infer_result.json envelope', definition['output_schema']['description'])
        self.assertIn('worker validation', definition['schema']['description'])
        self.assertEqual(validate_execution_spec(execution_spec())['inference'], execution_spec()['inference'])


class GenericOutputSchemaIntegrationTests(unittest.TestCase):
    setUp = fixtures.GenericRecipeTests.setUp
    run_fixture = fixtures.GenericRecipeTests.run_fixture

    def test_predict_checks_full_envelope_before_accepting_output_or_artifacts(self):
        self.contract['execution_spec']['inference']['output_schema'] = {'type': 'object', 'required': ['prediction'],
            'additionalProperties': False, 'properties': {'prediction': {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {'type': 'number'}}}}
        run = self.run_fixture()
        input_path = self.root / 'fresh.json'; write_json(input_path, {'left': 2, 'right': 1})
        context = RunExecutionContext(self.owner, run.name, run, self.root / 'isolated')
        for result in ({'prediction': 'PRIVATE_MODEL_OUTPUT'}, {'prediction': [1]}, {'prediction': [1, 2], 'unreviewed': True}):
            self.executor.result_overrides['predict'] = result
            with self.subTest(result=result), self.assertRaises(ContractError) as found:
                self.plugin.predict(self.contract, model_dir=run / 'artifacts', input_files={'sample/input.json': input_path}, context=context)
            self.assertNotIn('PRIVATE_MODEL_OUTPUT', str(found.exception))
        self.executor.result_overrides['predict'] = {'prediction': [2.5, -.5]}
        result = self.plugin.predict(self.contract, model_dir=run / 'artifacts', input_files={'sample/input.json': input_path}, context=context)
        self.assertEqual(result['output_schema_validation']['status'], 'passed')
        self.assertEqual(read_json(run / 'artifacts/metrics.json')['gate_checks']['all_offline_gates_passed'], True)


class SchemaDeliveryExecutor(fixtures.EvidenceExecutor):
    def run_stage(self, *args, **kwargs):
        evidence = super().run_stage(*args, **kwargs)
        evidence['created_at'] = '2026-10-04T00:00:00+00:00'
        evidence['evidence_sha256'] = fixtures.digest({key: value for key, value in evidence.items() if key != 'evidence_sha256'})
        return evidence


class GenericSchemaDeliveryTests(unittest.TestCase):
    client = delivery.GenericDeliveryTests.client
    _upload = delivery.GenericDeliveryTests._upload
    run_fixture = fixtures.GenericRecipeTests.run_fixture

    def setUp(self):
        fixtures.GenericRecipeTests.setUp(self)
        self.executor = SchemaDeliveryExecutor(); self.plugin.executor = self.executor
        self.contract['execution_spec']['inference'].update(
            schema={'type': 'object', 'required': ['left', 'right'], 'additionalProperties': False,
                'properties': {'left': {'type': 'number'}, 'right': {'type': 'number'}}},
            output_schema={'type': 'object', 'required': ['prediction'], 'additionalProperties': False,
                'properties': {'prediction': {'type': 'array', 'minItems': 2, 'maxItems': 2, 'items': {'type': 'number'}}}})
        self.run_dir = self.run_fixture(); self.run_id = self.run_dir.name
        write_json(self.task_dir / 'task.json', {'task_id': self.owner, 'name': 'Generic schema fixture', 'business_goal': self.contract['business_goal'],
            'status': 'completed', 'current_spec_revision': 1, 'capability_request': self.contract['execution_spec']['capability'],
            'recipe_id': 'generic-isolated-execution', 'run_ids': [self.run_id], 'current_run_id': self.run_id})
        self.home = self.root / 'fake-home'
        write_json(self.home / '.local/share/specialist-model-studio/execution-runtime.json', {'isolated_root': str(self.root / 'isolated')})

    def execute(self, client, content):
        response = self._upload(client, content=content)
        self.assertEqual(response.status_code, 201, response.text)
        record = response.json()['inference_input']
        base = f'/tasks/{self.owner}/runs/{self.run_id}'
        authorization = client.post(base + '/sample-inference-authorizations', headers={'X-Model-Harness-Agent-Token': 'generic-delivery-test-token'},
            json={'inference_input_id': record['inference_input_id'], 'inference_input_sha256': record['sha256'],
                'approval': {'actor': 'user', 'checkpoint_id': 'schema-native-' + uuid4().hex}})
        self.assertEqual(authorization.status_code, 201, authorization.text)
        result = authorization.json(); scope = result['sample_inference_authorization']
        return client.post(base + f"/inference-inputs/{record['inference_input_id']}/execute", json={
            'sample_inference_authorization_id': scope['authorization_id'], 'authorization_token': result['authorization_token'],
            'sample_inference_request_sha256': scope['scope_sha256']})

    def test_raw_upload_rejects_input_before_worker_and_output_before_accepted_prediction(self):
        with self.client() as (client, _app):
            before = len(self.executor.calls)
            invalid_input = self.execute(client, b'{"left":"PRIVATE_INPUT_VALUE","right":1}')
            self.assertEqual(invalid_input.status_code, 422, invalid_input.text)
            self.assertEqual(len(self.executor.calls), before)
            self.assertNotIn('PRIVATE_INPUT_VALUE', invalid_input.text)
            self.assertEqual(InferenceCheck(self.run_dir).list(), [])
            self.executor.result_overrides['predict'] = {'prediction': 'PRIVATE_OUTPUT_VALUE'}
            invalid_output = self.execute(client, b'{"left":2,"right":1}')
            self.assertEqual(invalid_output.status_code, 422, invalid_output.text)
            self.assertEqual(len(self.executor.calls), before + 1)
            self.assertNotIn('PRIVATE_OUTPUT_VALUE', invalid_output.text)
            self.assertEqual(InferenceCheck(self.run_dir).list(), [])
            self.executor.result_overrides['predict'] = {'prediction': [2.5, -.5]}
            success = self.execute(client, b'{"left":2,"right":1}')
            self.assertEqual(success.status_code, 201, success.text)
            report = success.json()['sample_inference']
            self.assertEqual(report['input_schema_validation']['status'], 'passed')
            self.assertEqual(report['output_schema_validation']['scope'], 'host_infer_result_envelope')
            persisted = InferenceCheck(self.run_dir).get(report['inference_check_id'])
            self.assertEqual(persisted['input_schema_validation'], report['input_schema_validation'])
            self.assertEqual(persisted['output_schema_validation'], report['output_schema_validation'])


if __name__ == '__main__':
    unittest.main()

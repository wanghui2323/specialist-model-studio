from __future__ import annotations

import csv
import io
import json
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from model_harness.errors import ContractError
from model_harness.generic_data import create_generic_dataset, generic_split_input_files, verify_generic_dataset_integrity
from model_harness.io_utils import write_json
from model_harness.material_inspection import MaterialConflict, MaterialInspectionStore


def zip_bytes(entries):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries:
            archive.writestr(name, content)
    return stream.getvalue()


class GenericDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.owner = 'task-' + '1' * 32
        self.task_dir = self.root / 'tasks' / self.owner
        write_json(self.task_dir / 'task.json', {'task_id': self.owner, 'status': 'needs_recipe'})
        self.store = MaterialInspectionStore(self.root)
        self.counter = 0

    def material(self, payload, name):
        self.counter += 1
        return self.store.upload(self.owner, payload, name, f'request-{self.counter}')[0]

    def selection(self, material, split, **kwargs):
        return {'material_id': material['material_id'], 'inspection_sha256': material['inspection_sha256'], 'split': split, **kwargs}

    def csv_material(self, contents=None):
        return self.material(contents or b'id,input,target\n0,a,1\n1,b,2\n2,c,3\n3,d,4\n4,e,5\n5,f,6\n', 'records.csv')

    def mapping(self, material):
        return [self.selection(material, 'train', csv_rows={'start': 0, 'stop': 3}), self.selection(material, 'validation', csv_rows=[3]), self.selection(material, 'test', csv_rows=[4, 5])]

    def test_single_csv_rows_are_physically_separated_and_repeatable(self):
        material = self.csv_material()
        before = (self.task_dir / 'task.json').read_bytes()
        result = create_generic_dataset(self.task_dir, self.store, self.owner, self.mapping(material))
        self.assertEqual(result.report['split_counts']['train']['csv_row_count'], 3)
        self.assertEqual(result.report['split_counts']['validation']['csv_row_count'], 1)
        self.assertEqual(result.report['split_counts']['test']['csv_row_count'], 2)
        manifest = verify_generic_dataset_integrity(result.contract_dataset)
        self.assertEqual(manifest['owner_id'], self.owner)
        training_inputs = generic_split_input_files(result.contract_dataset, ('train', 'validation'))
        self.assertEqual(set(training_inputs), {'train/records.csv', 'validation/records.csv'})
        self.assertNotIn(b'4,e,5', training_inputs['train/records.csv'].read_bytes())
        self.assertEqual(set(generic_split_input_files(result.contract_dataset, ('test',))), {'test/records.csv'})
        repeated = create_generic_dataset(self.task_dir, self.store, self.owner, self.mapping(material))
        self.assertEqual(repeated.dataset_dir, result.dataset_dir)
        self.assertEqual(repeated.contract_dataset, result.contract_dataset)
        self.assertEqual((self.task_dir / 'task.json').read_bytes(), before)
        self.assertFalse(result.report['execution_authorized'])
        self.assertFalse(result.report['semantic_leakage_checked'])

    def test_dataset_can_be_frozen_under_its_owned_proposal_directory(self):
        material = self.csv_material()
        proposal = self.task_dir / 'execution_proposals' / ('execution-' + '2' * 24)
        proposal.mkdir(parents=True)
        result = create_generic_dataset(proposal, self.store, self.owner, self.mapping(material))
        self.assertEqual(result.dataset_dir.parent, (proposal / 'datasets').resolve())
        self.assertTrue(result.contract_dataset['dataset_id'])
        verify_generic_dataset_integrity(result.contract_dataset)
        linked = self.task_dir / 'linked-proposal'
        linked.symlink_to(proposal, target_is_directory=True)
        with self.assertRaises(ContractError):
            create_generic_dataset(linked, self.store, self.owner, self.mapping(material))

    def test_zip_explicit_members_and_prefixes_exclude_undeclared_content(self):
        material = self.material(zip_bytes([('train/a.bin', b'train payload'), ('validation/b.bin', b'validation payload'), ('test/c.bin', b'final test payload'), ('never/d.bin', b'private undeclared')]), 'inputs.zip')
        mapping = [self.selection(material, 'train', member_prefixes=['train/']), self.selection(material, 'validation', member_paths=['validation/b.bin']), self.selection(material, 'test', member_prefixes=['test'])]
        result = create_generic_dataset(self.task_dir, self.store, self.owner, mapping)
        self.assertEqual(result.report['total_files'], 3)
        self.assertFalse(any(path.name == 'd.bin' for path in result.dataset_dir.rglob('*')))
        inputs = generic_split_input_files(result.contract_dataset, ['train'])
        self.assertEqual(set(inputs), {'train/train/a.bin'})
        self.assertEqual(inputs['train/train/a.bin'].read_bytes(), b'train payload')

    def test_source_overlap_and_exact_cross_split_duplicates_fail_atomically(self):
        material = self.csv_material()
        overlapping = [self.selection(material, 'train', csv_rows=[0, 1]), self.selection(material, 'test', csv_rows=[1, 2])]
        with self.assertRaises(ContractError):
            create_generic_dataset(self.task_dir, self.store, self.owner, overlapping)
        same_rows = self.csv_material(b'input,target\na,1\nb,2\na,1\n')
        with self.assertRaises(ContractError):
            create_generic_dataset(self.task_dir, self.store, self.owner, [self.selection(same_rows, 'train', csv_rows=[0]), self.selection(same_rows, 'test', csv_rows=[2])])
        bundle = self.material(zip_bytes([('a.bin', b'same'), ('b.bin', b'same')]), 'duplicates.zip')
        with self.assertRaises(ContractError):
            create_generic_dataset(self.task_dir, self.store, self.owner, [self.selection(bundle, 'train', member_paths=['a.bin']), self.selection(bundle, 'test', member_paths=['b.bin'])])
        self.assertEqual(list((self.task_dir / 'datasets').iterdir()), [])

    def test_source_identity_missing_selections_and_wrong_owner_are_rejected(self):
        material = self.csv_material()
        mapping = self.mapping(material); mapping[0]['inspection_sha256'] = '0' * 64
        with self.assertRaises(ContractError):
            create_generic_dataset(self.task_dir, self.store, self.owner, mapping)
        with self.assertRaises(ContractError):
            create_generic_dataset(self.root / 'foreign', self.store, self.owner, self.mapping(material))
        mapping = self.mapping(material); mapping[2]['csv_rows'] = [999]
        with self.assertRaises(ContractError):
            create_generic_dataset(self.task_dir, self.store, self.owner, mapping)
        source = self.root / 'materials' / self.owner / material['material_id'] / 'source.bin'
        source.chmod(0o600); source.write_bytes(b'changed')
        with self.assertRaises(MaterialConflict):
            create_generic_dataset(self.task_dir, self.store, self.owner, self.mapping(material))

    def test_archive_and_symlink_boundaries_are_preserved(self):
        material = self.csv_material()
        write_json(self.task_dir / 'task.json', {'task_id': self.owner, 'archived_at_utc': '2026-10-04'})
        with self.assertRaises(MaterialConflict):
            create_generic_dataset(self.task_dir, self.store, self.owner, self.mapping(material))
        self.assertFalse((self.task_dir / 'datasets').exists())
        write_json(self.task_dir / 'task.json', {'task_id': self.owner})
        outside = self.root / 'outside'; outside.mkdir()
        (self.task_dir / 'datasets').symlink_to(outside)
        with self.assertRaises(ContractError):
            create_generic_dataset(self.task_dir, self.store, self.owner, self.mapping(material))
        self.assertEqual(list(outside.iterdir()), [])

    def test_manifest_files_and_contract_cannot_be_tampered_or_widened(self):
        material = self.csv_material()
        result = create_generic_dataset(self.task_dir, self.store, self.owner, self.mapping(material))
        contract = result.contract_dataset
        extra = result.dataset_dir / 'train/undeclared.csv'; extra.write_text('private')
        with self.assertRaises(ContractError):
            generic_split_input_files(contract, ['train'])
        extra.unlink()
        original = result.dataset_dir / 'train/records.csv'
        original.chmod(0o600); original.write_bytes(b'corrupt')
        with self.assertRaises(ContractError):
            verify_generic_dataset_integrity(contract)
        widened = dict(contract, splits={})
        with self.assertRaises(ContractError):
            verify_generic_dataset_integrity(widened)

    def test_dataset_byte_caps_and_missing_zip_paths_leave_no_output(self):
        material = self.csv_material()
        with patch('model_harness.generic_data.MAX_DATASET_BYTES', 10), self.assertRaises(ContractError):
            create_generic_dataset(self.task_dir, self.store, self.owner, self.mapping(material))
        bundle = self.material(zip_bytes([('train/a', b'one'), ('test/b', b'two')]), 'data.zip')
        mapping = [self.selection(bundle, 'train', member_paths=['missing']), self.selection(bundle, 'test', member_prefixes=['test'])]
        with self.assertRaises(ContractError):
            create_generic_dataset(self.task_dir, self.store, self.owner, mapping)
        self.assertEqual(list((self.task_dir / 'datasets').iterdir()), [])

    def test_optional_validation_and_utf8_csv_quoting_are_preserved(self):
        payload = '标识;文本;目标\n1;"含;分号";好\n2;"跨\n行";坏\n'.encode('utf-8-sig')
        material = self.csv_material(payload)
        result = create_generic_dataset(self.task_dir, self.store, self.owner, [self.selection(material, 'train', csv_rows=[0]), self.selection(material, 'test', csv_rows=[1])])
        self.assertEqual(result.contract_dataset['splits']['validation'], [])
        parsed = list(csv.reader(io.StringIO((result.dataset_dir / 'test/records.csv').read_text()), delimiter=';'))
        self.assertEqual(parsed, [['标识', '文本', '目标'], ['2', '跨\n行', '坏']])

    def test_four_local_acceptance_formats_share_one_mapping_pipeline(self):
        fixtures = Path(__file__).resolve().parents[1] / 'runs/acceptance/20261004-four-scenarios'
        if not (fixtures / 'speech/tts_speech_review.zip').is_file():
            self.skipTest('generated private/local fixtures are not package source')
        speech = self.material((fixtures / 'speech/tts_speech_review.zip').read_bytes(), 'speech.zip')
        speech_test = self.material((fixtures / 'speech/tts_speech_holdout.zip').read_bytes(), 'speech-test.zip')
        mapping = [self.selection(speech, 'train', member_prefixes=['train/']), self.selection(speech, 'validation', member_prefixes=['validation/']), self.selection(speech_test, 'test', member_prefixes=['test/'])]
        speech_result = create_generic_dataset(self.task_dir, self.store, self.owner, mapping)
        self.assertTrue(generic_split_input_files(speech_result.contract_dataset, ['test']))
        ocr = self.material((fixtures / 'ocr/ocr-single-line.zip').read_bytes(), 'ocr.zip')
        ocr_result = create_generic_dataset(self.task_dir, self.store, self.owner, [self.selection(ocr, split, member_prefixes=[split + '/']) for split in ['train', 'validation', 'test']])
        self.assertEqual(ocr_result.report['split_counts']['test']['file_count'], 61)
        self.assertFalse(any('challenge' in key for key in generic_split_input_files(ocr_result.contract_dataset, ['train', 'validation'])))
        for scenario, expected in [('nlp', {'train': 72, 'validation': 36, 'test': 36}), ('timeseries', {'train': 1095, 'validation': 168, 'test': 168})]:
            mapping = []
            for split in ['train', 'validation', 'test']:
                source = fixtures / scenario / 'data' / (split + '.csv')
                material = self.material(source.read_bytes(), source.name)
                mapping.append(self.selection(material, split))
            result = create_generic_dataset(self.task_dir, self.store, self.owner, mapping)
            self.assertEqual({split: result.report['split_counts'][split]['csv_row_count'] for split in expected}, expected)
            verify_generic_dataset_integrity(result.contract_dataset)


if __name__ == '__main__':
    unittest.main()

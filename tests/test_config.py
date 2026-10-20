"""Identité, initialisation et sélection du fichier de configuration partagé."""
import json
import argparse
from pathlib import Path

import pytest

from lib.config import Config
from lib.siril_utils import default_siril_mode


def test_singleton_preserves_unsaved_changes(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'custom': 'initial'}))
    config = Config(path)
    config.set('custom', 'modified')

    assert Config() is config
    assert Config(str(path)) is config
    assert Config().get('custom') == 'modified'
    assert json.loads(path.read_text())['custom'] == 'initial'

    config.load()
    assert Config().get('custom') == 'initial'


def test_singleton_default_file(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    path = tmp_path / '.siril_darklib_config.json'
    path.write_text(json.dumps({'custom': 42}))

    config = Config()
    assert config.config_file == str(path)
    assert config.get('custom') == 42
    assert Config() is config


def test_singleton_accepts_equivalent_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Config('config.json')
    assert Config(tmp_path / 'config.json') is config


def test_singleton_rejects_another_file(tmp_path):
    config = Config(tmp_path / 'first.json')
    config.set('custom', 42)

    with pytest.raises(ValueError, match='Config utilise déjà'):
        Config(tmp_path / 'second.json')

    assert Config() is config
    assert config.get('custom') == 42


def test_command_line_uses_shared_instance(tmp_path):
    path = tmp_path / 'config.json'
    path.write_text(json.dumps({'siril_mode': 'native'}))
    config = Config.from_command_line(['--config', str(path)])

    assert Config() is config
    assert Config.from_command_line([]) is config
    assert Config.from_command_line(['--config', str(path)]) is config
    assert config.get('siril_mode') == 'native'


class ExampleTreatment:
    parameter_persistence = {'output': False, 'force': False}
    config_keys = {'age': 'max_age_days'}

    @staticmethod
    def add_arguments(parser):
        parser.add_argument('--amount', type=int, default=3)
        parser.add_argument('--age', type=int, default=182)
        parser.add_argument('--output', type=Path)
        parser.add_argument('--force', action='store_true')


def configured_parser(tmp_path, saved=None):
    path = tmp_path / 'settings.json'
    if saved is not None:
        path.write_text(json.dumps(saved))
    config = Config(path)
    parser = argparse.ArgumentParser()
    config.add_arguments(parser)
    config.register(ExampleTreatment, parser)
    return config, parser, path


def test_registered_precedence_and_selective_save(tmp_path):
    config, parser, path = configured_parser(tmp_path, {'amount': 7, 'force': True, 'custom': 42})
    assert config.parse_args(parser, []).amount == 7
    assert config.get('force') is False
    args = config.parse_args(parser, ['--amount', '9', '--output', 'result.fit', '--force'])
    assert config.get('amount') == 9
    assert config.arguments().output == Path('result.fit')
    assert config.save_requested(args)
    assert json.loads(path.read_text())['amount'] == 7
    args.save_config = True
    assert config.save_requested(args)
    saved = json.loads(path.read_text())
    assert saved['amount'] == 9
    assert saved['custom'] == 42
    assert saved['max_age_days'] == 182
    assert not {'force', 'output', 'age', 'config', 'save_config'} & saved.keys()


def test_alias_updates_remain_consistent(tmp_path):
    config, parser, path = configured_parser(tmp_path)
    config.parse_args(parser, ['--age', '12'])
    config.set('max_age_days', 15)
    assert config.get('age') == 15
    assert config.arguments().age == 15
    assert config.save()
    assert json.loads(path.read_text())['max_age_days'] == 15
    config.set('age', 20)
    assert config.get('max_age_days') == 20
    assert config.save()
    assert 'age' not in json.loads(path.read_text())


def test_failed_serialization_preserves_existing_file(tmp_path):
    config, _, path = configured_parser(tmp_path, {'amount': 7})
    original = path.read_bytes()
    config.set('unserializable', object())
    assert config.save() is False
    assert path.read_bytes() == original


@pytest.mark.parametrize('invalid', [[], None, 'text', 12])
def test_invalid_json_root_falls_back_to_defaults(tmp_path, invalid):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps(invalid))
    config = Config(path)
    assert config.get('siril_mode') == default_siril_mode()


def test_legacy_set_from_args_normalizes_paths(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    config = Config(tmp_path / 'config.json')
    config.set_from_args(argparse.Namespace(work_dir='work', input_dirs=['darks'], max_age=12))
    assert config.get('work_dir') == str(tmp_path / 'work')
    assert config.get('input_dirs') == [str(tmp_path / 'darks')]
    assert config.get('max_age_days') == 12


def test_subclass_can_select_file_in_init(tmp_path):
    class LocalConfig(Config):
        def __init__(self):
            super().__init__(tmp_path / 'local.json')

    config = LocalConfig()
    config.set('custom', 42)
    assert LocalConfig() is config
    assert config.config_file == str(tmp_path / 'local.json')
    assert LocalConfig().get('custom') == 42


def test_atomic_replace_failure_keeps_file_and_cleans_temporary(tmp_path, monkeypatch):
    config, _, path = configured_parser(tmp_path, {'amount': 7})
    original = path.read_bytes()
    config.set('amount', 9)

    def fail_replace(*args):
        raise OSError('replacement failed')

    monkeypatch.setattr(Path, 'replace', fail_replace)
    assert not config.save()
    assert path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [path]

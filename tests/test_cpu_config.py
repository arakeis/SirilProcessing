import shutil

import pytest

from lib.cpu_config import CpuConfig
from lib.siril_utils import Siril


@pytest.fixture(autouse=True)
def restore_cpu_config(monkeypatch):
    monkeypatch.setattr(CpuConfig, '_limit', None)


@pytest.mark.parametrize('count, expected', [(16, 15), (4, 3), (1, 1), (None, 1)])
def test_automatic_limit(monkeypatch, count, expected):
    monkeypatch.setattr('lib.cpu_config.os.cpu_count', lambda: count)
    assert CpuConfig.get_limit() == expected


def test_global_override_and_reset(monkeypatch):
    monkeypatch.setattr('lib.cpu_config.os.cpu_count', lambda: 16)
    CpuConfig.configure(8)
    assert CpuConfig.get_limit() == 8
    CpuConfig.configure(32)
    assert CpuConfig.get_limit() == 16
    CpuConfig.configure()
    assert CpuConfig.get_limit() == 15


@pytest.mark.parametrize('limit', [0, -1, True, 2.5, '4'])
def test_invalid_limit(limit):
    with pytest.raises(ValueError):
        CpuConfig.configure(limit)


@pytest.mark.parametrize('header', ['', 'requires 1.2\n', '# Script\n\nrequires 1.4\n'])
def test_existing_siril_instance_uses_global_limit(tmp_path, monkeypatch, header):
    monkeypatch.setattr(Siril, '_validate_configuration', lambda self: True)
    monkeypatch.setattr('lib.cpu_config.os.cpu_count', lambda: 16)
    runner = Siril(siril_path=shutil.which('true'), siril_mode='native')
    runner._validated = True
    for limit in (8, 3):
        CpuConfig.configure(limit)
        assert runner.run_siril_script(header + 'close\n', str(tmp_path), 'cpu.sps')
        assert (tmp_path / 'cpu.sps').read_text() == header + f'setcpu {limit}\nclose\n'

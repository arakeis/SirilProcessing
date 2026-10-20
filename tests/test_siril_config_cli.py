"""Paramètres Siril partagés, priorité CLI et persistance via Config."""
import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

from lib.config import Config
from lib.siril_utils import Siril


def test_shared_parameters_and_service(tmp_path, monkeypatch):
    config = Config(str(tmp_path / 'config.json'))
    config.update(siril_path='/configured/siril-cli', siril_mode='appimage')
    parser = argparse.ArgumentParser()
    Siril.add_arguments(parser, config, photometry_aliases=True)
    args = parser.parse_args([])
    assert (args.siril_path, args.siril_mode) == ('/configured/siril-cli', 'appimage')
    args = parser.parse_args(['-s', '/override/siril-cli', '-m', 'native'])
    assert (args.siril_path, args.siril_mode) == ('/override/siril-cli', 'native')
    legacy = parser.parse_args(['--photometry-siril-path', '/legacy/siril-cli', '--photometry-siril-mode', 'native'])
    assert (legacy.siril_path, legacy.siril_mode) == ('/legacy/siril-cli', 'native')
    monkeypatch.setattr(Siril, '_validate_configuration', lambda self: True)
    service = Siril(siril_path=args.siril_path, siril_mode=args.siril_mode)
    assert (service.siril_path, service.siril_mode) == ('/override/siril-cli', 'native')
    monkeypatch.setattr(Siril, '_default_siril_path', '/global/siril')
    assert Siril().siril_path == '/global/siril'


def test_postprocess_save_reload_and_override(tmp_path: Path) -> None:
    """Les paramètres sauvegardés restent prioritaires ; le diagnostic accepte un FITS valide."""
    root = Path(__file__).resolve().parents[1]
    config_path = tmp_path / 'settings/config.json'
    config_path.parent.mkdir()
    config_path.write_text(json.dumps({'dark_library_path': str(tmp_path / 'darks'), 'custom': 42}))
    image = tmp_path / 'image.fit'
    # L’aperçu de qualité est désormais produit même sans traitement actif.
    fits.writeto(image, np.zeros((64, 64), dtype=np.float32))
    command = [str(root / 'bin/postProcess.sh'), str(image), str(tmp_path / 'report.json'),
               '--config', str(config_path), '--disable-gradient', '--disable-photometry', '--disable-denoise', '--disable-autoghs', '--disable-deconvolution']

    def run(*options: str) -> str:
        """Exécute le lanceur avec les surcharges et retourne son journal de session."""
        result = subprocess.run([*command, *options], cwd=tmp_path,
                                env={**os.environ, 'VENV_DIR': sys.prefix}, capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        return (tmp_path / 'image_postprocess/00_image_postProcess.log').read_text()

    run('-S', '-m', 'native', '-s', '/example/siril-cli')
    saved = json.loads(config_path.read_text())
    assert saved['siril_mode'] == 'native'
    assert saved['siril_path'] == '/example/siril-cli'
    assert saved['custom'] == 42
    assert saved['dark_library_path'] == str(tmp_path / 'darks')
    assert 'input_file' not in saved
    assert 'Siril: mode=native, path=/example/siril-cli' in run()
    assert 'Siril: mode=flatpak, path=/example/siril-cli' in run('-m', 'flatpak')
    assert json.loads(config_path.read_text()) == saved  # Pas d'écriture implicite.
    loaded = Config.from_command_line(['--config', str(config_path)])
    parser = argparse.ArgumentParser()
    Siril.add_arguments(parser, loaded)
    assert parser.parse_args([]).siril_path == '/example/siril-cli'


def test_lightprocess_loads_same_config(tmp_path):
    root = Path(__file__).resolve().parents[1]
    path = tmp_path / 'shared.json'
    path.write_text(json.dumps({'siril_path': '/shared/siril-cli', 'siril_mode': 'appimage'}))
    result = subprocess.run([sys.executable, str(root / 'bin/lightProcess.py'),
                             '--config', str(path), '--help'], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    assert '/shared/siril-cli' in result.stdout
    assert 'appimage' in result.stdout
    assert '--save-config' in result.stdout


def test_config_save_creates_parent(tmp_path):
    config = Config(str(tmp_path / 'new/directory/settings.json'))
    config.update(siril_mode='flatpak', siril_path='siril')
    assert config.save()
    assert json.loads(Path(config.config_file).read_text())['siril_mode'] == 'flatpak'


def test_save_failure_is_reported(tmp_path):
    root = Path(__file__).resolve().parents[1]
    # Le parent est un fichier : aucune dépendance aux permissions de l'utilisateur.
    blocker = tmp_path / 'not_a_directory'
    blocker.touch()
    image = tmp_path / 'image.fit'
    image.touch()
    starnet = tmp_path / 'starnet++'
    starnet.write_text('#!/bin/sh\nexit 0\n')
    starnet.chmod(0o755)
    result = subprocess.run([str(root / 'bin/postProcess.sh'), str(image),
                             '--config', str(blocker / 'config.json'), '-S', '--disable-gradient',
                             '--starnet-path', str(starnet)],
                            env={**os.environ, 'VENV_DIR': sys.prefix}, capture_output=True, text=True)
    assert result.returncode == 1
    assert 'Erreur lors de la sauvegarde' in result.stderr

"""Contrats SPCC/PCC, profils spectraux et erreurs sans catalogues réseau."""
import argparse
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

from lib.postprocess import PhotometricColorCalibrator, _PostProcessorSequence


@pytest.fixture
def rgb(tmp_path):
    path = tmp_path / 'source RGB.fit'
    data = np.arange(1200, dtype=np.float32).reshape(3, 20, 20)
    fits.writeto(path, data)
    return path


@pytest.fixture
def fake_siril(monkeypatch, rgb):
    runner = Mock()

    def run(script, working_dir, script_name):
        wcs = WCS(naxis=2)
        wcs.wcs.crpix = [10, 10]
        wcs.wcs.crval = [270.6, -23.0]
        wcs.wcs.cdelt = [-0.001, 0.001]
        wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']
        fits.writeto(Path(working_dir) / (f'{Path(script_name).stem}_calibrated.fits' if script_name[0].isdigit() else 'calibrated.fits'), fits.getdata(rgb) * 0.8, wcs.to_header())
        return True

    runner.run_siril_script.side_effect = run
    factory = Mock(return_value=runner)
    monkeypatch.setattr('lib.postprocess.Siril', factory)
    return factory, runner


def arguments(*options):
    parser = argparse.ArgumentParser()
    from lib.siril_utils import Siril
    Siril.add_arguments(parser, photometry_aliases=True)
    _PostProcessorSequence().add_arguments(parser)
    return parser.parse_args(['--disable-denoise', '--disable-autoghs', '--disable-deconvolution', *options])


def test_object_resolution_and_all_options(rgb, tmp_path, monkeypatch, fake_siril):
    factory, runner = fake_siril
    resolver = Mock(return_value=SkyCoord(270.6, -23.0, unit='deg'))
    monkeypatch.setattr('lib.postprocess.SkyCoord.from_name', resolver)
    original = rgb.read_bytes()
    output = tmp_path / 'colors' / 'M20.fits'
    args = arguments('--enable-photometry', '--disable-gradient', '--photometry-object', 'M20',
                     '--photometry-focal', '750', '--photometry-pixelsize', '3.76',
                     '--photometry-force', '--photometry-noflip', '--photometry-downscale',
                     '--photometry-method', 'pcc',
                     '--photometry-solve-catalog', 'gaia', '--photometry-catalog', 'apass',
                     '--photometry-limitmag', '14', '--photometry-output', str(output),
                     '--photometry-siril-mode', 'native', '--photometry-siril-path', '/opt/siril-cli')
    result = _PostProcessorSequence().post_process(rgb, tmp_path / 'report.json', args)['photometry']
    resolver.assert_called_once_with('M20', cache=False)
    factory.assert_called_once_with(siril_path='/opt/siril-cli', siril_mode='native')
    script = runner.run_siril_script.call_args.args[0]
    assert script.index('load ') < script.index('platesolve ') < script.index('\npcc ') < script.index('\nsave ')
    assert 'platesolve 270.6000000000,-23.0000000000 -force -focal=750 -pixelsize=3.76 -noflip -downscale -catalog=gaia' in script
    assert '\npcc -catalog=apass -limitmag=14\n' in script
    assert f'load "{rgb}"' in script
    assert result['output_image'] == str(output)
    assert result['center_coordinates_deg'] == [270.6, -23.0]
    assert WCS(fits.getheader(output)).has_celestial
    assert rgb.read_bytes() == original


def test_existing_header_and_explicit_coordinates(rgb, tmp_path, fake_siril, monkeypatch):
    resolver = Mock(side_effect=AssertionError('No name lookup expected'))
    monkeypatch.setattr('lib.postprocess.SkyCoord.from_name', resolver)
    processor = PhotometricColorCalibrator()
    result = processor.post_process(rgb, tmp_path / 'header.json')
    assert result['platesolve_command'] == 'platesolve -force -catalog=gaia'
    assert result['spcc_command'] == 'spcc -catalog=gaia "-oscfilter=No filter"'
    assert result['method'] == 'spcc'
    assert result['color_catalog'] == 'gaia'
    assert result['spectral_profiles'] == {'oscfilter': 'No filter'}
    result = processor.post_process(rgb, tmp_path / 'coordinates.json',
                                    arguments('--photometry-coordinates', '270.6', '-23'))
    assert result['platesolve_command'] == 'platesolve 270.6000000000,-23.0000000000 -force -catalog=gaia'
    resolver.assert_not_called()


def test_photometry_explicitly_disabled(rgb, tmp_path, monkeypatch):
    factory = Mock(side_effect=AssertionError('Siril must not start'))
    monkeypatch.setattr('lib.postprocess.Siril', factory)
    results = _PostProcessorSequence().post_process(rgb, tmp_path / 'report.json', arguments('--disable-photometry'))
    assert set(results) == {'gradient'}
    gradient = results['gradient']
    assert len(gradient['correction']['channels']) == 3
    corrected = Path(gradient['output_image'])
    assert corrected.is_file()
    assert fits.getdata(corrected).shape == (3, 20, 20)
    factory.assert_not_called()


@pytest.mark.parametrize('options', [
    ['--photometry-focal', '0'], ['--photometry-pixelsize', '-1'],
    ['--photometry-limitmag', 'nan'], ['--photometry-coordinates', '360', '0'],
    ['--photometry-coordinates', '180', '91'],
])
def test_invalid_options(rgb, tmp_path, options, fake_siril):
    with pytest.raises(ValueError):
        PhotometricColorCalibrator().post_process(rgb, tmp_path / 'report.json', arguments(*options))
    fake_siril[0].assert_not_called()


def test_monochrome_rejected(tmp_path, fake_siril):
    image = tmp_path / 'mono.fit'
    fits.writeto(image, np.zeros((20, 20)))
    with pytest.raises(ValueError, match='RGB'):
        PhotometricColorCalibrator().post_process(image, tmp_path / 'report.json')
    fake_siril[0].assert_not_called()


def test_name_resolution_failure(rgb, tmp_path, fake_siril, monkeypatch):
    monkeypatch.setattr('lib.postprocess.SkyCoord.from_name', Mock(side_effect=OSError('offline')))
    with pytest.raises(RuntimeError, match='Recherche CDS impossible'):
        PhotometricColorCalibrator().post_process(rgb, tmp_path / 'report.json', arguments('--photometry-object', 'M20'))
    fake_siril[1].run_siril_script.assert_not_called()


@pytest.mark.parametrize('failure', ['exit', 'missing', 'no_wcs'])
def test_siril_failure_does_not_publish_stale_output(rgb, tmp_path, fake_siril, failure):
    output = tmp_path / 'existing.fit'
    output.write_bytes(b'previous output')
    factory, runner = fake_siril

    def fail(script, working_dir, script_name):
        if failure == 'no_wcs':
            fits.writeto(Path(working_dir) / (f'{Path(script_name).stem}_calibrated.fits' if script_name[0].isdigit() else 'calibrated.fits'), fits.getdata(rgb))
        return failure != 'exit'

    runner.run_siril_script.side_effect = fail
    with pytest.raises(RuntimeError):
        _PostProcessorSequence().post_process(rgb, tmp_path / 'report.json', arguments(
            '--disable-gradient', '--enable-photometry', '--photometry-output', str(output)))
    assert output.read_bytes() == b'previous output'
    assert not (tmp_path / 'report.json').exists()


def test_cannot_overwrite_input(rgb, tmp_path, fake_siril):
    with pytest.raises(ValueError, match="différente"):
        PhotometricColorCalibrator().post_process(rgb, tmp_path / 'report.json',
                                                  arguments('--photometry-output', str(rgb)))
    fake_siril[0].assert_not_called()


def test_calibrated_image_reaches_next_processor(rgb, tmp_path, fake_siril):
    from lib.processor import processor

    class InspectImage(processor):
        def add_arguments(self, parser):
            pass

        def post_process(self, input_path, output_path, args=None):
            assert input_path != rgb
            assert WCS(fits.getheader(input_path)).has_celestial
            return {'input_received': str(input_path)}

    sequence = _PostProcessorSequence([PhotometricColorCalibrator(), InspectImage()])
    result = sequence.post_process(rgb, tmp_path / 'report.json', arguments('--enable-photometry'))
    assert result['inspectimage']['input_received'] == result['photometry']['output_image']
    script, work_dir = fake_siril[1].run_siril_script.call_args.args
    assert f'cd "{work_dir}"' in script


def test_rgb_sip_wcs_validates_spatial_axes(rgb, tmp_path, fake_siril):
    _, runner = fake_siril
    generate = runner.run_siril_script.side_effect

    def generate_sip(*args, **kwargs):
        generate(*args, **kwargs)
        with fits.open(Path(args[1]) / 'calibrated.fits', mode='update') as hdul:
            header = hdul[0].header
            header['WCSAXES'] = 3
            header['CTYPE1'] = 'RA---TAN-SIP'
            header['CTYPE2'] = 'DEC--TAN-SIP'
            header['CTYPE3'] = 'RGB'
            header['A_ORDER'] = 2
            header['B_ORDER'] = 2
            header['A_2_0'] = 1.e-5
            header['B_0_2'] = -1.e-5
        return True

    runner.run_siril_script.side_effect = generate_sip
    result = PhotometricColorCalibrator().post_process(rgb, tmp_path / 'report.json')
    with fits.open(result['output_image']) as hdul:
        assert hdul[0].shape == (3, 20, 20)
        assert hdul[0].header['A_2_0'] == 1.e-5
        spatial = WCS(hdul[0].header, naxis=2)
        assert spatial.has_celestial
        assert spatial.sip is not None
        assert np.isfinite(spatial.all_pix2world([[10, 10]], 0)).all()


def test_spcc_profiles_quotes_and_audit(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SPCC utilise Gaia, les noms exacts protégés et un audit lisible au niveau INFO."""
    args = arguments(
        '--photometry-osc-sensor', 'Sony IMX533',
        '--photometry-osc-filter', 'No filter',
        '--photometry-white-reference', 'Average Spiral Galaxy',
        '--photometry-catalog', 'localgaia', '--photometry-force',
    )
    with caplog.at_level('INFO'):
        result = PhotometricColorCalibrator().post_process(rgb, tmp_path / 'spcc.json', args)
    script = fake_siril[1].run_siril_script.call_args.args[0]
    expected = ('spcc -catalog=localgaia "-oscsensor=Sony IMX533" '
                '"-oscfilter=No filter" "-whiteref=Average Spiral Galaxy"')
    assert f'\n{expected}\n' in script
    assert '\npcc' not in script
    assert result['calibration_command'] == result['spcc_command'] == expected
    assert result['spectral_profiles']['oscsensor'] == 'Sony IMX533'
    assert result['force_solve'] is True
    assert result['flip_allowed'] is True
    assert 'méthode=SPCC ; catalogue couleur=localgaia' in caplog.text
    assert 'nouvelle résolution demandée=True' in caplog.text


@pytest.mark.parametrize('options,token', [
    (['--photometry-mono-sensor', 'Generic mono', '--photometry-red-filter', 'R',
      '--photometry-green-filter', 'G', '--photometry-blue-filter', 'B'],
     '"-monosensor=Generic mono" "-rfilter=R" "-gfilter=G" "-bfilter=B"'),
    (['--photometry-osc-sensor', 'Canon', '--photometry-osc-lpf', 'Full spectrum'],
     '"-oscsensor=Canon" "-oscfilter=No filter" "-osclpf=Full spectrum"'),
])
def test_spcc_other_profile_options(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock],
    options: list[str], token: str,
) -> None:
    """Les profils mono/RGB et passe-bas OSC atteignent la commande Siril."""
    result = PhotometricColorCalibrator().post_process(
        rgb, tmp_path / 'result.json', arguments(*options),
    )
    assert token in result['spcc_command']


@pytest.mark.parametrize('options', [
    ['--photometry-catalog', 'apass'],
    ['--photometry-method', 'pcc', '--photometry-osc-sensor', 'Sony IMX533'],
    ['--photometry-osc-sensor', 'Sony IMX533', '--photometry-red-filter', 'R'],
    ['--photometry-mono-sensor', 'Generic mono', '--photometry-osc-filter', 'No filter'],
    ['--photometry-white-reference', ''],
    ['--photometry-white-reference', 'bad"name'],
    ['--photometry-white-reference', 'bad\nname'],
])
def test_incompatible_spcc_options_do_not_run(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock], options: list[str],
) -> None:
    """Les catalogues/profils incompatibles et injections sont refusés avant Siril."""
    with pytest.raises(ValueError):
        PhotometricColorCalibrator().post_process(
            rgb, tmp_path / 'result.json', arguments(*options),
        )
    fake_siril[1].run_siril_script.assert_not_called()


def test_existing_wcs_and_noflip_are_audited(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock],
) -> None:
    """Refait le WCS existant et audite le retournement interdit, délégué à Siril."""
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [10, 10]
    wcs.wcs.crval = [23.4, 30.6]
    wcs.wcs.cdelt = [-.001, .001]
    wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    with fits.open(rgb, mode='update') as hdul:
        hdul[0].header.update(wcs.to_header())
        hdul[0].header['ROWORDER'] = 'TOP-DOWN'
    result = PhotometricColorCalibrator().post_process(
        rgb, tmp_path / 'result.json', arguments('--photometry-noflip'),
    )
    assert result['input_has_wcs'] is True
    assert result['force_solve'] is True
    assert result['flip_allowed'] is False
    assert result['input_row_order'] == 'TOP-DOWN'
    assert result['platesolve_command'] == 'platesolve -force -noflip -catalog=gaia'


def test_spcc_configuration_reload_and_cli_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mémorise les profils SPCC ; le CLI prime et force reste propre au lancement."""
    from lib.config import Config

    config_path = tmp_path / 'spcc-config.json'
    monkeypatch.setattr(Config, '_instance', None)
    config = Config(config_path)
    parser = argparse.ArgumentParser()
    config.add_arguments(parser)
    config.register(_PostProcessorSequence(), parser)
    args = config.parse_args(parser, [
        '--photometry-method', 'spcc', '--photometry-catalog', 'gaia',
        '--photometry-osc-sensor', 'Sony IMX533',
        '--photometry-osc-filter', 'No filter',
        '--photometry-white-reference', 'Average Spiral Galaxy',
        '--photometry-force', '-S',
    ])
    assert args.photometry_force is True
    assert config.save_requested(args)
    monkeypatch.setattr(Config, '_instance', None)
    config = Config(config_path)
    parser = argparse.ArgumentParser()
    config.register(_PostProcessorSequence(), parser)
    loaded = config.parse_args(parser, [])
    assert loaded.photometry_method == 'spcc'
    assert loaded.photometry_catalog == 'gaia'
    assert loaded.photometry_osc_sensor == 'Sony IMX533'
    assert loaded.photometry_osc_filter == 'No filter'
    assert loaded.photometry_white_reference == 'Average Spiral Galaxy'
    assert loaded.photometry_force is True
    overridden = config.parse_args(parser, ['--photometry-osc-filter', 'Different filter'])
    assert overridden.photometry_osc_filter == 'Different filter'
    assert config.parse_args(parser, []).photometry_osc_filter == 'No filter'


@pytest.mark.parametrize('options,command,forced,flip_allowed', [
    ([], 'platesolve -force -catalog=gaia', True, True),
    (['--photometry-noflip'], 'platesolve -force -noflip -catalog=gaia', True, False),
    (['--photometry-coordinates', '23.45', '30.68'],
     'platesolve 23.4500000000,30.6800000000 -force -catalog=gaia', True, True),
])
def test_default_resolve_and_orientation_overrides(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock],
    options: list[str], command: str, forced: bool, flip_allowed: bool,
) -> None:
    """Refait même un WCS existant ; les options distinguent résolution et retournement."""
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [10, 10]
    wcs.wcs.crval = [23.45, 30.68]
    wcs.wcs.cdelt = [-.001, .001]
    wcs.wcs.ctype = ['RA---TAN', 'DEC--TAN']
    with fits.open(rgb, mode='update') as hdul:
        hdul[0].header.update(wcs.to_header())
    result = PhotometricColorCalibrator().post_process(
        rgb, tmp_path / 'result.json', arguments(*options),
    )
    assert result['input_has_wcs'] is True
    assert result['force_solve'] is forced
    assert result['flip_allowed'] is flip_allowed
    assert result['platesolve_command'] == command
    assert f'\n{command}\n' in fake_siril[1].run_siril_script.call_args.args[0]


def test_legacy_false_force_cannot_skip_astrometry(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock],
) -> None:
    """Un ancien appel Python avec force=False refait toujours la résolution."""
    args = arguments()
    args.photometry_force = False
    result = PhotometricColorCalibrator().post_process(rgb, tmp_path / 'result.json', args)
    assert result['force_solve'] is True
    assert result['platesolve_command'] == 'platesolve -force -catalog=gaia'


@pytest.mark.parametrize('header_filter,options,expected,source', [
    (None, [], 'No filter', 'default'),
    ('   ', [], 'No filter', 'default'),
    ('  Optolong L-Pro  ', [], 'Optolong L-Pro', 'FITS FILTER'),
    ('Optolong L-Pro', ['--photometry-osc-filter', 'No filter'], 'No filter', 'options'),
])
def test_osc_filter_metadata_and_priority(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock],
    header_filter: str | None, options: list[str], expected: str, source: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Utilise FILTER ou No filter, avec priorité des options et provenance auditée."""
    if header_filter is not None:
        with fits.open(rgb, mode='update') as hdul:
            hdul[0].header['FILTER'] = header_filter
    with caplog.at_level('INFO'):
        result = PhotometricColorCalibrator().post_process(
            rgb, tmp_path / 'result.json', arguments(*options),
        )
    assert result['spectral_profiles']['oscfilter'] == expected
    assert result['filter_source'] == source
    assert f'"-oscfilter={expected}"' in result['spcc_command']
    assert f'source={source}' in caplog.text


@pytest.mark.parametrize('header_filter', [17, 'bad"profile'])
def test_invalid_fits_filter_rejected_before_siril(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock],
    header_filter: str | int,
) -> None:
    """Refuse les valeurs non textuelles et les arguments Siril non protégeables."""
    with fits.open(rgb, mode='update') as hdul:
        hdul[0].header['FILTER'] = header_filter
    with pytest.raises(ValueError):
        PhotometricColorCalibrator().post_process(rgb, tmp_path / 'result.json')
    fake_siril[0].assert_not_called()


@pytest.mark.parametrize('options', [
    ['--photometry-method', 'pcc'],
    ['--photometry-mono-sensor', 'Generic mono', '--photometry-red-filter', 'R',
     '--photometry-green-filter', 'G', '--photometry-blue-filter', 'B'],
])
def test_filter_metadata_does_not_override_pcc_or_mono_profiles(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock], options: list[str],
) -> None:
    """FILTER ne désigne pas le triplet de filtres mono et ne paramètre pas PCC."""
    with fits.open(rgb, mode='update') as hdul:
        hdul[0].header['FILTER'] = 'L'
    result = PhotometricColorCalibrator().post_process(
        rgb, tmp_path / 'result.json', arguments(*options),
    )
    assert result['filter_source'] is None
    assert 'oscfilter' not in result['spectral_profiles']


def test_photometry_reuses_ordered_directory(
    rgb: Path, tmp_path: Path, fake_siril: tuple[Mock, Mock]
) -> None:
    """Les relances réinitialisent le même dossier visible sans sortie périmée."""
    calibrator = PhotometricColorCalibrator()
    report = tmp_path / "02_photometry.json"
    calibrator.post_process(rgb, report)
    work = Path(fake_siril[1].run_siril_script.call_args.args[1])
    assert work == tmp_path / "02_photometry_work/001"
    stale = work / "obsolete.fits"
    stale.write_bytes(b"obsolete")
    calibrator.post_process(rgb, report)
    assert Path(fake_siril[1].run_siril_script.call_args.args[1]) == work
    assert not stale.exists()
    protected = work / "source.fits"
    protected.write_bytes(rgb.read_bytes())
    with pytest.raises(ValueError, match="réinitialisé"):
        calibrator.post_process(protected, report)
    assert protected.is_file()

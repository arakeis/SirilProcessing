"""Analyse du filtre : décision, en-tête et chaîne complète sur une brute synthétique."""

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

from lib import filter_analysis
from lib.filter_analysis import (
    FilterAnalyzer,
    FrameMeasurement,
    combine_frames,
    decide,
    filter_family,
    header_filter_candidates,
    sensor_for_instrument,
)
from lib.filter_model import blackbody_spectrum, simulate_rgb
from lib.gaia_xp import XP_WAVELENGTH_NM
from lib.spectral_response import WAVELENGTH_GRID_NM, SpccDatabase
from tests.test_spectral_response import entry

spec = importlib.util.spec_from_file_location("filter_analyze_cli", Path(__file__).parents[1] / "bin/filterAnalyze.py")
cli = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = cli
spec.loader.exec_module(cli)

SUPERPIXELS = (160, 240)
TEMPERATURES = np.linspace(3500, 12000, 48)


def test_families_and_sensor_lookup():
    """Familles connues, ``other`` sinon ; capteur déduit de INSTRUME sans casse."""
    assert filter_family("Optolong L-Pro") == "light_pollution"
    assert filter_family(filter_analysis.L_EXTREME_NAME) == "narrowband"
    assert filter_family("No filter") == "none" and filter_family("Inconnu") == "other"
    assert sensor_for_instrument("ZWO CCD ASI294MC Pro") == "Sony IMX294"
    assert sensor_for_instrument("Canon EOS") is None


def test_header_filter_matching():
    """Correspondance sans casse ni ponctuation ; valeur trop courte ignorée."""
    names = ["Optolong L-Pro", "Optolong L-eXtreme (synth.)", "No filter"]
    assert header_filter_candidates("L Extreme", names) == ["Optolong L-eXtreme (synth.)"]
    assert header_filter_candidates("NoFilter", names) == ["No filter"]
    assert header_filter_candidates("L", names) == [] and header_filter_candidates("", names) == []


@pytest.mark.parametrize("scores, status, family, chosen, ambiguous", [
    ([("Optolong L-Pro", 1.0), ("SvBONY SV260", 1.4), ("ZWO Duo-Band", 3.0)],
     "filter", "light_pollution", "Optolong L-Pro", []),
    ([("Optolong L-Pro", 1.0), ("SvBONY SV260", 1.1), ("IDAS LPS P3", 1.35), ("ZWO Duo-Band", 3.0)],
     "family", "light_pollution", None, ["SvBONY SV260"]),
    ([("Optolong L-Pro", 1.0), ("ZWO Duo-Band", 1.4)], "undetermined", None, None, []),
    # Scores proches de zéro : un écart relatif de 50 % reste un écart absolu négligeable.
    ([("UV/IR Block", 0.010), ("No filter", 0.015)], "undetermined", None, None, []),
])
def test_decision_levels(scores, status, family, chosen, ambiguous):
    """Filtre, famille seule ou indéterminé selon les écarts absolus de score."""
    decision = decide(scores, family_margin=0.5, filter_margin=0.3)
    assert (decision["status"], decision["family"], decision["filter"]) == (status, family, chosen)
    assert decision["ambiguous_with"] == ambiguous
    best = min(scores, key=lambda item: item[1])[0]
    assert decision["top3"][0]["name"] == best and decision["best_family"] == filter_family(best)


def test_decision_with_a_single_family_or_filter():
    """Une seule famille, un seul filtre : avances infinies, rapportées comme None."""
    decision = decide([("No filter", 1.0)], 0.5, 0.3)
    assert decision["status"] == "filter" and decision["family_margin"] is None and decision["filter_margin"] is None


@pytest.fixture
def database(tmp_path):
    """Mini-base SPCC : capteur RGB et trois filtres de familles différentes."""
    root = tmp_path / "spcc"
    (root / "osc_filters").mkdir(parents=True)
    (root / "osc_sensors").mkdir()
    filters = {"UV/IR Block": ([400, 405, 690, 700], [0, 1, 1, 0]),
               "Optolong L-Pro": ([400, 430, 440, 540, 560, 600, 690, 700], [0, 0.9, 0.9, 0.9, 0.1, 0.9, 0.9, 0]),
               "No filter": ([350, 1050], [1, 1])}
    for index, (name, (wavelength, values)) in enumerate(filters.items()):
        (root / f"osc_filters/f{index}.json").write_text(json.dumps(entry(name, "OSC_FILTER", wavelength, values)))
    sensor = [entry(f"S {c}", "OSC_SENSOR", w, v, channel=c, model="Test sensor") for c, w, v in (
        ("BLUE", [400, 420, 500, 520], [0, 1, 1, 0]), ("GREEN", [470, 490, 590, 610], [0, 1, 1, 0]),
        ("RED", [570, 590, 680, 700, 900, 950], [0, 1, 1, 0.5, 0.5, 0]))]
    (root / "osc_sensors/s.json").write_text(json.dumps(sensor))
    return SpccDatabase(root)


def field_wcs():
    """WCS TAN de l'image superpixel synthétique, 2,4″ par superpixel."""
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [SUPERPIXELS[1] / 2, SUPERPIXELS[0] / 2]
    wcs.wcs.crval = [311.5, 30.6]
    wcs.wcs.cdelt = [-2.4 / 3600, 2.4 / 3600]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


@pytest.fixture
def raw_light(tmp_path, database):
    """Brute RGGB d'étoiles corps noirs vues à travers le filtre UV/IR Block."""
    rows, columns = np.meshgrid(np.arange(20, SUPERPIXELS[0] - 19, 20), np.arange(20, SUPERPIXELS[1] - 19, 20))
    positions = np.column_stack([columns.ravel(), rows.ravel()])[:TEMPERATURES.size].astype(float) + 0.3
    sensor = database.osc_sensor("Test sensor")
    colours = simulate_rgb(blackbody_spectrum(TEMPERATURES), database.osc_filter("UV/IR Block"), sensor)
    # Éclats variés : seules les étoiles les plus brillantes atteignent la saturation par défaut.
    colours *= np.random.default_rng(0).uniform(1000, 4000, (TEMPERATURES.size, 1)) / colours[:, 1:2]
    yy, xx = np.mgrid[:SUPERPIXELS[0], :SUPERPIXELS[1]]
    planes = np.full((3,) + SUPERPIXELS, 100.0)
    for (x, y), rgb in zip(positions, colours):
        planes += rgb[:, None, None] * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / 2) / (2 * np.pi)
    planes += np.random.default_rng(1).normal(0, 0.5, planes.shape)
    cfa = np.zeros((2 * SUPERPIXELS[0], 2 * SUPERPIXELS[1]))
    cfa[0::2, 0::2], cfa[0::2, 1::2], cfa[1::2, 0::2], cfa[1::2, 1::2] = planes[0], planes[1], planes[1], planes[2]
    header = fits.Header({"BAYERPAT": "RGGB", "ROWORDER": "TOP-DOWN", "FILTER": "UV/IR", "AIRMASS": 1.1,
                          "INSTRUME": "Test camera", "XPIXSZ": 4.63, "FOCALLEN": 800})
    path = tmp_path / "light.fits"
    fits.writeto(path, cfa.astype(np.float32), header)
    sky = field_wcs().pixel_to_world_values(positions[:, 0], positions[:, 1])
    sources = Table({"source_id": np.arange(1, TEMPERATURES.size + 1), "ra": sky[0], "dec": sky[1],
                     "phot_g_mean_mag": np.full(TEMPERATURES.size, 12.0),
                     "bp_rp": np.linspace(2.0, -0.2, TEMPERATURES.size),
                     "has_xp_sampled": np.ones(TEMPERATURES.size, bool)})
    return path, sources


@pytest.fixture
def mocked_services(monkeypatch, raw_light):
    """Astrométrie et archive Gaia simulées ; spectres XP corps noirs."""
    _, sources = raw_light
    header = field_wcs().to_header()
    header["PLTSOLVD"] = True
    monkeypatch.setattr(filter_analysis, "plate_solve", Mock(return_value=header))
    monkeypatch.setattr(filter_analysis, "query_field_sources", Mock(return_value=sources))
    xp = np.stack([np.interp(XP_WAVELENGTH_NM, WAVELENGTH_GRID_NM, s) for s in blackbody_spectrum(TEMPERATURES)])

    def spectra(source_ids, cache_dir):
        indices = np.asarray(source_ids, int) - 1
        return xp[indices], 0.01 * xp[indices]

    fetch = Mock(side_effect=spectra)
    monkeypatch.setattr(filter_analysis, "fetch_xp_spectra", fetch)
    return fetch


def options(*argv):
    """Options du traitement résolues comme par la ligne de commande."""
    parser = argparse.ArgumentParser()
    FilterAnalyzer.add_arguments(parser)
    return parser.parse_args(["--filter-sensor", "Test sensor", *argv])


def test_full_chain_identifies_the_family_and_writes_the_report(tmp_path, database, raw_light, mocked_services):
    """Brute UV/IR Block : famille uv_ir_cut, filtre cohérent avec FILTER, rapport écrit."""
    path, _ = raw_light
    report_path = tmp_path / "out" / "light_filterAnalyze.json"
    report = FilterAnalyzer(database=database, siril=Mock()).post_process(path, report_path, options())
    assert report["decision"]["status"] == "filter" and report["decision"]["filter"] == "UV/IR Block"
    assert report["scores"][0]["name"] == "UV/IR Block" and len(report["scores"]) == 4
    assert report["header_consistency"] == {"header_filter": "UV/IR", "matching_candidates": ["UV/IR Block"],
                                            "consistent": True}
    # Les plus brillantes, au-delà de 90 % du maximum, sont écartées comme saturées.
    assert 30 <= report["stars"]["used"] < TEMPERATURES.size and report["airmass"] == 1.1
    assert json.loads(report_path.read_text()) == report
    assert (tmp_path / "out" / "light_filterAnalyze_work").is_dir()


def test_star_cap_limits_the_spectra_requested(tmp_path, database, raw_light, mocked_services):
    """--filter-max-stars borne le nombre de spectres demandés à l'archive."""
    path, _ = raw_light
    report = FilterAnalyzer(database=database, siril=Mock()).post_process(
        path, tmp_path / "r.json", options("--filter-max-stars", "25"))
    assert len(mocked_services.call_args.args[0]) == 25 and report["stars"]["used"] == 25


def test_too_few_stars_or_unknown_sensor_are_refused(tmp_path, database, raw_light, mocked_services):
    """Moins d'étoiles que le minimum, ou capteur introuvable : erreur explicite."""
    path, _ = raw_light
    analyzer = FilterAnalyzer(database=database, siril=Mock())
    with pytest.raises(ValueError, match="étoiles exploitables"):
        analyzer.post_process(path, tmp_path / "r.json", options("--filter-max-stars", "5", "--filter-min-stars", "10"))
    parser = argparse.ArgumentParser()
    FilterAnalyzer.add_arguments(parser)
    with pytest.raises(ValueError, match="--filter-sensor"):
        analyzer.post_process(path, tmp_path / "r.json", parser.parse_args([]))


def frame(source_id, colours, sigma, valid=None):
    """Mesure minimale d'une pose pour tester la combinaison."""
    colours = np.asarray(colours, float)
    return FrameMeasurement(
        input_path=Path("x.fits"), header=fits.Header(), sensor_name="S", airmass=None, centre_deg=(0, 0),
        scale_deg=1e-3, field_sources=len(source_id), source_id=np.asarray(source_id),
        bp_rp=np.asarray(source_id, float) / 10, colours=colours, colour_sigma=np.full(colours.shape, sigma),
        valid=np.ones(len(source_id), bool) if valid is None else np.asarray(valid), reasons=[""] * len(source_id))


def test_frames_are_combined_per_star_with_inverse_variance_weights():
    """Moyenne pondérée par étoile ; étoiles invalides ignorées ; σ combiné 1/√Σw."""
    first = frame([7, 3], [[0.0, 1.0], [0.5, 0.5]], 0.1)
    second = frame([3, 7, 9], [[0.8, 0.2], [0.3, 0.0], [9.0, 9.0]], 0.2, valid=[True, True, False])
    source_id, colours, sigma, bp_rp, counts = combine_frames([first, second])
    np.testing.assert_array_equal(source_id, [3, 7])
    np.testing.assert_allclose(colours, [[0.56, 0.44], [0.06, 0.8]])
    np.testing.assert_allclose(sigma, 1 / np.sqrt(1 / 0.01 + 1 / 0.04))
    np.testing.assert_allclose(bp_rp, [0.3, 0.7])
    np.testing.assert_array_equal(counts, [2, 2])


def test_series_combines_the_frames_and_writes_one_report(tmp_path, database, raw_light, mocked_services):
    """Deux poses du même champ : chaque étoile vue deux fois, une seule décision."""
    path, _ = raw_light
    copy = shutil.copy(path, tmp_path / "light2.fits")
    report_path = tmp_path / "out" / "light_series_filterAnalyze.json"
    report = FilterAnalyzer(database=database, siril=Mock()).post_process_series(
        [path, Path(copy)], report_path, options())
    assert report["decision"]["filter"] == "UV/IR Block" and len(report["frames"]) == 2
    assert report["stars"]["mean_frames_per_star"] == 2.0 and report["airmass"] == 1.1
    assert report["stars"]["combined"] == report["frames"][0]["stars"]["valid"]
    assert report["header_consistency"]["consistent"] is True
    assert json.loads(report_path.read_text()) == report
    assert sorted(p.name for p in (tmp_path / "out" / "light_series_filterAnalyze_work").iterdir()) == [
        "light", "light2"]


def test_series_refuses_mixed_sensors(tmp_path, database, raw_light, monkeypatch):
    """Capteurs différents dans une série : erreur explicite avant tout score."""
    analyzer = FilterAnalyzer(database=database, siril=Mock())
    frames = iter([frame([1, 2, 3], np.zeros((3, 2)), 0.1), frame([1, 2, 3], np.zeros((3, 2)), 0.1)])

    def measure(path, work_dir, args=None):
        measured = next(frames)
        measured.sensor_name = str(path)
        return measured

    monkeypatch.setattr(analyzer, "measure_frame", measure)
    with pytest.raises(ValueError, match="Capteurs différents"):
        analyzer.post_process_series([Path("a.fits"), Path("b.fits")], tmp_path / "s.json", options())
    with pytest.raises(ValueError, match="vide"):
        analyzer.post_process_series([], tmp_path / "s.json", options())


def test_cli_groups_frames_by_series(tmp_path):
    """Regroupement par OBJECT, FILTER, EXPTIME et INSTRUME ; rapport nommé d'après la première brute."""
    paths = []
    for name, obj, exposure in (("a", "M31", 120), ("b", "M33", 120), ("c", "M31", 120), ("d", "M31", 300)):
        paths.append(tmp_path / f"{name}.fits")
        fits.writeto(paths[-1], np.zeros((2, 2), np.float32), fits.Header({"OBJECT": obj, "EXPTIME": exposure}))
    groups = cli.group_series(paths)
    assert [[p.name for p in group] for group in groups] == [["a.fits", "c.fits"], ["b.fits"], ["d.fits"]]
    assert cli.series_report_path(groups[0], None) == tmp_path / "a_series_filterAnalyze.json"
    assert cli.series_report_path(groups[0], str(tmp_path / "r")) == tmp_path / "r" / "a_series_filterAnalyze.json"

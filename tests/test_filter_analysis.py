"""Analyse du filtre : décision, en-tête et chaîne complète sur une brute synthétique."""

import argparse
import json
from unittest.mock import Mock

import numpy as np
import pytest
from astropy.io import fits
from astropy.table import Table
from astropy.wcs import WCS

from lib import filter_analysis
from lib.filter_analysis import (
    FilterAnalyzer,
    decide,
    filter_family,
    header_filter_candidates,
    sensor_for_instrument,
)
from lib.filter_model import blackbody_spectrum, simulate_rgb
from lib.gaia_xp import XP_WAVELENGTH_NM
from lib.spectral_response import WAVELENGTH_GRID_NM, SpccDatabase
from tests.test_spectral_response import entry

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

"""Courbes spectrales : rééchantillonnage, base SPCC, bandes synthétisées et atmosphère."""

import json

import numpy as np
import pytest

from lib import spectral_response
from lib.spectral_response import (
    L_EXTREME_BANDS,
    WAVELENGTH_GRID_NM,
    SpccDatabase,
    SpectralCurve,
    atmospheric_transmission,
    narrowband_filter,
)


def entry(name, kind, wavelength, values, *, channel=None, model=None, units="nm", scale=1):
    """Entrée JSON au format de la base SPCC de Siril."""
    data = {
        "model": model or name, "name": name, "type": kind, "dataQualityMarker": 2,
        "dataSource": "test", "manufacturer": "test", "version": 1,
        "wavelength": {"value": list(wavelength), "units": units},
        "values": {"value": list(values), "range": scale},
    }
    if channel:
        data["channel"] = channel
    return data


@pytest.fixture
def spcc_root(tmp_path):
    """Mini-base SPCC : un filtre en %, un filtre en angströms, un capteur RGB."""
    root = tmp_path / "siril-spcc-database"
    (root / "osc_filters").mkdir(parents=True)
    (root / "osc_sensors").mkdir()
    (root / "osc_filters/broad.json").write_text(json.dumps(
        entry("Broad", "OSC_FILTER", [400, 700], [90, 90], scale=100)))
    (root / "osc_filters/lpf.json").write_text(json.dumps([
        entry("Camera LPF", "OSC_LPF", [4000, 6000], [1, 1], units="angstrom")]))
    (root / "osc_sensors/sensor.json").write_text(json.dumps([
        entry(f"Sensor {c}", "OSC_SENSOR", [400, 500, 600, 700], v, channel=c, model="Sensor")
        for c, v in (("RED", [0, 0, .5, 1]), ("GREEN", [0, 1, 1, 0]), ("BLUE", [1, .5, 0, 0]))
    ]))
    return root


def value_at(curve, wavelength):
    """Valeur d'une courbe au point de grille le plus proche."""
    return curve.values[np.argmin(np.abs(WAVELENGTH_GRID_NM - wavelength))]


def test_resampling_sorts_deduplicates_and_zeroes_outside_range():
    """Hors de l'intervalle mesuré la réponse est nulle ; les doublons gardent le premier point."""
    curve = SpectralCurve.from_samples(
        "test", "OSC_FILTER", np.array([600, 500, 500, 700]), np.array([0.6, 0.5, 0.9, 0.7]))
    assert value_at(curve, 450) == 0 and value_at(curve, 750) == 0
    assert value_at(curve, 500) == pytest.approx(0.5)
    assert value_at(curve, 650) == pytest.approx(0.65)


@pytest.mark.parametrize("wavelength, values, message", [
    ([500], [0.5], "deux points"),
    ([500, 600], [0.5], "incohérentes"),
    ([500, np.nan], [0.5, 0.5], "non finies"),
    ([500, 600], [0.5, 1.5], "hors de"),
    ([100, 200], [0.5, 0.5], "aucune réponse"),
])
def test_invalid_samples_are_refused(wavelength, values, message):
    """Mesures incohérentes ou inutilisables : erreur explicite."""
    with pytest.raises(ValueError, match=message):
        SpectralCurve.from_samples("bad", "OSC_FILTER", np.array(wavelength), np.array(values))


def test_database_reads_percent_angstrom_and_sensor(spcc_root):
    """Réponses en pourcentage et longueurs d'onde en angströms sont normalisées."""
    database = SpccDatabase(spcc_root)
    assert database.osc_filter_names() == ["Broad", "Camera LPF"]
    assert value_at(database.osc_filter("Broad"), 550) == pytest.approx(0.9)
    lpf = database.osc_filter("Camera LPF")
    assert value_at(lpf, 500) == 1 and value_at(lpf, 650) == 0
    sensor = database.osc_sensor("Sensor")
    assert set(sensor) == {"RED", "GREEN", "BLUE"}
    assert value_at(sensor["RED"], 650) == pytest.approx(0.75)
    with pytest.raises(KeyError):
        database.osc_filter("Absent")
    with pytest.raises(KeyError, match="incomplet"):
        database.osc_sensor("Absent")


def test_database_root_resolution(tmp_path, monkeypatch, spcc_root):
    """Le dossier explicite prime ; sans base, l'erreur cite les emplacements essayés."""
    with pytest.raises(FileNotFoundError, match="introuvable"):
        SpccDatabase(tmp_path / "missing")
    monkeypatch.setattr(spectral_response, "default_spcc_roots", lambda: (tmp_path / "x", spcc_root))
    assert SpccDatabase().root == spcc_root


def test_default_roots_follow_platform(monkeypatch, tmp_path):
    """macOS lit Application Support ; ailleurs XDG_DATA_HOME puis Flatpak."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(spectral_response.sys, "platform", "darwin")
    assert spectral_response.default_spcc_roots() == (
        tmp_path / "Library/Application Support/org.siril.Siril/siril-spcc-database",)
    monkeypatch.setattr(spectral_response.sys, "platform", "linux")
    assert spectral_response.default_spcc_roots()[0] == tmp_path / "xdg/siril/siril-spcc-database"


def test_l_extreme_bands_have_announced_center_and_width():
    """Chaque bande synthétisée a le maximum et la largeur à mi-hauteur annoncés."""
    curve = narrowband_filter("L-eXtreme", L_EXTREME_BANDS)
    for center, fwhm, peak in L_EXTREME_BANDS:
        assert np.interp(center, WAVELENGTH_GRID_NM, curve.values) == pytest.approx(peak, rel=1e-3)
        near = np.abs(WAVELENGTH_GRID_NM - center) < 2 * fwhm
        wavelength, values = WAVELENGTH_GRID_NM[near], curve.values[near]
        rising, falling = wavelength < center, wavelength > center
        low = np.interp(peak / 2, values[rising], wavelength[rising])
        high = np.interp(peak / 2, values[falling][::-1], wavelength[falling][::-1])
        assert high - low == pytest.approx(fwhm, abs=0.05)
        assert value_at(curve, center - fwhm) < 1e-3
    assert value_at(curve, 580) < 1e-6
    assert curve.kind == "NARROWBAND" and curve.channel is None


@pytest.mark.parametrize("bands", [(), ((200.0, 7.0, 0.9),), ((500.0, 0.0, 0.9),), ((500.0, 7.0, 1.5),)])
def test_invalid_narrowband_definition(bands):
    """Bande absente, hors grille, de largeur nulle ou trop transmissive : refus."""
    with pytest.raises(ValueError):
        narrowband_filter("bad", bands)


def test_atmosphere_reddens_and_scales_with_airmass():
    """L'extinction est plus forte dans le bleu et croît linéairement en magnitudes."""
    zenith, low = atmospheric_transmission(1.0), atmospheric_transmission(2.0)
    blue, red = np.argmin(abs(WAVELENGTH_GRID_NM - 400)), np.argmin(abs(WAVELENGTH_GRID_NM - 700))
    assert zenith[blue] < zenith[red] < 1
    np.testing.assert_allclose(low, zenith**2)
    # Rayleigh + aérosols à 550 nm : 0,105 + 0,08 = 0,185 mag par masse d'air.
    assert -2.5 * np.log10(zenith[np.argmin(abs(WAVELENGTH_GRID_NM - 550))]) == pytest.approx(0.185, abs=0.002)
    for bad in (0.9, np.nan):
        with pytest.raises(ValueError):
            atmospheric_transmission(bad)
    with pytest.raises(ValueError):
        atmospheric_transmission(1.0, -0.1)


def test_installed_siril_database_contains_l_pro_and_imx294():
    """Intégration : la base réelle de Siril, si présente, fournit les courbes utilisées."""
    try:
        database = SpccDatabase()
    except FileNotFoundError:
        pytest.skip("Base SPCC de Siril non installée")
    names = database.osc_filter_names()
    assert "Optolong L-Pro" in names
    for name in names:
        assert database.osc_filter(name).values.max() > 0
    assert set(database.osc_sensor("Sony IMX294")) == {"RED", "GREEN", "BLUE"}

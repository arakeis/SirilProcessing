"""Modèle direct RGB et score de compatibilité des filtres, sur étoiles synthétiques."""

import numpy as np
import pytest

from lib.filter_model import BLUE, GREEN, RED, blackbody_spectrum, score_colours, score_filter, simulate_rgb
from lib.spectral_response import (
    L_EXTREME_BANDS,
    WAVELENGTH_GRID_NM,
    SpectralCurve,
    atmospheric_transmission,
    narrowband_filter,
)


def smooth_band(name, low, high, channel=None):
    """Réponse trapézoïdale simple entre deux longueurs d'onde."""
    return SpectralCurve.from_samples(
        name, "OSC_SENSOR" if channel else "OSC_FILTER",
        np.array([low - 20, low, high, high + 20]), np.array([0, 1, 1, 0]), channel=channel)


@pytest.fixture
def sensor():
    """Capteur RGB synthétique aux bandes qui se recouvrent partiellement."""
    return {
        "BLUE": smooth_band("B", 400, 500, "BLUE"),
        "GREEN": smooth_band("G", 480, 600, "GREEN"),
        "RED": smooth_band("R", 580, 700, "RED"),
    }


@pytest.fixture
def candidates():
    """Filtre large bande, filtre coupant le bleu et bi-bande L-eXtreme."""
    return {
        "broad": smooth_band("broad", 400, 700),
        "yellow": smooth_band("yellow", 520, 700),
        "dual": narrowband_filter("dual", L_EXTREME_BANDS),
    }


@pytest.fixture
def spectra():
    """Corps noirs de 3500 à 12000 K, couleurs variées comme un champ stellaire."""
    return blackbody_spectrum(np.linspace(3500, 12000, 60))


def observe(spectra, curve, sensor, noise, seed=0):
    """Flux observés : modèle, balance des blancs quelconque et bruit relatif."""
    truth = simulate_rgb(spectra, curve, sensor) * np.array([0.7, 1.0, 1.4])
    rng = np.random.default_rng(seed)
    return truth * (1 + noise * rng.standard_normal(truth.shape)), noise * truth


def test_blackbody_colours_follow_temperature():
    """Une étoile chaude est plus bleue qu'une étoile froide ; normalisation à 1."""
    cold, hot = blackbody_spectrum(np.array([3500.0, 12000.0]))
    assert cold.max() == hot.max() == 1
    blue, red = np.argmin(abs(WAVELENGTH_GRID_NM - 420)), np.argmin(abs(WAVELENGTH_GRID_NM - 680))
    assert hot[blue] / hot[red] > 1 > cold[blue] / cold[red]
    with pytest.raises(ValueError):
        blackbody_spectrum(np.array([0.0]))


def test_simulation_is_linear_and_respects_the_filter(spectra, sensor, candidates):
    """Flux proportionnels au spectre ; un bi-bande coupe le vert entre ses bandes."""
    broad = simulate_rgb(spectra, candidates["broad"], sensor)
    np.testing.assert_allclose(simulate_rgb(3 * spectra, candidates["broad"], sensor), 3 * broad)
    dual = simulate_rgb(spectra, candidates["dual"], sensor)
    assert (dual < broad).all()
    # Le vert synthétique (460-620 nm) ne voit que la bande OIII, pas Hα à 656 nm.
    oiii = narrowband_filter("OIII", (L_EXTREME_BANDS[0],))
    np.testing.assert_allclose(dual[:, 1], simulate_rgb(spectra, oiii, sensor)[:, 1])
    attenuated = simulate_rgb(spectra, candidates["broad"], sensor, atmospheric_transmission(2.0))
    assert (attenuated[:, 2] / broad[:, 2] < attenuated[:, 0] / broad[:, 0]).all()


def test_simulation_rejects_invalid_inputs(spectra, sensor, candidates):
    """Spectres hors grille, négatifs ou atmosphère mal dimensionnée : erreur."""
    with pytest.raises(ValueError, match="WAVELENGTH_GRID_NM"):
        simulate_rgb(spectra[:, :10], candidates["broad"], sensor)
    with pytest.raises(ValueError, match="négatifs"):
        simulate_rgb(-spectra, candidates["broad"], sensor)
    with pytest.raises(ValueError, match="atmosphérique"):
        simulate_rgb(spectra, candidates["broad"], sensor, np.ones(5))


@pytest.mark.parametrize("truth", ["broad", "yellow", "dual"])
def test_true_filter_ranks_first(spectra, sensor, candidates, truth):
    """Le vrai filtre obtient le meilleur score, nettement devant les autres."""
    observed, sigma = observe(spectra, candidates[truth], sensor, noise=0.02)
    scores = {
        name: score_filter(name, observed, sigma, simulate_rgb(spectra, curve, sensor))
        for name, curve in candidates.items()
    }
    best = min(scores.values(), key=lambda score: score.reduced_score)
    assert best.name == truth
    assert all(s.reduced_score > 3 * best.reduced_score for s in scores.values() if s.name != truth)


def test_score_absorbs_white_balance_and_follows_noise(spectra, sensor, candidates):
    """Les décalages valent ln(0,7) et ln(1,4) ; sans incertitude de modèle, le score ≈ 1."""
    observed, sigma = observe(spectra, candidates["broad"], sensor, noise=0.02)
    score = score_filter("broad", observed, sigma, simulate_rgb(spectra, candidates["broad"], sensor),
                         model_uncertainty=0.0)
    assert score.color_offsets == pytest.approx((np.log(0.7), np.log(1.4)), abs=0.02)
    assert 0.6 < score.reduced_score < 1.5
    assert score.residuals.shape == (spectra.shape[0], 2) and score.star_count == spectra.shape[0]


def test_colour_score_matches_the_flux_score(spectra, sensor, candidates):
    """score_colours sur ln(R/G), ln(B/G) reproduit score_filter sur les flux."""
    observed, sigma = observe(spectra, candidates["broad"], sensor, noise=0.02)
    simulated = simulate_rgb(spectra, candidates["yellow"], sensor)
    colours = np.log(observed[:, [RED, BLUE]] / observed[:, [GREEN]])
    relative = sigma / observed
    colour_sigma = np.hypot(relative[:, [RED, BLUE]], relative[:, [GREEN]])
    expected = score_filter("yellow", observed, sigma, simulated)
    actual = score_colours("yellow", colours, colour_sigma, simulated)
    assert actual.reduced_score == pytest.approx(expected.reduced_score)
    assert actual.color_offsets == pytest.approx(expected.color_offsets)
    with pytest.raises(ValueError, match="formes"):
        score_colours("yellow", colours[:, :1], colour_sigma[:, :1], simulated)


def test_outlier_star_has_bounded_influence(spectra, sensor, candidates):
    """Une étoile aberrante (Huber) ne fait pas basculer le classement."""
    observed, sigma = observe(spectra, candidates["broad"], sensor, noise=0.02)
    observed[0, 0] *= 20
    simulated = {name: simulate_rgb(spectra, curve, sensor) for name, curve in candidates.items()}
    scores = {name: score_filter(name, observed, sigma, sim).reduced_score for name, sim in simulated.items()}
    assert min(scores, key=scores.get) == "broad"


@pytest.mark.parametrize("change, message", [
    (lambda o, s, m: (o[:2], s[:2], m[:2]), "trois étoiles"),
    (lambda o, s, m: (o[:, :2], s[:, :2], m[:, :2]), "formes"),
    (lambda o, s, m: (o * 0, s, m), "observés"),
    (lambda o, s, m: (o, s * 0, m), "Incertitudes"),
    (lambda o, s, m: (o, s, m * np.nan), "simulés"),
])
def test_score_rejects_invalid_inputs(spectra, sensor, candidates, change, message):
    """Entrées incomplètes, nulles ou non finies : erreur explicite."""
    observed, sigma = observe(spectra, candidates["broad"], sensor, noise=0.02)
    simulated = simulate_rgb(spectra, candidates["broad"], sensor)
    with pytest.raises(ValueError, match=message):
        score_filter("broad", *change(observed, sigma, simulated))
    with pytest.raises(ValueError, match="négative"):
        score_filter("broad", observed, sigma, simulated, model_uncertainty=-1)

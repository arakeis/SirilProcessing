"""Photométrie d'ouverture RGB sur étoiles gaussiennes synthétiques."""

import numpy as np
import pytest

from lib.star_photometry import measure_rgb, select_colour_spread

SHAPE = (3, 120, 160)
COLOURS = np.array([0.6, 1.0, 1.3])


def render(stars, sigma_psf=1.5, noise=0.001, background=(0.02, 0.03, 0.04), seed=0):
    """Image RGB : fond par canal, étoiles gaussiennes (x, y, flux) et bruit."""
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[:SHAPE[1], :SHAPE[2]]
    image = np.array(background, float)[:, None, None] + noise * rng.standard_normal(SHAPE)
    for x, y, flux in stars:
        psf = np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma_psf**2)) / (2 * np.pi * sigma_psf**2)
        image += flux * COLOURS[:, None, None] * psf
    return image


@pytest.fixture
def field():
    """Grille d'étoiles isolées, positions décalées de fractions de pixel."""
    stars = [(25.3 + 30 * i, 25.7 + 30 * j, 2.0 + i + j) for i in range(4) for j in range(3)]
    return render(stars), np.array([(x, y) for x, y, _ in stars]), np.array([f for *_, f in stars])


def test_fluxes_colours_and_centroids_are_recovered(field):
    """Flux à 4σ près, centroïde affiné depuis une position décalée."""
    image, positions, flux = field
    result = measure_rgb(image, positions + 0.6, aperture_radius=6, saturation_level=10)
    assert result.valid.all() and set(result.reason) == {""}
    assert (np.abs(result.flux - flux[:, None] * COLOURS) < 4 * result.sigma).all()
    np.testing.assert_allclose(result.positions, positions, atol=0.05)
    assert (result.flux / result.sigma > 100).all()


def test_rejection_reasons():
    """Bord, voisin dans l'anneau, saturation, centroïde lointain, étoile faible."""
    stars = [(4, 60, 3), (60, 60, 3), (68, 60, 0.5), (110, 30, 50), (110, 90, 3), (40, 100, 0.01)]
    image = render(stars)
    image[:, 25:35, 105:115] = np.minimum(image[:, 25:35, 105:115], 1.0)
    predicted = np.array([(4, 60), (60, 60), (110, 30), (113.5, 90), (40, 100)], float)
    # Les voisins sont au catalogue, donc aux positions prédites, plus l'astre en (68, 60).
    neighbors = np.vstack([predicted, [(68, 60)]])
    result = measure_rgb(image, predicted, aperture_radius=4, neighbors=neighbors, saturation_level=0.99)
    assert list(result.reason) == ["edge", "crowded", "saturated", "offset", "faint"]
    assert not result.valid.any()


def test_default_saturation_is_a_fraction_of_each_channel_maximum(field):
    """Sans niveau fourni, l'étoile la plus brillante de chaque canal est saturée."""
    image, positions, flux = field
    result = measure_rgb(image, positions, aperture_radius=6)
    assert list(np.flatnonzero(~result.valid)) == [int(np.argmax(flux))]


def test_duplicate_neighbor_of_itself_is_not_crowding(field):
    """La liste de voisins peut contenir l'étoile mesurée elle-même."""
    image, positions, _ = field
    assert measure_rgb(image, positions, aperture_radius=6, neighbors=positions,
                       saturation_level=10).valid.all()


@pytest.mark.parametrize("data, positions, radius, annulus", [
    (np.zeros((2, 10, 10)), [(5, 5)], 2, None),
    (np.zeros(SHAPE), [(5, 5, 5)], 2, None),
    (np.zeros(SHAPE), [(np.nan, 5)], 2, None),
    (np.zeros(SHAPE), [(5, 5)], 3, (2, 5)),
])
def test_invalid_inputs(data, positions, radius, annulus):
    """Image non RGB, positions mal formées ou rayons incohérents : erreur."""
    with pytest.raises(ValueError):
        measure_rgb(data, np.array(positions, float), aperture_radius=radius, annulus=annulus)


def test_colour_spread_keeps_both_ends_and_best_snr():
    """Les rares étoiles bleues et rouges sont gardées ; dans une tranche, les plus nettes."""
    colour = np.r_[np.full(50, 1.0), -0.2, 3.5, np.nan]
    snr = np.r_[np.arange(50.0), 40.0, 35.0, 1000.0]
    chosen = select_colour_spread(colour, snr, max_stars=5, bins=4)
    assert {50, 51} <= set(chosen) and len(chosen) == 5 and 52 not in chosen
    assert set(chosen) - {50, 51} == {49, 48, 47}
    np.testing.assert_array_equal(select_colour_spread(colour, snr, max_stars=100), np.arange(52))


@pytest.mark.parametrize("colour, snr, count", [([1.0, 2.0], [1.0], 1), ([1.0], [1.0], 0)])
def test_colour_spread_rejects_invalid_inputs(colour, snr, count):
    """Tailles différentes ou nombre d'étoiles nul : erreur."""
    with pytest.raises(ValueError):
        select_colour_spread(np.array(colour), np.array(snr), max_stars=count)

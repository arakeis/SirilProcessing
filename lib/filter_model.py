"""Modèle direct des flux RGB stellaires et score de compatibilité d'un filtre.

Le flux attendu d'une étoile dans le canal ``c`` d'un capteur couleur est
proportionnel au nombre de photons reçus :

    M_c = Σ_λ F(λ) · λ · T_atm(λ) · T_filtre(λ) · S_c(λ) · Δλ

où ``F`` est la densité spectrale d'énergie de l'étoile, ``λ`` convertit
l'énergie en photons, ``T_atm`` la transmission atmosphérique, ``T_filtre`` le
filtre candidat et ``S_c`` la réponse du canal. Les constantes communes (surface
collectrice, temps de pose, gain) ne sont pas modélisées.

Le score compare des couleurs, pas des flux : ``ln(R/G)`` et ``ln(B/G)``
observés moins simulés. Les pertes achromatiques propres à chaque étoile
(ouverture photométrique, flat imparfait, voile nuageux) s'annulent ainsi. Un
décalage constant par couleur, équivalent à une balance des blancs, est ajusté :
seul compte l'écart de forme entre étoiles de couleurs différentes. Avec le bon
filtre, les résidus sont compatibles avec le bruit ; avec un mauvais filtre, ils
dérivent avec la couleur des étoiles.

Exemple
-------
>>> simulated = simulate_rgb(spectra, l_extreme, sensor, atmosphere)  # doctest: +SKIP
>>> score_filter("L-eXtreme", observed, sigma, simulated).reduced_score  # doctest: +SKIP
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from lib.spectral_response import (
    OSC_CHANNELS,
    WAVELENGTH_GRID_NM,
    WAVELENGTH_STEP_NM,
    SpectralCurve,
)

# Constante de Planck × vitesse de la lumière / constante de Boltzmann, en nm·K.
HC_OVER_K_NM_K = 1.438777e7

# Seuil de la perte de Huber, en écarts-types : au-delà, une étoile aberrante
# (variable, mélangée, mal mesurée) pèse linéairement et non quadratiquement.
HUBER_THRESHOLD = 3.0
# Incertitude relative minimale du modèle par flux (courbes numérisées,
# spectres reconstruits), ajoutée en quadrature au bruit de mesure.
DEFAULT_MODEL_UNCERTAINTY = 0.02
ROBUST_ITERATIONS = 20

RED, GREEN, BLUE = range(3)


def blackbody_spectrum(temperatures_k: np.ndarray) -> np.ndarray:
    """Densités spectrales de corps noirs sur la grille commune, à une constante près.

    Parameters
    ----------
    temperatures_k : numpy.ndarray
        Températures effectives en kelvins, strictement positives.

    Returns
    -------
    numpy.ndarray
        Tableau ``(étoiles, longueurs d'onde)`` proportionnel à B_λ(T), normalisé
        à 1 au maximum de chaque étoile.

    Notes
    -----
    Approximation utile aux essais synthétiques : les raies d'absorption
    (Balmer, bandes moléculaires des étoiles froides) sont absentes.
    """
    temperatures_k = np.atleast_1d(np.asarray(temperatures_k, dtype=float))
    if not (np.isfinite(temperatures_k).all() and (temperatures_k > 0).all()):
        raise ValueError("Températures de corps noir invalides")
    wavelength = WAVELENGTH_GRID_NM[None, :]
    exponent = HC_OVER_K_NM_K / (wavelength * temperatures_k[:, None])
    spectra = wavelength**-5 / np.expm1(exponent)
    return spectra / spectra.max(axis=1, keepdims=True)


def simulate_rgb(
    spectra: np.ndarray,
    filter_curve: SpectralCurve,
    sensor: dict[str, SpectralCurve],
    atmosphere: np.ndarray | None = None,
) -> np.ndarray:
    """Simule les flux R, G, B de chaque étoile pour un filtre candidat.

    Parameters
    ----------
    spectra : numpy.ndarray
        Densités spectrales d'énergie ``(étoiles, longueurs d'onde)`` sur
        ``WAVELENGTH_GRID_NM``, positives ou nulles.
    filter_curve : SpectralCurve
        Transmission du filtre candidat.
    sensor : dict[str, SpectralCurve]
        Réponses ``RED``, ``GREEN`` et ``BLUE`` du capteur.
    atmosphere : numpy.ndarray | None
        Transmission atmosphérique sur la grille ; ``None`` pour l'ignorer.

    Returns
    -------
    numpy.ndarray
        Flux ``(étoiles, 3)`` en photons, à un facteur commun près.

    Raises
    ------
    ValueError
        Dimensions incompatibles avec la grille ou valeurs négatives ou non finies.
    """
    spectra = np.atleast_2d(np.asarray(spectra, dtype=float))
    if spectra.shape[1] != WAVELENGTH_GRID_NM.size:
        raise ValueError("Les spectres doivent être échantillonnés sur WAVELENGTH_GRID_NM")
    if not np.isfinite(spectra).all() or (spectra < 0).any():
        raise ValueError("Spectres négatifs ou non finis")
    transmission = filter_curve.values.copy()
    if atmosphere is not None:
        if atmosphere.shape != WAVELENGTH_GRID_NM.shape:
            raise ValueError("Transmission atmosphérique hors grille")
        transmission = transmission * atmosphere
    photons = spectra * (WAVELENGTH_GRID_NM * transmission * WAVELENGTH_STEP_NM)
    response = np.stack([sensor[channel].values for channel in OSC_CHANNELS], axis=1)
    return photons @ response


@dataclass(frozen=True)
class FilterScore:
    """Compatibilité d'un filtre candidat avec les couleurs observées.

    Attributes
    ----------
    name : str
        Filtre candidat.
    reduced_score : float
        Somme des pertes de Huber (×2) divisée par les degrés de liberté ; proche
        de 1 si les résidus suivent le bruit annoncé, nettement plus grand sinon.
    color_offsets : tuple[float, float]
        Décalages ajustés de ``ln(R/G)`` et ``ln(B/G)`` (balance des blancs).
    residuals : numpy.ndarray
        Résidus normalisés ``(étoiles, 2)`` après ajustement des décalages.
    star_count : int
        Nombre d'étoiles utilisées.
    """

    name: str
    reduced_score: float
    color_offsets: tuple[float, float]
    residuals: np.ndarray
    star_count: int


def _huber_location(values: np.ndarray, sigma: np.ndarray) -> float:
    """Moyenne pondérée robuste (Huber) par moindres carrés repondérés."""
    location = float(np.median(values))
    for _ in range(ROBUST_ITERATIONS):
        z = np.abs(values - location) / sigma
        weights = np.minimum(1.0, HUBER_THRESHOLD / np.maximum(z, 1e-12)) / sigma**2
        updated = float(np.sum(weights * values) / np.sum(weights))
        if abs(updated - location) < 1e-10:
            return updated
        location = updated
    return location


def _huber_loss(z: np.ndarray) -> np.ndarray:
    """Perte de Huber, égale à z²/2 sous le seuil et linéaire au-delà."""
    absolute = np.abs(z)
    return np.where(
        absolute <= HUBER_THRESHOLD,
        0.5 * z**2,
        HUBER_THRESHOLD * absolute - 0.5 * HUBER_THRESHOLD**2,
    )


def score_filter(
    name: str,
    observed: np.ndarray,
    observed_sigma: np.ndarray,
    simulated: np.ndarray,
    model_uncertainty: float = DEFAULT_MODEL_UNCERTAINTY,
) -> FilterScore:
    """Score la compatibilité des couleurs observées avec un filtre candidat.

    Parameters
    ----------
    name : str
        Nom du filtre candidat, recopié dans le résultat.
    observed, observed_sigma : numpy.ndarray
        Flux mesurés ``(étoiles, 3)`` en R, G, B et leurs écarts-types, dans la
        même unité. Les flux doivent être strictement positifs.
    simulated : numpy.ndarray
        Flux simulés ``(étoiles, 3)`` par :func:`simulate_rgb` pour ce filtre.
    model_uncertainty : float
        Incertitude relative du modèle par flux, ajoutée en quadrature.

    Returns
    -------
    FilterScore
        Score réduit, décalages ajustés et résidus normalisés.

    Raises
    ------
    ValueError
        Formes différentes, moins de trois étoiles, flux non positifs ou non
        finis, incertitudes non positives.
    """
    observed = np.asarray(observed, dtype=float)
    observed_sigma = np.asarray(observed_sigma, dtype=float)
    simulated = np.asarray(simulated, dtype=float)
    if not observed.shape == observed_sigma.shape == simulated.shape or observed.ndim != 2 or observed.shape[1] != 3:
        raise ValueError("Flux observés, incertitudes et simulations : formes (étoiles, 3) attendues")
    if observed.shape[0] < 3:
        raise ValueError("Au moins trois étoiles sont nécessaires")
    for label, values in (("observés", observed), ("simulés", simulated)):
        if not np.isfinite(values).all() or (values <= 0).any():
            raise ValueError(f"Flux {label} non positifs ou non finis")
    if not np.isfinite(observed_sigma).all() or (observed_sigma <= 0).any():
        raise ValueError("Incertitudes de mesure non positives ou non finies")
    if model_uncertainty < 0:
        raise ValueError("Incertitude du modèle négative")

    relative = observed_sigma / observed
    colours = np.log(observed[:, [RED, BLUE]] / observed[:, [GREEN]])
    colour_sigma = np.sqrt(relative[:, [RED, BLUE]] ** 2 + relative[:, [GREEN]] ** 2)
    return score_colours(name, colours, colour_sigma, simulated, model_uncertainty)


def score_colours(
    name: str,
    colours: np.ndarray,
    colour_sigma: np.ndarray,
    simulated: np.ndarray,
    model_uncertainty: float = DEFAULT_MODEL_UNCERTAINTY,
) -> FilterScore:
    """Score la compatibilité de couleurs observées ``ln(R/G)`` et ``ln(B/G)``.

    Cœur de :func:`score_filter`, utilisable directement lorsque les couleurs
    d'une étoile combinent plusieurs poses.

    Parameters
    ----------
    name : str
        Nom du filtre candidat, recopié dans le résultat.
    colours, colour_sigma : numpy.ndarray
        Couleurs ``(étoiles, 2)`` ``ln(R/G)`` et ``ln(B/G)`` et leurs
        écarts-types de mesure, strictement positifs.
    simulated : numpy.ndarray
        Flux simulés ``(étoiles, 3)`` par :func:`simulate_rgb` pour ce filtre.
    model_uncertainty : float
        Incertitude relative du modèle par flux ; elle ajoute
        ``2·σ_modèle²`` à la variance de chaque couleur.

    Returns
    -------
    FilterScore
        Score réduit, décalages ajustés et résidus normalisés.

    Raises
    ------
    ValueError
        Formes incohérentes, moins de trois étoiles, valeurs non finies ou
        incertitudes non positives.
    """
    colours = np.asarray(colours, dtype=float)
    colour_sigma = np.asarray(colour_sigma, dtype=float)
    simulated = np.asarray(simulated, dtype=float)
    if colours.shape != colour_sigma.shape or colours.ndim != 2 or colours.shape[1] != 2:
        raise ValueError("Couleurs et incertitudes : formes (étoiles, 2) attendues")
    if simulated.shape != (colours.shape[0], 3):
        raise ValueError("Flux simulés : forme (étoiles, 3) attendue")
    if colours.shape[0] < 3:
        raise ValueError("Au moins trois étoiles sont nécessaires")
    if not np.isfinite(colours).all():
        raise ValueError("Couleurs observées non finies")
    if not np.isfinite(simulated).all() or (simulated <= 0).any():
        raise ValueError("Flux simulés non positifs ou non finis")
    if not np.isfinite(colour_sigma).all() or (colour_sigma <= 0).any():
        raise ValueError("Incertitudes de mesure non positives ou non finies")
    if model_uncertainty < 0:
        raise ValueError("Incertitude du modèle négative")

    residuals, offsets = [], []
    for column, channel in enumerate((RED, BLUE)):
        difference = colours[:, column] - np.log(simulated[:, channel] / simulated[:, GREEN])
        sigma = np.sqrt(colour_sigma[:, column] ** 2 + 2 * model_uncertainty**2)
        offset = _huber_location(difference, sigma)
        offsets.append(offset)
        residuals.append((difference - offset) / sigma)
    normalized = np.stack(residuals, axis=1)
    degrees_of_freedom = normalized.size - len(offsets)
    reduced = float(2 * _huber_loss(normalized).sum() / degrees_of_freedom)
    return FilterScore(name, reduced, (offsets[0], offsets[1]), normalized, colours.shape[0])

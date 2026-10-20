"""Photométrie d'ouverture RGB d'étoiles à positions connues.

Les positions viennent d'un catalogue projeté par le WCS de l'image. Elles sont
affinées par un centroïde pondéré sur la somme des canaux, puis la même
ouverture circulaire mesure les trois canaux : les rapports de couleur ne
dépendent ainsi ni de la forme de la PSF ni d'une perte commune aux canaux. Le
fond est la médiane d'un anneau, son bruit par pixel l'écart absolu médian
(MAD) de cet anneau.

L'incertitude ne contient que le bruit du fond : le gain effectif d'un master
empilé n'est pas connu. Le bruit de photons des étoiles brillantes et les
erreurs de modèle sont couverts par l'incertitude relative du score
(:func:`lib.filter_model.score_filter`).

Une étoile est rejetée si elle sort de l'image, si un autre astre fourni tombe
dans son anneau, si un pixel de l'ouverture atteint la saturation, si son
centroïde s'éloigne trop de la position prédite ou si son rapport signal sur
bruit est trop faible dans un canal.

Exemple
-------
>>> photometry = measure_rgb(image.data, positions, aperture_radius=6)  # doctest: +SKIP
>>> photometry.flux[photometry.valid]  # doctest: +SKIP
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.spatial import cKDTree

# Rapport entre l'écart absolu médian et l'écart-type d'une loi normale.
MAD_TO_SIGMA = 1.4826
DEFAULT_MIN_SNR = 30.0
# Fraction du maximum de chaque canal au-delà de laquelle un pixel est saturé.
DEFAULT_SATURATION_FRACTION = 0.9
CENTROID_ITERATIONS = 3

REJECTION_REASONS = ("edge", "crowded", "saturated", "offset", "faint")
DEFAULT_COLOUR_BINS = 10


@dataclass(frozen=True)
class RgbPhotometry:
    """Flux RGB mesurés pour une liste de positions.

    Attributes
    ----------
    positions : numpy.ndarray
        Positions affinées ``(étoiles, 2)`` en ``(x, y)`` pixels, origine 0 au
        centre du premier pixel, comme Astropy.
    flux, sigma : numpy.ndarray
        Flux ``(étoiles, 3)`` R, G, B moins le fond et leurs écarts-types.
    valid : numpy.ndarray
        Étoiles utilisables pour le score.
    reason : numpy.ndarray
        Motif de rejet (``edge``, ``crowded``, ``saturated``, ``offset``,
        ``faint``) ou chaîne vide pour une étoile retenue.
    """

    positions: np.ndarray
    flux: np.ndarray
    sigma: np.ndarray
    valid: np.ndarray
    reason: np.ndarray


def _stamp_offsets(radius: float) -> tuple[np.ndarray, np.ndarray]:
    """Décalages entiers ``(dy, dx)`` d'un carré de demi-côté ``ceil(radius)``."""
    half = int(np.ceil(radius))
    return np.mgrid[-half:half + 1, -half:half + 1]


def measure_rgb(
    data: np.ndarray,
    positions: np.ndarray,
    *,
    aperture_radius: float,
    annulus: tuple[float, float] | None = None,
    neighbors: np.ndarray | None = None,
    min_snr: float = DEFAULT_MIN_SNR,
    saturation_level: float | np.ndarray | None = None,
    max_offset: float | None = None,
) -> RgbPhotometry:
    """Mesure les flux R, G, B d'étoiles à positions approchées.

    Parameters
    ----------
    data : numpy.ndarray
        Image linéaire ``(3, H, W)`` dans l'ordre R, G, B.
    positions : numpy.ndarray
        Positions prédites ``(étoiles, 2)`` en ``(x, y)`` pixels, origine 0.
    aperture_radius : float
        Rayon de l'ouverture en pixels, typiquement 2 à 3 FWHM.
    annulus : tuple[float, float] | None
        Rayons intérieur et extérieur de l'anneau de fond ; par défaut
        ``(1,5 r, 2,5 r)``.
    neighbors : numpy.ndarray | None
        Positions ``(n, 2)`` d'autres astres connus, plus faibles compris ; une
        étoile en a un dans son anneau est rejetée. ``None`` : ``positions``.
    min_snr : float
        Rapport signal sur bruit minimal dans chaque canal.
    saturation_level : float | numpy.ndarray | None
        Niveau de saturation, global ou par canal. Par défaut 90 % du maximum
        de chaque canal, ce qui suppose les étoiles les plus brillantes du champ
        saturées, comme sur une pose du ciel profond.
    max_offset : float | None
        Écart maximal entre centroïde et position prédite ; par défaut la moitié
        du rayon de l'ouverture.

    Returns
    -------
    RgbPhotometry
        Flux, incertitudes et motifs de rejet, dans l'ordre de ``positions``.

    Raises
    ------
    ValueError
        Image non RGB, positions mal formées ou rayons incohérents.
    """
    data = np.asarray(data, dtype=float)
    positions = np.atleast_2d(np.asarray(positions, dtype=float))
    if data.ndim != 3 or data.shape[0] != 3:
        raise ValueError("Image RGB (3, H, W) attendue")
    if positions.ndim != 2 or positions.shape[1] != 2 or not np.isfinite(positions).all():
        raise ValueError("Positions (étoiles, 2) finies attendues")
    inner, outer = annulus or (1.5 * aperture_radius, 2.5 * aperture_radius)
    if not 0 < aperture_radius < inner < outer:
        raise ValueError("Rayons attendus : 0 < ouverture < anneau intérieur < anneau extérieur")
    max_offset = 0.5 * aperture_radius if max_offset is None else max_offset

    count = positions.shape[0]
    flux, sigma = np.zeros((count, 3)), np.ones((count, 3))
    refined = positions.copy()
    reason = np.full(count, "", dtype=object)
    if saturation_level is None:
        saturation_level = DEFAULT_SATURATION_FRACTION * np.nanmax(data, axis=(1, 2))
    saturation = np.broadcast_to(np.asarray(saturation_level, dtype=float), (3,))
    height, width = data.shape[1:]
    dy, dx = _stamp_offsets(outer)
    half = dy.max()

    others = cKDTree(positions if neighbors is None else np.atleast_2d(neighbors))
    for index, predicted in enumerate(positions):
        centre = predicted.copy()
        inside = True
        for _ in range(CENTROID_ITERATIONS):
            column, row = np.rint(centre).astype(int)
            if not (half <= column < width - half and half <= row < height - half):
                inside = False
                break
            stamp = data[:, row + dy, column + dx]
            radius2 = (column + dx - centre[0]) ** 2 + (row + dy - centre[1]) ** 2
            ring = (radius2 >= inner**2) & (radius2 <= outer**2)
            signal = np.clip(stamp.sum(axis=0) - np.median(stamp[:, ring].sum(axis=0)), 0, None)
            signal = np.where(radius2 <= aperture_radius**2, signal, 0)
            if signal.sum() <= 0:
                break
            centre = np.array([np.sum(signal * (column + dx)), np.sum(signal * (row + dy))]) / signal.sum()
        refined[index] = centre
        if not inside:
            reason[index] = "edge"
            continue
        # La position prédite elle-même et ses doublons exacts ne comptent pas.
        close = others.query_ball_point(predicted, outer)
        if any(np.hypot(*(others.data[j] - predicted)) > 1e-6 for j in close):
            reason[index] = "crowded"
            continue
        column, row = np.rint(centre).astype(int)
        stamp = data[:, row + dy, column + dx]
        radius2 = (column + dx - centre[0]) ** 2 + (row + dy - centre[1]) ** 2
        aperture = radius2 <= aperture_radius**2
        ring = (radius2 >= inner**2) & (radius2 <= outer**2)
        background = np.median(stamp[:, ring], axis=1)
        noise = MAD_TO_SIGMA * np.median(np.abs(stamp[:, ring] - background[:, None]), axis=1)
        pixels, ring_pixels = aperture.sum(), ring.sum()
        flux[index] = stamp[:, aperture].sum(axis=1) - pixels * background
        sigma[index] = np.maximum(noise, np.finfo(float).tiny) * np.sqrt(pixels * (1 + pixels / ring_pixels))
        if (stamp[:, aperture].max(axis=1) >= saturation).any():
            reason[index] = "saturated"
        elif np.hypot(*(centre - predicted)) > max_offset:
            reason[index] = "offset"
        elif (flux[index] < min_snr * sigma[index]).any():
            reason[index] = "faint"
    return RgbPhotometry(refined, flux, sigma, reason == "", reason.astype(str))


def select_colour_spread(
    colour: np.ndarray, snr: np.ndarray, max_stars: int, bins: int = DEFAULT_COLOUR_BINS
) -> np.ndarray:
    """Choisit au plus ``max_stars`` étoiles réparties sur toute la gamme de couleurs.

    La gamme des couleurs est découpée en ``bins`` tranches de même largeur.
    Les tranches sont parcourues tour à tour, en prenant chaque fois la
    meilleure étoile restante (plus grand rapport signal sur bruit) : les
    étoiles des extrémités bleue et rouge, rares mais les plus utiles au score,
    sont ainsi conservées.

    Parameters
    ----------
    colour : numpy.ndarray
        Couleur de catalogue de chaque étoile, par exemple Gaia ``BP − RP`` ;
        les valeurs non finies sont exclues.
    snr : numpy.ndarray
        Rapport signal sur bruit de chaque étoile, par exemple le minimum sur
        les trois canaux.
    max_stars : int
        Nombre maximal d'étoiles retenues, strictement positif.
    bins : int
        Nombre de tranches de couleur.

    Returns
    -------
    numpy.ndarray
        Indices des étoiles retenues, en ordre croissant.

    Raises
    ------
    ValueError
        Tableaux de tailles différentes, ``max_stars`` ou ``bins`` non positifs.
    """
    colour, snr = np.asarray(colour, dtype=float), np.asarray(snr, dtype=float)
    if colour.shape != snr.shape or colour.ndim != 1:
        raise ValueError("Couleurs et rapports signal sur bruit : tableaux 1D de même taille attendus")
    if max_stars < 1 or bins < 1:
        raise ValueError("max_stars et bins doivent être strictement positifs")
    candidates = np.flatnonzero(np.isfinite(colour) & np.isfinite(snr))
    if candidates.size <= max_stars:
        return candidates
    edges = np.linspace(colour[candidates].min(), colour[candidates].max(), bins + 1)
    slot = np.clip(np.searchsorted(edges, colour[candidates], side="right") - 1, 0, bins - 1)
    queues = [list(candidates[slot == b][np.argsort(-snr[candidates[slot == b]])]) for b in range(bins)]
    chosen: list[int] = []
    while len(chosen) < max_stars:
        for queue in queues:
            if queue and len(chosen) < max_stars:
                chosen.append(int(queue.pop(0)))
    return np.sort(np.array(chosen))

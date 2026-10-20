"""Dématriçage superpixel d'une image brute de capteur couleur (CFA).

Chaque bloc 2×2 de la matrice de Bayer donne un pixel RGB : le rouge et le bleu
du bloc, et la moyenne de ses deux verts. L'image obtenue a une résolution
moitié, sans interpolation : les trois canaux d'une étoile proviennent
exactement des mêmes photosites, ce qui convient à la photométrie de couleur.

Le motif ``BAYERPAT`` (``RGGB``, ``BGGR``, ``GRBG``, ``GBRG``), décalé par
``XBAYROFF``/``YBAYROFF``, se lit dans le sens de lecture du haut vers le bas.
Pour une image ``ROWORDER = 'BOTTOM-UP'``, la parité des lignes est donc
inversée lorsque la hauteur est paire. Sans ``ROWORDER``, l'image est supposée
``TOP-DOWN``, comme l'écrivent Ekos et NINA.

Exemple
-------
>>> rgb, header = superpixel_rgb(hdu.data, hdu.header)  # doctest: +SKIP
>>> rgb.shape  # doctest: +SKIP
(3, 1411, 2072)
"""

from __future__ import annotations

import re

import numpy as np
from astropy.io import fits

BAYER_PATTERNS = ("RGGB", "BGGR", "GRBG", "GBRG")
# Mots-clés décrivant la matrice ou une solution astrométrique à pleine
# résolution, qui ne s'appliquent plus à l'image superpixel.
DROPPED_KEYWORDS = ("BAYERPAT", "XBAYROFF", "YBAYROFF", "PLTSOLVD")
WCS_KEYWORD = re.compile(r"(CTYPE|CRPIX|CRVAL|CDELT|CUNIT|CROTA)\d|(CD|PC)\d_\d|(A|B|AP|BP)_(\d_\d|ORDER)")


def superpixel_rgb(data: np.ndarray, header: fits.Header) -> tuple[np.ndarray, fits.Header]:
    """Convertit une image CFA en image RGB de résolution moitié.

    Parameters
    ----------
    data : numpy.ndarray
        Image brute ``(H, W)`` telle que lue dans le fichier.
    header : astropy.io.fits.Header
        En-tête contenant ``BAYERPAT`` et, au besoin, ``XBAYROFF``,
        ``YBAYROFF`` et ``ROWORDER``.

    Returns
    -------
    tuple[numpy.ndarray, astropy.io.fits.Header]
        Image ``(3, H // 2, W // 2)`` en R, G, B (flottants), rangée comme
        l'entrée, et en-tête copié : taille de pixel et binning doublés, mots-clés
        de matrice et WCS retirés. Une ligne ou colonne impaire finale est
        ignorée.

    Raises
    ------
    ValueError
        Image non bidimensionnelle, motif absent ou inconnu, ``ROWORDER``
        inconnu.
    """
    data = np.asarray(data)
    if data.ndim != 2 or min(data.shape) < 2:
        raise ValueError("Image CFA (H, W) attendue")
    pattern = str(header.get("BAYERPAT", "")).strip().upper()
    if pattern not in BAYER_PATTERNS:
        raise ValueError(f"Motif de Bayer absent ou inconnu : {pattern!r}")
    row_order = str(header.get("ROWORDER", "TOP-DOWN")).strip().upper()
    if row_order not in ("TOP-DOWN", "BOTTOM-UP"):
        raise ValueError(f"ROWORDER inconnu : {row_order!r}")

    x_offset = int(header.get("XBAYROFF", 0)) % 2
    y_offset = int(header.get("YBAYROFF", 0)) % 2
    if row_order == "BOTTOM-UP":
        # La ligne stockée i est la ligne H-1-i dans le sens de lecture du motif.
        y_offset ^= (data.shape[0] - 1) % 2
    height, width = (data.shape[0] // 2) * 2, (data.shape[1] // 2) * 2

    def plane(row: int, column: int) -> np.ndarray:
        """Photosites du bloc 2×2 à la position (ligne, colonne) du motif."""
        start_row, start_column = (row + y_offset) % 2, (column + x_offset) % 2
        return data[start_row:height:2, start_column:width:2].astype(np.float64)

    cells = {}
    for index, colour in enumerate(pattern):
        cells.setdefault(colour, []).append(plane(index // 2, index % 2))
    rgb = np.stack([cells["R"][0], (cells["G"][0] + cells["G"][1]) / 2, cells["B"][0]])

    result = header.copy()
    for key in DROPPED_KEYWORDS:
        result.remove(key, ignore_missing=True, remove_all=True)
    for key in [key for key in result if WCS_KEYWORD.fullmatch(key)]:
        result.remove(key, ignore_missing=True, remove_all=True)
    for key in ("XPIXSZ", "YPIXSZ", "XBINNING", "YBINNING"):
        if isinstance(result.get(key), (int, float)):
            result[key] = result[key] * 2
    return rgb, result

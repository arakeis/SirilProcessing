"""Dématriçage superpixel : motifs, décalages, ordre des lignes et en-tête."""

import numpy as np
import pytest
from astropy.io import fits

from lib.cfa_superpixel import superpixel_rgb

HEIGHT, WIDTH = 6, 8


def mosaic(pattern, x_offset=0, y_offset=0):
    """Image CFA dont chaque photosite vaut 1 (R), 2 ou 3 (G) ou 5 (B), en lecture haut-bas."""
    values = {"R": 1.0, "B": 5.0}
    cfa = np.zeros((HEIGHT, WIDTH))
    greens = iter((2.0, 3.0))
    for index, colour in enumerate(pattern):
        value = values.get(colour) or next(greens)
        row, column = (index // 2 + y_offset) % 2, (index % 2 + x_offset) % 2
        cfa[row::2, column::2] = value
    return cfa


@pytest.mark.parametrize("pattern", ["RGGB", "BGGR", "GRBG", "GBRG"])
@pytest.mark.parametrize("offsets", [(0, 0), (1, 0), (0, 1), (1, 1)])
def test_every_pattern_and_offset_gives_red_green_blue(pattern, offsets):
    """Rouge, moyenne des verts et bleu, quel que soit le motif ou son décalage."""
    header = fits.Header({"BAYERPAT": pattern, "XBAYROFF": offsets[0], "YBAYROFF": offsets[1],
                          "ROWORDER": "TOP-DOWN"})
    rgb, _ = superpixel_rgb(mosaic(pattern, *offsets), header)
    assert rgb.shape == (3, HEIGHT // 2, WIDTH // 2)
    np.testing.assert_array_equal(rgb[:, 0, 0], [1.0, 2.5, 5.0])
    assert all(np.unique(plane).size == 1 for plane in rgb)


def test_bottom_up_inverts_row_parity_for_even_height():
    """Une image BOTTOM-UP de hauteur paire est lue avec le motif retourné."""
    stored = mosaic("RGGB")[::-1]
    rgb, _ = superpixel_rgb(stored, fits.Header({"BAYERPAT": "RGGB", "ROWORDER": "BOTTOM-UP"}))
    np.testing.assert_array_equal(rgb[:, 0, 0], [1.0, 2.5, 5.0])
    # Sans ROWORDER, l'image est supposée TOP-DOWN, comme chez Ekos et NINA.
    rgb, _ = superpixel_rgb(mosaic("RGGB"), fits.Header({"BAYERPAT": "RGGB"}))
    np.testing.assert_array_equal(rgb[:, 0, 0], [1.0, 2.5, 5.0])


def test_odd_edges_are_dropped_and_header_is_adapted():
    """Dernière ligne impaire ignorée ; pixel et binning doublés ; matrice et WCS retirés."""
    header = fits.Header({"BAYERPAT": "RGGB", "XPIXSZ": 4.63, "YPIXSZ": 4.63, "XBINNING": 1,
                          "CTYPE1": "RA---TAN", "CRPIX1": 10.0, "CD1_1": 1e-4, "PLTSOLVD": True,
                          "EXPTIME": 120.0})
    cfa = np.vstack([mosaic("RGGB"), np.full((1, WIDTH), 99.0)]).astype(np.uint16)
    rgb, result = superpixel_rgb(cfa, header)
    assert rgb.shape == (3, HEIGHT // 2, WIDTH // 2) and rgb.dtype == np.float64
    assert result["XPIXSZ"] == pytest.approx(9.26) and result["XBINNING"] == 2
    assert not {"BAYERPAT", "CTYPE1", "CRPIX1", "CD1_1", "PLTSOLVD"} & set(result)
    assert result["EXPTIME"] == 120.0 and header["BAYERPAT"] == "RGGB"


@pytest.mark.parametrize("data, header", [
    (np.zeros((2, 4, 4)), {"BAYERPAT": "RGGB"}),
    (np.zeros((4, 4)), {}),
    (np.zeros((4, 4)), {"BAYERPAT": "RGBG"}),
    (np.zeros((4, 4)), {"BAYERPAT": "RGGB", "ROWORDER": "LEFT-RIGHT"}),
])
def test_invalid_inputs(data, header):
    """Image non CFA, motif absent ou inconnu, ordre des lignes inconnu : erreur."""
    with pytest.raises(ValueError):
        superpixel_rgb(data, fits.Header(header))

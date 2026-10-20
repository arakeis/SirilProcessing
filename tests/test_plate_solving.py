"""Résolution astrométrique : indications d'en-tête, commande Siril et contrôle du résultat."""

from pathlib import Path
from unittest.mock import Mock

import numpy as np
import pytest
from astropy.io import fits
from astropy.wcs import WCS

from lib.plate_solving import SOLVED_NAME, SolveHints, plate_solve, platesolve_command, solve_hints


def solved_header(shape):
    """En-tête minimal tel qu'écrit par Siril après une résolution réussie."""
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [shape[-1] / 2, shape[-2] / 2]
    wcs.wcs.crval = [311.5, 30.6]
    wcs.wcs.cdelt = [-3.3e-4, 3.3e-4]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    header = wcs.to_header()
    header["PLTSOLVD"] = True
    return header


def fake_siril(*, success=True, shape=None, solved=True):
    """Service Siril simulé : lit l'entrée et écrit l'image résolue."""
    siril = Mock()

    def run(script, working_dir, script_name):
        data = fits.getdata(Path(working_dir) / "plate_solve_input.fits")
        header = solved_header(data.shape) if solved else fits.Header()
        fits.writeto(Path(working_dir) / f"{SOLVED_NAME}.fits",
                     np.zeros(shape or data.shape, np.float32), header, overwrite=True)
        return success

    siril.run_siril_script.side_effect = run
    return siril


@pytest.fixture
def image():
    """Image RGB et en-tête Ekos avec une ancienne solution de monture."""
    header = fits.Header({"RA": 311.4953, "DEC": 30.5868, "FOCALLEN": 802.08, "XPIXSZ": 4.63,
                          "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN", "PLTSOLVD": True})
    return np.ones((3, 8, 12)), header


def test_hints_from_degrees_sexagesimal_or_missing():
    """RA/DEC en degrés priment ; sinon OBJCTRA/OBJCTDEC ; valeurs invalides ignorées."""
    hints = solve_hints(fits.Header({"RA": 311.5, "DEC": 30.6, "OBJCTRA": "0 0 0", "OBJCTDEC": "0 0 0",
                                     "FOCALLEN": 800, "XPIXSZ": 4.63}))
    assert hints == SolveHints((311.5, 30.6), 800.0, 4.63)
    hints = solve_hints(fits.Header({"RA": 400.0, "DEC": 0.0, "OBJCTRA": "20 45 58.8",
                                     "OBJCTDEC": "+30 35 12", "FOCALLEN": 0, "XPIXSZ": "?"}))
    assert hints.center_deg == pytest.approx((311.495, 30.5867), abs=1e-3)
    assert hints.focal_mm is None and hints.pixel_size_um is None
    assert solve_hints(fits.Header({"OBJCTRA": "?", "OBJCTDEC": "?"})) == SolveHints()


def test_command_puts_coordinates_before_force():
    """Siril 1.4.1 refuse les coordonnées après -force ; -noflip conserve les pixels."""
    assert platesolve_command(SolveHints((311.5, 30.6), 802.08, 4.63)) == (
        "platesolve 311.5000000000,30.6000000000 -force -noflip -focal=802.08 -pixelsize=4.63 -catalog=gaia")
    assert platesolve_command(SolveHints(), "localgaia") == "platesolve -force -noflip -catalog=localgaia"


def test_solve_returns_siril_header_and_keeps_input(image, tmp_path):
    """Le script charge l'entrée, résout puis sauvegarde ; l'en-tête source est intact."""
    data, header = image
    siril = fake_siril()
    solved = plate_solve(data, header, tmp_path / "work dir", siril=siril)
    script = siril.run_siril_script.call_args.args[0]
    assert f'cd "{(tmp_path / "work dir").resolve()}"' in script
    assert script.index("load ") < script.index("platesolve 311.4953") < script.index("save ")
    assert WCS(solved, naxis=2).has_celestial and solved["CRVAL1"] == 311.5
    assert "PLTSOLVD" in header
    assert "PLTSOLVD" not in fits.getheader(tmp_path / "work dir/plate_solve_input.fits")


@pytest.mark.parametrize("siril, message", [
    (fake_siril(success=False), "Échec de Siril"),
    (fake_siril(shape=(3, 12, 8)), "dimensions"),
    (fake_siril(solved=False), "solution astrométrique"),
])
def test_solve_failures_are_explicit(image, tmp_path, siril, message):
    """Échec du script, image retournée ou en-tête non résolu : erreur explicite."""
    with pytest.raises(RuntimeError, match=message):
        plate_solve(*image, tmp_path, siril=siril)


def test_unsafe_work_dir_is_refused(image, tmp_path):
    """Un guillemet casserait la commande « cd » du script Siril."""
    with pytest.raises(ValueError, match="incompatible"):
        plate_solve(*image, tmp_path / 'a"b', siril=fake_siril())

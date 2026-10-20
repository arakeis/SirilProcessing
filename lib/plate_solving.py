"""Résolution astrométrique d'une image en mémoire avec Siril ``platesolve``.

L'image (FITS ou XISF déjà lue) est écrite dans un dossier de travail, résolue
par Siril sur le catalogue Gaia DR3, puis seul l'en-tête résolu est relu. Les
pixels ne sont pas modifiés : ``-noflip`` interdit à Siril de retourner une
image vue à l'envers, de sorte que le WCS obtenu s'applique directement au
tableau fourni.

Les indications de départ (centre, focale, taille des pixels) sont lues dans
l'en-tête lorsqu'elles existent : mots-clés ``RA``/``DEC`` en degrés, sinon
``OBJCTRA``/``OBJCTDEC`` en sexagésimal, ``FOCALLEN`` en mm et ``XPIXSZ`` en µm.

Notes
-----
Siril 1.4.1 refuse les coordonnées du centre placées après ``-force`` : elles
suivent directement le nom de la commande. Le catalogue ``gaia`` distant exige
le réseau. Après une résolution réussie, Siril enregistre la focale et la taille
de pixel trouvées comme valeurs par défaut de ses préférences.

Exemple
-------
>>> header = plate_solve(image.data, image.header, Path("work"))  # doctest: +SKIP
>>> WCS(header, naxis=2).pixel_to_world(0, 0)  # doctest: +SKIP
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from astropy import units
from astropy.coordinates import SkyCoord
from astropy.io import fits
from astropy.wcs import WCS

from lib.siril_utils import Siril

INPUT_NAME = "plate_solve_input"
SOLVED_NAME = "plate_solve_solved"
DEFAULT_CATALOG = "gaia"


@dataclass(frozen=True)
class SolveHints:
    """Indications de départ passées à ``platesolve``.

    Attributes
    ----------
    center_deg : tuple[float, float] | None
        Ascension droite et déclinaison approximatives du centre, en degrés.
    focal_mm : float | None
        Focale en millimètres.
    pixel_size_um : float | None
        Taille des pixels en micromètres, binning compris.
    """

    center_deg: tuple[float, float] | None = None
    focal_mm: float | None = None
    pixel_size_um: float | None = None


def _positive(header: fits.Header, key: str) -> float | None:
    """Valeur numérique strictement positive d'un mot-clé, sinon ``None``."""
    try:
        value = float(header[key])
    except (KeyError, TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def solve_hints(header: fits.Header) -> SolveHints:
    """Extrait centre, focale et taille de pixel d'un en-tête d'acquisition.

    Parameters
    ----------
    header : astropy.io.fits.Header
        En-tête de l'image (Ekos, NINA, PixInsight).

    Returns
    -------
    SolveHints
        Indications trouvées ; un champ absent ou invalide vaut ``None``.
    """
    center = None
    try:
        ra, dec = float(header["RA"]), float(header["DEC"])
        if 0 <= ra < 360 and -90 <= dec <= 90:
            center = (ra, dec)
    except (KeyError, TypeError, ValueError):
        pass
    if center is None and "OBJCTRA" in header and "OBJCTDEC" in header:
        try:
            coordinates = SkyCoord(header["OBJCTRA"], header["OBJCTDEC"], unit=(units.hourangle, units.deg))
            center = (float(coordinates.ra.deg), float(coordinates.dec.deg))
        except ValueError:
            pass
    return SolveHints(center, _positive(header, "FOCALLEN"), _positive(header, "XPIXSZ"))


def platesolve_command(hints: SolveHints, catalog: str = DEFAULT_CATALOG) -> str:
    """Construit la commande Siril ``platesolve`` à partir des indications.

    Parameters
    ----------
    hints : SolveHints
        Centre, focale et taille de pixel ; les champs ``None`` sont omis.
    catalog : str
        Catalogue astrométrique Siril (``gaia``, ``localgaia``…).

    Returns
    -------
    str
        Commande avec les coordonnées avant ``-force``, comme l'exige Siril 1.4.1.
    """
    command = ["platesolve"]
    if hints.center_deg is not None:
        command.append(f"{hints.center_deg[0]:.10f},{hints.center_deg[1]:.10f}")
    command += ["-force", "-noflip"]
    if hints.focal_mm is not None:
        command.append(f"-focal={hints.focal_mm:.10g}")
    if hints.pixel_size_um is not None:
        command.append(f"-pixelsize={hints.pixel_size_um:.10g}")
    command.append(f"-catalog={catalog}")
    return " ".join(command)


def plate_solve(
    data: np.ndarray,
    header: fits.Header,
    work_dir: Path,
    *,
    siril: Siril | None = None,
    hints: SolveHints | None = None,
    catalog: str = DEFAULT_CATALOG,
) -> fits.Header:
    """Résout une image avec Siril et retourne son en-tête muni d'un WCS.

    Parameters
    ----------
    data : numpy.ndarray
        Image ``(H, W)`` ou ``(canaux, H, W)``, rangée comme ``header``
        l'indique (``ROWORDER``).
    header : astropy.io.fits.Header
        En-tête de l'image, recopié dans le fichier passé à Siril.
    work_dir : pathlib.Path
        Dossier de travail, créé au besoin ; les fichiers existants du même nom
        sont remplacés.
    siril : Siril | None
        Service Siril configuré ; ``None`` utilise la configuration par défaut.
    hints : SolveHints | None
        Indications de départ ; ``None`` les lit dans ``header``.
    catalog : str
        Catalogue astrométrique Siril.

    Returns
    -------
    astropy.io.fits.Header
        En-tête écrit par Siril, avec une solution céleste valide.

    Raises
    ------
    ValueError
        Dossier de travail incompatible avec un script Siril.
    RuntimeError
        Échec de Siril, image modifiée ou absence de solution céleste.
    """
    work_dir = Path(work_dir).resolve()
    if any(character in str(work_dir) for character in ('"', "\n", "\r", "\x00")):
        raise ValueError("Dossier de travail incompatible avec les scripts Siril")
    work_dir.mkdir(parents=True, exist_ok=True)
    solved_path = work_dir / f"{SOLVED_NAME}.fits"
    solved_path.unlink(missing_ok=True)
    # Le marqueur PLTSOLVD n'est conservé que s'il vient de cette résolution.
    header = header.copy()
    header.remove("PLTSOLVD", ignore_missing=True)
    fits.PrimaryHDU(np.asarray(data, dtype=np.float32), header).writeto(
        work_dir / f"{INPUT_NAME}.fits", overwrite=True, output_verify="silentfix")
    command = platesolve_command(hints or solve_hints(header), catalog)
    script = "\n".join([
        "requires 1.4", f'cd "{work_dir}"', "online", "setext fits",
        f"load {INPUT_NAME}", command, f"save {SOLVED_NAME}", "close", "",
    ])
    siril = siril or Siril()
    if not siril.run_siril_script(script, str(work_dir), script_name="plate_solve"):
        raise RuntimeError(f"Échec de Siril : {command} (journal dans {work_dir})")
    if not solved_path.exists():
        raise RuntimeError(f"Siril n'a pas produit {solved_path.name}")
    with fits.open(solved_path) as hdul:
        solved = hdul[0].header.copy()
        if hdul[0].data is None or hdul[0].data.shape != np.shape(data):
            raise RuntimeError("Siril a modifié les dimensions de l'image")
    if solved.get("PLTSOLVD") is not True or not WCS(solved, naxis=2).has_celestial:
        raise RuntimeError("Siril n'a pas écrit de solution astrométrique")
    return solved

"""Sources et spectres XP de Gaia DR3, téléchargés auprès de l'archive de l'ESA.

Deux services de l'archive Gaia (https://gea.esac.esa.int) sont utilisés :

- le service TAP, en mode asynchrone, donne les sources d'un champ (position,
  magnitude G, couleur BP − RP, disponibilité d'un spectre XP) depuis la table
  allégée ``gaiadr3.gaia_source_lite``. Les requêtes anonymes sont limitées à
  60 s ; sur la table complète, un champ de la Voie lactée jusqu'à G = 17
  dépasse parfois cette limite, alors que la table allégée répond en quelques
  secondes ;
- le service DataLink fournit les spectres XP échantillonnés : 343 valeurs de
  336 à 1020 nm au pas de 2 nm, en W·m⁻²·nm⁻¹, avec leurs incertitudes.

Les réponses sont gardées dans un dossier de cache : une table de sources par
requête et un fichier ``.npy`` par spectre. Une nouvelle analyse du même champ
ne télécharge rien. Les erreurs réseau passagères (codes 5xx, délai dépassé)
sont réessayées quelques fois avant d'échouer.

Exemple
-------
>>> sources = query_field_sources(311.5, 30.6, 0.9, 17.0, Path("cache"))  # doctest: +SKIP
>>> flux, error = fetch_xp_spectra(sources["source_id"][:10], Path("cache"))  # doctest: +SKIP
>>> spectra = xp_to_grid(flux)  # doctest: +SKIP
"""

from __future__ import annotations

import hashlib
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ElementTree
from pathlib import Path

import numpy as np
from astropy.table import Table

from lib.spectral_response import WAVELENGTH_GRID_NM

GAIA_TAP_URL = "https://gea.esac.esa.int/tap-server/tap"
GAIA_DATALINK_URL = "https://gea.esac.esa.int/data-server/data"
XP_WAVELENGTH_NM = np.arange(336.0, 1021.0, 2.0)
# Nombre maximal d'identifiants par requête DataLink pour un utilisateur anonyme.
DATALINK_BATCH = 50
HTTP_TIMEOUT_S = 120
HTTP_ATTEMPTS = 3
TAP_POLL_INTERVAL_S = 2.0
TAP_MAX_WAIT_S = 600.0
UWS_NAMESPACE = {"uws": "http://www.ivoa.net/xml/UWS/v1.0"}


def _request(url: str, params: dict[str, str] | None = None) -> bytes:
    """Requête HTTP (POST si ``params``), réessayée sur erreur serveur ou délai."""
    data = urllib.parse.urlencode(params).encode() if params is not None else None
    for attempt in range(HTTP_ATTEMPTS):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, data=data), timeout=HTTP_TIMEOUT_S) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            if error.code < 500 or attempt == HTTP_ATTEMPTS - 1:
                # Les pages d'erreur de l'archive donnent la cause après « due to: ».
                body = error.read().decode(errors="replace") if error.fp else ""
                reason = re.search(r"due to:([^<]*)", body)
                detail = f" ({reason.group(1).strip()})" if reason else ""
                raise RuntimeError(f"Archive Gaia : HTTP {error.code} pour {url}{detail}") from error
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == HTTP_ATTEMPTS - 1:
                raise RuntimeError(f"Archive Gaia injoignable : {url} ({error})") from error
        time.sleep(2**attempt)
    raise AssertionError("inaccessible")


def run_tap_query(query: str) -> Table:
    """Exécute une requête ADQL en mode asynchrone et retourne la table résultat.

    Parameters
    ----------
    query : str
        Requête ADQL.

    Returns
    -------
    astropy.table.Table
        Résultat lu depuis le CSV de l'archive.

    Raises
    ------
    RuntimeError
        Service injoignable, requête en erreur ou durée maximale dépassée.
    """
    job = _request(f"{GAIA_TAP_URL}/async", {
        "REQUEST": "doQuery", "LANG": "ADQL", "FORMAT": "csv", "QUERY": query, "PHASE": "RUN"})
    job_id = (ElementTree.fromstring(job).findtext("uws:jobId", namespaces=UWS_NAMESPACE) or "").strip()
    if not job_id:
        raise RuntimeError("Archive Gaia : identifiant de requête TAP absent")
    job_url = f"{GAIA_TAP_URL}/async/{job_id}"
    deadline = time.monotonic() + TAP_MAX_WAIT_S
    while (phase := _request(f"{job_url}/phase").decode().strip()) in ("PENDING", "QUEUED", "EXECUTING"):
        if time.monotonic() > deadline:
            raise RuntimeError(f"Archive Gaia : requête TAP {job_id} trop longue")
        time.sleep(TAP_POLL_INTERVAL_S)
    if phase != "COMPLETED":
        raise RuntimeError(f"Archive Gaia : requête TAP {job_id} terminée en {phase}")
    return Table.read(_request(f"{job_url}/results/result").decode(), format="ascii.csv")


def query_field_sources(ra_deg: float, dec_deg: float, radius_deg: float, max_g: float,
                        cache_dir: Path) -> Table:
    """Sources Gaia DR3 d'un cône, plus brillantes que ``max_g``.

    Parameters
    ----------
    ra_deg, dec_deg : float
        Centre du cône en degrés (ICRS).
    radius_deg : float
        Rayon en degrés, par exemple la demi-diagonale du champ.
    max_g : float
        Magnitude G limite ; les sources plus faibles servent de voisins pour
        le contrôle d'encombrement, les spectres ne concernent que les plus
        brillantes.
    cache_dir : pathlib.Path
        Dossier de cache, créé au besoin.

    Returns
    -------
    astropy.table.Table
        Colonnes ``source_id``, ``ra``, ``dec``, ``phot_g_mean_mag``,
        ``bp_rp`` et ``has_xp_sampled`` (booléen).

    Raises
    ------
    ValueError
        Cône invalide.
    RuntimeError
        Archive injoignable ou requête en erreur.
    """
    if not (0 <= ra_deg < 360 and -90 <= dec_deg <= 90 and 0 < radius_deg <= 5):
        raise ValueError("Cône invalide : 0 ≤ RA < 360, |Dec| ≤ 90, 0 < rayon ≤ 5°")
    query = (
        "SELECT source_id, ra, dec, phot_g_mean_mag, bp_rp, has_xp_sampled "
        "FROM gaiadr3.gaia_source_lite WHERE 1 = CONTAINS(POINT('ICRS', ra, dec), "
        f"CIRCLE('ICRS', {ra_deg:.6f}, {dec_deg:.6f}, {radius_deg:.6f})) "
        f"AND phot_g_mean_mag < {max_g:.3f}"
    )
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache = cache_dir / f"sources_{hashlib.sha256(query.encode()).hexdigest()[:16]}.ecsv"
    if cache.exists():
        return Table.read(cache, format="ascii.ecsv")
    table = run_tap_query(query)
    flags = np.asarray(table["has_xp_sampled"]).astype(str)
    table["has_xp_sampled"] = np.char.lower(flags) == "true"
    table.write(cache, format="ascii.ecsv")
    return table


def fetch_xp_spectra(source_ids, cache_dir: Path) -> tuple[np.ndarray, np.ndarray]:
    """Spectres XP échantillonnés des sources demandées, depuis le cache ou l'archive.

    Parameters
    ----------
    source_ids : array_like of int
        Identifiants Gaia DR3.
    cache_dir : pathlib.Path
        Dossier de cache ; les spectres sont rangés dans ``xp_sampled/``.

    Returns
    -------
    tuple[numpy.ndarray, numpy.ndarray]
        Flux et incertitudes ``(sources, 343)`` sur ``XP_WAVELENGTH_NM``, en
        W·m⁻²·nm⁻¹ ; une ligne de NaN pour une source sans spectre.

    Raises
    ------
    RuntimeError
        Archive injoignable.
    """
    source_ids = [int(source_id) for source_id in np.atleast_1d(source_ids)]
    folder = Path(cache_dir) / "xp_sampled"
    folder.mkdir(parents=True, exist_ok=True)
    missing = [source_id for source_id in dict.fromkeys(source_ids) if not (folder / f"{source_id}.npy").exists()]
    for start in range(0, len(missing), DATALINK_BATCH):
        batch = missing[start:start + DATALINK_BATCH]
        text = _request(GAIA_DATALINK_URL, {
            "RETRIEVAL_TYPE": "XP_SAMPLED", "DATA_STRUCTURE": "DATAMODEL_GAIA", "FORMAT": "ECSV",
            "ID": ",".join(map(str, batch))}).decode()
        received = set()
        if text.strip():
            table = Table.read(text, format="ascii.ecsv")
            for row in table:
                values = np.stack([np.ma.filled(np.ma.asarray(row[name], dtype=float), np.nan)
                                   for name in ("flux", "flux_error")])
                np.save(folder / f"{int(row['source_id'])}.npy", values.astype(np.float32))
                received.add(int(row["source_id"]))
        # Une source sans spectre est mémorisée pour ne pas être redemandée.
        for source_id in set(batch) - received:
            np.save(folder / f"{source_id}.npy", np.full((2, XP_WAVELENGTH_NM.size), np.nan, np.float32))
    spectra = np.stack([np.load(folder / f"{source_id}.npy") for source_id in source_ids]) if source_ids else (
        np.empty((0, 2, XP_WAVELENGTH_NM.size)))
    return spectra[:, 0].astype(float), spectra[:, 1].astype(float)


def xp_to_grid(flux: np.ndarray) -> np.ndarray:
    """Rééchantillonne des spectres XP sur ``WAVELENGTH_GRID_NM``.

    Parameters
    ----------
    flux : numpy.ndarray
        Flux ``(sources, 343)`` sur ``XP_WAVELENGTH_NM``, sans NaN.

    Returns
    -------
    numpy.ndarray
        Densités spectrales ``(sources, grille)``. Les valeurs négatives
        (bruit des étoiles faibles) sont ramenées à zéro ; hors de 336–1020 nm
        le flux est nul, sans effet pour l'IMX294 dont la réponse s'étend de
        401 à 966 nm.

    Raises
    ------
    ValueError
        Dimensions inattendues ou valeurs non finies.
    """
    flux = np.atleast_2d(np.asarray(flux, dtype=float))
    if flux.shape[1] != XP_WAVELENGTH_NM.size or not np.isfinite(flux).all():
        raise ValueError("Spectres XP (sources, 343) finis attendus")
    grid = np.stack([np.interp(WAVELENGTH_GRID_NM, XP_WAVELENGTH_NM, row, left=0.0, right=0.0) for row in flux])
    return np.clip(grid, 0.0, None)

"""Archive Gaia simulée : requête TAP asynchrone, spectres XP, cache et erreurs."""

import io
import urllib.error

import numpy as np
import pytest
from astropy.table import Table

from lib import gaia_xp
from lib.gaia_xp import XP_WAVELENGTH_NM, fetch_xp_spectra, query_field_sources, xp_to_grid
from lib.spectral_response import WAVELENGTH_GRID_NM

JOB = (b'<uws:job xmlns:uws="http://www.ivoa.net/xml/UWS/v1.0">'
       b'<uws:jobId>1700</uws:jobId><uws:phase>PENDING</uws:phase></uws:job>')
SOURCES = "source_id,ra,dec,phot_g_mean_mag,bp_rp,has_xp_sampled\n11,311.5,30.6,10.2,0.8,true\n12,311.6,30.5,16.1,1.4,false\n"


def xp_ecsv(rows):
    """Réponse DataLink ECSV : une ligne par (source_id, flux)."""
    table = Table({"source_id": [r[0] for r in rows], "flux": [r[1] for r in rows],
                   "flux_error": [0.1 * r[1] for r in rows]})
    stream = io.StringIO()
    table.write(stream, format="ascii.ecsv")
    return stream.getvalue().encode()


class FakeArchive:
    """Remplace ``_request`` : journalise les appels et répond selon l'URL."""

    def __init__(self, phases=("EXECUTING", "COMPLETED"), spectra=None):
        self.calls, self.phases, self.spectra = [], list(phases), spectra or {}

    def __call__(self, url, params=None):
        self.calls.append((url, params))
        if url.endswith("/async"):
            return JOB
        if url.endswith("/phase"):
            return self.phases.pop(0).encode()
        if url.endswith("/results/result"):
            return SOURCES.encode()
        ids = [int(i) for i in params["ID"].split(",")]
        return xp_ecsv([(i, self.spectra[i]) for i in ids if i in self.spectra])


@pytest.fixture(autouse=True)
def no_wait(monkeypatch):
    """Ni attente entre deux interrogations, ni pause avant une nouvelle tentative."""
    monkeypatch.setattr(gaia_xp.time, "sleep", lambda seconds: None)


def test_field_query_runs_async_job_and_caches(monkeypatch, tmp_path):
    """Requête lancée en asynchrone, suivie jusqu'à COMPLETED, puis relue du cache."""
    archive = FakeArchive()
    monkeypatch.setattr(gaia_xp, "_request", archive)
    sources = query_field_sources(311.5, 30.6, 0.9, 17.0, tmp_path)
    assert list(sources["source_id"]) == [11, 12] and list(sources["has_xp_sampled"]) == [True, False]
    query = archive.calls[0][1]["QUERY"]
    assert "CIRCLE('ICRS', 311.500000, 30.600000, 0.900000)" in query and "phot_g_mean_mag < 17.000" in query
    assert archive.calls[0][1]["PHASE"] == "RUN" and archive.calls[-1][0].endswith("/async/1700/results/result")
    count = len(archive.calls)
    assert list(query_field_sources(311.5, 30.6, 0.9, 17.0, tmp_path)["source_id"]) == [11, 12]
    assert len(archive.calls) == count


@pytest.mark.parametrize("phase", ["ERROR", "ABORTED"])
def test_failed_tap_job_is_reported(monkeypatch, tmp_path, phase):
    """Une requête TAP en erreur ou abandonnée lève une erreur explicite."""
    monkeypatch.setattr(gaia_xp, "_request", FakeArchive(phases=[phase]))
    with pytest.raises(RuntimeError, match=phase):
        query_field_sources(311.5, 30.6, 0.9, 17.0, tmp_path)


def test_invalid_cone_is_refused(tmp_path):
    """Coordonnées hors limites ou rayon nul : refus avant tout appel réseau."""
    with pytest.raises(ValueError):
        query_field_sources(400, 30.6, 0.9, 17.0, tmp_path)
    with pytest.raises(ValueError):
        query_field_sources(311.5, 30.6, 0, 17.0, tmp_path)


def test_spectra_are_downloaded_once_and_missing_ones_are_nan(monkeypatch, tmp_path):
    """Spectres mis en cache ; une source sans spectre donne une ligne NaN mémorisée."""
    spectrum = np.linspace(1, 2, XP_WAVELENGTH_NM.size)
    archive = FakeArchive(spectra={11: spectrum})
    monkeypatch.setattr(gaia_xp, "_request", archive)
    flux, error = fetch_xp_spectra([11, 12, 11], tmp_path)
    assert flux.shape == error.shape == (3, XP_WAVELENGTH_NM.size)
    np.testing.assert_allclose(flux[0], spectrum, rtol=1e-6)
    np.testing.assert_allclose(error[2], 0.1 * spectrum, rtol=1e-6)
    assert np.isnan(flux[1]).all()
    assert archive.calls[0][1]["ID"] == "11,12" and archive.calls[0][1]["DATA_STRUCTURE"] == "DATAMODEL_GAIA"
    fetch_xp_spectra([12, 11], tmp_path)
    assert len(archive.calls) == 1


def test_downloads_are_split_in_batches(monkeypatch, tmp_path):
    """Au-delà de DATALINK_BATCH identifiants, plusieurs requêtes sont envoyées."""
    archive = FakeArchive()
    monkeypatch.setattr(gaia_xp, "_request", archive)
    monkeypatch.setattr(gaia_xp, "DATALINK_BATCH", 2)
    fetch_xp_spectra([1, 2, 3, 4, 5], tmp_path)
    assert [call[1]["ID"] for call in archive.calls] == ["1,2", "3,4", "5"]


def test_server_errors_are_retried_then_reported(monkeypatch):
    """Erreur 503 réessayée ; erreur 400 immédiate ; échec final explicite."""
    attempts = []

    def urlopen(request, timeout):
        attempts.append(request.full_url)
        if len(attempts) < 3:
            raise urllib.error.HTTPError(request.full_url, 503, "busy", {}, None)
        return io.BytesIO(b"ok")

    monkeypatch.setattr(gaia_xp.urllib.request, "urlopen", urlopen)
    assert gaia_xp._request("https://example.invalid/x") == b"ok" and len(attempts) == 3

    def bad_request(request, timeout):
        page = io.BytesIO(b"<p>Error, due to: Maximum number of Source Ids reached (max: 50)</p>")
        raise urllib.error.HTTPError(request.full_url, 400, "bad", {}, page)

    monkeypatch.setattr(gaia_xp.urllib.request, "urlopen", bad_request)
    with pytest.raises(RuntimeError, match=r"HTTP 400 .*\(Maximum number of Source Ids reached \(max: 50\)\)"):
        gaia_xp._request("https://example.invalid/x")

    def timeout(request, timeout):
        raise TimeoutError("read")

    monkeypatch.setattr(gaia_xp.urllib.request, "urlopen", timeout)
    with pytest.raises(RuntimeError, match="injoignable"):
        gaia_xp._request("https://example.invalid/x")


def test_resampling_to_model_grid():
    """Interpolation linéaire, flux nul hors de 336–1020 nm, valeurs négatives ramenées à 0."""
    flux = np.vstack([XP_WAVELENGTH_NM / 1000, np.full(XP_WAVELENGTH_NM.size, -1.0)])
    grid = xp_to_grid(flux)
    assert grid.shape == (2, WAVELENGTH_GRID_NM.size)
    inside = (WAVELENGTH_GRID_NM >= 336) & (WAVELENGTH_GRID_NM <= 1020)
    np.testing.assert_allclose(grid[0, inside], WAVELENGTH_GRID_NM[inside] / 1000)
    assert (grid[0, ~inside] == 0).all() and (grid[1] == 0).all()
    with pytest.raises(ValueError):
        xp_to_grid(np.full((1, XP_WAVELENGTH_NM.size), np.nan))

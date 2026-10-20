"""Contrats StarNet : une séparation linéaire, erreurs fatales et préférences isolées."""

import argparse
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

from lib.star_separation import StarNetSeparator, quote_siril


def test_separation_signed_residual_and_geometry(tmp_path: Path, monkeypatch) -> None:
    """Une sortie retournée est réalignée et son résidu signé reconstruit l'entrée."""
    source = tmp_path / "rgb.fits"
    data = np.linspace(0.01, 0.7, 3 * 8 * 9).reshape(3, 8, 9).astype("float32")
    fits.writeto(source, data, fits.Header({"ROWORDER": "TOP-DOWN", "OBJECT": "Test"}))
    executable = tmp_path / "starnet++"
    executable.write_text("test")
    executable.chmod(0o755)
    calls = []

    class FakeSiril:
        """Double externe enregistrant les préférences et la commande exécutée."""

        def __init__(self, **kwargs):
            """Accepte le service configuré."""

        def run_siril_script(self, script, work, **kwargs):
            """Émet un starless signé, dans l'autre orientation FITS."""
            calls.append(script)
            assert kwargs["initfile"].is_file()
            fits.writeto(
                Path(work) / "starless_linear.fits",
                (data + 0.001)[:, ::-1],
                fits.Header({"ROWORDER": "BOTTOM-UP"}),
            )
            return True

    monkeypatch.setattr("lib.star_separation.Siril", FakeSiril)
    report = StarNetSeparator().post_process(
        source,
        tmp_path / "separation.json",
        argparse.Namespace(starnet_path=executable),
    )
    assert len(calls) == 1
    assert "starnet -stretch" in calls[0]
    assert "-nostarmask" not in calls[0]
    starless = fits.getdata(report["starless_linear"])
    stars = fits.getdata(report["stars_linear"])
    np.testing.assert_allclose(starless + stars, data, atol=1e-7)
    assert np.all(stars < 0)
    assert report["negative_fraction"] == 1
    assert fits.getheader(report["starless_linear"])["OBJECT"] == "Test"
    np.testing.assert_array_equal(fits.getdata(source), data)


@pytest.mark.parametrize(
    "header", [{"SPNLIN": True}, {"BAYERPAT": "RGGB"}, {"FILTER": "Starless"}]
)
def test_invalid_input_rejected(tmp_path: Path, header: dict) -> None:
    """Les entrées connues non linéaires/CFA/starless sont explicitement refusées."""
    source = tmp_path / "input.fits"
    fits.writeto(source, np.ones((3, 8, 8), dtype="float32") * 0.1, fits.Header(header))
    with pytest.raises(ValueError):
        StarNetSeparator().post_process(
            source, tmp_path / "report.json", argparse.Namespace()
        )


def test_quote_rejects_injection() -> None:
    """Un chemin ne peut pas ajouter de commande Siril."""
    with pytest.raises(ValueError):
        quote_siril('test"\nexit')


def test_uint16_conversion_preserves_scale_and_extensions(tmp_path: Path) -> None:
    """Le passage FITS entier vers float32 ne conserve pas un BZERO/BSCALE obsolète."""
    from lib.restoration_quality import normalized_planes
    from lib.star_separation import write_rgb

    source = tmp_path / "integer.fits"
    data = np.linspace(0, 65535, 3 * 8 * 8).reshape(3, 8, 8).astype(np.uint16)
    fits.HDUList(
        [fits.PrimaryHDU(data), fits.ImageHDU(np.arange(5), name="AUX")]
    ).writeto(source)
    normalized = normalized_planes(source)
    output = tmp_path / "float.fits"
    write_rgb(source, output, normalized, role="STARLESS")
    np.testing.assert_allclose(fits.getdata(output), data / 65535, atol=1e-7)
    with fits.open(output) as hdul:
        assert hdul[0].header["SPROLE"] == "STARLESS"
        assert hdul["AUX"].data.tolist() == list(range(5))


def test_starnet_failure_is_fatal(tmp_path: Path, monkeypatch) -> None:
    """Un échec de binaire/modèle ne rend ni image étoilée de secours ni succès."""
    from unittest.mock import Mock

    source = tmp_path / "rgb.fits"
    fits.writeto(source, np.full((3, 8, 8), 0.01, dtype=np.float32))
    executable = tmp_path / "starnet++"
    executable.touch()
    executable.chmod(0o755)
    fake_siril = Mock()
    fake_siril.run_siril_script.return_value = False
    monkeypatch.setattr("lib.star_separation.Siril", Mock(return_value=fake_siril))
    with pytest.raises(RuntimeError, match="StarNet échouée"):
        StarNetSeparator().post_process(
            source,
            tmp_path / "failure.json",
            argparse.Namespace(starnet_path=executable),
        )
    assert fake_siril.run_siril_script.call_count == 1
    assert not (tmp_path / "failure.json").exists()


@pytest.mark.parametrize("value", [np.nan, np.inf, -0.001, 1.001])
def test_invalid_intensities_are_never_silently_clipped(value: float) -> None:
    """La frontière image refuse les valeurs non finies et hors domaine."""
    from lib.star_separation import validate_rgb

    with pytest.raises(ValueError):
        validate_rgb(np.full((3, 8, 8), value))


def test_siril_preferences_directory_on_macos(monkeypatch, tmp_path):
    """Hors Flatpak, macOS lit les préférences dans Application Support."""
    import argparse
    from lib import star_separation
    directory = tmp_path / "Library/Application Support/org.siril.Siril/siril"
    directory.mkdir(parents=True)
    (directory / "config.1.4.ini").write_text("[core]\nstarnet_exe=/opt/starnet++\n")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setattr(star_separation.sys, "platform", "darwin")
    preferences, path = star_separation.StarNetSeparator.preferences(
        argparse.Namespace(siril_mode="native")
    )
    assert path == directory / "config.1.4.ini"
    assert preferences.get("core", "starnet_exe") == "/opt/starnet++"

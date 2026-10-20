"""Poids acquis à la demande, inférence native et contrôles communs sans réseau."""

import argparse
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from astropy.io import fits

from lib.graxpert import GraXpertDenoiseProcessor
from lib.graxpert_inference import GraXpertEngine
from lib.graxpert_models import GraXpertModels
from lib.config import Config
from lib.denoising import NoiseReductionProcessor
from lib.restoration_chains import RestorationChainProcessor


@pytest.fixture
def model_environment(tmp_path, monkeypatch):
    """Petit poids synthétique avec manifeste de test, sans cache utilisateur."""
    payload = b"verified-test-model"
    manifest = tmp_path / "models.json"
    manifest.write_text(
        json.dumps(
            {
                "3.0.2": dict(
                    size=len(payload),
                    sha256=hashlib.sha256(payload).hexdigest(),
                    provenance="test fixture",
                    reference="test",
                    license="test",
                )
            }
        )
    )
    monkeypatch.setattr("lib.graxpert_models.MANIFEST_PATH", manifest)
    monkeypatch.setattr(GraXpertModels, "_local_sources", lambda self: ())
    args = argparse.Namespace(graxpert_model_dir=tmp_path / "models")
    model = args.graxpert_model_dir / "3.0.2/model.onnx"
    return args, model, payload


def test_import_and_cache_integrity(model_environment, tmp_path, monkeypatch):
    """Le cache existant est importé sans être modifié ; un poids corrompu est réparé."""
    args, model, payload = model_environment
    original = tmp_path / "original.onnx"
    original.write_bytes(payload)
    monkeypatch.setattr(GraXpertModels, "_local_sources", lambda self: (original,))
    manager = GraXpertModels(args)
    assert manager.ensure_model() == model
    assert original.read_bytes() == payload
    model.write_bytes(b"corrupted")
    assert manager.ensure_model().read_bytes() == payload
    assert not list(model.parent.glob("*.part"))


def test_official_download_is_automatic_and_isolated(model_environment, tmp_path):
    """Le CLI acquiert seulement les poids dans un XDG temporaire, sans réseau réel."""
    args, model, payload = model_environment
    binary = tmp_path / "GraXpert-linux"
    binary.write_text(f"""#!{sys.executable}
import os,sys
from pathlib import Path
assert sys.argv[sys.argv.index('-cmd')+1]=='denoising'
assert sys.argv[sys.argv.index('-gpu')+1]=='false'
p=Path(os.environ['XDG_DATA_HOME'])/'GraXpert/denoise-ai-models/3.0.2/model.onnx'
p.parent.mkdir(parents=True)
p.write_bytes({payload!r})
""")
    binary.chmod(0o755)
    args.graxpert_path = str(binary)
    assert GraXpertModels(args).ensure_model().read_bytes() == payload
    assert not list(args.graxpert_model_dir.glob("download-*"))
    # L’utilisation suivante fonctionne sans le binaire d’acquisition.
    binary.unlink()
    assert GraXpertModels(args).ensure_model() == model


def test_bad_download_does_not_replace_previous_model(model_environment, tmp_path):
    """Un téléchargement invalide laisse le fichier précédent intact."""
    args, model, _ = model_environment
    model.parent.mkdir(parents=True)
    model.write_bytes(b"previous")
    binary = tmp_path / "bad-download"
    binary.write_text("#!/bin/sh\nexit 1\n")
    binary.chmod(0o755)
    args.graxpert_path = str(binary)
    with pytest.raises(RuntimeError, match="Téléchargement"):
        GraXpertModels(args).ensure_model()
    assert model.read_bytes() == b"previous"
    assert not list(args.graxpert_model_dir.glob("download-*"))


class Session:
    """Réseau déterministe NHWC pour vérifier normalisation, tuilage et mélange."""

    def run(self, names, feed):
        """Réduit les écarts à la médiane sans changer la forme du tenseur."""
        assert feed["gen_input_image"].dtype == np.float32
        return [feed["gen_input_image"] * 0.8]

    def get_providers(self):
        """Identifie le périphérique effectivement simulé."""
        return ["CPUExecutionProvider"]


@pytest.fixture
def native_engine(model_environment, monkeypatch):
    """Fournit un poids vérifié et un réseau indépendant de l’installation ONNX."""
    pytest.importorskip("onnxruntime")
    args, model, payload = model_environment
    model.parent.mkdir(parents=True)
    model.write_bytes(payload)
    monkeypatch.setattr(
        GraXpertEngine, "_create_session", lambda self, model, gpu: Session()
    )
    return args


@pytest.mark.parametrize("shape", [(191, 275), (3, 191, 275), (7, 13)])
def test_native_tiling_blending_and_geometry(tmp_path, native_engine, shape):
    """Les bords, canaux et petites images sont couverts sans rééchantillonnage."""
    source, candidate = tmp_path / "source.fits", tmp_path / "candidate.fits"
    original = np.random.default_rng(99).normal(0.1, 0.001, shape).astype("float32")
    header = fits.Header({"ROWORDER": "TOP-DOWN", "CRPIX1": 12.5, "BUNIT": "relative"})
    fits.writeto(source, original, header)
    args = native_engine
    args.graxpert_strength = 0.5
    args.graxpert_batch_size = 3
    result = GraXpertEngine(args).process(source, candidate)
    data = fits.getdata(candidate)
    sampled = original[::4, ::4] if original.ndim == 2 else original[:, ::4, ::4]
    median = (
        np.median(sampled)
        if original.ndim == 2
        else np.median(sampled, axis=(1, 2))[:, None, None]
    )
    np.testing.assert_allclose(data, median + 0.9 * (original - median), atol=3e-8)
    assert data.shape == original.shape
    assert fits.getheader(candidate)["ROWORDER"] == "TOP-DOWN"
    assert fits.getheader(candidate)["CRPIX1"] == 12.5
    assert result["providers"] == ["CPUExecutionProvider"]
    np.testing.assert_array_equal(fits.getdata(source), original)


def test_native_preserves_uint16_and_auxiliary_hdu(tmp_path, native_engine):
    """Le format entier et les extensions FITS sont conservés à intensité nulle."""
    source, candidate = tmp_path / "source.fits", tmp_path / "candidate.fits"
    data = np.random.default_rng(3).integers(9000, 10000, (128, 128), dtype="uint16")
    fits.HDUList([fits.PrimaryHDU(data), fits.ImageHDU(np.arange(5))]).writeto(source)
    native_engine.graxpert_strength = 0
    GraXpertEngine(native_engine).process(source, candidate)
    with fits.open(candidate) as hdul:
        assert len(hdul) == 2
        assert hdul[0].data.dtype == np.dtype("uint16")
        np.testing.assert_array_equal(hdul[0].data, data)
        np.testing.assert_array_equal(hdul[1].data, np.arange(5))


@pytest.mark.parametrize("allowed", [False, True])
def test_gpu_failure_retries_only_if_allowed(
    tmp_path, native_engine, monkeypatch, allowed
):
    """Le repli recommence toute l’image et est enregistré explicitement."""
    source, candidate = tmp_path / "source.fits", tmp_path / "candidate.fits"
    fits.writeto(
        source,
        np.random.default_rng(6).normal(0.1, 0.001, (128, 128)).astype("float32"),
    )
    attempts = []

    def create(self, model, gpu):
        """Simule une défaillance du fournisseur GPU demandé."""
        attempts.append(gpu)
        if gpu:
            raise RuntimeError("GPU unavailable")
        return Session()

    monkeypatch.setattr(GraXpertEngine, "_create_session", create)
    native_engine.graxpert_gpu = True
    native_engine.graxpert_cpu_fallback = allowed
    if allowed:
        result = GraXpertEngine(native_engine).process(source, candidate)
        assert result["cpu_fallback"]
        assert attempts == [True, False]
    else:
        with pytest.raises(RuntimeError):
            GraXpertEngine(native_engine).process(source, candidate)
        assert attempts == [True]
        assert not candidate.exists()


@pytest.mark.parametrize("orchestrated", [False, True])
def test_processor_uses_native_engine_and_common_controls(
    tmp_path: Path,
    native_engine: argparse.Namespace,
    monkeypatch: pytest.MonkeyPatch,
    orchestrated: bool,
) -> None:
    """Le candidat natif est contrôlé, y compris lors d’une activation automatique."""
    source = tmp_path / "source.fits"
    fits.writeto(
        source,
        np.random.default_rng(3).normal(0.1, 0.001, (128, 128)).astype("float32"),
    )
    monkeypatch.setattr(
        GraXpertDenoiseProcessor,
        "availability",
        staticmethod(lambda args: {"available": True}),
    )
    monkeypatch.setattr(
        "lib.graxpert.Siril",
        lambda **kwargs: SimpleNamespace(run_siril_script=lambda *a, **k: True),
    )
    comparison = dict(
        status="validated",
        pairs=[],
        before_fwhm_px={"mean": 4},
        after_fwhm_px={"mean": 4},
        paired_ratio={"median": 1},
        before_roundness={"mean": 1},
        after_roundness={"mean": 1},
    )
    monkeypatch.setattr(
        "lib.deconvolution.compare_star_catalogs", lambda *a, **k: comparison
    )
    monkeypatch.setattr(
        "lib.graxpert.artifact_metrics",
        lambda *a, **k: dict(max_noise_ratio=0.8, max_ring_fraction=0),
    )
    if orchestrated:
        native_engine.enable_clarity = False
        native_engine.restoration_siril = False
        native_engine.quality_mode = "legacy"
        treatment = NoiseReductionProcessor()
    else:
        treatment = GraXpertDenoiseProcessor()
    result = treatment.post_process(source, tmp_path / "report.json", native_engine)
    assert result["status"] == "accepted"
    if orchestrated:
        assert result["selected_engine"] == "graxpert"
        result = result["evaluations"]["graxpert"]
    assert result["inference"]["engine"] == "onnxruntime"
    assert "command" not in result


def test_optional_native_defaults() -> None:
    """L’activation est automatique, les poids épinglés et le cache ignoré."""
    parser = argparse.ArgumentParser()
    GraXpertDenoiseProcessor.add_arguments(parser)
    args = parser.parse_args([])
    assert args.enable_graxpert is None
    assert args.graxpert_model_version == "3.0.2"
    assert args.graxpert_model_dir.name == "graxpert"


@pytest.mark.parametrize(
    "location,valid",
    [
        ("absent", False),
        ("project", True),
        ("project", False),
        ("external", True),
        ("external", False),
    ],
)
def test_auto_activation_follows_verified_local_weights(
    model_environment: tuple[argparse.Namespace, Path, bytes],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    location: str,
    valid: bool,
) -> None:
    """Moteurs et chaînes suivent les poids locaux, sans acquisition ni copie."""
    args, model, payload = model_environment
    if location != "absent":
        local = model if location == "project" else tmp_path / "external/model.onnx"
        local.parent.mkdir(parents=True)
        # Même taille, empreinte différente : la présence seule ne suffit pas.
        local.write_bytes(payload if valid else b"x" * len(payload))
        if location == "external":
            monkeypatch.setattr(GraXpertModels, "_local_sources", lambda self: (local,))
    args.enable_graxpert = None

    def forbidden(self: GraXpertModels) -> Path:
        """Interdit installation et téléchargement lors de la détection."""
        raise AssertionError("La détection ne doit pas acquérir les poids")

    monkeypatch.setattr(GraXpertModels, "ensure_model", forbidden)
    before = set(tmp_path.rglob("*"))
    engines = dict(NoiseReductionProcessor.engines(args))
    assert ("graxpert" in engines) is valid
    variants = RestorationChainProcessor.variants(args)
    assert (
        any(name == "graxpert" for chain in variants for _, name, _ in chain) is valid
    )
    assert args.enable_graxpert is None
    assert set(tmp_path.rglob("*")) == before


@pytest.mark.parametrize("requested", [False, True])
def test_explicit_activation_bypasses_local_detection(
    monkeypatch: pytest.MonkeyPatch,
    requested: bool,
) -> None:
    """Un choix explicite domine les caches et True permet l’acquisition future."""

    def forbidden(self: GraXpertModels) -> Path | None:
        """Refuse de sonder les caches lorsque le choix est explicite."""
        raise AssertionError("Le choix explicite doit être prioritaire")

    monkeypatch.setattr(GraXpertModels, "find_local_model", forbidden)
    engines = dict(
        NoiseReductionProcessor.engines(argparse.Namespace(enable_graxpert=requested))
    )
    assert ("graxpert" in engines) is requested


@pytest.mark.parametrize(
    "saved,option,expected",
    [
        (None, None, True),
        (False, None, False),
        (True, None, True),
        (False, "--enable-graxpert", True),
        (True, "--no-enable-graxpert", False),
        (None, "--no-enable-graxpert", False),
    ],
)
def test_activation_respects_config_cli_and_late_binding(
    model_environment: tuple[argparse.Namespace, Path, bytes],
    tmp_path: Path,
    saved: bool | None,
    option: str | None,
    expected: bool,
) -> None:
    """CLI > sauvegarde > automatique reste valable pour les enfants tardifs."""
    model_args, model, payload = model_environment
    model.parent.mkdir(parents=True)
    model.write_bytes(payload)
    config = Config(tmp_path / "settings.json")
    config.set("enable_graxpert", saved)
    config.set("graxpert_model_dir", str(model_args.graxpert_model_dir))
    parser = argparse.ArgumentParser()
    config.register(NoiseReductionProcessor, parser)
    args = config.parse_args(parser, [option] if option else [])
    config.bind_parameters(args)
    treatment = NoiseReductionProcessor()
    assert ("graxpert" in dict(treatment.engines(treatment._get_args()))) is expected
    assert args.enable_graxpert is (saved if option is None else expected)


def test_saving_preserves_auto_mode(
    model_environment: tuple[argparse.Namespace, Path, bytes],
    tmp_path: Path,
) -> None:
    """La sauvegarde conserve null, sans figer la présence actuelle des poids."""
    model_args, model, payload = model_environment
    model.parent.mkdir(parents=True)
    model.write_bytes(payload)
    settings = tmp_path / "settings.json"
    config = Config(settings)
    config.set("graxpert_model_dir", str(model_args.graxpert_model_dir))
    parser = argparse.ArgumentParser()
    config.register(NoiseReductionProcessor, parser)
    args = config.parse_args(parser, [])
    assert GraXpertDenoiseProcessor.is_enabled(args)
    args.save_config = True
    assert config.save_requested(args)
    assert json.loads(settings.read_text())["enable_graxpert"] is None
    model.unlink()
    assert not GraXpertDenoiseProcessor.is_enabled(args)


def test_unreadable_local_model_is_ignored(
    model_environment: tuple[argparse.Namespace, Path, bytes],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Un cache inaccessible n’empêche pas la comparaison des autres moteurs."""
    args, _, _ = model_environment

    def unreadable(self: GraXpertModels, path: Path) -> bool:
        """Simule une erreur de droits lors de la lecture du poids."""
        raise PermissionError(path)

    monkeypatch.setattr(GraXpertModels, "_valid", unreadable)
    assert not GraXpertDenoiseProcessor.is_enabled(args)


def test_real_model_on_m33_crop_when_available(tmp_path, monkeypatch, project_root):
    """Inférence CPU réelle conditionnelle, sans téléchargement dans la non-régression."""
    pytest.importorskip("onnxruntime")
    from lib.cpu_config import CpuConfig
    from lib.graxpert_models import DEFAULT_MODEL_DIR
    from lib.restoration_quality import QualityReference

    model = DEFAULT_MODEL_DIR / "3.0.2/model.onnx"
    example = project_root / "imagesExample/M_33_combined.fits"
    if not model.is_file() or not example.is_file():
        pytest.skip("Poids GraXpert 3.0.2 ou exemple M33 absent")
    monkeypatch.setattr(CpuConfig, "_limit", 2)
    with fits.open(example) as hdul:
        data = hdul[0].data[:, 1100:1228, 1200:1328].copy()
        header = hdul[0].header.copy()
    header["CRPIX1"] -= 1200
    header["CRPIX2"] -= 1100
    source, candidate = tmp_path / "m33.fits", tmp_path / "m33_native.fits"
    fits.writeto(source, data, header)
    report = GraXpertEngine(argparse.Namespace()).process(source, candidate)
    result = fits.getdata(candidate)
    assert result.shape == data.shape
    assert np.isfinite(result).all()
    assert not np.array_equal(result, data)
    np.testing.assert_array_equal(fits.getdata(source), data)
    QualityReference.validate_metadata(source, candidate)
    assert report["providers"] == ["CPUExecutionProvider"]
    assert report["model_version"] == "3.0.2"


def test_auto_gpu_inference_failure_does_not_restart_cpu(
    tmp_path: Path, native_engine: argparse.Namespace, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto peut choisir CPU au démarrage, mais ne reprend pas une inférence échouée."""
    import onnxruntime as ort

    source = tmp_path/'image.fits'
    fits.writeto(source, np.random.default_rng(51).normal(.1, .001, (32, 32)).astype(np.float32))
    native_engine.graxpert_gpu = None
    native_engine.compute_backend = 'auto'
    native_engine.graxpert_cpu_fallback = False
    calls = []
    class FailedSession(Session):
        """Simule une panne après création réussie de la session GPU."""
        def run(self, names: list[str], feed: dict[str, np.ndarray]) -> list[np.ndarray]:
            """Échoue pendant le premier lot de calcul."""
            raise RuntimeError('inference GPU failure')
    def create(self: GraXpertEngine, model: Path, gpu: bool) -> FailedSession:
        """Enregistre le périphérique sélectionné avant calcul."""
        calls.append(gpu)
        return FailedSession()
    monkeypatch.setattr(ort, 'get_available_providers', lambda: ['CUDAExecutionProvider', 'CPUExecutionProvider'])
    monkeypatch.setattr(GraXpertEngine, '_create_session', create)
    with pytest.raises(RuntimeError, match='inference GPU failure'):
        GraXpertEngine(native_engine).process(source, tmp_path/'candidate.fits')
    assert calls == [True]


def test_native_data_root_follows_platform(monkeypatch, tmp_path):
    """macOS lit Application Support ; ailleurs XDG_DATA_HOME ou ~/.local/share."""
    from lib import graxpert_models
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    monkeypatch.setattr(graxpert_models.sys, "platform", "darwin")
    assert graxpert_models.native_data_root() == tmp_path / "Library/Application Support/GraXpert"
    monkeypatch.setattr(graxpert_models.sys, "platform", "linux")
    assert graxpert_models.native_data_root() == tmp_path / "xdg/GraXpert"

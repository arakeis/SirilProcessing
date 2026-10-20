"""Orchestration CLI : calibration par sous-session, stack par session, mosaïque."""
import importlib.util
import argparse
from contextlib import contextmanager, nullcontext
from collections.abc import Callable
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import Mock
from typing import Iterator

import pytest

from lib.postprocessing import PostProcessingProcessor
from lib.siril_utils import default_siril_mode
from lib.type_defs import ConfigValue, JSONReport

PipelineFixture = tuple[
    ModuleType, Callable[..., int], Mock, Mock, dict[Path, list[Path]],
]
PostprocessCalls = list[tuple[Path, Path, argparse.Namespace]]


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    import lib.lightprocessor as processing
    import lib.mosaic as mosaic
    from lib.config import Config
    from lib.siril_utils import Siril

    spec = importlib.util.spec_from_file_location('light_process_cli', Path(__file__).parents[1] / 'bin/lightProcess.py')
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    monkeypatch.setattr(cli, 'PowerGuard', nullcontext)
    class TestConfig(Config):
        def __init__(self):
            super().__init__(str(tmp_path / 'config.json'))

    monkeypatch.setattr(cli, 'Config', TestConfig)
    monkeypatch.setattr(cli, 'setup_logging', lambda level: None)
    monkeypatch.setattr(Siril, 'configure_defaults', Mock())
    calibrated = {}

    class Processor(processing.LightProcessor):
        def __init__(self, session_dir, output_dir, **kwargs):
            self.session_dir = session_dir
            directory = output_dir / 'group_calibrated'
            directory.mkdir(parents=True, exist_ok=True)
            self.outputs = [directory / f'pp_light_{i}.fits' for i in range(2)]
            for path in self.outputs:
                path.touch()
            calibrated[session_dir] = self.outputs

        def process_session(self, params):
            return True

        def get_session_stats(self):
            return {}

        def get_output_files(self):
            return self.outputs

    def stack(**kwargs):
        result = kwargs['output_dir'] / (kwargs['target_name'] + '_combined.fits')
        result.touch()
        return result

    stack_mock = Mock(side_effect=stack)
    mosaic_mock = Mock()
    mosaic_mock.return_value.add_arguments.side_effect = mosaic.Mosaic().add_arguments
    mosaic_mock.return_value.parameter_persistence = mosaic.Mosaic.parameter_persistence
    mosaic_mock.return_value.config_keys = {}
    mosaic_mock.return_value.config_path_parameters = set()
    mosaic_output = tmp_path / 'mosaic.fits'
    mosaic_output.touch()
    mosaic_mock.return_value.post_process.return_value = {'output_image': str(mosaic_output)}
    monkeypatch.setattr(processing, 'LightProcessor', Processor)
    monkeypatch.setattr(processing, 'stack_session_outputs', stack_mock)
    class TestMosaic(mosaic.Mosaic):
        """Déclare les options réelles et simule seulement l’exécution."""

        def __new__(cls, *args, **kwargs):
            """Retourne le double de traitement sans créer de fichiers réels."""
            return mosaic_mock(*args, **kwargs)

    monkeypatch.setattr(mosaic, 'Mosaic', TestMosaic)

    def run(
        roots: list[Path], *options: str, use_postprocess_default: bool = False,
    ) -> int:
        """Isole le stacking, sauf si le test demande le vrai défaut d’enchaînement.

        Les options explicites restent prioritaires sur --no-postprocess utilisé
        pour les tests de calibration et mosaïque avec fichiers factices.
        """
        isolation = [] if use_postprocess_default else ["--no-postprocess"]
        monkeypatch.setattr(sys, 'argv', ['lightProcess.py', *map(str, roots), '--no-dark', '--output', str(tmp_path / 'out'), '--work-dir', str(tmp_path / 'work'), *isolation, *options])
        return cli.main()

    return cli, run, stack_mock, mosaic_mock, calibrated


def make_session(tmp_path, name, count):
    root = tmp_path / name
    children = [root] if count == 0 else [root / f'night_{i}' for i in range(count)]
    for child in children:
        (child / 'light').mkdir(parents=True)
    return root, children


@pytest.mark.parametrize('count', [0, 1, 3])
@pytest.mark.parametrize('force', [False, True])
def test_every_session_is_stacked_with_all_its_calibrations(tmp_path, pipeline, count, force):
    cli, run, stack, mosaic, calibrated = pipeline
    root, children = make_session(tmp_path, 'field', count)
    directories, parents = cli.build_session_target_map([root])
    assert directories == children
    assert all(parents[child] == root for child in children)
    assert run([root], *(['--force-stacking'] if force else [])) == 0
    stack.assert_called_once()
    call = stack.call_args.kwargs
    assert call['output_dir'] == tmp_path / 'out' / 'field'
    assert set(call['output_files']) == {path for child in children for path in calibrated[child]}
    mosaic.return_value.post_process.assert_not_called()


def test_mosaic_uses_only_one_stack_per_input_session(tmp_path, pipeline):
    _, run, stack, mosaic, calibrated = pipeline
    roots = [make_session(tmp_path, name, count)[0] for name, count in [('north', 0), ('south', 1), ('east', 3)]]
    assert run(roots, '--mosaic', '--mosaic-name', 'field') == 0
    assert stack.call_count == 3
    call = mosaic.return_value.post_process.call_args.kwargs
    args = mosaic.return_value.set_from_args.call_args.args[0]
    assert 'args' not in call
    inputs = [call['input_path'], *args.mosaic_inputs]
    assert call['output_path'] == tmp_path / 'work/field/field_mosaic.json'
    assert args.mosaic_name == 'field'
    assert args.output_dir == tmp_path / 'work/field'
    assert args.work_dir == tmp_path / 'work/field'
    assert args.mosaic_directory == tmp_path / 'work/field'
    for files in calibrated.values():
        assert all(path.is_relative_to(tmp_path / 'work/field') for path in files)
    for stack_call in stack.call_args_list:
        assert stack_call.kwargs['work_dir'] == tmp_path / 'work/field'
    assert args.siril_mode == default_siril_mode()
    mosaic.return_value.add_arguments.assert_not_called()
    assert inputs == [tmp_path / 'work/field' / root.name / f'{root.name}_combined.fits' for root in roots]
    assert not set(inputs).intersection(path for files in calibrated.values() for path in files)
    mosaic.return_value.post_process.assert_called_once()
    mosaic.return_value.create_mosaic.assert_not_called()


def test_one_session_with_many_subsessions_is_not_a_mosaic(tmp_path, pipeline):
    _, run, stack, mosaic, _ = pipeline
    root, _ = make_session(tmp_path, 'field', 3)
    assert run([root], '--mosaic', '--mosaic-name', 'field') == 1
    stack.assert_called_once()
    mosaic.return_value.post_process.assert_not_called()


@pytest.mark.parametrize('failure', [None, RuntimeError('Siril failed')])
def test_failed_stack_is_not_replaced_by_calibrations_in_mosaic(tmp_path, pipeline, failure):
    _, run, stack, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 1)[0] for name in ['north', 'south']]
    stack.side_effect = [failure, tmp_path / 'south_combined.fits']
    assert run(roots, '--mosaic', '--mosaic-name', 'field') == 1
    assert stack.call_count == 2
    mosaic.return_value.post_process.assert_not_called()


def test_dry_run_never_executes_stack_or_mosaic(tmp_path, pipeline):
    _, run, stack, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 1)[0] for name in ['north', 'south']]
    assert run(roots, '--mosaic', '--mosaic-name', 'field', '--dry-run') == 0
    stack.assert_not_called()
    mosaic.return_value.post_process.assert_not_called()


def test_mosaic_accepts_cached_session_stacks(
    tmp_path: Path, pipeline: PipelineFixture, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Les stacks repris annoncent la réutilisation sans annoncer les sous-étapes."""
    import lib.drizzle as drizzle
    caplog.set_level("INFO")
    cli, run, stack, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 1)[0] for name in ['north', 'south']]
    expected = []
    for root in roots:
        result = tmp_path / 'work/field' / root.name / f'{root.name}_combined.fits'
        result.parent.mkdir(parents=True)
        result.touch()
        expected.append(result)
    monkeypatch.setattr(drizzle, 'cache_matches', lambda *args: True)
    monkeypatch.setattr(cli, 'should_rebuild_stack', lambda *args: False)
    assert run(roots, '--mosaic', '--mosaic-name', 'field') == 0
    stack.assert_not_called()
    call = mosaic.return_value.post_process.call_args.kwargs
    args = mosaic.return_value.set_from_args.call_args.args[0]
    assert 'args' not in call
    assert [call['input_path'], *args.mosaic_inputs] == expected
    for root, result in zip(roots, expected):
        log_path = result.parent / "stacking" / f"{root.name}_stacking.log"
        log = log_path.read_text(encoding="utf-8")
        assert f"Début du stacking : {root.name}" in log
        assert f"Réutilisation du stack existant : {root.name}" in log
        assert "Stacking — " not in log


def test_mosaic_failure_is_reported_as_failure(tmp_path, pipeline):
    _, run, stack, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 1)[0] for name in ['north', 'south']]
    mosaic.return_value.post_process.side_effect = RuntimeError('Siril failed')
    assert run(roots, '--mosaic', '--mosaic-name', 'field') == 1
    assert stack.call_count == 2
    mosaic.return_value.post_process.assert_called_once()


def test_mosaic_passes_automatic_name_and_siril_options(tmp_path, pipeline):
    _, run, _, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 0)[0] for name in ['M31_north', 'M31_south']]
    assert run(roots, '--mosaic', '--siril-mode', 'native', '--siril-path', '/custom/siril') == 0
    args = mosaic.return_value.set_from_args.call_args.args[0]
    assert args.mosaic_name == 'M31'
    assert args.siril_mode == 'native' and args.siril_path == '/custom/siril'


@pytest.mark.parametrize('method', ['rbf', 'polynomial'])
def test_mosaic_gradient_method_forwarded(tmp_path, pipeline, method):
    _, run, _, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 0)[0] for name in ['north', 'south']]
    assert run(roots, '--mosaic', '--mosaic-name', 'field', '--gradient-method', method) == 0
    assert mosaic.return_value.set_from_args.call_args.args[0].gradient_method == method


def test_mosaic_gradient_can_be_disabled_from_cli(tmp_path, pipeline):
    _, run, _, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 0)[0] for name in ['north', 'south']]
    assert run(roots, '--mosaic', '--mosaic-name', 'field', '--no-mosaic-gradient') == 0
    assert mosaic.return_value.set_from_args.call_args.args[0].mosaic_gradient is False


@pytest.mark.parametrize('name', ['../escape', '..', 'bad/name'])
def test_invalid_mosaic_name_fails_before_calibration(tmp_path, pipeline, name):
    _, run, stack, mosaic, calibrated = pipeline
    roots = [make_session(tmp_path, label, 0)[0] for label in ['north', 'south']]
    assert run(roots, '--mosaic', '--mosaic-name', name) == 1
    assert not calibrated
    stack.assert_not_called()


@pytest.fixture
def postprocess_calls(monkeypatch: pytest.MonkeyPatch) -> PostprocessCalls:
    """Trace le processeur complet sans exécuter de moteurs sur les faux stacks."""
    from copy import deepcopy
    import shutil

    calls: PostprocessCalls = []

    def postprocess(
        self: PostProcessingProcessor, input_path: Path, output_path: Path,
        args: argparse.Namespace | None = None,
    ) -> JSONReport:
        """Publie une copie et capture l’instantané résolu lors de l’instanciation."""
        calls.append((input_path, output_path, deepcopy(self._get_args(args))))
        destination = output_path.with_suffix(".fits")
        shutil.copyfile(input_path, destination)
        return {"status": "SUCCESS", "output_image": str(destination)}

    monkeypatch.setattr(PostProcessingProcessor, "post_process", postprocess)
    return calls


def test_postprocess_each_final_stack_with_shared_parameters(
    tmp_path: Path, pipeline: PipelineFixture, postprocess_calls: PostprocessCalls,
) -> None:
    """Les stacks finaux reçoivent les options communes, sans traiter les calibrations."""
    _, run, stack, _, _ = pipeline
    roots = [make_session(tmp_path, name, 1)[0] for name in ("north", "south")]
    assert run(roots, "--postprocess", "--compute-backend", "cpu",
               "--ghs-chroma", "enhanced", "--ghs-dynamic-target", "0.8",
               "--photometry-object", "M33") == 0
    assert stack.call_count == len(postprocess_calls) == 2
    for root, (image, report, args) in zip(roots, postprocess_calls):
        assert image == tmp_path / "out" / root.name / f"{root.name}_combined.fits"
        assert report == image.with_name(f"{image.stem}_postprocess.json")
        assert args.compute_backend == "cpu"
        assert args.ghs_chroma == "enhanced" and args.ghs_dynamic_target == 0.8
        assert args.photometry_object == "M33"
        assert args.enable_autoghs is True
        assert args.restoration_compare_chains is True
        assert image.is_file() and report.with_suffix(".fits").is_file()


def test_postprocess_only_final_mosaic(
    tmp_path: Path, pipeline: PipelineFixture, postprocess_calls: PostprocessCalls,
) -> None:
    """La mosaïque reçoit les stacks linéaires et son résultat est traité une fois."""
    _, run, stack, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 0)[0] for name in ("north", "south")]
    assert run(roots, "--postprocess", "--mosaic", "--mosaic-name", "field") == 0
    assert stack.call_count == 2 and len(postprocess_calls) == 1
    image, report, _ = postprocess_calls[0]
    assert image == tmp_path / "mosaic.fits"
    assert report == tmp_path / "mosaic_postprocess.json"
    call = mosaic.return_value.post_process.call_args.kwargs
    assert call["input_path"].name == "north_combined.fits"


@pytest.mark.parametrize("disabled", ["saved", "explicit", "dry-run"])
def test_postprocess_not_executed_when_disabled_or_simulated(
    tmp_path: Path, pipeline: PipelineFixture,
    postprocess_calls: PostprocessCalls, disabled: str,
) -> None:
    """La configuration, le CLI ou la simulation peuvent empêcher le calcul final."""
    import json

    _, run, _, _, _ = pipeline
    root, _ = make_session(tmp_path, "field", 0)
    options = []
    if disabled == "saved":
        (tmp_path / "config.json").write_text(json.dumps({"enable_postprocess": False}))
    elif disabled == "explicit":
        (tmp_path / "config.json").write_text(json.dumps({"enable_postprocess": True}))
        options = ["--no-postprocess"]
    elif disabled == "dry-run":
        options = ["--dry-run"]
    assert run([root], *options, use_postprocess_default=True) == 0
    assert not postprocess_calls


def test_postprocess_reused_stack(
    tmp_path: Path, pipeline: PipelineFixture,
    postprocess_calls: PostprocessCalls, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La reprise d’un stack à jour enchaîne quand même le post-traitement demandé."""
    cli, run, stack, _, _ = pipeline
    root, _ = make_session(tmp_path, "field", 0)
    image = tmp_path / "out/field/field_combined.fits"
    image.parent.mkdir(parents=True)
    image.touch()
    monkeypatch.setattr("lib.drizzle.cache_matches", lambda *args: True)
    monkeypatch.setattr(cli, "should_rebuild_stack", lambda *args: False)
    assert run([root], "--postprocess") == 0
    stack.assert_not_called()
    assert len(postprocess_calls) == 1 and postprocess_calls[0][0] == image


def test_failed_mosaic_never_postprocesses_panels(
    tmp_path: Path, pipeline: PipelineFixture, postprocess_calls: PostprocessCalls,
) -> None:
    """Un assemblage en erreur ne provoque aucun rendu des panneaux à sa place."""
    _, run, _, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 0)[0] for name in ("north", "south")]
    mosaic.return_value.post_process.side_effect = RuntimeError("mosaic failed")
    assert run(roots, "--mosaic", "--mosaic-name", "field", "--postprocess") == 1
    assert not postprocess_calls


@pytest.mark.parametrize("failure", ["exception", "missing_output"])
def test_postprocess_failure_fails_pipeline_without_removing_stack(
    tmp_path: Path, pipeline: PipelineFixture,
    monkeypatch: pytest.MonkeyPatch, failure: str,
) -> None:
    """Les erreurs de rendu affectent le code retour, sans perdre les stacks suivants."""
    _, run, _, _, _ = pipeline
    roots = [make_session(tmp_path, name, 0)[0] for name in ("north", "south")]
    calls = []

    def fail(
        self: PostProcessingProcessor, input_path: Path, output_path: Path,
        args: argparse.Namespace | None = None,
    ) -> JSONReport:
        """Simule soit une erreur du moteur, soit une sortie annoncée absente."""
        calls.append(input_path)
        if failure == "exception":
            raise RuntimeError("render failed")
        return {"output_image": str(output_path.with_suffix(".fits"))}

    monkeypatch.setattr(PostProcessingProcessor, "post_process", fail)
    assert run(roots, "--postprocess") == 1
    assert len(calls) == 2
    assert all(image.is_file() for image in calls)


def test_lightprocess_saves_discovered_starnet_and_reuses_activation(
    tmp_path: Path, pipeline: PipelineFixture, postprocess_calls: PostprocessCalls,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """-S mémorise le choix d’enchaînement, le chemin découvert et les réglages."""
    import json

    from lib.star_separation import StarNetSeparator

    executable = str(tmp_path / "starnet++")
    monkeypatch.setattr(StarNetSeparator, "resolve_executable", lambda args: executable)
    _, run, _, _, _ = pipeline
    root, _ = make_session(tmp_path, "field", 0)
    assert run([root], "--postprocess", "--ghs-chroma", "enhanced", "-S") == 0
    saved = json.loads((tmp_path / "config.json").read_text())
    assert saved["enable_postprocess"] is True
    assert saved["starnet_path"] == executable
    assert saved["ghs_chroma"] == "enhanced"
    assert postprocess_calls[0][2].starnet_path == executable
    postprocess_calls.clear()
    assert run([root], use_postprocess_default=True) == 0
    assert len(postprocess_calls) == 1
    assert postprocess_calls[0][2].ghs_chroma == "enhanced"


@pytest.mark.parametrize("mosaic", [False, True])
def test_postprocess_runs_by_default_without_activation_flag(
    tmp_path: Path, pipeline: PipelineFixture, postprocess_calls: PostprocessCalls,
    caplog: pytest.LogCaptureFixture, mosaic: bool,
) -> None:
    """Les commandes usuelles de stack et mosaïque enchaînent sans --postprocess."""
    import logging

    caplog.set_level(logging.INFO)
    _, run, _, _, _ = pipeline
    names = ("north", "south") if mosaic else ("M_33",)
    roots = [make_session(tmp_path, name, 0)[0] for name in names]
    options = (
        ["--mosaic", "--force", "--keep-intermediate", "--mosaic-name", "M31"]
        if mosaic else []
    )
    assert run(roots, *options, use_postprocess_default=True) == 0
    assert len(postprocess_calls) == 1
    image, _, args = postprocess_calls[0]
    assert args.enable_postprocess is True
    assert image == (
        tmp_path / "mosaic.fits" if mosaic
        else tmp_path / "out/M_33/M_33_combined.fits"
    )
    assert "Post-traitement final : activé" in caplog.text


def test_lightprocess_executes_common_exports_after_stack(
    tmp_path: Path, pipeline: PipelineFixture, monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Un vrai FITS empilé rejoint la classe commune et ses exports/diagnostics."""
    import json

    import numpy as np
    from astropy.io import fits

    _, run, stack, _, _ = pipeline
    root, _ = make_session(tmp_path, "field", 0)

    def stack_rgb(*, output_dir: Path, **kwargs: object) -> Path:
        """Simule seulement le stacking, en écrivant un FITS valide et non constant."""
        destination = output_dir / "field_combined.fits"
        pixels = np.linspace(0.01, 0.1, 3 * 64 * 64, dtype=np.float32)
        fits.writeto(destination, pixels.reshape(3, 64, 64))
        return destination

    stack.side_effect = stack_rgb
    caplog.set_level("INFO")
    assert run([root], "--postprocess", "--disable-photometry", "--disable-autoghs",
               "--disable-denoise", "--disable-deconvolution",
               "--gradient-method", "polynomial", "--gradient-min-order", "1",
               "--gradient-max-order", "1", "--no-gradient-measurement-image") == 0
    directory = tmp_path / "out/field"
    source = directory / "field_combined.fits"
    final = directory / "field_combined_postprocess.fits"
    report = directory / "field_combined_postprocess.json"
    result = json.loads(report.read_text())
    assert set(result) == {"gradient"}
    assert final.read_bytes() == Path(result["gradient"]["output_image"]).read_bytes()
    assert source.is_file() and not final.with_suffix(".jpg").exists()
    work = directory / "field_combined_postprocess"
    assert (work / "quality_masks.png").is_file()
    assert (work / "00_field_combined_postProcess.log").is_file()
    log = (work / "00_field_combined_postProcess.log").read_text(encoding="utf-8")
    assert "Début du post-traitement : field_combined.fits" in log
    assert "Post-traitement — étape 01 : Correction du gradient" in log


@pytest.mark.parametrize("mode", ["stack", "postprocess", "mosaic"])
def test_lightprocess_owns_one_guard_for_all_processing(
    tmp_path: Path, pipeline: PipelineFixture, monkeypatch: pytest.MonkeyPatch,
    mode: str,
) -> None:
    """Un seul contexte couvre calibration, stacks et traitements finaux."""
    import lib.lightprocessor as processing

    cli, run, stack, mosaic, _ = pipeline
    roots = [make_session(tmp_path, name, 1)[0] for name in ("north", "south")]
    events: list[str] = []

    @contextmanager
    def guard() -> Iterator[None]:
        """Trace l’acquisition et la libération autour de toute la commande."""
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def record(stage: str) -> None:
        """Refuse une opération exécutée hors de la protection du script."""
        assert events[0] == "enter" and "exit" not in events
        events.append(stage)

    def calibrate(
        self: processing.LightProcessor, params: dict[str, ConfigValue],
    ) -> bool:
        """Simule la calibration à l’intérieur du contexte."""
        record("calibration")
        return True

    original_stack = stack.side_effect

    def protected_stack(**kwargs: object) -> Path:
        """Conserve le résultat du double de stacking en vérifiant sa protection."""
        record("stack")
        return original_stack(**kwargs)

    def postprocess(
        self: PostProcessingProcessor, input_path: Path, output_path: Path,
    ) -> JSONReport:
        """Fournit un résultat existant sans acquérir un second contexte."""
        record("postprocess")
        return {"output_image": str(input_path)}

    def assemble(**kwargs: object) -> JSONReport:
        """Vérifie la protection pendant l’assemblage final."""
        record("mosaic")
        return mosaic.return_value.post_process.return_value

    monkeypatch.setattr(cli, "PowerGuard", guard)
    monkeypatch.setattr(processing.LightProcessor, "process_session", calibrate)
    monkeypatch.setattr(PostProcessingProcessor, "post_process", postprocess)
    stack.side_effect = protected_stack
    mosaic.return_value.post_process.side_effect = assemble
    options = [] if mode == "stack" else ["--postprocess"]
    if mode == "mosaic":
        options.extend(["--mosaic", "--mosaic-name", "field"])
    assert run(roots, *options) == 0
    assert events[0] == "enter" and events[-1] == "exit"
    assert events.count("enter") == events.count("exit") == 1
    assert events.count("calibration") == events.count("stack") == 2
    assert events.count("postprocess") == {"stack": 0, "postprocess": 2, "mosaic": 1}[mode]
    assert events.count("mosaic") == int(mode == "mosaic")


@pytest.mark.parametrize("failure", [RuntimeError("pipeline failed"), KeyboardInterrupt()])
def test_lightprocess_releases_guard_when_pipeline_raises(
    tmp_path: Path, pipeline: PipelineFixture, monkeypatch: pytest.MonkeyPatch,
    failure: RuntimeError | KeyboardInterrupt,
) -> None:
    """Les exceptions et interruptions libèrent le contexte détenu par main."""
    cli, run, _, _, _ = pipeline
    root, _ = make_session(tmp_path, "field", 0)
    events: list[str] = []

    @contextmanager
    def guard() -> Iterator[None]:
        """Trace la libération même lorsque le parcours est interrompu."""
        events.append("enter")
        try:
            yield
        finally:
            events.append("exit")

    def fail(*args: object) -> int:
        """Interrompt le parcours à l’intérieur de la portée protégée."""
        assert events == ["enter"]
        raise failure

    monkeypatch.setattr(cli, "PowerGuard", guard)
    monkeypatch.setattr(cli, "_process_sessions", fail)
    with pytest.raises(type(failure)):
        run([root])
    assert events == ["enter", "exit"]


def test_lightprocess_dry_run_does_not_activate_guard(
    tmp_path: Path, pipeline: PipelineFixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """La simulation ne demande pas de ressources énergétiques au système."""
    cli, run, _, _, _ = pipeline
    root, _ = make_session(tmp_path, "field", 0)
    guard = Mock(side_effect=AssertionError("Dry run must not activate PowerGuard"))
    monkeypatch.setattr(cli, "PowerGuard", guard)
    assert run([root], "--dry-run") == 0
    guard.assert_not_called()

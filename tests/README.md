# Tests et non-régression

[Documentation](../docs/README.md)

Tous les tests du projet se trouvent dans `tests/`. Le fichier `pytest.ini`
définit ce répertoire comme point de découverte par défaut et rend les imports
du projet accessibles aux tests.

## Exécution

Depuis la racine du projet, avec les dépendances de `requirements.txt` installées :

```bash
# Suite complète, y compris le contrôle de synthèse de non-régression
.venv/bin/python -m pytest -q

# Non-régression avec vérification du nombre de tests collectés et réussis
.venv/bin/python -m pytest -q tests/test_regression_summary.py

# Tests de mosaïque et d’accès à Siril
.venv/bin/python -m pytest -q tests/test_mosaic.py tests/test_mosaic_validation.py tests/test_integrated_script.py tests/test_simplified_mosaic.py tests/test_siril_validation.py

# Post-traitements FITS (Siril classique + backend Cosmic Clarity)
.venv/bin/python -m pytest -q tests/test_postprocess.py tests/test_deconvolution.py tests/test_denoising.py tests/test_cosmic_clarity.py tests/test_cosmic_inference.py

# Couverture des bibliothèques
.venv/bin/python -m pytest --cov=lib --cov-report=html
```

`test_regression_summary.py` découvre récursivement les `test_*.py` dans
`tests/`, s’exclut lui-même pour éviter une récursion, puis exécute ces tests
dans un sous-processus. Il vérifie le succès de l’exécution et compare le
nombre de tests réussis au nombre collecté par pytest. Le compte rendu est
écrit dans `regression_summary.txt` dans le répertoire temporaire du test.
Un nouveau fichier `test_*.py` est ainsi inclus automatiquement.

La suite complète exécute aussi cette synthèse, donc répète les autres tests.
Pour une exécution simple sans ce contrôle supplémentaire :

```bash
.venv/bin/python -m pytest -q --ignore=tests/test_regression_summary.py
```

## Domaines couverts

| Domaine | Fichiers de tests |
|---|---|
| Métadonnées FITS | `test_fits_info.py` |
| Lecture des masters XISF PixInsight | `test_xisf_reader.py` |
| Analyse des filtres : courbes spectrales, modèle direct, score, astrométrie et photométrie | `test_spectral_response.py`, `test_filter_model.py`, `test_plate_solving.py`, `test_star_photometry.py` |
| Calibration et reprises | `test_lightprocessor_calibration.py`, `test_force_recalc.py` |
| Sessions, stacking et orchestration mosaïque | `test_session_pipeline.py` |
| Sélection et profils stellaires | `test_quality_filter.py`, `test_stellar_quality.py` |
| Drizzle et transformations | `test_drizzle.py`, `test_registration_geometry.py` |
| Séquences Siril | `test_siril_sequence.py` |
| Post-traitements Siril et backend Cosmic Clarity | `test_postprocessor.py`, `test_postprocess.py`, `test_deconvolution.py`, `test_denoising.py`, `test_deconvolution_quality.py`, `test_photometric_color.py`, `test_cosmic_clarity.py`, `test_cosmic_inference.py` |
| Pipeline de post-traitement partagé | `test_postprocessing.py`, `test_session_pipeline.py` |
| Qualité astrophotographique, chaînes et GraXpert | `test_restoration_quality.py`, `test_restoration_chains.py`, `test_restoration_summary.py`, `test_graxpert.py`, `test_restoration.py` |
| Mosaïque : noms, entrées, préparation et script généré | `test_mosaic.py`, `test_mosaic_validation.py`, `test_integrated_script.py`, `test_simplified_mosaic.py` |
| Configuration, lancement et journaux Siril | `test_siril_validation.py` |
| Génération et navigation HTML, titres uniques et ancres du monofichier | `test_docs_html.py` |
| Synthèse de non-régression | `test_regression_summary.py` |

## Isolation et automatisation

`test_calibration_logging.py` vérifie les titres INFO et leur ordre pour les
quatre combinaisons dark/flat, la reprise sans nouvel appel Siril, la simulation
et l’arrêt après échec du master flat. Les détails de préparation restent en
DEBUG. Les scénarios utilisent de petits FITS et simulent les produits Siril.

`test_drizzle.py` vérifie l’ordre des bandeaux INFO du stacking sur les branches
CFA standard et Drizzle forcé, ainsi que l’absence de titres pour les étapes
non exécutées après un échec. `test_session_pipeline.py` vérifie les bandeaux
de réutilisation dans les journaux de stacking, sans annonces de recalcul.

`test_postprocessing.py` compare les appels scientifiques, les paramètres et
les exports FITS/JPEG entre l’appel du processeur complet et le CLI autonome.
Il vérifie aussi les priorités de configuration, les instantanés indépendants,
les déclarations uniques partagées avec la mosaïque, les chemins protégés et
la fermeture du journal sur erreur ou interruption sans activation énergétique
dans la bibliothèque. Le CLI autonome détient et libère son propre PowerGuard.
Les bandeaux INFO du début de post-traitement sont vérifiés dans la console
capturée et les fichiers des deux modes d’appel. `test_postprocessor.py`
vérifie les titres et numéros des étapes actives, avec restauration groupée,
restauration par étape ou photométrie désactivée.
`test_restoration_chains.py` vérifie les sous-titres en tirets pour les calculs
et contrôles réellement exécutés, sans nouveau bandeau pour un calcul réutilisé.
`test_restoration.py` vérifie aussi l’ordre des titres pour les moteurs évalués
séparément et le classement final.
`test_session_pipeline.py` couvre l’option `--postprocess`, les stacks repris,
la mosaïque finale seule, la simulation et les échecs sans perte des stacks.
Deux scénarios vérifient l’enchaînement activé par défaut, sans option, sur un
stack et une mosaïque ; les tests limités aux étapes amont le désactivent
explicitement. Les désactivations JSON/CLI restent testées séparément.
Les moteurs simulés isolent l’enchaînement de la validation astrophotographique.
Les scénarios PowerGuard vérifient un contexte unique dans lightProcess pour
la calibration, les stacks, la mosaïque et les post-traitements, même lorsque
ces derniers sont désactivés. La simulation ne demande pas de protection ;
une erreur ou une interruption libère celle détenue par le script.

```bash
PIP_NO_INDEX=1 .venv/bin/python -m pytest -q tests/test_postprocessing.py tests/test_session_pipeline.py tests/test_render_exports.py
```

Les données de test sont créées dans des répertoires temporaires, notamment
avec la fixture `tmp_path`. `conftest.py` fournit les fixtures partagées, les
FITS simulés et l’environnement du wrapper `lightProcess.sh`.
Les tests Siril utilisent des commandes simulées ou de faux exécutables ;
ils ne constituent pas une validation d’un stacking réel sur les acquisitions.

Le workflow GitHub **Documentation MkDocs** exécute les tests des générateurs
avec `unittest`. La suite de non-régression complète s’exécute avec les
commandes pytest ci-dessus ; aucun workflow GitHub dédié à cette suite
n’est actuellement configuré.

## Refactoring des moteurs Siril

`test_deconvolution.py` et `test_denoising.py` couvrent les objets d’exécution
indépendants, les copies des options et l’audit des essais. Le repli adaptatif
vérifie aussi que le recadrage ne change pas la fraction minimale d’appariement.
Les tests appellent directement les méthodes des moteurs de type `processor`.
Les doubles de calcul sont injectés dans ces moteurs ; `test_restoration.py` contrôle leur
orchestration sur la même entrée.

Pour mesurer la couverture des deux modules sans créer d’artefact dans le dépôt :

```bash
PIP_NO_INDEX=1 COVERAGE_FILE=/tmp/siril-refactoring.coverage \
  .venv/bin/python -m pytest -q \
  --cov=lib.deconvolution --cov=lib.denoising \
  tests/test_deconvolution.py tests/test_denoising.py \
  tests/test_restoration.py tests/test_cosmic_clarity.py \
  tests/test_processor_args.py tests/test_processor_parameters.py
```

Ce contrôle porte sur ces modules et utilise des exécutions Siril simulées.
Il ne mesure pas la couverture complète du dépôt ni la validité d’un traitement
réel sur GPU.

Le test `test_cosmic_inference.py::test_real_weights_cuda` appartient à la
non-régression et s’exécute automatiquement si PyTorch et CUDA sont disponibles.
Sans CUDA, pytest affiche explicitement la raison du test ignoré (`-rs`). Il
charge les six vrais modèles et peut télécharger les poids manquants ; les
erreurs de téléchargement, de chargement et de calcul font échouer le test.
Aucune variable d’activation n’est nécessaire. `COSMIC_MODEL_DIR` peut choisir
le dossier des poids ; sinon le dossier ignoré `tmp/models/cosmicclarity` est utilisé.

## Qualité astrophotographique

Les tests synthétiques utilisent un ciel/bruit et des structures connus, y compris
une galaxie et un filament effacés, une nébulosité dominante, du signal rouge et
du bruit corrélé. Les décisions UNKNOWN sont vérifiées sans faux bonus de bruit.
Les champs stellaires denses vérifient que le lissage ne transforme pas les
étoiles en faux signal diffus. Une image majoritairement couverte de signal
vérifie que le ciel connu dans les quatre coins reste exploitable, tandis
qu’un champ sans ciel identifiable conserve UNKNOWN.
Les tests des chaînes évaluent 12/18 variantes et 11/17 opérations élémentaires
avec cache par entrée effective ; le choix final ne somme pas les scores locaux.
Les synthèses distinguent rejets locaux et globaux, erreurs, indisponibilités,
UNKNOWN et candidats acceptés mais moins bien classés ; elles conservent les
audits écrits avant une erreur et les références des calculs réutilisés.
La conclusion explicative est vérifiée sur une chaîne retenue et une entrée
conservée, avec traduction des régions UNKNOWN et des limites du contrôle diffus.
`test_quality_preview.py` vérifie les couleurs des masques, les cadres verts,
l’orientation de l’aperçu, le cas sans ciel et la conservation des données.
`test_power_guard.py` vérifie les services D-Bus facultatifs, les ressources
acquises et leur libération même après une erreur de traitement.
La conservation du type du cookie est contrôlée systématiquement ; si
`dbus-python` est disponible, sa sérialisation réelle en `UInt32` est également
vérifiée sans connexion à un service système.
Les tests de paramètres vérifient l’activation des chaînes par défaut et la
priorité CLI > configuration > défauts.
GraXpert est testé par des sessions ONNX et une acquisition de poids simulées,
sans réseau. L’activation automatique est vérifiée sur les caches locaux valides,
absents, corrompus ou inaccessibles, ainsi que ses priorités CLI/configuration,
sa sauvegarde et son intégration aux comparaisons et aux chaînes.
Les scénarios à deux moteurs isolent les caches utilisateur.
Les tests de transmission entre déconvolution et débruitage désactivent
explicitement AutoGHS, dont le rendu est couvert par ses propres tests.
Une inférence CPU réelle conditionnelle sur un extrait de M33 est
exécutée lorsque ONNX Runtime, les poids et l’image exemple sont disponibles.
Les nouveaux contrôles de flux sont diagnostiques par défaut : ces tests ne
remplacent pas une calibration sur plusieurs références astrophotographiques.
Voir [le contrat et les limites](../docs/scripts/postProcess/quality.md).

`test_docs_html.py` vérifie la navigation, l’exclusion des commentaires de code
du sommaire, les diagrammes et la copie des fichiers
Python, shell et JSON liés dans l’export HTML. Les poids binaires et les cibles
hors dépôt restent exclus ; la génération n’exécute pas les sources copiées.
`test_documentation_site.py` couvre les ancres distinctes des chapitres, leurs
liens internes, les ressources embarquées du monofichier et la protection des
dossiers. Une construction MkDocs complète rend les diagrammes dans Chromium
et génère le PDF avant de publier les téléchargements sur le site.
Les tests vérifient aussi l’ordre commun des rubriques, le sommaire imbriqué,
les accès directs aux options sans duplication des chapitres, le regroupement
des annexes et les ancres conservées après numérotation des manuels. Une cible
absente ou hors des sources de navigation est refusée explicitement.

## AutoGHS, StarNet et rendu final

Les tests de compensation vérifient les dépassements locaux StarNet de type
M31, même supérieurs au seuil d’alerte : branches positives, somme linéaire
conservée, données d’entrée inchangées et diagnostic explicite. Un scénario
complet produit les deux rendus et leurs JPEG après compensation. Les seuils
invalides et les branches corrigées hors domaine restent refusés.

Les tests `test_star_separation.py`, `test_star_rendering.py`, `test_auto_ghs.py`
et `test_final_render.py` couvrent respectivement l'adaptateur externe, le rendu
stellaire/fusion, les mathématiques/recherches et le contrat du pipeline :

Le rendu stellaire adaptatif est vérifié sur un champ synthétique de 36 pics
colorés : davantage de pics franchissent le contraste indicatif 0,03, avec
conservation des zéros, rapports RGB, plafond et garde de largeur. Les cas
constants, plateaux et forces invalides sont couverts. Les exports étoiles
FITS/JPEG et le diagnostic PNG sont vérifiés dans le pipeline. La cible de
dynamique 1,0 est testée pour RANGE et PEAK ; la configuration préserve les
surcharges et la nouvelle force stellaire sauvegardée.

```bash
.venv/bin/python -m pytest -q tests/test_star_separation.py tests/test_star_rendering.py tests/test_auto_ghs.py tests/test_final_render.py tests/test_postprocessor.py
```

Le contrat `both` exige une séparation, un rendu stellaire, deux traitements du
même fond initial et deux fusions avec la même couche d'étoiles ; les valeurs des
FITS finaux sont vérifiées, ainsi que les métadonnées, extensions et la source
inchangée. Les pannes d'extraction, calcul, fusion et publication sont injectées
sans autoriser de reprise. La configuration vérifie priorité, sauvegarde
explicite et instantanés d'instance. Les histogrammes constants, gaussiens,
points noirs ambigus/sûrs, limites des courbes, convergence et déterminisme sont
vérifiés ; la chroma RGB optionnelle conserve la direction au gris et le gamut.

`tests/data/auto_ghs_siril_1_4_4.json` contient des références **réellement
calculées par Siril 1.4.4**, et non par une deuxième copie de l'implémentation
Python. L'écart maximal GHS observé d'environ `1.02e-6` motive la tolérance absolue `2e-6`.
Le point noir de référence donne un écart nul. Les branches B négatives passent
les tests mathématiques, mais la CLI Siril locale les refuse.

La validation réelle est volontairement opt-in : elle nécessite Siril Flatpak,
StarNet V2, ses poids, et un dossier temporaire accessible depuis Flatpak. La
commande suivante crée ses FITS et rapports **dans `tmp/autoghs-validation/`**,
qui est réinitialisé par pytest et ne doit contenir que ces données de test :

```bash
SIRIL_AUTOGHS_INTEGRATION=1 .venv/bin/python -m pytest -q tests/test_auto_ghs_integration.py --basetemp=tmp/autoghs-validation
```

Le test CLI utilise un extrait RGB 512 × 512 de `imagesExample/M_33_combined.fits`.
Le chemin StarNet vient des préférences Siril ; `STARNET_PATH` permet une
surcharge pour cette validation. Siril est en Flatpak par défaut ; pour une
installation native ou AppImage (macOS, Windows), définir `SIRIL_MODE=native` et
`SIRIL_PATH=/chemin/siril-cli`, utilisés par les deux tests. La CLI désactive les traitements amont pour
ne pas les réexécuter et conserve le chemin réellement résolu dans un JSON
isolé avec `-S`. Elle vérifie les deux sorties **avec étoiles**, les deux fonds,
le rendu stellaire, les histogrammes, la reconstruction linéaire, l'absence
d'écrêtage, les indicateurs non linéaires et les données originales intactes.
Un second test recalcule les oracles mathématiques dans le Siril installé et
compare la recomposition screen à la commande PixelMath réelle ; l’écart screen
mesuré est de `5.96e-8` environ.

Le test CuPy est ignoré sans CUDA/CuPy fonctionnel. Des doubles couvrent
l'absence initiale de CUDA et une panne après initialisation ; ils ne valident
pas une exécution matérielle GPU. Une inspection astrophotographique sur
nébuleuse, IFN, bande étroite, ciel bruité et étoiles très brillantes reste
nécessaire pour qualifier les heuristiques de rendu. Voir
[AutoGHS](../docs/scripts/postProcess/auto-ghs.md), son
[algorithme](../docs/scripts/postProcess/auto-ghs-algorithm.md) et le
[traitement des étoiles](../docs/scripts/postProcess/star-rendering.md).

La politique générale de calcul est vérifiée par `test_compute_config.py` :
déclaration unique, défaut auto, transmission aux moteurs créés tardivement,
sauvegarde, surcharges historiques et choix CPU/CUDA selon la disponibilité.
Les doubles de disponibilité ne constituent pas une validation matérielle GPU.

```bash
.venv/bin/python -m pytest -q tests/test_compute_config.py
```

Les tests de `test_final_render.py` vérifient aussi la publication de deux PNG
distincts (sans étoiles et avec étoiles recomposées), l’absence de mélange de
leurs courbes et les axes logarithmiques, y compris avec des classes vides.

Les encarts AutoGHS sont vérifiés sur des recherches acceptées, refusées et
un arrêt avant recherche, avec distinction des candidats et corrections BP.

Les tests AutoGHS vérifient les dossiers visibles et ordonnés, le numéro fixe 05
même après fusion des étapes de restauration, la conservation des produits
partiels accompagnés d’un rapport ERROR et la réinitialisation sans produits
périmés lors d’une relance. Une source dans le dossier réinitialisé est protégée.

Le test CLI du nom de sortie vérifie le dossier, le rapport et le FITS
`<image>_postprocess`, avec Clarity activé puis désactivé.

La boucle d’expansion AutoGHS est vérifiée pour RANGE et PEAK avec les cibles
0,8/0,9, le gain borné, les images déjà étendues ou constantes, la limite de
passages et les paramètres invalides. Les tests vérifient BP sur le premier RGB
strictement positif, la conservation des valeurs supérieures et la sérialisation
du rapport complet, avec les deux boucles distinguées dans les figures.

L’égalisation partielle AutoGHS est vérifiée sur un histogramme concentré :
diminution de la dispersion des effectifs, étalement des intensités, monotonie,
respect des bornes, conservation des ratios RGB, désactivation et cas constant.
Le renforcement stellaire vérifie le gain des faibles intensités, le plafond,
l’absence de nouveaux pixels stellaires et la reproduction du rendu antérieur
avec un facteur 1. Les gardes de largeur et de couleur restent actives.

Les tests des chaînes de restauration vérifient que masques et opérations sont
placés directement dans `<rapport>_work/`, sans niveau `001`, y compris après
une relance sur une ancienne arborescence. Une entrée située dans le dossier
réinitialisé est refusée avant toute suppression.

Le défaut stellaire `star_faint_boost=5` est vérifié contre le facteur 3 : gain
des très faibles intensités proche de 5/3, même support positif, ratios RGB et
plafond conservés. Les profils gaussiens sont contrôlés aux deux réglages.

`test_render_exports.py` vérifie les exports JPEG RGB pleine résolution, les
intensités directes, l’orientation ROWORDER, l’intégrité du FITS, les entrées
invalides et la copie du JPEG principal par le CLI. Les comparatifs vérifient
que les pixels précédents sont capturés avant nettoyage et que les catégories
sans/avec étoiles restent séparées. Le contrat AutoGHS vérifie les nouveaux
chemins et le premier lancement, puis une relance avec historique disponible.

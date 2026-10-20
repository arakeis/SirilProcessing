# SirilProcessing

**Documentation générée par MkDocs et publiée sur GitHub Pages :**

- [Consulter la documentation HTML en ligne](https://dgedgedge.github.io/SirilProcessing/)
- [Télécharger la documentation complète en PDF](https://dgedgedge.github.io/SirilProcessing/downloads/documentation.pdf)
- [Télécharger la documentation complète en HTML autonome](https://dgedgedge.github.io/SirilProcessing/downloads/documentation.html)

Scripts de traitement d’images astronomiques avec Siril : bibliothèque de darks,
calibration des lights, sélection des images, stacking, mosaïques et animations
d’éclipse solaire.

<a id="documentation"></a>

## 1. Documentation

Le site MkDocs publié sur GitHub Pages donne accès aux guides suivants.
Les mêmes pages restent consultables en Markdown dans le dépôt.

### 1.1. Installation et plan de lecture

- [Installation sur le site](https://dgedgedge.github.io/SirilProcessing/docs/INSTALLATION.html)
  ou [source Markdown](docs/INSTALLATION.md).
- [Plan de la documentation](https://dgedgedge.github.io/SirilProcessing/docs/index.html)
  ou [source Markdown](docs/README.md).

### 1.2. Manuels des scripts

Le [sommaire des scripts](https://dgedgedge.github.io/SirilProcessing/docs/scripts/index.html)
([Markdown](docs/scripts/README.md)) regroupe, pour chaque script, son manuel,
ses options et ses traitements détaillés.

| Guide sur le site publié | Source dans le dépôt |
|---|---|
| [Traitement des lights : calibration, stacking et mosaïques](https://dgedgedge.github.io/SirilProcessing/docs/scripts/lightProcess/index.html) | [Markdown](docs/scripts/lightProcess/README.md) |
| [Post-traitement et rendu AutoGHS](https://dgedgedge.github.io/SirilProcessing/docs/scripts/postProcess/index.html) | [Markdown](docs/scripts/postProcess/README.md) |
| [Bibliothèque de darks](https://dgedgedge.github.io/SirilProcessing/docs/scripts/darkLibUpdate/index.html) | [Markdown](docs/scripts/darkLibUpdate/README.md) |
| [Animations d’éclipse solaire](https://dgedgedge.github.io/SirilProcessing/docs/scripts/solarEclipseGif/index.html) | [Markdown](docs/scripts/solarEclipseGif/README.md) |
| [Visualiseur des analyses KStars / Ekos](https://dgedgedge.github.io/SirilProcessing/docs/scripts/kstarsAnalyze/index.html) | [Markdown](docs/scripts/kstarsAnalyze/README.md) |
| [Visualiseur des guide logs KStars / Ekos](https://dgedgedge.github.io/SirilProcessing/docs/scripts/guideLogAnalyze/index.html) | [Markdown](docs/scripts/guideLogAnalyze/README.md) |
| [Identification du filtre d’acquisition](https://dgedgedge.github.io/SirilProcessing/docs/scripts/filterAnalyze/index.html) | [Markdown](docs/scripts/filterAnalyze/README.md) |

### 1.3. Architecture et maintenance

- [Architecture sur le site](https://dgedgedge.github.io/SirilProcessing/docs/architecture/index.html)
  ou [source Markdown](docs/architecture/README.md).
- [Règles documentaires](docs/CONTRIBUTING.md) et [tests du projet](tests/README.md).

La publication est actualisée par GitHub Actions après intégration des changements
sur la branche par défaut. Voir [la construction et la publication](docs/scripts/generate_docs_html/README.md).

<a id="ressources-de-calcul"></a>

## 2. Ressources de calcul

Tous les scripts Siril utilisent par défaut le nombre de processeurs logiques
du PC d’exécution moins un (minimum : un). La classe commune
`lib.cpu_config.CpuConfig` permet de changer cette limite pour tous les lancements
du processus : `CpuConfig.configure(limit=8)`. Utiliser
`CpuConfig.configure()` pour rétablir le calcul automatique. Une limite explicite
est plafonnée au nombre de processeurs du PC.

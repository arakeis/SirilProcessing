# Documentation SirilProcessing

[Projet](../README.md)

Ce plan est commun au site MkDocs, au PDF et au HTML autonome. Les manuels
regroupent, pour chaque script, son utilisation, ses options et ses traitements.
Les wrappers shell sont documentés avec leur script Python.

<a id="installation-et-d-marrage"></a>
<a id="installation-et-démarrage"></a>

## 1. Installation et démarrage

[Installer les dépendances](INSTALLATION.md) : Python, Siril, StarNet,
GraXpert, Cosmic Clarity et dépendances facultatives.

<a id="manuels-des-scripts"></a>

## 2. Manuels des scripts

Le [sommaire des scripts](scripts/README.md) donne accès aux rubriques suivantes :

| Rubrique | Manuel |
|---|---|
| 2.1 | [darkLibUpdate — bibliothèque de darks](scripts/darkLibUpdate/README.md) |
| 2.2 | [lightProcess — calibration, stacking et mosaïques](scripts/lightProcess/README.md) |
| 2.3 | [postProcess — gradient, couleurs, restauration et AutoGHS](scripts/postProcess/README.md) |
| 2.4 | [solarEclipseGif — animation solaire](scripts/solarEclipseGif/README.md) |
| 2.5 | [kstarsAnalyze — journaux d’acquisition Ekos](scripts/kstarsAnalyze/README.md) |
| 2.6 | [guideLogAnalyze — journaux de guidage](scripts/guideLogAnalyze/README.md) |
| 2.7 | [Construction de la documentation HTML/PDF](scripts/generate_docs_html/README.md) |
| 2.8 | [Utilitaires](scripts/README.md#utilitaires) |
| 2.9 | [filterAnalyze — identification du filtre d’acquisition](scripts/filterAnalyze/README.md) |

<a id="architecture"></a>

## 3. Architecture

[Organisation et catalogue des bibliothèques](architecture/README.md) :
responsabilités et relations entre modules. Les algorithmes et paramètres
restent dans les rubriques des scripts concernés.

<a id="maintenance-et-v-rification"></a>
<a id="maintenance-et-vérification"></a>

## 4. Maintenance et vérification

- [Contribuer à la documentation](CONTRIBUTING.md).
- [Exécuter les tests et connaître leur portée](../tests/README.md).
- [Construire et publier les trois formats](scripts/generate_docs_html/README.md).

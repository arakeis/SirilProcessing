# Options de filterAnalyze

[Documentation](../../README.md) › [Scripts](../README.md) › [filterAnalyze](README.md) › Options

Les options suivent la priorité commune du projet : ligne de commande, puis
configuration JSON sauvegardée avec `-S`, puis valeurs par défaut ci-dessous.
`--help` affiche la même liste.

## 1. Entrées, sorties et exécution

| Option | Défaut | Rôle |
|---|---|---|
| `input_files` (positionnel) | — | Une ou plusieurs brutes FITS CFA non calibrées |
| `-o`, `--output-dir` | dossier de chaque brute | Dossier des rapports `<brute>_filterAnalyze.json` |
| `-c`, `--combine` | désactivé | Analyser ensemble les brutes d’une même série (mêmes `OBJECT`, `FILTER`, `EXPTIME` et `INSTRUME`) ; un rapport `<première brute>_series_filterAnalyze.json` par série |
| `-l`, `--log-level` | `INFO` | Niveau de journalisation |
| `-s`, `--siril-path` | défaut Siril du projet ([Installation](../../INSTALLATION.md)) | Exécutable Siril (modes `native` et `appimage`) |
| `-m`, `--siril-mode` | défaut Siril du projet | `native`, `flatpak` ou `appimage` |
| `--config` | `~/.siril_darklib_config.json` | Fichier de configuration partagé |
| `-S`, `--save-config` | désactivé | Sauvegarder les options dans la configuration |

## 2. Analyse

| Option | Défaut | Rôle |
|---|---|---|
| `--filter-max-stars` | 100 | Nombre maximal d’étoiles dont le spectre Gaia XP est utilisé, réparties en couleur (par série avec `--combine`) |
| `--filter-min-stars` | 20 | Nombre minimal d’étoiles exploitables ; en dessous, la brute est refusée |
| `--filter-max-g` | 15,0 | Magnitude G limite des étoiles mesurées |
| `--filter-neighbor-g` | 17,0 | Magnitude G limite des voisins pris en compte pour rejeter les étoiles serrées |
| `--filter-aperture` | 3,0 | Rayon d’ouverture en superpixels (blocs 2×2 de photosites) ; anneau de fond de 1,5 à 2,5 fois ce rayon |
| `--filter-min-snr` | 30 | Rapport signal sur bruit minimal dans chacun des trois canaux |
| `--filter-sensor` | déduit de `INSTRUME` | Nom exact d’un capteur de la base SPCC, par exemple `Sony IMX294` |
| `--filter-cache-dir` | `~/.cache/sirilprocessing/gaia` | Cache des sources et des spectres Gaia |
| `--filter-family-margin` | 0,5 | Écart de score minimal entre la meilleure famille et la suivante |
| `--filter-margin` | 0,3 | Écart de score minimal entre le meilleur filtre et le suivant de sa famille |
| `--filter-model-uncertainty` | 0,02 | Incertitude relative du modèle par flux, ajoutée au bruit de mesure |

Seul l’ASI294MC (capteur `Sony IMX294`) est reconnu automatiquement par
`INSTRUME`. Pour une autre caméra, indiquer `--filter-sensor` avec le nom de
la base SPCC (dossier `osc_sensors` de la base de Siril).

# Manuels des scripts

<a id="documentation-des-scripts"></a>

[Documentation](../README.md)

Chaque rubrique réunit le manuel d’utilisation, les options et la description
des traitements. Les liens « Options » mènent directement aux tableaux ou
pages de référence correspondantes, sans seconde copie de leurs tableaux.

<a id="darklibupdate-biblioth-que-de-darks"></a>
<a id="darklibupdate-bibliothèque-de-darks"></a>

## 2.1. darkLibUpdate — bibliothèque de darks

<a id="manuel-d-utilisation"></a>
<a id="manuel-dutilisation"></a>

### 2.1.1. Manuel d’utilisation

[Présentation](darkLibUpdate/README.md) et [guide complet](darkLibUpdate/GUIDE.md)
de `darkLibUpdate.py` et `darkLibUpdate.sh`.

<a id="options-et-configuration"></a>

### 2.1.2. Options et configuration

[Options courtes](darkLibUpdate/OPTIONS_COURTES_GUIDE.md),
[paramètres du manuel](darkLibUpdate/GUIDE.md#options-principales) et
[configuration persistante](darkLibUpdate/VALIDATION_CONFIG_GUIDE.md).

<a id="traitements-et-sorties"></a>

### 2.1.3. Traitements et sorties

[Validation, statistiques, rapports et interruptions](darkLibUpdate/README.md#traitements).

<a id="lightprocess-calibration-stacking-et-mosa-ques"></a>
<a id="lightprocess-calibration-stacking-et-mosaïques"></a>

## 2.2. lightProcess — calibration, stacking et mosaïques

<a id="manuel-d-utilisation_1"></a>
<a id="manuel-dutilisation_1"></a>

### 2.2.1. Manuel d’utilisation

[Présentation](lightProcess/README.md), [commandes de démarrage](lightProcess/GUIDE.md)
et [organisation des sessions](lightProcess/SESSIONS.md).

<a id="options-et-configuration_1"></a>

### 2.2.2. Options et configuration

[Options par étape](lightProcess/OPTIONS.md) et
[paramètres partagés avec postProcess](lightProcess/README.md#paramètres-siril-partagés).

<a id="traitements-et-sorties_1"></a>

### 2.2.3. Traitements et sorties

[Parcours complet](lightProcess/treatments/README.md),
[mosaïques](lightProcess/MOSAIC.md) et
[résultats, reprises et journaux](lightProcess/treatments/OUTPUTS.md).

<a id="postprocess-post-traitement-et-rendu-final"></a>

## 2.3. postProcess — post-traitement et rendu final

<a id="manuel-d-utilisation_2"></a>
<a id="manuel-dutilisation_2"></a>

### 2.3.1. Manuel d’utilisation

[Lancer un traitement](postProcess/README.md#lancer-un-traitement),
[ordre des étapes](postProcess/README.md#ordre-et-circulation-des-images) et
[enchaînement depuis lightProcess](postProcess/pipeline.md).

<a id="options-et-configuration_2"></a>

### 2.3.2. Options et configuration

[Configuration et mémorisation](postProcess/OPTIONS.md),
[choix CPU/GPU](postProcess/compute-backend.md) et
[activation des traitements](postProcess/README.md#utiliser-seulement-certaines-étapes).

<a id="traitements-et-sorties_2"></a>

### 2.3.3. Traitements et sorties

[Manuel complet](postProcess/README.md), [restauration](postProcess/restoration.md),
[AutoGHS](postProcess/auto-ghs.md) et [FITS, JPEG et comparatifs](postProcess/render-exports.md).

<a id="solareclipsegif-animation-solaire"></a>

## 2.4. solarEclipseGif — animation solaire

<a id="manuel-d-utilisation_3"></a>
<a id="manuel-dutilisation_3"></a>

### 2.4.1. Manuel d’utilisation

[Présentation](solarEclipseGif/README.md) et [guide du script](solarEclipseGif/GUIDE.md).

<a id="options-et-r-sultats"></a>
<a id="options-et-résultats"></a>

### 2.4.2. Options et résultats

[Paramètres](solarEclipseGif/OPTIONS.md),
[commandes](solarEclipseGif/GUIDE.md#commandes) et
[fichiers générés](solarEclipseGif/GUIDE.md#fichiers-generes).

<a id="kstarsanalyze-journaux-d-acquisition-ekos"></a>
<a id="kstarsanalyze-journaux-dacquisition-ekos"></a>

## 2.5. kstarsAnalyze — journaux d’acquisition Ekos

<a id="manuel-d-utilisation_4"></a>
<a id="manuel-dutilisation_4"></a>

### 2.5.1. Manuel d’utilisation

[Fenêtre native et rapports HTML](kstarsAnalyze/README.md).

<a id="options"></a>

### 2.5.2. Options

[Options de ligne de commande](kstarsAnalyze/OPTIONS.md).

<a id="guideloganalyze-journaux-de-guidage"></a>

## 2.6. guideLogAnalyze — journaux de guidage

<a id="manuel-d-utilisation_5"></a>
<a id="manuel-dutilisation_5"></a>

### 2.6.1. Manuel d’utilisation

[Explorer une nuit](guideLogAnalyze/README.md#explorer-une-nuit),
[mesures et statistiques](guideLogAnalyze/README.md#mesures-et-statistiques) et
[export HTML](guideLogAnalyze/README.md#export-html-autonome).

<a id="options_1"></a>

### 2.6.2. Options

[Options de ligne de commande](guideLogAnalyze/OPTIONS.md).

<a id="g-n-rer-la-documentation"></a>
<a id="générer-la-documentation"></a>

## 2.7. Générer la documentation

<a id="manuel-d-utilisation_6"></a>
<a id="manuel-dutilisation_6"></a>

### 2.7.1. Manuel d’utilisation

[Construction locale et publication GitHub Pages](generate_docs_html/README.md).

<a id="options_2"></a>

### 2.7.2. Options

[Options du constructeur](generate_docs_html/OPTIONS.md)
pour `build_documentation.py` et `build_docs.sh` ; le même manuel décrit
l’ancien point d’entrée `generate_docs_html.py`.

<a id="utilitaires"></a>

## 2.8. Utilitaires

| Script | Manuel d’utilisation et arguments |
|---|---|
| `pyecho.py` | [Messages et intégration Siril](pyecho/README.md) |
| `pydir.py` | [Affichage d’un répertoire](pydir/README.md) |
| `trouve_doublons.py` | [Comparaison de contenu et script de nettoyage](trouve_doublons/README.md) |

<a id="filteranalyze-identification-du-filtre"></a>

## 2.9. filterAnalyze — identification du filtre (en développement)

[Présentation et état d’avancement](filterAnalyze/README.md) et
[modèle direct et score de compatibilité](filterAnalyze/MODEL.md).

Pour comprendre les responsabilités des modules communs, consulter
l’[architecture](../architecture/README.md).

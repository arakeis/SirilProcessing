# Options de postProcess

[Documentation des scripts](../README.md) › [postProcess](README.md)

<a id="configuration-et-m-morisation"></a>
<a id="configuration-et-mémorisation"></a>

## 1. Configuration et mémorisation

Au démarrage, `Config` interroge les classes de traitement, charge leurs options
et résout les valeurs selon la priorité **ligne de commande → fichier JSON →
défauts locaux des classes**. Les défauts décrits dans les références des
traitements peuvent donc être remplacés par une configuration sauvegardée.

| Option commune | Rôle |
|---|---|
| `--config FICHIER` | Fichier partagé ; défaut `~/.siril_darklib_config.json` |
| `-S`, `--save-config` | Mémoriser les paramètres rémanents |
| `-m`, `--siril-mode` | `flatpak` par défaut sous Linux (`native` ailleurs), ou `native`, `appimage` |
| `-s`, `--siril-path` | `siril` par défaut sous Linux (`siril-cli` ailleurs, ou celui de Siril.app sous macOS) ; chemin de l’exécutable en mode native/appimage |
| `-l`, `--log-level` | `INFO` par défaut ; aussi `DEBUG`, `WARNING`, `ERROR`, `CRITICAL` |

`-S` mémorise les paramètres Siril, les activations/désactivations et les réglages
rémanents des **cinq traitements**, y compris ceux désactivés. Les clés déjà
présentes concernant d’autres traitements sont conservées. Sans `-S`, aucune
écriture du fichier de configuration n’est effectuée.

Restent propres à l’exécution : les chemins d’entrée et de rapport, le niveau
de journalisation, `--gradient-output`, `--photometry-object`,
`--photometry-coordinates`, `--photometry-force`, `--photometry-output` et
`--deconvolution-output`. Ces paramètres ne sont pas mémorisés par `-S`.
Les anciens noms `--photometry-siril-path` et `--photometry-siril-mode` sont des
alias des réglages Siril communs.

```bash
# Mémoriser les réglages, puis traiter l’image.
bin/postProcess.sh image_RGB.fit rapports/resultat.json \
  --config config/postprocess.json -m native -s siril-cli \
  --photometry-object M20 --denoise-modulation 0.4 -S

# Réutiliser ces réglages sur une autre image ; le nom d’objet est fourni à nouveau.
bin/postProcess.sh autre_image_RGB.fit rapports/autre.json \
  --config config/postprocess.json --photometry-object M31
```

La sauvegarde intervient avant les traitements, après vérification de la présence
de l’image d’entrée. Les réglages peuvent donc être mémorisés même si une étape
échoue ensuite. Un échec de sauvegarde arrête le programme.
Les réglages de qualité et des chaînes sont également rémanents. Pour GraXpert,
`enable_graxpert: null` conserve l’activation automatique ; `false` reste une
désactivation explicite, même avec des poids présents.

<a id="choix-du-calcul-cpu-gpu"></a>
<a id="choix-du-calcul-cpugpu"></a>

## 2. Choix du calcul CPU/GPU

`--compute-backend auto|cpu|cuda` s'applique aux moteurs de postProcess et se
sauvegarde avec `-S`. Le défaut `auto` choisit l'accélérateur disponible pour
chaque moteur, CPU sinon, avant calcul. Les options propres aux moteurs restent
des surcharges explicites, y compris dans les anciens JSON. Voir la
[politique commune, ses priorités et ses limites](compute-backend.md).

<a id="options-des-traitements"></a>

## 3. Options des traitements

Les tableaux des sections suivantes décrivent les options de chaque étape. Les références spécialisées complètent celles de [GraXpert](graxpert.md#paramètres), [AutoGHS](auto-ghs.md#paramètres) et de la [politique CPU/GPU](compute-backend.md).

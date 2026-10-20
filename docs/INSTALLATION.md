# Installation et démarrage

[Documentation](README.md)

Les lanceurs actuels ciblent Linux avec Bash. L’installation comprend les
paquets Python du projet et les logiciels astronomiques externes. **Installer
les dépendances Python n’installe ni Siril, ni StarNet, ni l’application GraXpert.**

<a id="d-pendances-pr-voir"></a>
<a id="dépendances-à-prévoir"></a>

## 1. Dépendances à prévoir

| Dépendance | Utilisation | Installation |
|---|---|---|
| Python 3, `venv` et pip système | Tous les lanceurs | Gestionnaire de paquets du système ; pip doit prendre en charge `--python` |
| Siril 1.4.x | Calibration, alignement, stacking, photométrie et contrôles de restauration | Logiciel externe ; modes Flatpak, natif ou AppImage |
| StarNet++ V2 historique et son modèle | Séparation des étoiles pour AutoGHS, actif par défaut | Archive CLI externe, puis chemin configuré dans Siril ou avec `--starnet-path` |
| ONNX Runtime et poids GraXpert 3.0.2 | Moteur de débruitage GraXpert, facultatif | `--install-graxpert` pour le runtime CPU ; poids importés ou acquis séparément |
| Application GraXpert | Acquisition des poids manquants uniquement | Logiciel externe, inutile si un modèle local conforme est déjà présent |
| PyTorch et poids Cosmic Clarity | Moteurs de netteté et débruitage Cosmic Clarity | `--install-cosmic-clarity` pour les dépendances optionnelles et les poids |
| CuPy ou fournisseur ONNX GPU | Accélération AutoGHS ou GraXpert | Dépendances GPU distinctes ; le calcul CPU reste disponible |
| Tkinter | Interfaces graphiques des visualiseurs | Paquet système, par exemple `python3-tk` sous Debian/Ubuntu |
| MkDocs, Playwright et Chromium | Construction du site, du HTML autonome et du PDF | `requirements-docs.txt`, puis navigateur Chromium séparément |
| `dbus-python` et services d’énergie Linux | PowerGuard, facultatif | `requirements-power.txt` ; l’absence de ces services ne bloque pas le calcul |

Siril reste nécessaire même si les réseaux GraXpert ou Cosmic Clarity sont
utilisés : les mesures et contrôles stellaires passent aussi par Siril.
Les visualiseurs KStars/guide logs et la génération documentaire seule n’ont
pas besoin de Siril, StarNet ou des modèles de traitement.

<a id="environnement-python-et-lanceurs"></a>

## 2. Environnement Python et lanceurs

Les lanceurs `.sh` utilisent Python et pip **du système** pour créer et mettre
à jour leur environnement virtuel, puis exécutent les scripts avec le Python
de cet environnement. Ils ne nécessitent pas pip dans le venv.

Depuis la racine du projet :

```bash
./bin/lightProcess.sh /chemin/vers/la/session
```

Le module partagé `bin/venv_helpers.sh` sélectionne `VENV_DIR` s’il est défini,
sinon `.venv`, puis `venv` lorsqu’il existe déjà. Sans environnement existant,
il crée `.venv`. Il utilise `python3` pour retrouver l’interpréteur système,
même lorsqu’un venv est activé dans le terminal, puis effectue l’équivalent de :

```bash
python3 -m venv --without-pip .venv
python3 -m pip --python .venv/bin/python install --upgrade -r requirements.txt
```

Ces commandes manuelles supposent un terminal sans venv activé. Le Python
système doit fournir les modules `venv` et `pip` avec prise en charge de
`--python` (pip 22.3 ou plus récent). Un échec de création ou d’installation
interrompt le lanceur. Les paquets système ne sont pas modifiés.

Chaque lancement vérifie les mises à jour et peut nécessiter Internet, y compris
avec `--help`. Pour exécuter sans mise à jour, appeler directement le script :

```bash
.venv/bin/python bin/postProcess.py --help
.venv/bin/python -m pytest -q tests/test_deconvolution.py tests/test_denoising.py
```

`requirements.txt` inclut les traitements, les visualiseurs, la documentation
HTML/PDF et les tests. Les lanceurs KStars et guide logs utilisent seulement
`requirements-analyze.txt`. Le fichier `requirements-docs.txt` permet une
installation documentaire seule, avec MkDocs et Playwright. Chromium est installé
séparément pour les exports HTML/PDF ; voir le [guide documentaire](scripts/generate_docs_html/README.md).
Tkinter reste une dépendance système (`python3-tk`
sous Debian/Ubuntu).

<a id="installer-et-s-lectionner-siril"></a>
<a id="installer-et-sélectionner-siril"></a>

## 3. Installer et sélectionner Siril

Installer Siril depuis les [distributions officielles](https://siril.org/download/),
qui proposent notamment AppImage et un lien vers la distribution Flatpak.
Le parcours complet du projet utilise Siril **1.4.x** ; l’installation de
référence validée est Siril **1.4.4**. Une ancienne version 1.2 ne couvre pas
toutes les commandes de photométrie, de restauration et d’AutoGHS utilisées.

Les options sont communes à lightProcess et postProcess :

| Installation Siril | Options de sélection | Exécutable lancé |
|---|---|---|
| Flatpak, mode par défaut sous Linux | `--siril-mode flatpak` | `flatpak run --command=siril-cli org.siril.Siril` |
| Installation native, mode par défaut hors Linux | `--siril-mode native --siril-path /chemin/siril-cli` | Le programme indiqué par `--siril-path` ; sans `--siril-path`, `siril-cli` du `PATH`, ou celui de `/Applications/Siril.app` sous macOS |
| AppImage | `--siril-mode appimage --siril-path /chemin/Siril.AppImage` | L’AppImage indiquée, qui doit être exécutable |

Pour vérifier la présence et la version de l’application Flatpak :

```bash
flatpak info org.siril.Siril
```

Les données, dossiers de sortie et programmes externes doivent être accessibles
depuis le mode choisi, notamment dans l’environnement Flatpak. Les wrappers
Python ne changent pas les droits d’accès du bac à sable.
`-S/--save-config` mémorise les réglages dans `~/.siril_darklib_config.json` par
défaut ; `--config fichier.json` sélectionne un autre fichier. Les valeurs de
la ligne de commande priment sur ce fichier. Voir la
[configuration partagée](scripts/postProcess/README.md#configuration-et-mémorisation).

<a id="installer-starnet-pour-autoghs"></a>

## 4. Installer StarNet pour AutoGHS

AutoGHS utilise un logiciel externe pour séparer étoiles et fond :
**StarNet++ V2 historique en version CLI**, avec ses bibliothèques et son modèle.
La validation du projet porte sur StarNet++ **2.0.2** avec Siril 1.4.4.

1. Récupérer l’archive CLI adaptée au système parmi les
   [archives historiques officielles StarNet](https://starnetastro.com/cli-tools/legacy/).
   Extraire l’ensemble et suivre son README, en conservant les fichiers associés
   au programme. L’adaptateur utilise typiquement l’exécutable `starnet++`.
2. Définir le chemin du programme dans les préférences Siril, ou fournir
   `--starnet-path /chemin/StarNetv2CLI_linux/starnet++` au traitement.
3. Ajouter `-S/--save-config` au lancement pour mémoriser ce chemin dans la
   configuration du projet. Sans chemin explicite ou sauvegardé, le programme
   recherche celui des préférences Siril du mode sélectionné.

Le projet appelle la commande Siril historique `starnet -stretch`. Il ne lance
pas le script `StarNet.py` des nouvelles versions : une installation récente
2.5/2.6 ne remplace donc pas automatiquement cette dépendance. La
[documentation Siril sur StarNet](https://siril.readthedocs.io/en/stable/processing/stars/starnet.html)
décrit cette distinction d’interfaces.

AutoGHS est **actif par défaut**, également lors de l’enchaînement depuis
lightProcess. StarNet est donc nécessaire pour ce parcours par défaut.
`--disable-autoghs` permet de conserver un parcours sans rendu AutoGHS ;
`--no-postprocess` désactive l’ensemble du post-traitement dans lightProcess.
Le contrat et les chemins de découverte sont détaillés dans
[AutoGHS : prérequis et configuration](scripts/postProcess/auto-ghs.md).

<a id="installer-le-d-bruitage-graxpert"></a>
<a id="installer-le-débruitage-graxpert"></a>

## 5. Installer le débruitage GraXpert

Le moteur du projet utilise **ONNX Runtime et les poids GraXpert 3.0.2**.
L’application GraXpert sert seulement à acquérir un modèle absent des caches ;
l’inférence sur les images se fait ensuite directement en Python/ONNX.

Installer le runtime CPU optionnel dans le venv sélectionné :

```bash
bin/postProcess.sh --install-graxpert
```

Cette commande installe `requirements-graxpert.txt` ; elle n’installe pas
l’application GraXpert et ne télécharge pas les poids. Les dépendances ainsi
préparées servent aussi à l’enchaînement depuis lightProcess, si les deux
lanceurs utilisent le même venv.

Le moteur s’active automatiquement si un poids local conforme est présent
dans le cache du projet ou dans un cache GraXpert/Siril, sauf désactivation
explicite. Pour acquérir un modèle absent :

1. Installer l’[application GraXpert officielle](https://github.com/Dark-Matters-Astro/GraXpert/releases).
2. La rendre accessible sous le nom `GraXpert-linux` dans le `PATH`, ou indiquer
   `--graxpert-path /chemin/GraXpert-linux`.
3. Utiliser `--enable-graxpert` lors d’un traitement pour autoriser l’acquisition.
   Un accès Internet est alors nécessaire si le poids manque dans tous les caches.

Le modèle pris en charge reste celui du manifeste du projet, même si le numéro
de version de l’application externe diffère. Une fois le poids validé importé,
l’exécutable GraXpert n’est plus nécessaire à l’inférence. Le cache du projet
est `tmp/models/graxpert/`, exclu de Git et de l’archive.
`--no-enable-graxpert` désactive ce moteur. Voir
[GraXpert : modèles, activation et périphériques](scripts/postProcess/graxpert.md)
pour les contrôles d’intégrité, les erreurs d’acquisition et l’option GPU.

<a id="cosmic-clarity-et-acc-l-ration-gpu"></a>
<a id="cosmic-clarity-et-accélération-gpu"></a>

## 6. Cosmic Clarity et accélération GPU

Les dépendances Cosmic Clarity sont optionnelles et séparées de
`requirements.txt`. Le lanceur fournit :

```bash
bin/postProcess.sh --install-cosmic-clarity
```

Cette commande installe les dépendances PyTorch CUDA déclarées dans
`requirements-cosmic-clarity.txt` et précharge les six poids nécessaires dans
`tmp/models/cosmicclarity/`. Ce moteur effectue son inférence dans Python :
il ne nécessite pas l’installation de l’application graphique Cosmic Clarity.
La comparaison Cosmic Clarity est activée par défaut ; `--disable-clarity`
permet de l’écarter. Siril reste requis pour les contrôles.
Voir [Cosmic Clarity](scripts/postProcess/cosmic-clarity.md) pour les versions
épinglées, les prérequis GPU, les erreurs et les volumes de téléchargement.

`--compute-backend auto`, réglage général par défaut, choisit le GPU disponible
pour chaque moteur ou le CPU avant calcul. **Ce choix n’installe aucune
dépendance GPU.** PyTorch CUDA, `onnxruntime-gpu` pour GraXpert et CuPy pour
AutoGHS sont trois installations distinctes. Le pilote et les bibliothèques
doivent être compatibles avec le runtime choisi ; voir la
[politique de calcul CPU/GPU](scripts/postProcess/compute-backend.md).

<a id="documentation-visualiseurs-et-gestion-de-l-nergie"></a>
<a id="documentation-visualiseurs-et-gestion-de-lénergie"></a>

## 7. Documentation, visualiseurs et gestion de l’énergie

Pour les visualiseurs seuls, utiliser `requirements-analyze.txt` et prévoir
Tkinter pour les interfaces graphiques. Pour construire la documentation,
utiliser `requirements-docs.txt` et installer Chromium pour Playwright selon
le [guide documentaire](scripts/generate_docs_html/README.md).

PowerGuard utilise facultativement `requirements-power.txt` et les services
D-Bus Linux d’inhibition de veille et de profil énergétique. Les scripts de
haut niveau l’activent pendant les calculs ; son indisponibilité laisse le
traitement continuer. Voir la [gestion de l’énergie](scripts/postProcess/power-guard.md).

Consulter ensuite la [documentation du script](scripts/README.md) concerné
pour les entrées attendues, les paramètres et les vérifications propres à chaque moteur.

#!/usr/bin/env bash
# Lanceur de filterAnalyze.py : prépare l'environnement Python du projet puis l'exécute.
set -euo pipefail

# Dossiers du lanceur et du projet, indépendants du dossier de lancement.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

# Environnement virtuel du projet, créé ou mis à jour depuis requirements.txt.
# shellcheck source=bin/venv_helpers.sh
source "${SCRIPT_DIR}/venv_helpers.sh"
prepare_project_venv "${PROJECT_ROOT}/requirements.txt"

# Exécution du script avec tous les arguments reçus.
exec "${SELECTED_VENV}/bin/python" "${SCRIPT_DIR}/filterAnalyze.py" "$@"

#!/usr/bin/env bash
set -euo pipefail

DEPLOYMENT_REPO_URL=${OEDS_DEPLOYMENT_REPO_URL:-https://gitlab.kit.edu/kit/iip/energyeconomics/sem-fec/josc/oeds-deployment.git}
DEPLOYMENT_REF=${OEDS_DEPLOYMENT_REF:-main}
WORK_DIR=${OEDS_INSTALL_WORK_DIR:-$HOME/oeds-modular-git-install}
CHECKOUT_DIR=${OEDS_DEPLOYMENT_CHECKOUT_DIR:-$WORK_DIR/oeds-deployment}
ASSEMBLED_DIR=${OEDS_ASSEMBLED_DIR:-$WORK_DIR/assembled}
OEDS_ROOT=${OEDS_ROOT:-/open_energy_data_server}
RESET=false
SKIP_HOST_PREP=false
LOAD_SAMPLE_DATA=false
INCLUDE_ENTSOE_FMS=false

usage() {
  cat <<'USAGE'
Usage:
  OEDS_GIT_TOKEN=<token> [OEDS_GIT_USERNAME=oauth2] tools/oeds_clean_install_from_git.sh [options]

Options:
  --reset                 Run a destructive OEDS uninstall before installing.
  --skip-host-prep        Skip OS/Docker host preparation.
  --load-sample-data      Load and verify a small real-data sample after install.
  --include-entsoe-fms    Include ENTSO-E FMS in the sample-data load.
  --repo-url URL          Deployment repository URL.
  --ref REF               Deployment repository branch, tag, or commit.
  --work-dir DIR          Working directory for clone and assembled workspace.
  --root DIR              Target OEDS root, default /open_energy_data_server.
  -h, --help              Show this help.

Environment:
  OEDS_GIT_TOKEN              GitLab PAT or deploy token password for private HTTPS clones.
  OEDS_GIT_USERNAME           GitLab username for the token. Use "oauth2" for PATs.
  OEDS_BECOME_PASSWORD_FILE   Optional sudo password file for non-interactive Ansible runs.

The token is passed to git through a temporary GIT_ASKPASS helper and is removed
when the script exits. It is not written to the repository or Ansible inventory.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset) RESET=true; shift ;;
    --skip-host-prep) SKIP_HOST_PREP=true; shift ;;
    --load-sample-data) LOAD_SAMPLE_DATA=true; shift ;;
    --include-entsoe-fms) INCLUDE_ENTSOE_FMS=true; shift ;;
    --repo-url) DEPLOYMENT_REPO_URL=$2; shift 2 ;;
    --ref) DEPLOYMENT_REF=$2; shift 2 ;;
    --work-dir) WORK_DIR=$2; CHECKOUT_DIR=$2/oeds-deployment; ASSEMBLED_DIR=$2/assembled; shift 2 ;;
    --root) OEDS_ROOT=$2; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "unknown argument: $1" >&2; usage >&2; exit 2 ;;
  esac
done

log() {
  printf '\n==> %s\n' "$*"
}

require_command() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "missing required command: $1" >&2
    exit 1
  fi
}

ASKPASS_DIR=""
cleanup() {
  if [[ -n "$ASKPASS_DIR" ]]; then
    rm -rf "$ASKPASS_DIR"
  fi
}
trap cleanup EXIT

setup_git_auth() {
  export GIT_TERMINAL_PROMPT=0
  if [[ -z "${OEDS_GIT_TOKEN:-}" ]]; then
    log "No OEDS_GIT_TOKEN set; git clones must be public or already authenticated"
    return
  fi

  ASKPASS_DIR=$(mktemp -d)
  chmod 0700 "$ASKPASS_DIR"
  cat > "$ASKPASS_DIR/oeds-git-askpass.sh" <<'SH'
#!/usr/bin/env bash
case "$1" in
  *Username*) printf '%s\n' "${OEDS_GIT_USERNAME:-oauth2}" ;;
  *Password*) printf '%s\n' "$OEDS_GIT_TOKEN" ;;
  *) printf '\n' ;;
esac
SH
  chmod 0700 "$ASKPASS_DIR/oeds-git-askpass.sh"
  export GIT_ASKPASS="$ASKPASS_DIR/oeds-git-askpass.sh"
}

ensure_ansible() {
  if command -v ansible-playbook >/dev/null 2>&1; then
    return
  fi
  log "ansible-playbook not found; installing Ansible for the current user"
  python3 -m pip install --user ansible
  export PATH="$HOME/.local/bin:$PATH"
  require_command ansible-playbook
}

become_args() {
  if [[ -n "${OEDS_BECOME_PASSWORD_FILE:-}" ]]; then
    printf '%s\0%s\0' "--become-password-file" "$OEDS_BECOME_PASSWORD_FILE"
  elif sudo -n true >/dev/null 2>&1; then
    true
  else
    printf '%s\0' "--ask-become-pass"
  fi
}

readarray_nul() {
  local -n out=$1
  out=()
  while IFS= read -r -d '' item; do
    out+=("$item")
  done
}

require_command git
require_command python3
setup_git_auth
ensure_ansible
require_command ansible-galaxy

log "Cloning deployment repository"
rm -rf "$CHECKOUT_DIR"
mkdir -p "$WORK_DIR"
git clone "$DEPLOYMENT_REPO_URL" "$CHECKOUT_DIR"
git -C "$CHECKOUT_DIR" fetch --tags origin
git -C "$CHECKOUT_DIR" checkout "$DEPLOYMENT_REF"

log "Assembling compatible modular workspace"
python3 "$CHECKOUT_DIR/tools/assemble_workspace.py" --output "$ASSEMBLED_DIR" --clean

PLAYBOOK_DIR="$ASSEMBLED_DIR/modular_repos/modules/oeds-deployment/playbooks"
if [[ ! -d "$PLAYBOOK_DIR" ]]; then
  echo "assembled playbook directory not found: $PLAYBOOK_DIR" >&2
  exit 1
fi

log "Preparing local Ansible inventory"
cat > "$PLAYBOOK_DIR/inventory.local.yml" <<YAML
all:
  children:
    oeds:
      hosts:
        local:
          ansible_connection: local
          ansible_user: $(id -un)
          ansible_become: true
          ansible_become_method: sudo
          ansible_python_interpreter: /usr/bin/python3
YAML

cd "$PLAYBOOK_DIR"
export ANSIBLE_CONFIG=ansible.cfg
ansible-galaxy collection install -r requirements.yml

BECOME_ARGS=()
readarray_nul BECOME_ARGS < <(become_args)
COMMON_ARGS=(-i inventory.local.yml "${BECOME_ARGS[@]}")
MODULAR_EXTRA=(
  -e "oeds_root=$OEDS_ROOT"
  -e "oeds_repo_source_mode=local_worktree"
  -e "oeds_repo_local_src=$ASSEMBLED_DIR"
  -e "oeds_enable_crawlers=true"
  -e "oeds_compose_dir=$OEDS_ROOT/repo/modular_repos/modules/oeds-deployment"
  -e '{"oeds_compose_files":["compose.yml","compose.modular.yml"]}'
)

if [[ "$SKIP_HOST_PREP" != "true" ]]; then
  log "Preparing host packages and Docker"
  ansible-playbook "${COMMON_ARGS[@]}" oeds-install-host-prep.yml
fi

if [[ "$RESET" == "true" ]]; then
  log "Running destructive OEDS reset"
  ansible-playbook "${COMMON_ARGS[@]}" oeds-uninstall.yml \
    -e "oeds_root=$OEDS_ROOT" \
    -e "oeds_compose_dir=$OEDS_ROOT/repo/modular_repos/modules/oeds-deployment" \
    -e '{"oeds_compose_files":["compose.yml","compose.modular.yml"]}' \
    -e oeds_uninstall_remove_repo=true \
    -e oeds_uninstall_remove_runtime=true \
    -e oeds_uninstall_destroy_data=true \
    -e oeds_uninstall_confirm=DELETE_OEDS_DATA
fi

log "Installing modular OEDS"
ansible-playbook "${COMMON_ARGS[@]}" oeds-install-crawlers.yml "${MODULAR_EXTRA[@]}"

log "Running final Ansible smoke test"
ansible-playbook "${COMMON_ARGS[@]}" oeds-smoke-test.yml \
  -e "oeds_root=$OEDS_ROOT" \
  -e oeds_expect_crawler_admin=true

if [[ "$LOAD_SAMPLE_DATA" == "true" ]]; then
  log "Loading sample data into the installed OEDS database"
  SAMPLE_ARGS=()
  if [[ "$INCLUDE_ENTSOE_FMS" == "true" ]]; then
    SAMPLE_ARGS+=(--include-entsoe-fms)
  fi
  if [[ -n "${OEDS_BECOME_PASSWORD_FILE:-}" ]]; then
    sudo -S bash "$OEDS_ROOT/repo/modular_repos/modules/oeds-deployment/tools/load_sample_data.sh" "${SAMPLE_ARGS[@]}" < "$OEDS_BECOME_PASSWORD_FILE"
  else
    sudo bash "$OEDS_ROOT/repo/modular_repos/modules/oeds-deployment/tools/load_sample_data.sh" "${SAMPLE_ARGS[@]}"
  fi
fi

log "Clean Git-based modular install finished"

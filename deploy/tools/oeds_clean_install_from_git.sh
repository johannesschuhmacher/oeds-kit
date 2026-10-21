#!/usr/bin/env bash
set -euo pipefail

REPO_URL=${OEDS_REPO_URL:-https://github.com/johannesschuhmacher/oeds-kit.git}
REPO_REF=${OEDS_REPO_REF:-main}
WORK_DIR=${OEDS_INSTALL_WORK_DIR:-$HOME/oeds-modular-git-install}
CHECKOUT_DIR=${OEDS_CHECKOUT_DIR:-$WORK_DIR/oeds-kit}
INVENTORY_FILE=${OEDS_ANSIBLE_INVENTORY_FILE:-$WORK_DIR/inventory.local.yml}
OEDS_ROOT=${OEDS_ROOT:-/open_energy_data_server}
RESET=false
SKIP_HOST_PREP=false
LOAD_SAMPLE_DATA=false
INCLUDE_ENTSOE_FMS=false
CRAWLER_ENV_FILE=${OEDS_CRAWLER_ENV_FILE:-}

usage() {
  cat <<'USAGE'
Usage:
  bash deploy/tools/oeds_clean_install_from_git.sh [options]

Clones oeds-kit (crawler pack, scheduler/admin UI, post-processing and the
deployment) into the working directory and installs it with the Ansible
playbooks from deploy/playbooks. The repository is public; no GitHub account
or token is needed. Re-running the script on an installed host updates it
(the database is dumped to /home/oeds/backups/<timestamp> first).

Options:
  --reset                 Run a destructive OEDS uninstall before installing.
  --skip-host-prep        Skip OS/Docker host preparation.
  --load-sample-data      Load and verify a small real-data sample after install.
  --include-entsoe-fms    Include ENTSO-E FMS in the sample-data load.
  --crawler-env-file FILE Copy crawler secrets from FILE into the installed runtime.
  --repo-url URL          oeds-kit repository URL.
  --ref REF               oeds-kit branch, tag, or commit.
  --work-dir DIR          Working directory for the clone.
  --root DIR              Target OEDS root, default /open_energy_data_server.
  -h, --help              Show this help.

Environment:
  OEDS_GIT_TOKEN              Optional GitHub token, only for private forks.
  OEDS_GIT_USERNAME           GitHub username for the token. Defaults to "x-access-token".
  OEDS_CRAWLER_ENV_FILE       Optional crawler .env installed before services start.
  OEDS_BECOME_PASSWORD_FILE   Optional sudo password file for non-interactive Ansible runs.
  OEDS_ANSIBLE_INVENTORY_FILE Optional inventory path outside the working directory.

A token is passed to git through a temporary GIT_ASKPASS helper and is removed
when the script exits. It is not written to the repository or Ansible inventory.
USAGE
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset) RESET=true; shift ;;
    --skip-host-prep) SKIP_HOST_PREP=true; shift ;;
    --load-sample-data) LOAD_SAMPLE_DATA=true; shift ;;
    --include-entsoe-fms) INCLUDE_ENTSOE_FMS=true; shift ;;
    --crawler-env-file) CRAWLER_ENV_FILE=$2; shift 2 ;;
    --repo-url) REPO_URL=$2; shift 2 ;;
    --ref) REPO_REF=$2; shift 2 ;;
    --work-dir)
      WORK_DIR=$2
      CHECKOUT_DIR=$2/oeds-kit
      if [[ -z "${OEDS_ANSIBLE_INVENTORY_FILE:-}" ]]; then
        INVENTORY_FILE=$2/inventory.local.yml
      fi
      shift 2
      ;;
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
  *Username*) printf '%s\n' "${OEDS_GIT_USERNAME:-x-access-token}" ;;
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
  python3 -m venv "$HOME/.local/share/oeds-ansible"
  "$HOME/.local/share/oeds-ansible/bin/pip" install ansible
  export PATH="$HOME/.local/share/oeds-ansible/bin:$PATH"
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
if [[ -n "$CRAWLER_ENV_FILE" ]]; then
  CRAWLER_ENV_FILE=$(realpath -e "$CRAWLER_ENV_FILE")
  if [[ "$RESET" == true && "$CRAWLER_ENV_FILE" == "$(realpath -m "$OEDS_ROOT")/"* ]]; then
    echo 'Move the credential file outside the installation before using --reset.' >&2
    exit 2
  fi
fi
setup_git_auth
ensure_ansible
require_command ansible-galaxy

log "Cloning oeds-kit"
mkdir -p "$WORK_DIR"
if [[ ! -e "$CHECKOUT_DIR" ]]; then
  git clone "$REPO_URL" "$CHECKOUT_DIR"
elif [[ ! -d "$CHECKOUT_DIR/.git" ]] || [[ "$(git -C "$CHECKOUT_DIR" remote get-url origin)" != "$REPO_URL" ]] || [[ -n "$(git -C "$CHECKOUT_DIR" status --porcelain)" ]]; then
  echo 'Checkout already exists and is not a clean clone of the requested repository. Choose another --work-dir.' >&2
  exit 2
fi
git -C "$CHECKOUT_DIR" fetch --tags origin
if git -C "$CHECKOUT_DIR" show-ref --verify --quiet "refs/remotes/origin/$REPO_REF"; then
  git -C "$CHECKOUT_DIR" checkout --detach "origin/$REPO_REF"
else
  git -C "$CHECKOUT_DIR" checkout --detach "$REPO_REF"
fi

PLAYBOOK_DIR="$CHECKOUT_DIR/deploy/playbooks"
if [[ ! -d "$PLAYBOOK_DIR" ]]; then
  echo "playbook directory not found: $PLAYBOOK_DIR" >&2
  exit 1
fi

log "Preparing local Ansible inventory"
cat > "$INVENTORY_FILE" <<YAML
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
COMMON_ARGS=(-i "$INVENTORY_FILE" "${BECOME_ARGS[@]}")
# The checkout is transferred as a worktree archive, so a private clone made
# with OEDS_GIT_TOKEN needs no Git access from the playbooks.
MODULAR_EXTRA=(
  -e "oeds_root=$OEDS_ROOT"
  -e "oeds_repo_source_mode=local_worktree"
  -e "oeds_repo_local_src=$CHECKOUT_DIR"
  -e "oeds_enable_crawlers=true"
)
if [[ -n "$CRAWLER_ENV_FILE" ]]; then
  MODULAR_EXTRA+=(-e "oeds_crawler_env_file=$CRAWLER_ENV_FILE")
fi

if [[ "$SKIP_HOST_PREP" != "true" ]]; then
  log "Preparing host packages and Docker"
  ansible-playbook "${COMMON_ARGS[@]}" oeds-install-host-prep.yml
fi

if [[ "$RESET" == "true" ]]; then
  log "Running destructive OEDS reset"
  ansible-playbook "${COMMON_ARGS[@]}" oeds-uninstall.yml \
    -e "oeds_root=$OEDS_ROOT" \
    -e oeds_uninstall_remove_repo=true \
    -e oeds_uninstall_remove_runtime=true \
    -e oeds_uninstall_destroy_data=true \
    -e oeds_uninstall_confirm=DELETE_OEDS_DATA
fi

log "Installing modular OEDS"
ansible-playbook "${COMMON_ARGS[@]}" oeds-install-crawlers.yml "${MODULAR_EXTRA[@]}"

log "Verifying installed repository"
python3 "$OEDS_ROOT/repo/deploy/tools/verify_deployment.py"

log "Running final Ansible smoke test"
ansible-playbook "${COMMON_ARGS[@]}" oeds-smoke-test.yml \
  -e "oeds_root=$OEDS_ROOT" \
  -e oeds_expect_crawler_admin=true

if [[ "$LOAD_SAMPLE_DATA" == "true" ]]; then
  if [[ -z "$CRAWLER_ENV_FILE" ]]; then
    log "No crawler env file supplied; live token-backed crawlers may fail if runtime secrets are absent"
  fi
  log "Loading sample data into the installed OEDS database"
  SAMPLE_ARGS=()
  if [[ "$INCLUDE_ENTSOE_FMS" == "true" ]]; then
    SAMPLE_ARGS+=(--include-entsoe-fms)
  fi
  if [[ -n "${OEDS_BECOME_PASSWORD_FILE:-}" ]]; then
    sudo -S bash "$OEDS_ROOT/repo/deploy/tools/load_sample_data.sh" "${SAMPLE_ARGS[@]}" < "$OEDS_BECOME_PASSWORD_FILE"
  else
    sudo bash "$OEDS_ROOT/repo/deploy/tools/load_sample_data.sh" "${SAMPLE_ARGS[@]}"
  fi
fi

log "Clean Git-based modular install finished"

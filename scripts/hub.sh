#!/bin/bash
set -euo pipefail
repo_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
cd "$repo_root"
action=${1:-doctor}
shift || true
project=${ATUIN_SSH_PROJECT:-atuin-ssh}
compose=(docker compose --project-name "$project" --file "$repo_root/compose.yaml")
case "$action" in
    setup)
        public_key=${1:-$HOME/.ssh/id_ed25519.pub}
        [[ -f $public_key ]] || { echo 'Supply an existing SSH public key path.' >&2; exit 1; }
        grep -Eq '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-|sk-ssh-|sk-ecdsa-)' "$public_key" || { echo 'Expected SSH public key.' >&2; exit 1; }
        [[ -f .env ]] || cp .env.example .env
        [[ ! -e config/authorized_keys ]] || { echo 'config/authorized_keys exists; edit it to update keys.' >&2; exit 1; }
        cp -- "$public_key" config/authorized_keys
        echo 'Configured. Run docker compose build, docker compose up -d, then ssh -p 2222 hubuser@localhost.'
        ;;
    build) "${compose[@]}" build ;;
    start) "${compose[@]}" up --detach ;;
    stop) "${compose[@]}" stop ;;
    doctor) "${compose[@]}" exec --no-TTY hub /bin/bash -c 'exec runuser -u "$HUB_USER" -- env ATUIN_HOME=/state/atuin ATUIN_CONFIG_DIR=/state/atuin ATUIN_SSH_STATE_DIR=/state/bridge atuin-ssh doctor' ;;
    test|test-import)
        if [[ $action == test ]]; then
            docker compose --project-name atuin-ssh-test --file compose.test.yaml up --build --detach hub destination
            docker compose --project-name atuin-ssh-test --file compose.test.yaml run --rm client
            docker run --rm --network none --entrypoint python atuin-ssh:test /opt/atuin-ssh/privacy-probe.py
            docker run --rm --network none --entrypoint python atuin-ssh:test /opt/atuin-ssh/blesh-privacy-probe.py
        fi
        import_compose=(docker compose --project-name atuin-ssh-import-check --file compose.test.yaml)
        cleanup_import() { TEST_HUB_PORT=22224 "${import_compose[@]}" down; }
        trap cleanup_import EXIT
        TEST_HUB_PORT=22224 "${import_compose[@]}" up --no-build --detach hub destination
        TEST_HUB_PORT=22224 "${import_compose[@]}" exec --no-TTY destination /bin/bash -c 'install -m 0600 -o remote -g remote /dev/null /home/remote/import_history; touch /home/remote/.bash_profile; grep -qxF "export HISTFILE=/home/remote/import_history" /home/remote/.bash_profile || printf "\nexport HISTFILE=/home/remote/import_history\n" >> /home/remote/.bash_profile; chown remote:remote /home/remote/.bash_profile; chmod 0600 /home/remote/.bash_profile'
        TEST_HUB_PORT=22224 "${import_compose[@]}" run --rm import-client
        cleanup_import
        trap - EXIT
        ;;
    backup|restore)
        if [[ $action == restore ]]; then "${compose[@]}" create hub; fi
        container_id=$("${compose[@]}" ps --all --quiet hub)
        [[ -n $container_id ]] || { echo 'Create hub first.' >&2; exit 1; }
        state_volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Destination "/state"}}{{.Name}}{{end}}{{end}}' "$container_id")
        home_volume=$(docker inspect --format '{{range .Mounts}}{{if eq .Type "volume"}}{{if eq (index (split .Destination "/") 1) "home"}}{{.Name}}{{end}}{{end}}{{end}}' "$container_id")
        image_id=$(docker inspect --format '{{.Image}}' "$container_id")
        running=$(docker inspect --format '{{.State.Running}}' "$container_id")
        [[ -n $state_volume && -n $home_volume ]] || { echo 'Default named volumes required.' >&2; exit 1; }
        if [[ $action == backup ]]; then
            backup_dir=${1:-"$repo_root/backups/$(date -u +%Y%m%d-%H%M%S)"}
            mkdir -p -- "$(dirname -- "$backup_dir")"
            mkdir -- "$backup_dir"
            backup_dir=$(cd -- "$backup_dir" && pwd)
            trap 'if [[ $running == true ]]; then "${compose[@]}" start hub; fi' EXIT
            "${compose[@]}" stop hub
            docker run --rm --entrypoint /bin/tar --mount "type=volume,src=$state_volume,dst=/snapshot/state,readonly" --mount "type=volume,src=$home_volume,dst=/snapshot/home,readonly" --mount "type=bind,src=$backup_dir,dst=/backup" "$image_id" --numeric-owner -czf /backup/hub.tar.gz -C /snapshot state home
            printf '{"format":1,"consistent":"all hub writers stopped","image_id":"%s","includes":["state","home"]}\n' "$image_id" > "$backup_dir/manifest.json"
            sha256sum "$backup_dir/hub.tar.gz" | sed 's| .*|  hub.tar.gz|' > "$backup_dir/hub.tar.gz.sha256"
            echo "Complete consistent backup: $backup_dir"
        else
            [[ $running == false ]] || { echo 'Restore requires stopped fresh hub.' >&2; exit 1; }
            archive=$(realpath -- "${1:?Supply backup archive path}")
            docker run --rm --entrypoint /bin/bash --mount "type=volume,src=$state_volume,dst=/restore/state" --mount "type=volume,src=$home_volume,dst=/restore/home" --mount "type=bind,src=$(dirname -- "$archive"),dst=/backup,readonly" "$image_id" /usr/share/atuin-ssh/restore.sh "/backup/$(basename -- "$archive")"
            echo 'Restored stopped hub. Keep original stopped when moving writer identity.'
        fi
        ;;
    *) echo 'Usage: hub.sh {setup [public-key]|build|start|stop|doctor|test|test-import|backup [directory]|restore archive}' >&2; exit 2 ;;
esac

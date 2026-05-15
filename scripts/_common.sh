#!/bin/bash
# Common functions shared across install/upgrade/remove/backup/restore scripts.

pkg_dependencies="python3 python3-pip python3-venv"

# Set up a dedicated Python venv inside $install_dir/venv and install requirements.
setup_python_venv() {
  ynh_exec_as_app python3 -m venv "$install_dir/venv"
  ynh_exec_as_app "$install_dir/venv/bin/pip" install --upgrade pip wheel
  ynh_exec_as_app "$install_dir/venv/bin/pip" install -r "$install_dir/sources/requirements.txt"
}

# Ensure rclone RC API is reachable before we declare the app installed.
check_rclone_rc() {
  local url="${1:-http://127.0.0.1:5572}"
  if ! curl -sf -X POST "$url/rc/noop" >/dev/null; then
    ynh_print_warn --message="rclone RC API not reachable at $url. The dashboard will still install but will show a 'reconnecting' state until rclone is reachable. Make sure rclone is running with --rc --rc-addr=$(echo $url | sed 's#http://##')."
  fi
}

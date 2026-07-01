# Live Warden terminal surface (tool status + breaking diff + call log).
# Runs with a TTY so the rich table refreshes in place. Ctrl+C to exit.
docker compose run --rm -e WARDEN_URL=http://warden:8080 warden python -m warden.cli --watch

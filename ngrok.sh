#!/bin/bash

PORT="8765"
LOG_FILE="ngrok.log"

install_ngrok() {
    if ! command -v ngrok >/dev/null 2>&1; then
        echo "ngrok not found. Installing..."

        sudo snap install ngrok

        if ! command -v ngrok >/dev/null 2>&1; then
            echo "Failed to install ngrok."
            exit 1
        fi

        echo "✓ ngrok installed successfully"
    fi
}

start_ngrok() {
    install_ngrok

    read -p "Enter ngrok auth token: " NGROK_TOKEN
    read -p "Enter ngrok domain (e.g. clawdia-one18media.ngrok.app): " NGROK_DOMAIN

    ngrok config add-authtoken "$NGROK_TOKEN"

    echo "Starting ngrok..."

    nohup ngrok http --url="$NGROK_DOMAIN" "$PORT" > "$LOG_FILE" 2>&1 &

    sleep 5

    if pgrep -f "ngrok http" >/dev/null; then
        echo "✓ ngrok started successfully"
        echo "URL: https://$NGROK_DOMAIN"
    else
        echo "✗ ngrok failed to start"
        echo "Logs:"
        cat "$LOG_FILE"
    fi
}

stop_ngrok() {
    pkill -f "ngrok http"
    echo "✓ ngrok stopped"
}

status_ngrok() {
    if pgrep -f "ngrok http" >/dev/null; then
        echo "✓ ngrok is running"
    else
        echo "✗ ngrok is not running"
    fi
}

logs_ngrok() {
    tail -f "$LOG_FILE"
}

case "$1" in
    start)
        start_ngrok
        ;;
    stop)
        stop_ngrok
        ;;
    status)
        status_ngrok
        ;;
    logs)
        logs_ngrok
        ;;
    restart)
        stop_ngrok
        sleep 2
        start_ngrok
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status|logs}"
        ;;
esac

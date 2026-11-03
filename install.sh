#!/usr/bin/env bash
# Установка CMF Buds для текущего пользователя (без sudo).
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
APP_DIR="$HOME/.local/share/cmf-buds"
DESKTOP="$HOME/.local/share/applications/cmf-buds.desktop"

if ! python3 -c "import gi; gi.require_version('Gtk','4.0'); gi.require_version('Adw','1'); from gi.repository import Adw; assert (Adw.get_major_version(), Adw.get_minor_version()) >= (1, 7)" 2>/dev/null; then
    echo "Нужны Python GTK4 и libadwaita 1.7 или новее. Смотрите README, раздел «Шаг 1»." >&2
    exit 1
fi

mkdir -p "$APP_DIR" "$(dirname "$DESKTOP")"
install -m 755 "$DIR/cmf_buds.py" "$APP_DIR/cmf_buds.py"

cat > "$DESKTOP" <<EOF
[Desktop Entry]
Type=Application
Name=CMF Buds
Comment=Настройки наушников CMF Buds
Exec=python3 $APP_DIR/cmf_buds.py
Icon=audio-headphones
Categories=AudioVideo;Settings;
EOF

echo "Готово. Откройте «CMF Buds» в меню приложений."

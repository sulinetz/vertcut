#!/usr/bin/env bash
# Сборка дистрибутива: DMG (если разрешает система) + ZIP (всегда)
set -euo pipefail
cd "$(dirname "$0")"

APP="dist/ViralCut.app"
[ -d "$APP" ] || { echo "Сначала соберите приложение: ./build_app.sh"; exit 1; }

# ZIP — универсальный вариант, сохраняет подпись и права
ditto -c -k --sequesterRsrc --keepParent "$APP" "dist/ViralCut-1.0.0-macOS-arm64.zip"
du -sh "dist/ViralCut-1.0.0-macOS-arm64.zip"

# DMG — красивее, но требует прав на создание образов
STAGE="build/dmg"
rm -rf "$STAGE"
mkdir -p "$STAGE"
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"

if hdiutil create -volname "ViralCut" -srcfolder "$STAGE" -ov -format UDZO \
    "dist/ViralCut-1.0.0.dmg" >/dev/null 2>&1; then
  echo "DMG: dist/ViralCut-1.0.0.dmg"
else
  echo "DMG создать не удалось (нет прав) — используйте ZIP."
fi
rm -rf "$STAGE"

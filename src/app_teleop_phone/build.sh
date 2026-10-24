#!/usr/bin/env bash
# Build the Android app (flutter/) in a container and put the APK in www/,
# so orintwo serves it at http://10.42.0.1:8080/rover-teleop.apk for the phone to install.
# Memory-capped: the laptop has 15 GB (CLAUDE.md). The Gradle/pub caches and the debug
# signing key live in the navws_flutter_cache volume; keeping that key is what lets a
# new APK install over the old one.
set -euo pipefail
cd "$(dirname "$0")"

docker build -q -t navws/flutter-build builder >/dev/null
docker volume create navws_flutter_cache >/dev/null
docker run --rm -v navws_flutter_cache:/cache navws/flutter-build \
  bash -c "mkdir -p /cache/home && chown -R $(id -u):$(id -g) /cache"

docker run --rm --memory 7g --memory-swap 7g --cpus 4 \
  -u "$(id -u):$(id -g)" -e HOME=/cache/home \
  -v "$PWD/flutter:/src" -v navws_flutter_cache:/cache \
  navws/flutter-build \
  bash -c 'flutter pub get && flutter build apk --release --target-platform android-arm64'

cp flutter/build/app/outputs/flutter-apk/app-release.apk www/rover-teleop.apk
ls -lh www/rover-teleop.apk

# Build environment for the Flutter teleop app: Flutter 3.24.5 + Android SDK 34, JDK 17.
# build-tools 33.0.1 and NDK 23.1 are what Flutter 3.24's Android template asks for.
# Used by ../build.sh; nothing Flutter or Android is installed on the host.
FROM eclipse-temurin:17-jdk-jammy

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl unzip xz-utils ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV ANDROID_HOME=/opt/android ANDROID_SDK_ROOT=/opt/android
RUN curl -fsSL https://dl.google.com/android/repository/commandlinetools-linux-11076708_latest.zip -o /tmp/c.zip \
    && mkdir -p $ANDROID_HOME/cmdline-tools \
    && unzip -q /tmp/c.zip -d $ANDROID_HOME/cmdline-tools \
    && mv $ANDROID_HOME/cmdline-tools/cmdline-tools $ANDROID_HOME/cmdline-tools/latest \
    && rm /tmp/c.zip \
    && yes | $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager --licenses >/dev/null \
    && $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager \
       "platforms;android-34" "build-tools;34.0.0" "build-tools;33.0.1" "platform-tools" \
       "ndk;23.1.7779620" \
    && chmod -R a+rwX $ANDROID_HOME

RUN curl -fsSL https://storage.googleapis.com/flutter_infra_release/releases/stable/linux/flutter_linux_3.24.5-stable.tar.xz \
    | tar -xJ -C /opt \
    && git config --system --add safe.directory /opt/flutter \
    && git config --system --add safe.directory '*'
ENV PATH=/opt/flutter/bin:/opt/flutter/bin/cache/dart-sdk/bin:$PATH \
    PUB_CACHE=/cache/pub GRADLE_USER_HOME=/cache/gradle
RUN flutter config --no-analytics --android-sdk $ANDROID_HOME && flutter precache --android \
    && chmod -R a+rwX /opt/flutter
# Flutter 3.24's Android Gradle plugin also asks for build-tools 33.0.1; writable so a
# component it wants later can install at build time instead of failing
RUN $ANDROID_HOME/cmdline-tools/latest/bin/sdkmanager "build-tools;33.0.1" >/dev/null \
    && chmod -R a+rwX $ANDROID_HOME
WORKDIR /src

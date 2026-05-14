[app]

# (str) Title of your application
title = Outline VPN IP Rotator

# (str) Package name
package.name = outlinevpn

# (str) Package domain (needed for android/ios packaging)
package.domain = org.outlinevpn

# (str) Source code where the main.py live
source.dir = .

# (list) Source files to include (let empty to include all the files)
source.include_exts = py,png,jpg,kv,atlas,ttf,json

# (list) List of inclusions using pattern matching
#source.include_patterns = assets/*,images/*.png

# (list) Source files to exclude (let empty to not exclude anything)
source.exclude_exts = spec,md

# (list) List of directory to exclude (let empty to not exclude anything)
source.exclude_dirs = tests, bin, .buildozer, .github, __pycache__

# (str) Application versioning (method 1)
version = 1.1.0

# (list) Application requirements
# 원본 앱 + boto3, requests, urllib3, certifi, charset-normalizer, idna 등 의존성
requirements = python3,kivy==2.3.0,certifi,charset-normalizer,idna,urllib3,requests,boto3,botocore,jmespath,python-dateutil,s3transfer,six

# (str) Presplash of the application
presplash.filename = %(source.dir)s/NotoSansKR.ttf

# (str) Icon of the application
#icon.filename = %(source.dir)s/icon.png

# (str) Supported orientation (one of landscape, sensorLandscape, portrait or all)
orientation = portrait

# (bool) Indicate if the application should be fullscreen or not
fullscreen = 0

# (list) Permissions
android.permissions = INTERNET, ACCESS_NETWORK_STATE, WAKE_LOCK

# (list) features (adds uses-feature -tags to manifest)
android.features = android.hardware.wifi

# (int) Target Android API, should be as high as possible.
android.api = 33

# (int) Minimum API your APK / AAB will support.
android.minapi = 24

# (int) Android SDK version to use
android.ndk = 25b

# (str) Android NDK API to use. This is the minimum API your app will support, it should usually match android.minapi.
android.ndk_api = 24

# (bool) If True, then automatically accept SDK license
android.accept_sdk_license = True

# (list) The Android archs to build for, choices: armeabi-v7a, arm64-v8a, x86, x86_64
# Note: must be arch=armeabi-v7a or arch=arm64-v8a (or both, comma separated) — multi-arch APK
android.archs = arm64-v8a, armeabi-v7a

# (bool) enables Android auto backup feature (Android API >=23)
android.allow_backup = True

# (str) Format used to package the app for release mode (aab or apk or aar).
android.release_artifact = apk

# (str) Format used to package the app for debug mode (apk or aar).
android.debug_artifact = apk


[buildozer]

# (int) Log level (0 = error only, 1 = info, 2 = debug (with command output))
log_level = 2

# (int) Display warning if buildozer is run as root (0 = False, 1 = True)
warn_on_root = 1

# Kärcher App APK Audit

**App version:** KHR 1.4.32 (APKPure, `tencentyyb` distribution flavor)
**Audit date:** 2026-05-10
**Method:** Static analysis of decompiled APK via jadx

---

## Camera and image data

The RCV-5 has two physical cameras used for AI obstacle detection. Kärcher claims images never leave the robot.

**Finding: claim is consistent with the app code.**

- The app does not use the Android Camera API for any robot-monitoring purpose.
- No HTTP endpoints accept binary/multipart image data.
- No MQTT topics carry image or video streams. All 10 MQTT topics are property updates, commands, and OTA only.
- No cloud vision APIs are integrated (Google Vision, AWS Rekognition, Alibaba Vision, etc.).
- The AI feature is controlled by a single MQTT property flag (`ai_recognize: 0|1`) sent to the robot. The app toggles it; no data comes back.
- The camera-related UI assets (`picture_ic_camera`, `picture_icon_camera`) belong to the voluntary feedback form, where users can optionally attach photos to a bug report.

**Open question not resolvable from the APK:** what exactly is in the `record_uploads` payload at the firmware level. If the robot firmware includes AI detection metadata (obstacle counts, categories) in cleaning records, those would be uploaded when `record_uploads` is enabled. This requires a live network capture to verify, not APK analysis.

---

## Third-party SDKs

| SDK | Vendor | Purpose |
|---|---|---|
| Firebase Analytics + Crashlytics | Google | In-app event tracking, crash reporting |
| UMeng + UMCrash | Alibaba | Analytics, crash/ANR/memory reporting |
| MMKV | Tencent | Local encrypted key-value store — no network component |

The `tencentyyb` flavor name is a distribution channel label (Tencent's app store), not a Tencent analytics integration.

---

## Data transmission — what is always-on

These are active in the release build with no user consent gate and no opt-out:

### Firebase Analytics
- Initialized unconditionally in `IotApp.onCreate()` before login.
- Device model set as a permanent default event parameter.
- `setUserId()` called after login — user ID tagged to all subsequent events.
- 44+ event types tracked: MQTT failures, map load errors, Wi-Fi config steps, HTTP errors, OTA events.
- HTTP error events fire from `ResponseInterceptor` before authentication.

### UMeng Analytics + UMCrash
- Initialized unconditionally in `MainApp.onCreate()`.
- All monitoring flags hardcoded `true`: Java crashes, native crashes, ANRs, memory dumps, network monitoring, app launch tracking.

### HTTP request/response logging
- `ResponseInterceptor` is registered with no `BuildConfig.DEBUG` guard — active in the release build.
- Logs full request URLs and response bodies (up to 10,000 chars) to local disk.
- On errors, reports to Firebase including full URLs and error codes.

---

## Data transmission — on by default, user can disable

Both controlled via robot MQTT privacy flags. Settings UI toggles exist in the app.

| Flag | Default | What it controls |
|---|---|---|
| `map_uploads` | Enabled | Floor map cloud backup (AWS S3 or Alibaba OSS depending on region) |
| `record_uploads` | Enabled | Cleaning records uploaded to Kärcher/3iRobotix cloud |

---

## Data transmission — opt-in only

| Feature | Trigger |
|---|---|
| App log uploads | Explicit user consent dialog, shown only after a crash |
| Feedback photos | Manual feedback form; user selects and submits |

---

## What each log upload contains

**Runtime/crash log bundle** (uploaded to `/log-service/log/app/report/runtime`):
- App version, Android version, device model
- User ID and username
- Robot serial number (`sn`)
- Tenant/organization ID
- Log content (text), timestamp, geographic zone

**Device log bundle** (uploaded to `sweeper-report/app/log`):
- Same fields plus serialized MQTT message history

No image or binary data in any log bundle.

---

## Cloud endpoints

Primary API servers (region-selected at account setup):
```
https://cn-appaiot.kahechina.com      (China)
https://eu-appaiot.3irobotix.net      (Europe)
https://us-appaiot.3irobotix.net      (USA)
https://ru-appaiot.3irobotix.net      (Russia)
https://sg-appaiot.3irobotix.net      (Singapore)
```

Storage (maps, logs):
- AWS S3 via `/storage-management/storage/aws/getAccessUrl`
- Alibaba OSS via `/storage-management/storage/oss/getAccessUrl`

Privacy policy: `https://privacy.3irobotix.net/RCV-home/CRT350privacy.html`

---

## GDPR / consent posture

Firebase and UMeng initialise and transmit data unconditionally from first app launch, before login, with no consent dialog and no in-app opt-out. This is not consistent with GDPR consent-first requirements.

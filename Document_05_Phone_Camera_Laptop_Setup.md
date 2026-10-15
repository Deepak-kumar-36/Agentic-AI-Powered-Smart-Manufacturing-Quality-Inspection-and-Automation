# Document 05 — Phone Camera & Laptop Setup
**Project:** Agentic AI Smart Manufacturing Quality Inspection & Automation Platform  
**Document version:** 1.0  
**Date:** 15 October 2026  
**Status:** Implementation guide — phone/device compatibility must be verified  
**Owner:** Edge Runtime / Computer Vision Engineering  
**Related documents:** Documents 01–04; Production-Grade PRD v3.0

---

## 1. Objective

Connect a borrowed phone camera to the Linux laptop/PC that runs local inference, then verify the complete path from camera frame to the existing model adapter. The first milestone is a stable, visible, **read-only/shadow-mode** camera feed. No actuator may be triggered by this document's setup steps.

The object/category is still undecided. Therefore, camera distance, field of view, resolution, and lighting below are starting points. Final geometry must be set after choosing an object and inspecting the model's input requirements.

### Done means

- The laptop can identify the camera source consistently after reconnect/reboot.
- A live frame can be viewed and captured to disk without cropping away the object.
- The running application can read the frames through a documented camera adapter.
- Timestamps, image dimensions, frame read failures, and capture latency can be logged.
- A known-good test image produces a model result in the same local inference path used later for conveyor inspections.
- The feed remains local; the initial workflow does not require a cloud service.
- Camera/model errors are visibly represented as errors or `UNVERIFIED`, never silently converted into `PASS`.

## 2. Recommended connection strategy

Use the first applicable option that works reliably on the available phone:

1. **Native Android USB webcam mode** — preferred if the phone supports the device-as-webcam feature and exposes itself as a USB Video Class (UVC) camera.
2. **DroidCam OBS plugin over USB** — fallback for supported Android phones; the plugin exposes the feed through OBS, and a virtual camera can be used where a V4L2 loopback device is available.
3. **DroidCam OBS over Wi-Fi or another reviewed IP-camera source** — useful if USB is unavailable. Keep the stream on the local network and test packet loss/latency.
4. **Temporary image upload** — for model smoke tests only; it does not prove live camera integration.

Android's USB webcam support is available in Android Open Source Project for devices running Android 14 QPR1 or higher, but availability still depends on the specific device/build and vendor implementation. Check the actual phone rather than assuming the feature exists.

### 2.1 Quick decision table

| Available phone capability | Start with | Notes |
|---|---|---|
| Android shows “Webcam” after connecting USB | Native USB webcam mode | Simplest path if the phone appears as a UVC camera on Linux |
| Android phone, no native webcam option | DroidCam OBS over USB | Requires app/plugin setup and USB debugging authorization |
| USB data connection unreliable or unavailable | DroidCam OBS over Wi-Fi | Same local network; monitor jitter and disconnects |
| iPhone available instead | Check the current DroidCam OBS iOS instructions or a compatible UVC workflow | Do not assume Android instructions apply |
| No streaming path works yet | Save sample frames/upload for smoke test | Temporary only; live capture acceptance remains blocked |

## 3. Laptop and OS baseline

The project developer environment is expected to be Linux/Arch Linux with GNOME, but verify the actual target machine before installing anything.

Record this baseline:

```bash
date -Is
uname -a
cat /etc/os-release
python --version
git rev-parse --short HEAD 2>/dev/null || true
```

Useful tools on Arch Linux:

```bash
sudo pacman -S --needed v4l-utils ffmpeg
```

`v4l-utils` provides tools to inspect Video4Linux devices, and `ffmpeg` includes utilities for probing and viewing camera streams. Install only what is needed for this step; do not modify the production application's dependencies just to make a camera preview work.

To see available camera devices:

```bash
v4l2-ctl --list-devices
ls -l /dev/video*
```

A `/dev/videoN` device can be a camera or a virtual/loopback device. Confirm its identity and supported formats rather than assuming `/dev/video0` is always the phone.

If no V4L2 device appears but an app exposes a network stream, document the stream type/URL privately in local configuration. Do **not** commit phone IP addresses, access tokens, credentials, or private stream URLs to Git.

## 4. Option A — Native Android USB webcam

Use this when the phone itself offers a webcam function over USB.

1. Use a known-good USB **data** cable, not a charge-only cable.
2. Unlock the phone and connect it to the laptop.
3. If the USB notification allows it, select the device's **Webcam** mode.
4. Grant the camera/USB permission if prompted.
5. On the laptop run:

   ```bash
   v4l2-ctl --list-devices
   ```

6. Identify the phone-associated device and inspect supported formats:

   ```bash
   v4l2-ctl -d /dev/videoN --all
   v4l2-ctl -d /dev/videoN --list-formats-ext
   ```

   Replace `/dev/videoN` with the confirmed device path.

7. Preview the camera with an available tool, for example:

   ```bash
   ffplay -f video4linux2 -i /dev/videoN
   ```

   If preview fails, first check the device path, supported formats, permissions, and whether another application has the camera open. The exact `ffplay` format options may need adjustment for the reported camera format.

8. Move the phone to the back camera if the phone's webcam UI provides that option. Verify the preview uses the intended lens and orientation.

**Exit condition:** the feed is visible, a frame can be captured, and Linux sees the camera consistently through unplug/replug. If native mode is absent, move to Option B rather than losing time trying to enable an unsupported feature.

## 5. Option B — DroidCam OBS over USB on Arch Linux

This option uses DroidCam on the phone and the DroidCam OBS plugin on the laptop. Current vendor instructions describe an OBS workflow and provide an Arch-based installation route via AUR; AUR packaging is community-maintained, so review the package recipe and current vendor instructions before installing.

1. Install required tools:

   ```bash
   sudo pacman -S --needed obs-studio android-tools v4l-utils ffmpeg
   ```

2. Install the DroidCam OBS plugin using the current official vendor guide. On Arch-based systems, the vendor-linked guidance lists `droidcam-obs-plugin` as an AUR package. If using `yay`, review the PKGBUILD before confirming:

   ```bash
   yay -Si droidcam-obs-plugin
   yay -S droidcam-obs-plugin
   ```

   If the package is unavailable or its dependencies conflict, stop and follow the currently published plugin instructions instead of installing random mirrors/builds.

3. Install/open the DroidCam app on the borrowed phone from a trusted app source.
4. On the phone, find Developer Options. Enable **USB debugging** only for this setup session. Android menu names vary by manufacturer.
5. Connect the phone with a data cable. Confirm the laptop can see the device:

   ```bash
   adb devices
   ```

6. On the phone, approve the USB debugging prompt for this laptop only if the owner consents. Do not accept unknown computers. If the device is not listed, check cable/data mode, USB permissions, and the `android-tools` installation.
7. Open OBS Studio, add a DroidCam source, refresh the device list, select the connected phone and activate it. Exact UI labels can change with plugin versions.
8. Confirm the video preview in OBS. Start the virtual camera only if the application needs a V4L2 virtual device.
9. Check device visibility:

   ```bash
   v4l2-ctl --list-devices
   ls -l /dev/video*
   ```

10. Test the virtual camera with the target application or a preview tool. Keep the source set to **video only** unless audio is explicitly needed; this project does not require audio for visual inspection.

**Important:** the native camera device and an OBS virtual camera are different sources. Record which source the model application actually reads. Do not assume the physical phone is `/dev/video0` simply because OBS displays it.

### USB debugging cleanup

At the end of the session:
- Stop OBS and disconnect the phone.
- Disable USB debugging on the borrowed phone unless the owner explicitly wants it kept enabled.
- Revoke this laptop's debugging authorization on the phone if appropriate.
- Remove any temporary camera credentials and delete accidental test images containing personal content.
- Return the phone with its settings restored to the owner's preferred state.

## 6. Option C — DroidCam OBS over Wi-Fi

Use this if the USB workflow is not available or is less stable.

1. Connect laptop and phone to the **same trusted local network**.
2. Open DroidCam on the phone and find its displayed connection address.
3. Open OBS on the laptop and add a DroidCam source. Select the Wi-Fi option and enter or discover the address shown by the phone app.
4. Confirm the video preview.
5. Start a virtual camera only if the application requires a V4L2 source. If the app can read a supported stream directly, prefer a proper camera-adapter implementation and keep stream parsing isolated from the UI.
6. Begin at 1280×720 / 30 FPS. If stable, test higher quality/resolution while measuring dropped frames, CPU use and end-to-end latency.
7. Keep phone and laptop on the same local network. Avoid exposing the stream to the public internet or forwarding camera ports through the router.

Wi-Fi can introduce jitter, packet loss, and discovery problems. It is suitable for a supervised prototype only after repeated-run testing. A dedicated local router/access point is preferable to a crowded guest network when available.

## 7. Camera positioning and lighting

Because the object is not selected, use the following as a temporary calibration setup:

- Mount the phone securely overhead or at a repeatable fixed angle.
- Start around 35–50 cm from the inspection plane, then adjust so the entire candidate object and a small margin fit in frame at useful resolution.
- Prefer the rear 1× main camera; avoid ultra-wide distortion, portrait mode, digital zoom, beauty filters and scene effects.
- Keep the camera perpendicular to the surface when the relevant defect is on that surface. Use a different angle only if the inspection requires it and the model/data match that view.
- Use stable diffuse lighting. Avoid direct specular glare, flickering lights, changing sunlight and hard moving shadows.
- Use a plain, consistent background that contrasts with the object without creating unsupported visual cues.
- Secure the mount so touching the table or belt does not shift the view.
- Mark the object region, camera mount position, light position and phone orientation so the setup can be recreated.
- Keep the phone powered for long sessions, allow ventilation, and watch for heat-induced camera throttling or focus changes.

These dimensions are starting points only. After product selection, document working distance, visible field of view, minimum defect size, pixel coverage per feature, lighting type, exposure and fixed pose. The final camera profile is part of the model/policy qualification.

### 7.1 Lock the image where possible

If the phone app supports it, lock focus/exposure/white balance after the scene is set. If not, check that the camera does not repeatedly refocus or change brightness when an object enters the scene. Record the limitations. Avoid manually enhancing captured images between the camera and inference pipeline.

## 8. From camera device to application adapter

Do not scatter camera-opening code through UI components or model code. Create one interface that can be implemented by each transport:

```python
from dataclasses import dataclass
from typing import Protocol
import numpy as np

@dataclass
class CameraFrame:
    frame: np.ndarray
    captured_at_utc: str
    camera_id: str
    sequence_no: int
    width: int
    height: int

class CameraSource(Protocol):
    def open(self) -> None: ...
    def read(self, timeout_ms: int) -> CameraFrame | None: ...
    def health(self) -> dict: ...
    def close(self) -> None: ...
```

This is an interface example, not existing code. Adapt it to the actual framework after the repository audit. A returned `None` or typed capture error means there is no usable frame; it must not be replaced by a stale frame without explicitly recording that fact.

### 8.1 Capture worker responsibilities

- Own one camera connection and reconnect with bounded backoff.
- Apply a read timeout and record stream/camera health.
- Assign a monotonically increasing sequence number for each accepted frame.
- Preserve capture timestamp and processing timestamp separately.
- Validate dimensions, channel order, data type and content before inference.
- Bound frame buffers; do not allow a slow model to create an unbounded queue of stale frames.
- Record dropped frames and the reason.
- Save a raw selected frame and hash when the evidence-retention policy requires it.
- Distinguish “no object present”, “camera disconnected”, “frame unreadable” and “image quality failed”.
- Never let UI lag block capture-state tracking.

### 8.2 Don't infer from stale frames

For a live inspection, the chosen frame must be within a configured age limit and associated with the active part/trigger where applicable. If the buffer contains only stale frames, report capture failure or `UNVERIFIED`; do not reuse a previous part's frame.

## 9. Frame-quality and camera acceptance tests

Before allowing any verdict to drive a physical action, pass this camera-only test matrix:

| Test | Method | Expected result |
|---|---|---|
| Device discovery | Unplug/replug five times | Same documented source is identified each time, or recovery error is visible |
| Resolution | Read multiple frames and inspect dimensions | Actual dimensions match the selected profile |
| Frame freshness | Log capture timestamps over a one-minute run | No silent replay of old frames |
| Focus | Capture object/detail at near/far allowed positions | Required features are reasonably sharp under the documented setup |
| Lighting | Repeat capture with intended lights and normal room variations | No unrecorded automatic exposure changes that invalidate the profile |
| Background | Capture empty belt, normal object, test anomalous object | Background/fixture doesn't dominate the scoring unexpectedly |
| Dropped frames | Run preview and inference together | Queue is bounded; missed frames are counted; no silent stale decision |
| App restart | Close and reopen camera client | Application detects reconnect and shows healthy/unhealthy state correctly |
| Laptop load | Run camera plus model inference for a sustained session | No runaway memory growth; latency and disconnects recorded |
| Network disconnect (Wi-Fi mode) | Temporarily disconnect the phone/AP path | Clear unavailable state; reconnect recovers without reusing stale frames |
| Privacy/locality | Inspect application connections and logs | No unexpected upload; no personal material saved without permission |
| Error mapping | Disable camera during a test inspection | No implicit PASS; issue reaches a visible error/UNVERIFIED state |

Repeat the core camera tests across at least three independent start/stop sessions and keep the results with the model/dataset qualification artifacts.

## 10. Measuring camera-to-model latency

Measure separate stages. Use monotonic time for durations and UTC timestamps for records.

- `t0`: frame made available by camera source.
- `t1`: frame validated/selected.
- `t2`: preprocessing complete.
- `t3`: model inference complete.
- `t4`: heatmap/result formatting complete.
- `t5`: decision record durably committed.

Report capture-to-result (`t4 - t0`) and capture-to-durable-decision (`t5 - t0`) separately. Do not describe one as the other.

For each test run, save:
- camera source identifier and resolution/FPS;
- count of candidate, accepted, dropped and invalid frames;
- warm-up count and measured inspection count;
- p50/p95/p99 latency, not just a single best run;
- CPU/RAM and GPU/VRAM usage where available;
- model digest, preprocessing version and policy version;
- error/reconnect count and environmental notes.

For the tabletop prototype, stop the belt during capture/inference as specified in Document 01. Do not choose conveyor speed until the whole capture-to-decision path is measured.

## 11. Security, privacy and local operation

- Obtain the phone owner's permission before installing an app, enabling debugging, capturing images or changing settings.
- Do not copy photos, contacts, messages or other personal content from the borrowed phone.
- Use a trusted local network; never expose a raw camera feed on a public interface.
- Do not commit Wi-Fi credentials, camera stream URLs containing tokens, device identifiers or personal images to source control.
- Disable USB debugging and remove temporary access after testing.
- Keep the initial image flow and inference local. Cloud sync and remote monitoring are out of scope for this setup milestone.
- Limit raw image retention; keep only approved test evidence. Avoid images that accidentally include people, documents or sensitive surroundings.
- Logs should store error codes and technical metadata instead of embedding full image payloads.

## 12. Troubleshooting

| Symptom | Checks | Next action |
|---|---|---|
| No `/dev/videoN` appears | Cable type, Android webcam mode, OBS virtual camera start, USB permissions | Recheck native UVC support; if unsupported, try DroidCam OBS path |
| Phone appears in `adb` but not OBS | USB debugging approval, plugin version, OBS restart, plugin architecture/FFmpeg compatibility | Follow the current plugin guide; inspect OBS logs |
| OBS has a picture but the app cannot open camera | Virtual camera not started, wrong `/dev/videoN`, device busy or permissions | List V4L2 devices; test selected device; close conflicting preview app |
| Black image | Lens selected, phone screen/lock state, app permissions, USB mode, another client owns camera | Reopen source; verify preview; keep the phone unlocked during initial validation |
| Video is choppy on Wi-Fi | Signal congestion, bitrate, resolution/FPS, phone heat | Try 720p/30 FPS, improve access-point proximity, then repeat the latency test |
| Camera disconnects during long run | Cable/connector, power saving, overheating, network roaming | Secure cable, keep powered/ventilated, disable aggressive app sleep only with owner approval |
| Frame is rotated/cropped | Orientation metadata, application transform, phone mount angle | Standardize orientation in the adapter and test; do not manually edit source images |
| Object looks different across captures | Auto exposure/focus, variable light, mount movement | Stabilize camera/lighting, lock controls where possible and requalify |
| Model score changes unexpectedly | Wrong resolution/preprocessing, old frame, different camera/lens, lighting drift | Compare input hashes and pipeline settings; do not change threshold as the first response |

## 13. Camera configuration record

Save a version-controlled, non-secret configuration similar to this:

```yaml
camera_profile_id: phone_overhead_v1
source_type: v4l2
device_path: /dev/videoN  # local machine setting; verify after replug
requested_width: 1280
requested_height: 720
requested_fps: 30
color_order: BGR  # only if confirmed by the actual adapter
orientation: landscape
roi: null          # define only after object/category is selected
max_frame_age_ms: 500
read_timeout_ms: 1000
queue_capacity: 2
reconnect_backoff_ms: [250, 500, 1000, 2000, 5000]
audio_enabled: false
save_raw_evidence: true  # subject to retention/consent policy
```

This is an illustrative starting configuration. Requested resolution/FPS and the example frame-age limits must be compared with actual device behavior and the model latency. Do not set `color_order`, ROI, or frame-age policy without verifying the real implementation and use case. Keep machine-specific device paths outside shared configuration if they differ by machine.

## 14. Completion record

Fill this before moving on:

| Field | Record |
|---|---|
| Phone model / OS version | To record |
| Connection option | Native USB / DroidCam USB / Wi-Fi / temporary upload |
| Laptop OS / kernel | To record |
| Camera source ID / device path | To record |
| Resolution / actual FPS | To measure |
| Camera-only test run ID | To record |
| Known limitations | To record |
| Model integration status | Not verified until tested with actual application |
| Cloud dependency | None for initial local path |
| Physical actuation | Disabled during camera qualification |
| Result | `PASS`, `FAIL`, `BLOCKED`, or `NOT_RUN` |

## 15. References

1. Android Open Source Project, “Use a device as a webcam”: https://source.android.com/docs/core/camera/webcam
2. DroidCam OBS official site: https://www.droidcam.app/obs/
3. DroidCam OBS usage and Android USB setup: https://www.droidcam.app/obs/usage/
4. DroidCam OBS Linux releases and Arch/AUR guidance: https://github.com/dev47apps/droidcam-obs-plugin/wiki/Linux-Releases
5. DroidCam Linux client repository: https://github.com/dev47apps/droidcam-linux-client

Exact device support and installer steps change. Use official/current instructions and verify the package source before installing. This document defines the method; it does not assert that the specific phone or laptop has already been configured or tested.

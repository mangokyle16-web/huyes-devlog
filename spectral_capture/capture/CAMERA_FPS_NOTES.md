# Camera FPS Notes

## Local SDK findings

`qs_camera.h` exposes only these camera-control commands through
`controlQsCamera(QsCameraContext* camera, const QsCameraCommand command, void* value)`:

- `QS_CAMERA_GET_EXPOSURE_MAX`: get max exposure time, `int`
- `QS_CAMERA_GET_EXPOSURE_MIN`: get min exposure time, `int`
- `QS_CAMERA_SET_EXPOSURE`: set exposure time, `int`
- `QS_CAMERA_GET_EXPOSURE`: get exposure time, `int`
- `QS_CAMERA_HAS_LAMP`: get whether a lamp exists, `bool`
- `QS_CAMERA_SET_LAMP`: set lamp on/off, `bool`
- `QS_CAMERA_GET_LAMP`: get whether lamp is on, `bool`
- `QS_CAMERA_GET_NAME`: get camera name, `const char*`

No SDK frame-rate, gain, resolution, pixel-format, or camera-mode command is
declared in the local headers. `qs_imgproc.h` has no camera controls; it only
initializes image processing and converts `.qs` frames to gray/RGB.

`preview_daemon.cpp` now calls `QS_CAMERA_SET_EXPOSURE` immediately after
`openQsCamera(..., true)`. Default target exposure is `6000` us. Pass `0` as the
third runtime argument to keep the camera default:

```bash
LD_PRELOAD=.../uvc_fix.so ./preview_daemon /home/kyle/KyleClaude/camera_new.qsbs 13 6000
LD_PRELOAD=.../uvc_fix.so ./preview_daemon /home/kyle/KyleClaude/camera_new.qsbs 13 0
```

Check stderr for:

```text
[preview_daemon] exposure set target=6000 us actual=... us range=[...,...]
[preview_daemon] frame=... fps=...
```

If actual exposure changes but callback FPS stays near 5.6 fps, exposure is not
the current limiting control.

## V4L2 checks to run on Pi5

The direct V4L2 demo already requests frame interval with `VIDIOC_S_PARM`:

```c
struct v4l2_streamparm parm = {};
parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
parm.parm.capture.timeperframe.numerator = 1;
parm.parm.capture.timeperframe.denominator = use_grey ? 10 : 5;
ioctl(fd, VIDIOC_S_PARM, &parm);
```

Run these on the Pi5 to see what the UVC device actually advertises and accepts:

```bash
v4l2-ctl --list-devices
v4l2-ctl -d /dev/video1 --all
v4l2-ctl -d /dev/video1 --list-formats-ext
v4l2-ctl -d /dev/video1 --list-ctrls
```

Try full-frame YUYV with higher requested frame intervals:

```bash
v4l2-ctl -d /dev/video1 \
  --set-fmt-video=width=1600,height=1200,pixelformat=YUYV \
  --set-parm=10

v4l2-ctl -d /dev/video1 --get-parm
v4l2-ctl -d /dev/video1 --stream-mmap=4 --stream-count=120 --stream-to=/dev/null
```

If `--get-parm` reports 5 fps after requesting 10 fps, the camera or driver is
rejecting that full-resolution interval. Confirm whether the lower-bandwidth
GREY mode can run faster:

```bash
v4l2-ctl -d /dev/video1 \
  --set-fmt-video=width=544,height=384,pixelformat=GREY \
  --set-parm=10

v4l2-ctl -d /dev/video1 --get-parm
v4l2-ctl -d /dev/video1 --stream-mmap=4 --stream-count=120 --stream-to=/dev/null
```

Try V4L2 exposure controls directly if `--list-ctrls` shows them:

```bash
v4l2-ctl -d /dev/video1 --set-ctrl=exposure_auto=1
v4l2-ctl -d /dev/video1 --set-ctrl=exposure_time_absolute=60
v4l2-ctl -d /dev/video1 --get-ctrl=exposure_time_absolute
```

`exposure_time_absolute` is usually in 100 us units, so `60` is approximately
`6000` us. Some UVC drivers use `exposure_absolute` instead; use the exact
control name shown by `--list-ctrls`.

## Concrete next code experiment if SDK exposure is not enough

Add a V4L2 `VIDIOC_S_PARM` call before SDK open, or extend `uvc_fix.so`, to set
the desired frame interval on the camera node the SDK uses:

```c
int fd = open("/dev/video1", O_RDWR | O_CLOEXEC);
struct v4l2_streamparm parm = {};
parm.type = V4L2_BUF_TYPE_VIDEO_CAPTURE;
parm.parm.capture.timeperframe.numerator = 1;
parm.parm.capture.timeperframe.denominator = 10;
ioctl(fd, VIDIOC_S_PARM, &parm);
close(fd);
```

Then start `preview_daemon` and compare its callback FPS. If the SDK reopens and
overwrites the interval, the frame-rate request has to be inserted inside the
same open/configure path the SDK uses, most likely through the existing UVC
preload shim.

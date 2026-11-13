# Zenscreen Auto-rotate on Linux
A Python tool to read screen orientation sensor on Zenscreen without vendor software.

![Investigation](https://img.shields.io/badge/Investigation-COMPLETE-brightgreen)
![Python Implementation](https://img.shields.io/badge/Python_Implementation-WIP-yellow)

> [!IMPORTANT]
> The work is only being done on `MB165B`. The investigation reveals no differences to other models, yet it's worth to keep that in mind if it doesn't work for you.
> Only special one I saw was `MQ149CD`.
> Own a different model? Test it and post an issue!

## Some background...
My ASUS Zenscreen MB165B requires an ASUS Windows-only app **DisplayWidget Center** to enable auto-rotation.

I was NOT a fan of that. So I tried to analyze the packages over the USB using Wireshark, and what came out wasn't exactly as consistent as I hoped for (noisy, `usbmon` either 1 or 2...) and I tried it recently and it stopped working *completely*.

So here I realized I missed such a straight-forward solution; just decompile the Windows-only app itself.

## Spilling the bins
A *fun* evening revelaeed to me the following...
### Tracing the trail
The folder has `.dll` that were a mix of .NET and C++ executables.

My instinct was to jump to `AsusDisplayTracker.dll`. Disappointingly, it was a dead-end. It turned out to be a generic pose-fusion/filtering engine without any HID/USB code in sight. But hey, no Ghidra hell! The sensor protocol is elsewhere...

I cracked open `DisplayWidgetCenter.exe` using ILSpy. I saw `DisplayWidgetCenter.AutoRotationHelper.RotateDisplay`, good start right? It ended with just `ChangeDisplaySettingsEx`, Win32 equivalent to rotating via `xrandr` or `kscreen-doctor`. Dead end.

So let's trace things back, and thankfully we have ILSpy's analyze for this, to see who uses what. So ILSpy with my little eye `DisplayWidgetCenter.AutoRotationManager.AssignRotationCommand`... `SetAutoPivot`... and then the real discovery: it's that the latter calls `DisplayWidgetCenter.VCPAPI.GetOrientation`.

What's `VCP` and why it got me excited? It's the **Virtual Control Panel**, and it's our guy. It's a software-based interface that allows us to adjust hardware settings.

Let us dig deeper... `VCPAPI.GetOrientation` calls `VCPAPI.GetVCPFeatureInternal` with VCP feature code set to `0xAA`, which in turn calls `DisplayWidgetCenter.DDCMethods.GetVCPFeatureAndVCPFeatureReply` and that's a P/Invoke wrapper around Windows' real `dxva2.dll` DDC/CI API.

While `VCP` is the *command set and parameter language*, `DDC/CI` is the *communication protocol and transport layer*.

This tells us the monitor exposes the orientation result over standard DDC/CI, instead of a raw accelerometer stream (not gonna lie, I would've been excited for that more so I could turn my monitor into an egg frying pan).

### Extracted values
* `0xAA` - VCP feature code for orientation, found in `VCPAPI.GetOrientation`. It could be confirmed independently with `ddcutil` which labels it as "Screen Orientation".
* `1/241 -> 0°, 2/243 -> 90°, 3/242 -> 180°, 4/240 -> 270°` - Set of raw value-to-degrees to determine orientation from `SetAutoPivot()` switch. 

---

*This project documents reverse-engineered protocol behavior for interoperability purposes only. No ASUS code or binaries are included or redistributed.*

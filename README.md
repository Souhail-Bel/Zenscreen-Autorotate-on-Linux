# Zenscreen Auto-rotate on Linux
A Python tool to read screen orientation sensor on Zenscreen without vendor software.

![Investigation](https://img.shields.io/badge/Investigation-COMPLETE-brightgreen)
![Python Implementation](https://img.shields.io/badge/Python_Implementation-WIP-yellow)

> [!IMPORTANT]
> The work is only being done on `MB165B`. The investigation reveals no differences to other models, yet it's worth to keep that in mind if it doesn't work for you.
> Only special one I saw was `MQ149CD`.
> Own a different model? Test it and post an issue!

## Table of Contents

- [Some background...](#some-background)
- [Spilling the bins](#spilling-the-bins)
  - [Tracing the trail](#tracing-the-trail)
  - [Extracted values](#extracted-values)
- [I2C communication](#i2c-communication)
  - [Incoveniences encountered](#incoveniences-encountered)
  - [Building the request](#building-the-request)
  - [Reading the reply](#reading-the-reply)

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

## I2C communication

### Incoveniences encountered
`0xAA` is a standard DDC/CI feature code, so the obvious next step was just use `ddcutil`, a Linux tool for this. It didn't go smoothly.

`ddcutil detect` only found my laptop's own internal panel. The MB165B is a DisplayLink-chipset monitor, driven on Linux through `evdi` (DisplayLink's open-source kernel driver), which creates its own virtual I2C bus for the connector, and in my case `/dev/i2c-14`, found manually via
`/sys/class/drm/*/ddc/i2c-dev/`.

Pointing `ddcutil` straight at that bus was refused outright: `Bus /dev/i2c-14 cannot be used for DDC/CI communication.`. Even `--force` didn't help, and running plain `i2cdetect -y 14` failed with `Error: Bus doesn't support detection commands`.

And both failures turned out to share one root cause. `i2cdetect -F 14` (which dumps the adapter's supported operations) showed evdi's virtual adapter implements only raw `I2C_FUNC_I2C` transfers: every single SMBus flag was `no`. `ddcutil` and `i2cdetect -y` both lean on SMBus-style quick/read commands to probe a bus, so they fail here regardless of whether DDC/CI itself would actually work.

```
Functionalities implemented by /dev/i2c-14:
I2C                              yes
SMBus Quick Command              no
SMBus Send Byte                  no
SMBus Receive Byte               no
SMBus Write Byte                 no
SMBus Read Byte                  no
SMBus Write Word                 no
SMBus Read Word                  no
SMBus Process Call               no
SMBus Block Write                no
SMBus Block Read                 no
SMBus Block Process Call         no
SMBus PEC                        no
I2C Block Write                  no
I2C Block Read                   no
SMBus Host Notify                no
10-bit addressing                no
Target mode                      no
```

And it would: DDC/CI is fundamentally a raw-I2C protocol, not an SMBus one. It doesn't need anything `ddcutil`'s gate or `i2cdetect`'s scan is checking for. So the fix wasn't finding a flag to force but it was skipping both tools and directly reading/writing to `/dev/i2c-14`, implementing the DDC/CI packet format by hand per the VESA spec. [^1]

### Building the request

Before any of this, we open the bus and tell it which device to talk to. In my case, as mentioned earlier, it's bus `14`. Found yours under `/sys/class/drm/*/ddc/i2c-dev/`.

So we want to talk to **I2C_SLAVE** (`0x0703` ioctl number) and use DDC/CI command address `0x37`.

The request packet itself is made of these 5 bytes[^1]:

* **Host address:** `0x51` the host's identity byte, DDC/CI spec
* **Length byte:** `0x82` with `0x80` flagging it as DDC/CI packet and `0x02` as in 2 data bytes follow
* **opcode:** `0x01` the *get VCP feature* command
* **VCP code:** `0xAA` the feature being requested, in this case *orientation*
* **Checksum:** `0x04` computed by XORing bytes 0-3 with seed `0x6E` (I2C address, seen first by DDC/CI).

So our full packet would look like `51 82 01 AA 04`. Once written, we wait at least *40ms*[^1] before reading.

> [!NOTE]
> In the documentation, you might notice we send `0x6E` the destination address as the first byte.
> It's not missing here, each subquent `write` call after `ioctl` automatically gets the address-plus-write-bit byte `0x6E`.

### Reading the reply
The reply is made up of the following 11 bytes[^1]:
```
0x6E  source address
0x88  length
0x02  VCP feature reply op code
RC    result code
    0x00  NoError
    0x01  Unsupported VCP code
CP    VCP opcode from feature request message
TP    VCP type code
    0x00  Set parameter
    0x01  Momentary
MH    maximum value HIGH byte
ML    maximum value LOW byte
SH    present value HIGH byte
SL    present value LOW byte
CHK   checksum
```

The `MH/ML` and `SH/SL` are the max and current values as big-endian pairs `high << 8 | low`.

The cheksum is the XOR of all those bytes, this time seeded with `0x50` instead of `0x6E`.
> [!NOTE]
> We're seeding with `0x50` here.
> That's the VESA spec's *virtual* I2C address assigned to the *host, since the host is a bus master.
> The pattern follows that DDC/CI checksum is always seeded with whoever's about to receive the message.
> Request is addressed to dsiaply, so seeded with its real address `0x6E`. Reply is addressed to host, so it's seeded with the host's virtual address `0x50`.

The reply I received, while the monitor was at 0 degrees, was:
`6e 88 02 00 aa 00 00 ff 00 f1 10`

---

*This project documents reverse-engineered protocol behavior for interoperability purposes only. No ASUS code or binaries are included or redistributed.*

[^1]: VESA DDC/CI Standard v1.1 https://milek7.pl/ddcbacklight/ddcci.pdf

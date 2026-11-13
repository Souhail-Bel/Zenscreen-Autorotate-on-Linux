# NOTE
# Opening the bus requires some priviliges
# It doesn't require complex setup like separate shell script or sudo...
# Check whether i2c group exists via ls -l /dev/i2c-{BUS}
# If the I2C group exists, add yourself to it via:
# sudo usermod -aG i2c $USER, then reboot
# GROUP EXISTS: crw-rw---- 1 root i2c
# GROUP DOESNT EXIST: crw------- 1 root root

import os, fcntl, sys
from functools import reduce
import bpy
from mathutils import Vector

def _xor(data, seed):
    return reduce(lambda x, y: x ^ y, data, seed)

# I2C COMMUNICATION CONFIG
BUS_ID    = 14             # configure as you see fit
I2C_SLAVE = 0x0703
DDC_ADDR  = 0x37
DEST_ADDR = DDC_ADDR << 1  # for R/W bit
VIRT_ADDR = 0x50

ORIENTATION_MAP = {
    241: 0,   243: 90,
    242: 180, 240: 270,
}

GRAVITY_MAP = {
    0: (0, 0, -50), 90: (0, 50, 0),
    180: (0, 0, 50), 270: (0, -50, 0),
}

def open_bus(bus_id):
    fd = os.open(f"/dev/i2c-{bus_id}", os.O_RDWR)
    fcntl.ioctl(fd, I2C_SLAVE, DDC_ADDR)
    return fd

def build_request():
    host_addr   = 0x51  # source address
    length_byte = 0x82  # 0x80 flag | 2 data bytes
    opcode      = 0x01  # get VCP feature command
    vcp_code    = 0xAA  # orientation

    header   = bytes([host_addr, length_byte, opcode, vcp_code])
    checksum = _xor(header, DEST_ADDR)
    return header + bytes([checksum])

def parse_reply(reply):
    if _xor(reply, VIRT_ADDR) != 0:
        raise IOError(f"! Checksum mismatch in reply: {reply.hex()}")
    if reply[0] != DEST_ADDR or reply[2] != 0x02:
        raise IOError(f"! Unexpected reply header: {reply.hex()}")

    curr_value = (reply[8] << 8) | reply[9]
    return ORIENTATION_MAP.get(curr_value, -1)

def start_orientation_polling():
    fd = open_bus(BUS_ID)
    packet = build_request()
    scene = bpy.context.scene  # capture scene reference safely on start, avoiding None
    state = {"waiting_reply": False, "prev": None}

    def poll_step():
        try:
            if not state["waiting_reply"]:
                os.write(fd, packet)
                state["waiting_reply"] = True
                return 0.05  # non-blocking 50ms wait for monitor DDC response

            reply = os.read(fd, 11)
            state["waiting_reply"] = False
            cur = parse_reply(reply)

            if cur != state["prev"]:
                print(f"Rotation at {cur}°")
                scene.gravity = GRAVITY_MAP.get(cur, Vector((0, 0, 0)))
                state["prev"] = cur

            return 0.05  # 50ms pull

        except OSError as e:
            print(f"! Read error: {e}", file=sys.stderr)
            state["waiting_reply"] = False
            return 1.0

    bpy.app.timers.register(poll_step, persistent=True)

if __name__ == "__main__":
    start_orientation_polling()
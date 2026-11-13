import os, fcntl, time, sys
from functools import reduce

def _xor(data, seed):
  return reduce(lambda x,y: x^y, data, seed)

# I2C COMMUNICATION CONFIG
I2C_SLAVE = 0x0703
DDC_ADDR  = 0x37
DEST_ADDR = DDC_ADDR << 1 # for R/W bit
VIRT_ADDR = 0x50

ORIENTATION_MAP = {
    241: 0,   243: 90,
    242: 180, 240: 270,
}

def open_bus(BUS_ID): # via /sys/class/drm/*/ddc/i2c-dev/
  fd = os.open(f"/dev/i2c-{BUS_ID}", os.O_RDWR)
  fcntl.ioctl(fd, I2C_SLAVE, DDC_ADDR)
  return fd

def build_request():
  host_addr   = 0x51  # source address
  length_byte = 0x82  # 0x80 flag | 2 data bytes
  opcode      = 0x01  # get VCP feature command
  vcp_code    = 0xAA  # orientation

  header   = bytes([host_addr, length_byte, opcode, vcp_code])
  checksum = _xor(header, DEST_ADDR)
  packet   = header + bytes([checksum])

  return packet


def get_reply(fd, packet):
  os.write(fd, packet)
  time.sleep(0.05)  # 50ms for safety
  reply = os.read(fd, 11)

  checksum = _xor(reply, VIRT_ADDR)

  if checksum != 0:
    raise IOError(f"! Checksum mismatch in reply: {reply.hex()}")
  if reply[0] != DEST_ADDR or reply[2] != 0x02:
    raise IOError(f"! Unexpected reply header: {reply.hex()}")

  return reply

def get_orientation(reply):
  curr_value = (reply[8] << 8) | reply[9]
  deg = ORIENTATION_MAP.get(curr_value, -1)
  return deg


def main():
  if len(sys.argv) != 2:
    print(f"Usage: {sys.argv[0]} <i2c-bus>")
    sys.exit(1)

  fd = open_bus(int(sys.argv[1]))
  packet = build_request()

  prev = None
  while True:
    try:
      reply = get_reply(fd, packet)
    except IOError as e:
      print(f"! Read error: {e}", file=sys.stderr)
      time.sleep(1)
      continue

    cur = get_orientation(reply)
    if(cur != prev):
      print(f"Rotation at {cur}°")
      prev = cur
    time.sleep(0.1)


if __name__ == "__main__":
    main()

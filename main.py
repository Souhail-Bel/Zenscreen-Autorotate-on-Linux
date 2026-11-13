import os, fcntl, time
from functools import reduce

# I2C COMMUNICATION CONFIG
BUS_ID    = 14      # via /sys/class/drm/*/ddc/i2c-dev/
I2C_SLAVE = 0x0703
DDC_ADDR  = 0x37
DEST_ADDR = DDC_ADDR << 1 # for R/W bit

fd = os.open(f"/dev/i2c-{BUS_ID}", os.O_RDWR)
fcntl.ioctl(fd, I2C_SLAVE, DDC_ADDR)

# BUILDING REQUEST
host_addr   = 0x51  # source address
length_byte = 0x82  # 0x80 flag | 2 data bytes
opcode      = 0x01  # get VCP feature command
vcp_code    = 0xAA  # orientation

header   = bytes([host_addr, length_byte, opcode, vcp_code])
checksum = reduce(lambda x,y: x^y, header, DEST_ADDR)
packet   = header + bytes([checksum])

# SENDING, READING REPLY
os.write(fd, packet)
time.sleep(0.05)  # 50ms for safety
reply = os.read(fd, 11)
os.close(fd)

print(reply.hex())

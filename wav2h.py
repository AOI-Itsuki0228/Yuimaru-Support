data = open("reply.wav", "rb").read()
with open("reply_wav.h", "w") as f:
    f.write("#pragma once\n#include <stdint.h>\n")
    f.write(f"const uint32_t reply_wav_len = {len(data)};\n")
    f.write("const uint8_t reply_wav[] PROGMEM = {\n")
    for i in range(0, len(data), 16):
        f.write(",".join(str(b) for b in data[i:i+16]) + ",\n")
    f.write("};\n")
print("reply_wav.h を作成:", len(data), "bytes")
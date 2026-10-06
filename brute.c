// mem.bin 暴力 AES-256-CBC raw key 搜索器
// 已知: 页1 salt(16) + C1(16..32密文) + IV(页尾) + SQLite头明文8字节
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <CommonCrypto/CommonCrypto.h>
#include <sys/mman.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <unistd.h>

static const unsigned char KNOWN[8] = {0x10,0x00,0x01,0x01,0x50,0x40,0x20,0x20};
static const unsigned char KNOWN_WAL[8] = {0x10,0x00,0x02,0x02,0x50,0x40,0x20,0x20};

int main(int argc, char **argv) {
    const char *path = argv[1];
    unsigned char C1[16], iv80[16], iv48[16];
    {
        unsigned char page[4096];
        FILE *f = fopen("/tmp/trae_export/database.db", "rb");
        if (!f || fread(page, 1, 4096, f) != 4096) { fprintf(stderr, "db read fail\n"); return 1; }
        fclose(f);
        memcpy(C1, page+16, 16);
        memcpy(iv80, page+4096-80, 16);
        memcpy(iv48, page+4096-48, 16);
    }
    // 期望的 AES_dec(C1) 前8字节
    unsigned char t80[8], t48[8];
    for (int i = 0; i < 8; i++) { t80[i] = KNOWN[i] ^ iv80[i]; t48[i] = KNOWN[i] ^ iv48[i]; }

    int fd = open(path, O_RDONLY);
    if (fd < 0) { perror("open"); return 1; }
    struct stat st; fstat(fd, &st);
    size_t sz = st.st_size;
    unsigned char *buf = mmap(NULL, sz, PROT_READ, MAP_PRIVATE, fd, 0);
    if (buf == MAP_FAILED) { perror("mmap"); return 1; }

    // 解析区域记录
    size_t off = 0; size_t nreg = 0;
    while (off + 16 <= sz) {
        uint64_t addr = *(uint64_t*)(buf+off);
        uint64_t ln   = *(uint64_t*)(buf+off+8);
        if (ln == 0 || off+16+ln > sz) break;
        (void)addr;
        nreg++;
        off += 16 + ln;
    }
    fprintf(stderr, "regions=%zu parsed, total=%zuMB\n", nreg, off/1048576);

    unsigned char out[16]; size_t moved = 0;
    for (size_t roff = 0; roff + 32 <= sz; ) {
        uint64_t ln = *(uint64_t*)(buf+roff+8);
        if (ln == 0 || roff+16+ln > sz) break;
        unsigned char *d = buf + roff + 16;
        for (size_t o = 0; o + 32 <= ln; o += 4) {
            unsigned char *k = d + o;
            // reserve80: CCCrypt 内部已做 P=D(C1)^iv，直接比 KNOWN（兼容 WAL/非WAL 头）
            CCCrypt(kCCDecrypt, kCCAlgorithmAES, 0, k, 32, iv80, C1, 16, out, 16, &moved);
            if (memcmp(out, KNOWN, 8) == 0 || memcmp(out, KNOWN_WAL, 8) == 0) {
                printf("[FOUND reserve80] key=");
                for (int i=0;i<32;i++) printf("%02x", k[i]);
                printf(" @file=%zu\n", roff+16+o);
                fflush(stdout);
            }
            // reserve48
            CCCrypt(kCCDecrypt, kCCAlgorithmAES, 0, k, 32, iv48, C1, 16, out, 16, &moved);
            if (memcmp(out, KNOWN, 8) == 0 || memcmp(out, KNOWN_WAL, 8) == 0) {
                printf("[FOUND reserve48] key=");
                for (int i=0;i<32;i++) printf("%02x", k[i]);
                printf(" @file=%zu\n", roff+16+o);
                fflush(stdout);
            }
        }
        roff += 16 + ln;
    }
    fprintf(stderr, "scan done\n");
    return 0;
}

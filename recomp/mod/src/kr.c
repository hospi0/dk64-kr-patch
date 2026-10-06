/* DK64: Recompiled — Korean mod.
 *
 * Port of the ROM patch (tools/dkbuild.py HOOK_ASM).  Data comes from tools/dkmod.py (krdata.h + krblob.bin).
 * Only RECOMP_PATCH / events are used: RECOMP_HOOK does not load in this port ("Code mod loading
 * internal error", 2026-10-06 stage tests), so nothing runs before/after a renderer call.
 *
 * Korean text = 2 bytes: lead 0x80..0x8F x trail 0x90..0xFE; glyph g = (lead-0x80)*111 + (trail-0x90).
 * Every text renderer (printStyledText, 806FCC88, 806FD094) works page by page: one pass per font page,
 * drawing the chars whose index (806FB914) falls in that page's bounds.  For styles 1 (menu) and 6
 * (dialogue / captions) every Korean glyph page r is a fixed «virtual page» FC+1+r:
 *   - file_count = FC + Korean pages (set once at init; the cache release loop 806FBC34 is patched to
 *     the original counts), style-6 quad height 13 (806FD894 still reports 12 to the layout code).
 *   - lookup: lead -> remembers the bank, returns Z (width 0, never drawn); trail -> writes the glyph's
 *     cell into spare entry D and rewrites the bounds so D falls in virtual page FC+1+r.
 *   - every page costs one pass + PipeSync per renderer call: style-6 pages are 512-px strips (39
 *     glyphs) and the display-list allocation is raised (recomp_adjust_dl_allocation).
 *   - texture loader: virtual page FC+1+r loads table-14 file KR_TEX0+.. (our page, served by the
 *     file-load event so it sits in the game heap like the original pages).
 * Dialogue draws node by node: the lead node draws nothing (width 0), the trail node draws the glyph
 * (bank remembered from the lead node just drawn) and advances KR_ADV.
 */
#include "modding.h"
#include "ultra64.h"
#include "krdata.h"

typedef struct {
    u32 tab, bnd;               /* blob offsets -> pointers at init */
    u16 ng;                     /* glyphs in this font */
    u8 d, fc, per, cw, wd;      /* spare entry D (Z = D+1), original file_count, cells/page, cell w, glyph w */
    u32 pages;
    u16 pbytes;
    u8 hset, horig;             /* quad height while Korean pages exist (0 = keep), original height */
} KrFont;

typedef struct { s16 x; u8 w; u8 pad; } KrChar;
typedef struct { u8 first, file_count, height, kerning_space, kerning_character, kerning_animation; } KrDesc;

extern u8 kr_blob[];
static KrFont P1 = KR_P1_INIT, P6 = KR_P6_INIT;
static int kr_ready = 0;
static u8 vs_lead;

#define DESC ((KrDesc *)0x80754A34)
#define TABS ((u32 *)0x80754A18)
#define BNDS ((u32 *)0x807549FC)
#define KR_TEX0 256                          /* table-14 file index of our first glyph page */
#define KR_TEXN 512                          /* font texture cache size (original 43) */

static KrFont *font_for(int style) {
    return style == 1 ? &P1 : style == 6 ? &P6 : NULL;
}

static void kr_init(void) {
    if (kr_ready)
        return;
    kr_ready = 1;
    P1.tab += (u32)kr_blob; P1.bnd += (u32)kr_blob; P1.pages += (u32)kr_blob;
    P6.tab += (u32)kr_blob; P6.bnd += (u32)kr_blob; P6.pages += (u32)kr_blob;
}

/* style tables / counts / kong names in global_asm .data (re-applied if the data was reloaded) */
static void kr_apply(void) {
    int i;
    kr_init();
    TABS[1] = P1.tab; BNDS[1] = P1.bnd;
    TABS[6] = P6.tab; BNDS[6] = P6.bnd;
    DESC[1].file_count = P1.fc + KR_NPAGES1;
    DESC[6].file_count = P6.fc + KR_NPAGES6;
    if (P6.hset)
        DESC[6].height = P6.hset;
    if (KR_NCODE && *(u32 *)kr_code[0][0] != kr_code[0][1])
        for (i = 0; i < KR_NCODE; i++)
            *(u32 *)kr_code[i][0] = kr_code[i][1];
}

/* every font page costs the renderers a pass + a PipeSync per call: room for the Korean pages */
RECOMP_CALLBACK("*", recomp_adjust_dl_allocation) void kr_dl_alloc(s32 *allocation) {
    *allocation += 8000;
}

RECOMP_CALLBACK("*", recomp_on_init) void kr_on_init(void) {
    kr_apply();
}

/* --- text files and glyph pages -------------------------------------------------------------- */
RECOMP_CALLBACK("*", recomp_on_asset_file_load_override)
void kr_file_override(s32 table, s32 file, u8 **out, s32 *size) {
    int i;
    kr_init();
    if (table == 14 && file >= KR_TEX0 && file < KR_TEX0 + KR_NPAGES6 + KR_NPAGES1) {
        int k = file - KR_TEX0;
        KrFont *P = k < KR_NPAGES6 ? &P6 : &P1;
        if (k >= KR_NPAGES6)
            k -= KR_NPAGES6;
        *out = (u8 *)(P->pages + k * P->pbytes);
        *size = P->pbytes;
        return;
    }
    if (table != 12)
        return;
    for (i = 0; i < KR_NTEXT; i++) {
        if (kr_text_file[i] == file) {
            *out = kr_blob + kr_text_off[i];
            *size = kr_text_len[i];
            return;
        }
    }
}

/* --- glyph lookup (func_806FB914, rewritten: the original is asm only) ------------------------- */
char *_strchr(const char *s, int c);

static u8 set_index(const char *set, u8 c) {
    char *p = _strchr(set, c);
    return p ? (u8)(p - set) : 0;
}

RECOMP_PATCH s8 func_global_asm_806FB914(s16 style, u8 *c) {
    s8 flag = 0;
    u8 ch = *c;
    KrFont *P = font_for(style);

    if (P != NULL && ch >= KR_LEAD0 && ch != 0xFF) {
        kr_init();
        if (TABS[style] != P->tab)
            kr_apply();
        if (ch < KR_TRAIL0) {                 /* lead: Z */
            vs_lead = ch - KR_LEAD0;
            *c = P->d + 1;
        } else {
            u32 g = vs_lead * KR_NTRAIL + (ch - KR_TRAIL0);
            u32 r, j, np = style == 1 ? KR_NPAGES1 : KR_NPAGES6;
            u8 *bnd = (u8 *)P->bnd;
            KrChar *tab = (KrChar *)P->tab;
            if (g >= P->ng) {
                *c = P->d + 1;
                return 0;
            }
            r = g / P->per;
            tab[P->d].x = (g % P->per) * P->cw;
            tab[P->d].w = P->wd;
            /* B[FC+1+j] = D (j < r) / D+1 (j >= r): D falls in virtual page FC+1+r only */
            for (j = 0; j < np; j++)
                bnd[P->fc + 1 + j] = j < r ? P->d : P->d + 1;
            *c = P->d;
        }
        return 0;
    }

    switch (style) {
        case 0:
            if (ch < 0x2F) {
                if (ch == '.')
                    flag = 2;
            } else if ((u8)(ch - 0x61) < 0x20) {
                u8 k = ch - 0x61;
                if (k == 0x00 || k == 0x18)
                    flag = 1;
                else if (k == 0x06 || k == 0x0F || k == 0x10 || k == 0x1F)
                    flag = 2;
            }
            *c = ch - 0x21;
            break;
        case 1:
            *c = set_index((const char *)0x80754A64, ch);
            break;
        case 2:
            *c = set_index((const char *)0x8075DC20, ch);
            break;
        case 3:
        case 7:
            *c = set_index((const char *)0x8075DC5C, ch);
            break;
        case 4:
            *c = ch == '@' ? 0x60 : ch - 0x21;
            break;
        case 5:
            *c = ch - 0x21;
            break;
        case 6:
            *c = set_index((const char *)0x80754AA0, ch);
            break;
    }
    return flag;
}

/* --- widths (func_806FD7A8) / height (func_806FD894) ----------------------------------------- */
RECOMP_PATCH s16 func_global_asm_806FD7A8(s16 arg0, u8 arg1) {
    s16 var_v1;

    if (arg0 == 6 && arg1 >= KR_LEAD0 && arg1 != 0xFF)   /* dialogue node: lead 0, trail = the glyph */
        return arg1 < KR_TRAIL0 ? 0 : KR_ADV;
    if (arg0 & 0x80) {
        arg0 ^= 0x80;
        var_v1 = DESC[arg0].kerning_animation;
    } else if (arg1 == ' ') {
        var_v1 = DESC[arg0].kerning_space;
    } else {
        func_global_asm_806FB914(arg0, &arg1);
        var_v1 = ((KrChar *)TABS[arg0])[arg1].w;
    }
    var_v1 += DESC[arg0].kerning_character;
    return var_v1;
}

RECOMP_PATCH u8 func_global_asm_806FD894(s16 arg0) {
    if (arg0 & 0x80)
        arg0 ^= 0x80;
    if (arg0 == 6)
        return P6.horig;                      /* layout keeps the original line height */
    return DESC[arg0].height;
}


/* --- file release (func_8066B434) ------------------------------------------------------------
   files handed out by the load event (our text files / glyph pages) are not in the game's
   pointer->(table, file) tree: 8066BC00 then leaves table/file unset and 8066B4AC wrote a 0 through a
   garbage index (crash right after the first Korean caption).  Unknown pointers are just freed. */
s32 func_global_asm_8066B9F4(void *arg0);
void func_global_asm_8066BC00(void *arg0, s32 *arg1, s32 *arg2);
void func_global_asm_8066B4AC(s32 arg0, s32 arg1, void *arg2);
void func_global_asm_8061134C(void *arg0);
void _free(void *arg0);
extern u8 D_global_asm_807F967D;

RECOMP_PATCH void func_global_asm_8066B434(void *arg0, s32 arg1, s32 arg2) {
    s32 sp1C = -1;
    s32 sp18 = -1;

    if (func_global_asm_8066B9F4(arg0) == 0) {
        func_global_asm_8066BC00(arg0, &sp1C, &sp18);
        if (sp1C >= 0 && sp1C < 32 && sp18 >= 0)
            func_global_asm_8066B4AC(sp1C, sp18, 0);
        if (D_global_asm_807F967D == 0) {
            func_global_asm_8061134C(arg0);
        } else {
            _free(arg0);
        }
    }
    D_global_asm_807F967D = 0;
}

/* --- font page textures ---------------------------------------------------------------------- */
void *func_global_asm_806FBB9C(s16 textureIndex);
void func_global_asm_80611690(void *arg0);
void *_malloc(s32);
extern void **D_global_asm_807FD7F0;           /* page cache: malloc'd arrays (pointer, refcount) */
extern u8 *D_global_asm_807FD7F4;

RECOMP_PATCH void func_global_asm_806FBB58(void) {
    D_global_asm_807FD7F0 = _malloc(sizeof(s32) * KR_TEXN);
    func_global_asm_80611690(D_global_asm_807FD7F4 = _malloc(sizeof(u8) * KR_TEXN));
}

RECOMP_PATCH void func_global_asm_806FBC34(void) {
    s16 i, k, j, n;

    i = 0;
    for (j = 0; j < 8; j++) {
        n = j == 1 ? P1.fc : j == 6 ? P6.fc : DESC[j].file_count;     /* original page counts */
        for (k = 0; k < n; k++) {
            if (D_global_asm_807FD7F4[i++]) {
                if (--D_global_asm_807FD7F4[i - 1] == 0) {
                    func_global_asm_8066B434(D_global_asm_807FD7F0[i - 1], 0x156, 0x23);
                }
            }
        }
    }
    for (i = KR_TEX0; i < KR_TEX0 + KR_NPAGES6 + KR_NPAGES1; i++) {
        if (D_global_asm_807FD7F4[i] && --D_global_asm_807FD7F4[i] == 0) {
            func_global_asm_8066B434(D_global_asm_807FD7F0[i], 0x156, 0x23);
        }
    }
}

RECOMP_PATCH Gfx *func_global_asm_806FBEF0(Gfx *dl, u8 arg1, s16 arg2) {
    s16 textureIndex;
    KrFont *P = font_for(arg1);

    if (P != NULL && arg2 > P->fc) {
        textureIndex = KR_TEX0 + (arg2 - P->fc - 1) + (arg1 == 1 ? KR_NPAGES6 : 0);
        func_global_asm_806FBB9C(textureIndex);
        if (arg1 == 6) {                      /* IA4 512x13 strip (39 cells), LoadTile: no LoadBlock dxt slip */
            gDPLoadTextureTile_4b(dl++, (s32)D_global_asm_807FD7F0[textureIndex] + 0x80000000, G_IM_FMT_IA, 512, 13,
                                  0, 0, 511, 12, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMIRROR | G_TX_CLAMP,
                                  G_TX_NOMASK, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOLOD);
        } else {                              /* RGBA16 76x24, same as the original style-1 pages */
            gDPSetTextureImage(dl++, G_IM_FMT_RGBA, G_IM_SIZ_16b, 1, (s32)D_global_asm_807FD7F0[textureIndex] + 0x80000000);
            gDPSetTile(dl++, G_IM_FMT_RGBA, G_IM_SIZ_16b, 0, 0x0000, G_TX_LOADTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPLoadSync(dl++);
            gDPLoadBlock(dl++, G_TX_LOADTILE, 0, 0, 1823, 108);
            gDPPipeSync(dl++);
            gDPSetTile(dl++, G_IM_FMT_RGBA, G_IM_SIZ_16b, 19, 0x0000, G_TX_RENDERTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPSetTileSize(dl++, G_TX_RENDERTILE, 0, 0, 0x012C, 0x005C);
        }
        return dl;
    }

    textureIndex = (DESC[arg1].first + arg2) - 1;
    func_global_asm_806FBB9C(textureIndex);
    switch (arg1) {
        case 6:
            gDPSetTextureImage(dl++, G_IM_FMT_IA, G_IM_SIZ_16b, 1, (s32)D_global_asm_807FD7F0[textureIndex] + 0x80000000);
            gDPSetTile(dl++, G_IM_FMT_IA, G_IM_SIZ_16b, 0, 0x0000, G_TX_LOADTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPLoadSync(dl++);
            gDPLoadBlock(dl++, G_TX_LOADTILE, 0, 0, 1143, 94);
            gDPPipeSync(dl++);
            gDPSetTile(dl++, G_IM_FMT_IA, G_IM_SIZ_8b, 22, 0x0000, G_TX_RENDERTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPSetTileSize(dl++, G_TX_RENDERTILE, 0, 0, 0x02BC, 0x0030);
            break;
        case 0:
            gDPSetTextureImage(dl++, G_IM_FMT_IA, G_IM_SIZ_16b, 1, (s32)D_global_asm_807FD7F0[textureIndex] + 0x80000000);
            gDPSetTile(dl++, G_IM_FMT_IA, G_IM_SIZ_16b, 0, 0x0000, G_TX_LOADTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPLoadSync(dl++);
            gDPLoadBlock(dl++, G_TX_LOADTILE, 0, 0, 2047, 64);
            gDPPipeSync(dl++);
            gDPSetTile(dl++, G_IM_FMT_IA, G_IM_SIZ_4b, 32, 0x0000, G_TX_RENDERTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPSetTileSize(dl++, G_TX_RENDERTILE, 0, 0, 0x07FC, 0x003C);
            break;
        case 1:
            gDPSetTextureImage(dl++, G_IM_FMT_RGBA, G_IM_SIZ_16b, 1, (s32)D_global_asm_807FD7F0[textureIndex] + 0x80000000);
            gDPSetTile(dl++, G_IM_FMT_RGBA, G_IM_SIZ_16b, 0, 0x0000, G_TX_LOADTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPLoadSync(dl++);
            gDPLoadBlock(dl++, G_TX_LOADTILE, 0, 0, 1823, 108);
            gDPPipeSync(dl++);
            gDPSetTile(dl++, G_IM_FMT_RGBA, G_IM_SIZ_16b, 19, 0x0000, G_TX_RENDERTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPSetTileSize(dl++, G_TX_RENDERTILE, 0, 0, 0x012C, 0x005C);
            break;
        case 2:
            gDPSetTextureImage(dl++, G_IM_FMT_I, G_IM_SIZ_16b, 1, (s32)D_global_asm_807FD7F0[textureIndex] + 0x80000000);
            gDPSetTile(dl++, G_IM_FMT_I, G_IM_SIZ_16b, 0, 0x0000, G_TX_LOADTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPLoadSync(dl++);
            gDPLoadBlock(dl++, G_TX_LOADTILE, 0, 0, 1023, 64);
            gDPPipeSync(dl++);
            gDPSetTile(dl++, G_IM_FMT_I, G_IM_SIZ_4b, 32, 0x0000, G_TX_RENDERTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPSetTileSize(dl++, G_TX_RENDERTILE, 0, 0, 0x07FC, 0x001C);
            break;
        case 3:
        case 7:
            gDPSetTextureImage(dl++, G_IM_FMT_RGBA, G_IM_SIZ_16b, 1, (s32)D_global_asm_807FD7F0[textureIndex] + 0x80000000);
            gDPSetTile(dl++, G_IM_FMT_RGBA, G_IM_SIZ_16b, 0, 0x0000, G_TX_LOADTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPLoadSync(dl++);
            gDPLoadBlock(dl++, G_TX_LOADTILE, 0, 0, 1023, 256);
            gDPPipeSync(dl++);
            gDPSetTile(dl++, G_IM_FMT_RGBA, G_IM_SIZ_16b, 8, 0x0000, G_TX_RENDERTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPSetTileSize(dl++, G_TX_RENDERTILE, 0, 0, 0x007C, 0x007C);
            break;
        case 4:
        case 5:
            gDPSetTextureImage(dl++, G_IM_FMT_I, G_IM_SIZ_16b, 1, (s32)D_global_asm_807FD7F0[textureIndex] + 0x80000000);
            gDPSetTile(dl++, G_IM_FMT_I, G_IM_SIZ_16b, 0, 0x0000, G_TX_LOADTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPLoadSync(dl++);
            gDPLoadBlock(dl++, G_TX_LOADTILE, 0, 0, 2047, 32);
            gDPPipeSync(dl++);
            gDPSetTile(dl++, G_IM_FMT_I, G_IM_SIZ_4b, 64, 0x0000, G_TX_RENDERTILE, 0, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD, G_TX_NOMIRROR | G_TX_CLAMP, G_TX_NOMASK, G_TX_NOLOD);
            gDPSetTileSize(dl++, G_TX_RENDERTILE, 0, 0, 0x0FFC, 0x001C);
            break;
    }
    return dl;
}

/* --- voiced cutscene captions ---------------------------------------------------------------
   Cutscene commands are 12-byte records; a delayed one is queued (8060098C) and run later by the
   delayed-call dispatcher 80600B10 as func_80627F04(a, b, c).  Sound command = sub-command 20
   (a & 0xFF), sound id = (s16)b.  The dispatcher is patched (hooks do not load in this port): before a
   queued voiced sound runs, the caption (text file 01 box) is shown with func_80627C5C. */
typedef struct KrDelayed {
    struct KrDelayed *next;
    s32 (*function)(s32 a, s32 b, s32 c);
    s32 action_frame;
    s32 args[3];
} KrDelayed;

extern KrDelayed *D_global_asm_807452A0;
extern u32 D_global_asm_8076A068[1];
void func_global_asm_80627C5C(s32 arg0, s16 arg1, u8 arg2);

static void kr_voice_play(s16 sound) {
    int i;
    for (i = 0; i < KR_NVOICE; i++) {
        if (kr_voice[i][0] == (u16)sound) {
            s16 n = *(s16 *)0x807FC3F0;          /* actor_count */
            u8 **list = (u8 **)0x807FBFF0;       /* actor_list */
            for (; n > 0; n--, list++) {         /* a new voiced line: drop caption overlays still on screen */
                u8 *a = *list;
                if (a != NULL && *(s32 *)(a + 0x58) == 0xE8 && *(s16 *)(a + 0xEE) == 0) {
                    a[0x154] = 1;                /* control_state 1 */
                    a[0x155] = 3;                /* progress 3 = free + despawn on its next update */
                }
            }
            func_global_asm_80627C5C(kr_voice[i][1], kr_voice[i][3], kr_voice[i][2]);
            return;
        }
    }
}

RECOMP_PATCH void func_global_asm_80600B10(void) {
    s32 var_s1;
    KrDelayed *var_s0;

    var_s0 = D_global_asm_807452A0;
    var_s1 = 0;
    while (var_s0 != NULL && !var_s1) {
        if (D_global_asm_8076A068[0] >= (var_s0->action_frame & 0x7FFFFFFF)) {
            if ((u32)var_s0->function == 0x80627F04 && (var_s0->args[0] & 0xFF) == 20)
                kr_voice_play((s16)var_s0->args[1]);
            /* a voiced line started by an actor animation (no sound command): Helm_IntroStory cutscene 12
               frame 255, sub 4 actor 7 (Klump) animation 0x33 = «we've already taken care of business» (sound 843) */
            if ((u32)var_s0->function == 0x80627F04 && (var_s0->args[0] & 0xFF) == 4 &&
                var_s0->args[1] == 0x00070002 && var_s0->args[2] == 0x00330000 && *(s32 *)0x8076A0A8 == 0x98)
                kr_voice_play(843);
            var_s0->function(var_s0->args[0], var_s0->args[1], var_s0->args[2]);
            _free(var_s0);
            var_s0 = var_s0->next;
        } else {
            var_s1 = 1;
        }
    }
    D_global_asm_807452A0 = var_s0;
}

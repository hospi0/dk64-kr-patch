/* Text bubble renderer: the port's own patch (patches_matrix.c) copied with a bigger display list.
   Korean glyph pages make every node's printStyledText run ~22 passes (one PipeSync each), so the
   port's fixed 0x5000-byte list overflowed into the heap on long lines (crash in the heap code). */
#include "modding.h"
#include "ultra64.h"
#include "enums.h"
#include "common_structs.h"

#define KR_BUBBLE_DL 0x10000

extern void *_malloc(s32);
void func_global_asm_8061134C(void *arg0);
Gfx *func_global_asm_806A3E9C(Gfx *, void *, s16);
void func_global_asm_806A3B78(Gfx **arg0, AAD_global_asm_806A4DDC *arg1, Struct806A57C0_2 *arg2, u8 arg3, u8 *arg4);
Gfx *func_global_asm_806A3C6C(Gfx *dl, Mtx *arg1, u8 arg2, s32 arg3);
extern Gfx D_1000118[];
extern Mtx D_20000C0;
extern u8 D_global_asm_807444FC;
extern u8 cc_player_index;

RECOMP_FORCE_PATCH Gfx* func_global_asm_806A4284(Gfx* dl, Actor* arg1) {
    AAD_global_asm_806A4DDC* temp_s2;
    Struct806A57C0_2* var_s1;
    s32 i;
    u8 sp13B;
    s32 pad2;
    s16 sp132;
    s32 pad[3];
    u8 res;
    f32 spE0[4][4];
    f32 spA0[4][4];
    f32 temp_f20;
    Gfx* dl_0; // 98
    Gfx* dl_0_start; // 94
    f32 var_f2;
    f32 temp_f0;

    temp_s2 = arg1->AAD_as_array[0];
    var_s1 = temp_s2->unkC;
    sp13B = 0;
    dl_0 = _malloc(KR_BUBBLE_DL); // Korean: every font page costs one pass + PipeSync per glyph node
    func_global_asm_8061134C(dl_0);
    dl_0_start = dl_0;
    gSPDisplayList(dl_0++, &D_1000118);
    gSPMatrix(dl_0++, &D_20000C0, G_MTX_NOPUSH | G_MTX_LOAD | G_MTX_PROJECTION);
    gDPPipeSync(dl_0++);
    gDPSetRenderMode(dl_0++, G_RM_XLU_SURF, G_RM_XLU_SURF2);
    gDPSetCycleType(dl_0++, G_CYC_1CYCLE);
    gDPSetCombineMode(dl_0++, G_CC_MODULATEIA_PRIM, G_CC_MODULATEIA_PRIM);
    gSPLoadGeometryMode(dl_0++, 0);
    gSPSetGeometryMode(dl_0++, G_SHADE | G_SHADING_SMOOTH);
    sp132 = temp_s2->unk1C / 2;
    temp_f20 = (f32) ((1.0 - ((f64) temp_s2->unk40 * 0.5)) * (f64) temp_s2->unk20 * 1.899999976158142 * 4.0);
    guTranslateF(spE0, -48.0f, -32.0f, 0.0f);
    guScaleF(spA0, temp_f20, temp_f20, 1.0f);
    guMtxCatF(spE0, spA0, spE0);
    guTranslateF(spA0, arg1->position.f[0] * 4.0f, arg1->position.f[1] * 4.0f, 0.0f);
    guMtxCatF(spE0, spA0, spE0);
    guMtxF2L(spE0, &temp_s2->unk34[D_global_asm_807444FC]);
    gDPPipeSync(dl_0++);
    
    gDPSetScissor(dl_0++, G_SC_NON_INTERLACE,
        character_change_array[0].unk270[0],
        character_change_array[0].unk270[1],
        character_change_array[0].unk270[2],
        character_change_array[0].unk270[3]);
    dl_0 = func_global_asm_806A3E9C(dl_0, temp_s2, sp132);
    temp_f0 = temp_s2->unk20 * 150.0f * 2;
    var_f2 = MIN(150.0f, temp_f0);
    dl_0 = func_global_asm_806A3C6C(dl_0, &temp_s2->unk34[D_global_asm_807444FC], var_f2, sp132);
    if (temp_s2->unk1D != 0) {
        gDPPipeSync(dl_0++);
        gDPSetScissor(dl_0++, G_SC_NON_INTERLACE,
            temp_s2->unk44,
            temp_s2->unk48,
            temp_s2->unk4C,
            temp_s2->unk50);
    }
    for (i = 0; (i <= temp_s2->unk10) && (var_s1) && (!sp13B); i++) {
        gDPPipeSync(dl_0++);
        res = i == temp_s2->unk10;
        func_global_asm_806A3B78(&dl_0, temp_s2, var_s1, res, &sp13B);
        if (!sp13B) {
            var_s1 = var_s1->next;
        }
    }
    gDPPipeSync(dl_0++);
    if (temp_s2->unk1D != 0) {
        gDPSetScissor(dl_0++, G_SC_NON_INTERLACE,
            character_change_array[cc_player_index].unk270[0],
            character_change_array[cc_player_index].unk270[1],
            character_change_array[cc_player_index].unk270[2],
            character_change_array[cc_player_index].unk270[3]);
    }
    temp_s2->unk1C++;
    temp_s2->unk1C %= 16;
    gSPEndDisplayList(dl_0++);
    gSPDisplayList(dl++, dl_0_start);
    return dl;
}

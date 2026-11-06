// Indirect-count multi-draws masked on the GPU (nvn_mtl.m mdx_run)
#include <metal_stdlib>
using namespace metal;
struct mjob { device const uint *rec; device const uint *cnt; device uint *out; uint i, words; };
kernel void mdx_mask(device const mjob *j [[buffer(0)]], uint t [[thread_position_in_grid]]) {
  mjob m = j[t]; if (!m.out) return;
  // An indirect mesh draw: NVN's {count, first} as Metal's threadgroups {x, y, z} (nvn_geometry.inc mesh_tasks_draw). The count is clamped to the 65,535 task groups NVN allows:
  // a stale or overwritten record (the host reads records ahead, mdx_run) launched ~10^9 groups and the GPU watchdog killed the command buffer (Ocarina, Link's house, M1 Pro)
  if (!m.words) { m.out[0] = min(m.rec[0], 65535u); m.out[1] = 1u; m.out[2] = 1u; return; }
  // A multi-draw record whose vertex/index or instance count is past 2^24 is garbage for the same reason: it is drawn as empty instead of hanging the GPU
  bool live = m.i < *m.cnt && m.rec[0] <= (1u << 24) && m.rec[1] <= (1u << 24);
  for (uint k = 0; k < m.words; k++) m.out[k] = live ? m.rec[k] : 0u; }

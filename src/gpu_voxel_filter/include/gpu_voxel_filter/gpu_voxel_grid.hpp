#pragma once

#include <cstddef>
#include <cstdint>
#include <memory>

namespace gpu_voxel_filter
{

// Byte offsets of the fields we read from one point of a PointCloud2 buffer.
struct CloudLayout
{
  uint32_t point_step;
  uint32_t x, y, z;
  uint32_t intensity;
  bool has_intensity;
};

// Voxel-grid downsampling on the GPU: every point inside [min_range, max_range]
// falls into a cube of side `leaf`; each occupied cube becomes one point at the
// centroid of its points (x, y, z and mean intensity). No ROS types, so the CUDA
// side compiles with plain nvcc.
class GpuVoxelGrid
{
public:
  GpuVoxelGrid();
  ~GpuVoxelGrid();

  // Filters n points from a host buffer; returns the number of output points.
  size_t filter(
    const uint8_t * data, size_t n, const CloudLayout & layout,
    float leaf, float min_range, float max_range);

  // Copies the last result to dst as x, y, z, intensity float32 quadruples
  // (16 bytes per point, the layout of the published cloud).
  void download(void * dst) const;

private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace gpu_voxel_filter

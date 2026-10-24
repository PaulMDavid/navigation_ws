#include "gpu_voxel_filter/gpu_voxel_grid.hpp"

#include <cuda_runtime.h>
#include <thrust/device_vector.h>
#include <thrust/execution_policy.h>
#include <thrust/functional.h>
#include <thrust/reduce.h>
#include <thrust/sort.h>

#include <stdexcept>
#include <string>

namespace gpu_voxel_filter
{
namespace
{

using Key = unsigned long long;
constexpr Key kInvalid = ~0ULL;  // sorts last, so dropped points end up in one trailing group
constexpr int kBits = 21;        // per axis: 3 * 21 bits packed into one 64-bit key
constexpr long long kHalf = 1LL << (kBits - 1);

struct Acc
{
  float x, y, z, i;
  int n;
};

struct AccSum
{
  __host__ __device__ Acc operator()(const Acc & a, const Acc & b) const
  {
    return {a.x + b.x, a.y + b.y, a.z + b.z, a.i + b.i, a.n + b.n};
  }
};

__device__ float read_float(const uint8_t * p)
{
  float v;
  memcpy(&v, p, sizeof(v));  // fields need not be 4-byte aligned in every driver's layout
  return v;
}

// One thread per point: drop invalid/out-of-range points, otherwise emit the
// point's voxel key and a one-point accumulator.
__global__ void voxelize(
  const uint8_t * data, size_t n, CloudLayout L, float inv_leaf,
  float min_r2, float max_r2, Key * keys, Acc * acc)
{
  const size_t k = blockIdx.x * static_cast<size_t>(blockDim.x) + threadIdx.x;
  if (k >= n) {return;}
  const uint8_t * p = data + k * L.point_step;
  const float x = read_float(p + L.x), y = read_float(p + L.y), z = read_float(p + L.z);
  const float r2 = x * x + y * y + z * z;
  const long long ix = static_cast<long long>(floorf(x * inv_leaf)) + kHalf;
  const long long iy = static_cast<long long>(floorf(y * inv_leaf)) + kHalf;
  const long long iz = static_cast<long long>(floorf(z * inv_leaf)) + kHalf;
  const long long lim = 1LL << kBits;
  const bool ok = isfinite(r2) && r2 >= min_r2 && r2 <= max_r2 &&
    ix >= 0 && ix < lim && iy >= 0 && iy < lim && iz >= 0 && iz < lim;
  if (!ok) {
    keys[k] = kInvalid;
    acc[k] = {0.f, 0.f, 0.f, 0.f, 0};
    return;
  }
  keys[k] = (static_cast<Key>(ix) << (2 * kBits)) | (static_cast<Key>(iy) << kBits) |
    static_cast<Key>(iz);
  acc[k] = {x, y, z, L.has_intensity ? read_float(p + L.intensity) : 0.f, 1};
}

__global__ void centroids(const Acc * acc, size_t m, float4 * out)
{
  const size_t k = blockIdx.x * static_cast<size_t>(blockDim.x) + threadIdx.x;
  if (k >= m) {return;}
  const Acc a = acc[k];
  const float inv = 1.f / a.n;
  out[k] = make_float4(a.x * inv, a.y * inv, a.z * inv, a.i * inv);
}

void check(cudaError_t e, const char * what)
{
  if (e != cudaSuccess) {
    throw std::runtime_error(std::string(what) + ": " + cudaGetErrorString(e));
  }
}

template<typename T>
T * raw(thrust::device_vector<T> & v) {return thrust::raw_pointer_cast(v.data());}

}  // namespace

// Buffers persist across calls so steady-state filtering allocates nothing new.
struct GpuVoxelGrid::Impl
{
  cudaStream_t stream{};
  thrust::device_vector<uint8_t> input;
  thrust::device_vector<Key> keys, keys_out;
  thrust::device_vector<Acc> acc, acc_out;
  thrust::device_vector<float4> points;
  size_t count = 0;
};

GpuVoxelGrid::GpuVoxelGrid()
: impl_(std::make_unique<Impl>())
{
  check(cudaStreamCreateWithFlags(&impl_->stream, cudaStreamNonBlocking), "cudaStreamCreate");
}

GpuVoxelGrid::~GpuVoxelGrid()
{
  cudaStreamDestroy(impl_->stream);
}

size_t GpuVoxelGrid::filter(
  const uint8_t * data, size_t n, const CloudLayout & layout,
  float leaf, float min_range, float max_range)
{
  Impl & d = *impl_;
  d.count = 0;
  if (n == 0) {return 0;}
  const size_t bytes = n * layout.point_step;
  if (d.input.size() < bytes) {d.input.resize(bytes);}
  if (d.keys.size() < n) {
    d.keys.resize(n);
    d.keys_out.resize(n);
    d.acc.resize(n);
    d.acc_out.resize(n);
  }
  check(
    cudaMemcpyAsync(raw(d.input), data, bytes, cudaMemcpyHostToDevice, d.stream),
    "copy to GPU");

  const int block = 256;
  const int grid = static_cast<int>((n + block - 1) / block);
  voxelize<<<grid, block, 0, d.stream>>>(
    raw(d.input), n, layout, 1.f / leaf, min_range * min_range, max_range * max_range,
    raw(d.keys), raw(d.acc));
  check(cudaGetLastError(), "voxelize");

  auto policy = thrust::cuda::par.on(d.stream);
  thrust::sort_by_key(policy, d.keys.begin(), d.keys.begin() + n, d.acc.begin());
  auto ends = thrust::reduce_by_key(
    policy, d.keys.begin(), d.keys.begin() + n, d.acc.begin(),
    d.keys_out.begin(), d.acc_out.begin(), thrust::equal_to<Key>(), AccSum());
  size_t m = ends.first - d.keys_out.begin();

  Key last = 0;
  check(
    cudaMemcpyAsync(&last, raw(d.keys_out) + m - 1, sizeof(Key), cudaMemcpyDeviceToHost, d.stream),
    "read last key");
  check(cudaStreamSynchronize(d.stream), "sync");
  if (last == kInvalid) {--m;}
  if (m == 0) {return 0;}

  if (d.points.size() < m) {d.points.resize(m);}
  centroids<<<static_cast<int>((m + block - 1) / block), block, 0, d.stream>>>(
    raw(d.acc_out), m, raw(d.points));
  check(cudaGetLastError(), "centroids");
  d.count = m;
  return m;
}

void GpuVoxelGrid::download(void * dst) const
{
  Impl & d = *impl_;
  if (d.count == 0) {return;}
  check(
    cudaMemcpyAsync(dst, raw(d.points), d.count * sizeof(float4), cudaMemcpyDeviceToHost, d.stream),
    "copy from GPU");
  check(cudaStreamSynchronize(d.stream), "sync");
}

}  // namespace gpu_voxel_filter

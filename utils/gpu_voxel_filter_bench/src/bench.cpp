// GPU vs CPU voxel-grid downsampling on recorded Ouster clouds.
//
//   bench <bag_dir> [topic=/ouster/points] [clouds=300] [leaf=0.1] [min_range=0.3] [max_range=50]
//
// Reads the bag directly (no playback, so no rate limit) and runs both filters on
// every cloud. GPU time includes the copy to and from the GPU; CPU time is the
// range crop + pcl::VoxelGrid, excluding the PointCloud2 -> PCL conversion, which
// a CPU node would also pay but is reported separately.
#include <pcl/filters/voxel_grid.h>
#include <pcl/point_types.h>
#include <pcl_conversions/pcl_conversions.h>

#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdio>
#include <string>
#include <vector>

#include "gpu_voxel_filter/gpu_voxel_grid.hpp"
#include "rclcpp/serialization.hpp"
#include "rosbag2_cpp/reader.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"

using Clock = std::chrono::steady_clock;
using sensor_msgs::msg::PointCloud2;

static double ms_since(Clock::time_point t0)
{
  return std::chrono::duration<double, std::milli>(Clock::now() - t0).count();
}

static void report(const char * name, std::vector<double> v)
{
  std::sort(v.begin(), v.end());
  double mean = 0;
  for (double x : v) {mean += x;}
  mean /= v.size();
  std::printf("%-26s mean %7.2f ms   median %7.2f   p95 %7.2f   max %7.2f\n", name, mean,
    v[v.size() / 2], v[v.size() * 95 / 100], v.back());
}

int main(int argc, char ** argv)
{
  if (argc < 2) {
    std::fprintf(stderr, "usage: %s <bag_dir> [topic] [clouds] [leaf] [min_range] [max_range]\n",
      argv[0]);
    return 1;
  }
  const std::string topic = argc > 2 ? argv[2] : "/ouster/points";
  const size_t clouds = argc > 3 ? std::stoul(argv[3]) : 300;
  const float leaf = argc > 4 ? std::stof(argv[4]) : 0.1f;
  const float min_r = argc > 5 ? std::stof(argv[5]) : 0.3f;
  const float max_r = argc > 6 ? std::stof(argv[6]) : 50.f;
  const size_t warmup = 5;

  rosbag2_cpp::Reader reader;
  reader.open(argv[1]);
  rosbag2_storage::StorageFilter filter;
  filter.topics = {topic};
  reader.set_filter(filter);

  rclcpp::Serialization<PointCloud2> ser;
  gpu_voxel_filter::GpuVoxelGrid grid;
  std::vector<double> t_gpu, t_cpu, t_conv;
  double pts_in = 0, pts_gpu = 0, pts_cpu = 0;
  std::vector<uint8_t> out;

  size_t seen = 0;
  while (reader.has_next() && t_gpu.size() < clouds) {
    auto bag_msg = reader.read_next();
    rclcpp::SerializedMessage raw(*bag_msg->serialized_data);
    PointCloud2 cloud;
    ser.deserialize_message(&raw, &cloud);

    gpu_voxel_filter::CloudLayout layout{cloud.point_step, 0, 0, 0, 0, false};
    for (const auto & f : cloud.fields) {
      if (f.name == "x") {layout.x = f.offset;}
      if (f.name == "y") {layout.y = f.offset;}
      if (f.name == "z") {layout.z = f.offset;}
      if (f.name == "intensity") {layout.intensity = f.offset; layout.has_intensity = true;}
    }
    const size_t n = static_cast<size_t>(cloud.width) * cloud.height;

    auto t0 = Clock::now();
    const size_t m = grid.filter(cloud.data.data(), n, layout, leaf, min_r, max_r);
    out.resize(m * 16);
    grid.download(out.data());
    const double gpu_ms = ms_since(t0);

    t0 = Clock::now();
    pcl::PointCloud<pcl::PointXYZI>::Ptr pc(new pcl::PointCloud<pcl::PointXYZI>);
    pcl::fromROSMsg(cloud, *pc);
    const double conv_ms = ms_since(t0);

    t0 = Clock::now();
    pcl::PointCloud<pcl::PointXYZI>::Ptr cropped(new pcl::PointCloud<pcl::PointXYZI>);
    cropped->reserve(pc->size());
    for (const auto & p : pc->points) {
      const float r2 = p.x * p.x + p.y * p.y + p.z * p.z;
      if (std::isfinite(r2) && r2 >= min_r * min_r && r2 <= max_r * max_r) {
        cropped->push_back(p);
      }
    }
    pcl::VoxelGrid<pcl::PointXYZI> vg;
    vg.setInputCloud(cropped);
    vg.setLeafSize(leaf, leaf, leaf);
    pcl::PointCloud<pcl::PointXYZI> cpu_out;
    vg.filter(cpu_out);
    const double cpu_ms = ms_since(t0);

    if (++seen <= warmup) {continue;}
    t_gpu.push_back(gpu_ms);
    t_cpu.push_back(cpu_ms);
    t_conv.push_back(conv_ms);
    pts_in += n;
    pts_gpu += m;
    pts_cpu += cpu_out.size();
  }
  if (t_gpu.empty()) {
    std::fprintf(stderr, "no clouds read from %s on %s\n", argv[1], topic.c_str());
    return 1;
  }

  const double k = t_gpu.size();
  std::printf("%zu clouds (after %zu warm-up), leaf %.2f m, range %.1f-%.1f m\n",
    t_gpu.size(), warmup, leaf, min_r, max_r);
  std::printf("points per cloud: in %.0f, GPU out %.0f, CPU out %.0f\n",
    pts_in / k, pts_gpu / k, pts_cpu / k);
  report("GPU (incl. copies)", t_gpu);
  report("CPU crop + VoxelGrid", t_cpu);
  report("CPU PointCloud2->PCL", t_conv);
  return 0;
}

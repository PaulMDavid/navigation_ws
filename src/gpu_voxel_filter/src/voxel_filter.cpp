#include <cstring>
#include <memory>
#include <string>

#include "gpu_voxel_filter/gpu_voxel_grid.hpp"
#include "rclcpp/rclcpp.hpp"
#include "rclcpp_components/register_node_macro.hpp"
#include "sensor_msgs/msg/point_cloud2.hpp"
#include "sensor_msgs/point_cloud2_iterator.hpp"

namespace gpu_voxel_filter
{

using sensor_msgs::msg::PointCloud2;
using sensor_msgs::msg::PointField;

// Downsamples a point cloud on the GPU and republishes it as x, y, z, intensity.
// Takes the input as a const shared_ptr and publishes a unique_ptr, so both ends
// are zero-copy when loaded into the same container with intra-process comms.
class VoxelFilter : public rclcpp::Node
{
public:
  explicit VoxelFilter(const rclcpp::NodeOptions & options)
  : Node("voxel_filter", options),
    leaf_(declare_parameter("leaf_size", 0.1)),
    min_range_(declare_parameter("min_range", 0.3)),
    max_range_(declare_parameter("max_range", 50.0))
  {
    pub_ = create_publisher<PointCloud2>(
      declare_parameter("output_topic", std::string("/ouster/points_filtered")), rclcpp::SensorDataQoS());
    sub_ = create_subscription<PointCloud2>(
      declare_parameter("input_topic", std::string("/ouster/points")), rclcpp::SensorDataQoS(),
      [this](PointCloud2::ConstSharedPtr msg) {on_cloud(*msg);});
  }

private:
  void on_cloud(const PointCloud2 & in)
  {
    if (pub_->get_subscription_count() + pub_->get_intra_process_subscription_count() == 0) {
      return;
    }
    CloudLayout layout{in.point_step, 0, 0, 0, 0, false};
    int found = 0;
    for (const auto & f : in.fields) {
      if (f.datatype != PointField::FLOAT32) {continue;}
      if (f.name == "x") {layout.x = f.offset; ++found;}
      if (f.name == "y") {layout.y = f.offset; ++found;}
      if (f.name == "z") {layout.z = f.offset; ++found;}
      if (f.name == "intensity") {layout.intensity = f.offset; layout.has_intensity = true;}
    }
    if (found != 3) {
      RCLCPP_ERROR_THROTTLE(get_logger(), *get_clock(), 5000, "input has no float32 x/y/z");
      return;
    }

    const size_t m = grid_.filter(
      in.data.data(), static_cast<size_t>(in.width) * in.height, layout,
      leaf_, min_range_, max_range_);

    auto out = std::make_unique<PointCloud2>();
    out->header = in.header;
    sensor_msgs::PointCloud2Modifier mod(*out);
    mod.setPointCloud2Fields(
      4, "x", 1, PointField::FLOAT32, "y", 1, PointField::FLOAT32,
      "z", 1, PointField::FLOAT32, "intensity", 1, PointField::FLOAT32);
    mod.resize(m);
    grid_.download(out->data.data());
    out->is_dense = true;
    pub_->publish(std::move(out));
  }

  const float leaf_, min_range_, max_range_;
  GpuVoxelGrid grid_;
  rclcpp::Publisher<PointCloud2>::SharedPtr pub_;
  rclcpp::Subscription<PointCloud2>::SharedPtr sub_;
};

}  // namespace gpu_voxel_filter

RCLCPP_COMPONENTS_REGISTER_NODE(gpu_voxel_filter::VoxelFilter)

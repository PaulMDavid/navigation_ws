// Body pitch against gravity from the IMU orientation -> body_tilt_joint on /joint_states.
// Assumes the drivetrain stands level.

#include <cmath>
#include <memory>
#include <string>

#include <rclcpp/rclcpp.hpp>
#include <rclcpp_components/register_node_macro.hpp>
#include <sensor_msgs/msg/imu.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <tf2/LinearMath/Matrix3x3.h>
#include <tf2/LinearMath/Quaternion.h>
#include <tf2/LinearMath/Vector3.h>
#include <tf2_geometry_msgs/tf2_geometry_msgs.hpp>
#include <tf2_ros/buffer.h>
#include <tf2_ros/transform_listener.h>

namespace app_body_tilt
{

class BodyTilt : public rclcpp::Node
{
public:
  explicit BodyTilt(const rclcpp::NodeOptions & options)
  : Node("body_tilt", options)
  {
    imu_topic_ = declare_parameter<std::string>("imu_topic", "/imu/data");
    joint_name_ = declare_parameter<std::string>("joint_name", "body_tilt_joint");
    body_frame_ = declare_parameter<std::string>("body_frame", "chassis_link");
    frame_mode_ = declare_parameter<std::string>("orientation_frame", "auto");
    pitch_offset_ = declare_parameter<double>("pitch_offset", 0.0);
    const double rate = declare_parameter<double>("publish_rate", 50.0);
    min_period_ = rate > 0.0 ? 1.0 / rate : 0.0;

    if (frame_mode_ == "enu") {
      up_sign_ = 1.0;
    } else if (frame_mode_ == "ned") {
      up_sign_ = -1.0;
    } else if (frame_mode_ != "auto") {
      throw std::invalid_argument("orientation_frame must be auto, enu or ned");
    }

    tf_buffer_ = std::make_shared<tf2_ros::Buffer>(get_clock());
    tf_listener_ = std::make_shared<tf2_ros::TransformListener>(*tf_buffer_);
    pub_ = create_publisher<sensor_msgs::msg::JointState>("joint_states", 10);
    sub_ = create_subscription<sensor_msgs::msg::Imu>(
      imu_topic_, rclcpp::SensorDataQoS(),
      [this](sensor_msgs::msg::Imu::ConstSharedPtr msg) {on_imu(*msg);});
    RCLCPP_INFO(get_logger(), "%s -> %s (body %s, orientation_frame %s)",
      imu_topic_.c_str(), joint_name_.c_str(), body_frame_.c_str(), frame_mode_.c_str());
  }

private:
  void on_imu(const sensor_msgs::msg::Imu & msg)
  {
    if (msg.orientation_covariance[0] == -1.0) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000,
        "%s carries no orientation (covariance[0] == -1)", imu_topic_.c_str());
      return;
    }
    if (!have_mount_ && !lookup_mount(msg.header.frame_id)) {
      return;
    }

    tf2::Quaternion q;
    tf2::fromMsg(msg.orientation, q);
    const double qn = q.length();
    if (!std::isfinite(qn) || qn < 0.5) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000,
        "dropping %s with an invalid orientation quaternion", imu_topic_.c_str());
      return;
    }
    const tf2::Matrix3x3 R(q / qn);
    const tf2::Vector3 z_row = R.getRow(2);  // world z in the sensor frame

    if (up_sign_ == 0.0 && !decide_frame(msg, z_row)) {
      return;
    }

    const rclcpp::Time stamp(msg.header.stamp);
    const double dt = (stamp - last_pub_).seconds();
    if (last_pub_.nanoseconds() > 0 && dt >= 0.0 && dt < min_period_) {
      return;
    }

    const tf2::Vector3 up = mount_ * (z_row * up_sign_);
    const double pitch = std::atan2(-up.x(), up.z()) + pitch_offset_;
    if (std::abs(pitch) > 1.0) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000,
        "body pitch %.0f deg: is the IMU mount (imu_rpy in sensorsuite_front.xacro) right?",
        pitch * 180.0 / M_PI);
    }

    sensor_msgs::msg::JointState js;
    js.header.stamp = msg.header.stamp;
    js.name.push_back(joint_name_);
    js.position.push_back(pitch);
    pub_->publish(js);
    last_pub_ = stamp;
  }

  bool lookup_mount(const std::string & imu_frame)
  {
    try {
      const auto t = tf_buffer_->lookupTransform(body_frame_, imu_frame, tf2::TimePointZero);
      tf2::Quaternion q;
      tf2::fromMsg(t.transform.rotation, q);
      mount_ = tf2::Matrix3x3(q);
      have_mount_ = true;
      RCLCPP_INFO(get_logger(), "IMU mount %s -> %s found", body_frame_.c_str(), imu_frame.c_str());
      return true;
    } catch (const tf2::TransformException & e) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 5000,
        "waiting for TF %s -> %s: %s", body_frame_.c_str(), imu_frame.c_str(), e.what());
      return false;
    }
  }

  // Still, the accelerometer reads +g along up.
  bool decide_frame(const sensor_msgs::msg::Imu & msg, const tf2::Vector3 & z_row)
  {
    tf2::Vector3 a;
    tf2::fromMsg(msg.linear_acceleration, a);
    const double n = a.length();
    if (n > 0.8 * 9.81 && n < 1.2 * 9.81) {
      const double d = z_row.dot(a / n);
      if (d > 0.9) {
        enu_votes_++;
      } else if (d < -0.9) {
        ned_votes_++;
      }
    }
    if (enu_votes_ >= 50 || ned_votes_ >= 50) {
      up_sign_ = enu_votes_ >= 50 ? 1.0 : -1.0;
      RCLCPP_INFO(get_logger(), "orientation is %s referenced (votes enu %d, ned %d)",
        up_sign_ > 0 ? "ENU" : "NED", enu_votes_, ned_votes_);
      return true;
    }
    RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 10000,
      "deciding ENU/NED from the accelerometer, needs the rover still (votes enu %d, ned %d); "
      "set orientation_frame to skip", enu_votes_, ned_votes_);
    return false;
  }

  std::string imu_topic_, joint_name_, body_frame_, frame_mode_;
  double pitch_offset_{0.0}, min_period_{0.0}, up_sign_{0.0};
  int enu_votes_{0}, ned_votes_{0};
  bool have_mount_{false};
  tf2::Matrix3x3 mount_;
  rclcpp::Time last_pub_{0, 0, RCL_ROS_TIME};
  std::shared_ptr<tf2_ros::Buffer> tf_buffer_;
  std::shared_ptr<tf2_ros::TransformListener> tf_listener_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr pub_;
  rclcpp::Subscription<sensor_msgs::msg::Imu>::SharedPtr sub_;
};

}  // namespace app_body_tilt

RCLCPP_COMPONENTS_REGISTER_NODE(app_body_tilt::BodyTilt)

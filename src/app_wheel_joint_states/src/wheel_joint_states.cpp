// /Motor_pos (wheels_cpp MD80 positions, rad) -> /joint_states. Port of aizzaf's
// motor_controller/joint_state_node.py (git.tu-berlin.de/rover/erc25, test_teleop 59b8f93).
// Shafts have no encoder and go out as 0.

#include <array>
#include <cmath>
#include <string>
#include <utility>

#include <rclcpp/rclcpp.hpp>
#include <rclcpp_components/register_node_macro.hpp>
#include <sensor_msgs/msg/joint_state.hpp>
#include <std_msgs/msg/float64_multi_array.hpp>

namespace app_wheel_joint_states
{

// /Motor_pos order: steer 11-14, drive 21-24 (FL FR RL RR). Right drive motors are mirrored.
static const std::array<std::pair<const char *, double>, 8> kMotorJoints{{
  {"steering_fl_joint", +1.0},
  {"steering_fr_joint", +1.0},
  {"steering_rl_joint", +1.0},
  {"steering_rr_joint", +1.0},
  {"wheel_fl_joint", +1.0},
  {"wheel_fr_joint", -1.0},
  {"wheel_rl_joint", +1.0},
  {"wheel_rr_joint", -1.0},
}};
static const std::array<const char *, 2> kShaftJoints{{"shaft_left_joint", "shaft_right_joint"}};

class WheelJointStates : public rclcpp::Node
{
public:
  explicit WheelJointStates(const rclcpp::NodeOptions & options)
  : Node("wheel_joint_states", options)
  {
    const auto topic = declare_parameter<std::string>("motor_pos_topic", "/Motor_pos");

    for (auto n : kShaftJoints) {msg_.name.emplace_back(n);}
    for (auto & j : kMotorJoints) {msg_.name.emplace_back(j.first);}
    msg_.position.assign(msg_.name.size(), 0.0);

    pub_ = create_publisher<sensor_msgs::msg::JointState>("joint_states", 50);
    sub_ = create_subscription<std_msgs::msg::Float64MultiArray>(
      topic, 50, [this](std_msgs::msg::Float64MultiArray::ConstSharedPtr m) {on_motor_pos(*m);});
  }

private:
  void on_motor_pos(const std_msgs::msg::Float64MultiArray & m)
  {
    if (m.data.size() != kMotorJoints.size()) {
      RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
        "dropping /Motor_pos with %zu values, expected %zu", m.data.size(), kMotorJoints.size());
      return;
    }
    for (double v : m.data) {
      if (!std::isfinite(v)) {
        RCLCPP_WARN_THROTTLE(get_logger(), *get_clock(), 2000,
          "dropping /Motor_pos with a non-finite value");
        return;
      }
    }
    for (size_t i = 0; i < kMotorJoints.size(); ++i) {
      msg_.position[kShaftJoints.size() + i] = kMotorJoints[i].second * m.data[i];
    }
    msg_.header.stamp = now();
    pub_->publish(msg_);
  }

  sensor_msgs::msg::JointState msg_;
  rclcpp::Publisher<sensor_msgs::msg::JointState>::SharedPtr pub_;
  rclcpp::Subscription<std_msgs::msg::Float64MultiArray>::SharedPtr sub_;
};

}  // namespace app_wheel_joint_states

RCLCPP_COMPONENTS_REGISTER_NODE(app_wheel_joint_states::WheelJointStates)

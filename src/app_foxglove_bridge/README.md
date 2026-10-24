# app_foxglove_bridge

[foxglove_bridge](https://github.com/foxglove/foxglove-sdk) (Humble apt release, 3.6.0):
the phone app's link to ROS over the Foxglove WebSocket protocol, port 8765,
subprotocol `foxglove.sdk.v1`. Clients may publish JSON-encoded messages, so the phone
app needs no CDR encoder. Runs only when `TELEOP_SOURCE=phone` (see `app_teleop`).

It runs in its own DDS domain (`TELEOP_PHONE_DOMAIN`, 51), because 3.6.0 ignores
`client_topic_whitelist` and would publish any topic a client asks for. Only teleop_mux
joins that domain, so `/teleop/phone/cmd_vel`, `/teleop/phone/set_mode` and
`/teleop/state` are all a client can reach. The whitelist in
`config/foxglove_bridge.yaml` is kept for when upstream honours it again.

Same protocol as the Foxglove app, so the phone (or a laptop on the AP) can also open
`ws://10.42.0.1:8765` in Foxglove to look at what's relayed into the phone domain.

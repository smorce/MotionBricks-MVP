"""足の下降速度と観測した着地間隔から、次の接地までを推定する。"""


def landing_horizon(height, vertical_speed, step_period):
    if height <= .015:
        return 0.0
    if vertical_speed < -.02:
        return min(step_period, height / -vertical_speed)
    return step_period

"""F001の最低限の採用ガードと、人間のための診断を分ける。"""
import math

POLICY = 'prepared-minimum-guards-v1'
REQUIRED_CHECKS = ('bones', 'root', 'feet')
ADVISORY_CHECKS = ('knees', 'ankles', 'support', 'swing', 'idle')


def evaluate_prepared_stop(validation, arrival_error_m, progress_reason):
    checks = validation.get('checks', {})
    failures = []
    warnings = [name for name in ADVISORY_CHECKS if name in checks and not checks[name]['passed']]
    if progress_reason:
        warnings.append('progress')
    if not checks or 'rotation_peak' not in validation:
        failures.append('invalid_motion')
    else:
        failures.extend(name for name in REQUIRED_CHECKS if not checks.get(name, {}).get('passed', False))
        if not validation['bone_lengths_valid'] and 'bones' not in failures:
            failures.append('bones')
        angle = validation['rotation_peak']['angle_rad']
        if not math.isfinite(angle) or angle > .35:
            failures.append('joint_continuity')
        if not checks.get('swing', {}).get('landed', False):
            failures.append('terminal_contact')
    if not math.isfinite(arrival_error_m) or arrival_error_m > .05 + 1e-9:
        failures.append('destination')
    return dict(policy=POLICY, accepted=not failures, hard_failures=failures,
                warnings=warnings, reason='Prepared stop guard failed: '+', '.join(failures) if failures else '')

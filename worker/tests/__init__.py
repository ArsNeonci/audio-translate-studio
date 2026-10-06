from audio_translate.core import edition

# Tests run as the full-featured edition unless a test sets edition._cached itself; this keeps
# tests that patch subprocess.run from routing the native edition query into their fakes.
edition._cached = 'plus'

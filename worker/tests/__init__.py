import os

# The community moderation list is put in at the first read; tests start from an empty list (test_community_rules.py covers the seeding).
os.environ['AUDIO_NO_RULE_SEED'] = '1'

from audio_translate.core import edition

# Tests run as the full-featured edition unless a test sets edition._cached itself; this keeps
# tests that patch subprocess.run from routing the native edition query into their fakes.
edition._cached = 'plus'

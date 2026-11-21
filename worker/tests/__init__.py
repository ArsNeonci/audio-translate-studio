import os

# The community moderation list is put in at the first read; tests start from an empty list (test_community_rules.py covers the seeding).
os.environ['AUDIO_NO_RULE_SEED'] = '1'


# No test reads the signed address file from the Internet; core/endpoint.py is tested with its own copies (test_endpoint.py).
os.environ['AUDIO_ENDPOINT_MIRRORS'] = ''

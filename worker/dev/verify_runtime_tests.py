"""Regression runner with an isolated ASR policy; safe Windows spawn entrypoint."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from audio_translate.core import memory_policy


def main():
    names=['tests.test_'+n for n in ('compute_settings','translation_runtime','translation_server','tts_runtime','postprocess',
           'workflow_lifecycle','workflow_admission','memory_policy','resume','providers')]
    with tempfile.TemporaryDirectory() as directory:
        config=Path(directory)/'asr-test.json'
        config.write_text(json.dumps(dict(start_free_gib=4.5,extra_worker_gib=3.0,max_workers=0,pressure_reserve_gib=1.5)),encoding='utf8')
        with patch.object(memory_policy,'CONFIG',config):
            result=unittest.TextTestRunner(verbosity=1).run(unittest.TestLoader().loadTestsFromNames(names))
    raise SystemExit(not result.wasSuccessful())


if __name__=='__main__':main()

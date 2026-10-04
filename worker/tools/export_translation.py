"""Export completed translation checkpoints while a job runs or is paused."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))  # worker/ import root
import argparse
import json
from pathlib import Path
from audio_translate.workflow.postprocess import export_translation_partial

if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--job',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(export_translation_partial(args.job),ensure_ascii=False))

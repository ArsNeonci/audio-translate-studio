"""Offline Hy-MT2 GGUF translation with self-contained prompts and durable parts."""
import hashlib
import math
import os
from pathlib import Path
import re
import time

from audio_translate.core.control import Cancelled, check_cancel, complete_task
from audio_translate.core.storage import ROOT, atomic_json

# Hy-MT2-7B Q4_K_M (tencent/Hy-MT2-7B-GGUF @ ab84726): accuracy over speed on ~5 GiB free RAM.
MODEL_NAME = 'Hy-MT2-7B-Q4_K_M.gguf'
MODEL_DIRECTORY = 'Hy-MT2-7B-Q4_K_M'
MODEL_SHA256 = '9f96256500f3fc1ab4d64336b58f52a949a95ad7516b0c229476eef782f9f77b'
BOS = '<｜hy_begin▁of▁sentence｜>'
USER = '<｜hy_User｜>'
ASSISTANT = '<｜hy_Assistant｜>'
EOS = '<｜hy_place▁holder▁no▁2｜>'
END = '<｜hy_End▁of▁sentence｜>'
STOP = [EOS, END]
# The GGUF's own chat template decides the turn tokens. Hy-MT2-1.8B uses the hy_* tokens;
# Hy-MT2-7B uses the Hunyuan template (<|startoftext|>user<|extra_0|> ... <|eos|>), and the
# hy_* strings are plain text to it (it then often ended at once: 1-token outputs).
CHAT_FORMATS = {
    'hy-mt2': (BOS + USER, ASSISTANT, STOP),
    'hunyuan': ('<|startoftext|>', '<|extra_0|>', ['<|eos|>', END]),
}


def chat_format(metadata):
    return 'hunyuan' if '<|extra_0|>' in (metadata or {}).get('tokenizer.chat_template', '') else 'hy-mt2'

# Tencent's official zh->xx template, without background blocks: with long or even
# 60-character context the 1.8B model translated the context instead of the
# source (workflow 000007 rows 553/567/570). Each attempt changes the instruction,
# temperature and seed; a rejected draft is never fed back into the prompt.
# Asset 1 (translation prompt/strategy): templates live in the encrypted vault
# (`translation-prompts`), loaded through the security service, with a plaintext dev fallback
# (`worker/config/translation-prompts.json`). The exact strings are preserved so checkpoint
# fingerprints stay valid.
from functools import lru_cache as _lru_cache


@_lru_cache(maxsize=1)
def _prompts():
    from audio_translate.core import vault
    data = vault.load_json('translation-prompts', ROOT / 'worker' / 'config' / 'translation-prompts.json')
    if data.get('version') != 1 or not isinstance(data.get('strategies'), list) or not data['strategies']:
        raise ValueError('Invalid translation prompts')
    strategies = tuple((s['name'], s['prompt'], s['temperature']) for s in data['strategies'])
    return {'strategies': strategies, 'group_prompt': data['group_prompt'],
            'group_temperatures': tuple(data['group_temperatures'])}


def strategies():
    return _prompts()['strategies']


def prompt_text():
    return strategies()[0][1]


def group_prompt():
    return _prompts()['group_prompt']


def group_temperatures():
    return _prompts()['group_temperatures']


QUARANTINE_STREAK = 5

# Sentence mode: consecutive subtitle rows are translated together with <sN> markers
# (Hunyuan's formatted-translation template), then split back to the original rows and
# timestamps. Measured on workflow 000007: tags kept for 18/19 groups without and 24/24
# with a name glossary; rows cut mid-sentence by ASR read naturally again.
SEGMENTATION = 'sentence-v1'
GROUP_ROWS, GROUP_CHARS, GROUP_ROW_CHARS = 6, 120, 80
SENTENCE_END = '。！？!?…'
# GROUP_PROMPT and GROUP_TEMPERATURES moved to the vault asset `translation-prompts`
# (see strategies()/group_prompt()/group_temperatures() above).


class GroupFailure(RuntimeError):
    """The group could not be aligned; its rows fall back to row-by-row translation."""
LABEL = re.compile(r'^\s*[\[【][^\]】\n]{1,40}[\]】]')


class TranslationFailure(RuntimeError):
    def __init__(self, message, attempts):
        super().__init__(message)
        self.attempts = attempts


def output_problem(result, source):
    if not result or any(token in result for token in ('<think>', '</think>', '<|im_', '<｜hy_', '<|eos|>', '<|extra_', '<|startoftext|>')):
        return 'empty text or reasoning/control tokens'
    if re.search(r'[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U000323af]', result):
        return 'untranslated Chinese'
    # Reject leaked prompt sections, while allowing labels that actually occur in the source.
    for label in ('[Background Information]', '[Source Text]', '[Draft to correct]',
                  '[Thông tin cơ bản]', '[Thông tin nền]', '[Văn bản nguồn]'):
        if label.casefold() in result.casefold() and label.casefold() not in source.casefold():
            return 'additional prompt/explanation content'
    if LABEL.match(result) and not LABEL.match(source):
        return 'additional prompt/explanation content'
    # A subtitle row becoming several paragraphs means the model translated something else.
    if '\n' in result.strip() and '\n' not in source and len(source) <= 120:
        return 'additional prompt/explanation content'
    # Old-prompt cache held single-line translations of the whole background (e.g. 5 source
    # characters -> 1,200); real rows stay below ~10x and 80 characters (workflow 000007).
    if len(source) <= 120 and len(result) > max(80, 12 * len(source)):
        return 'output much longer than the source'
    return None


def gender_problem(source, result, names=()):
    """Soft check for a subject the model invented.

    With exactly one 他/她 and no known name in the Chinese row, pronouns of both genders in
    the Vietnamese cannot all be right ("可能是和她男朋友在一起吧" -> "anh ấy ... của cô ấy").
    Only the disagreement is flagged: ASR writes 他/她 unreliably, so the pronoun's own
    gender is never enforced here (repair uses the character sheet instead).
    """
    if len(re.findall('[他她]', source)) != 1 or any(name and name in source for name in names):
        return None
    from audio_translate.moderation.address import GENDER_OF, THIRD_RE
    genders = {GENDER_OF.get(m.group(1).lower()) for m in THIRD_RE.finditer(result)} - {None}
    return 'pronoun genders disagree' if len(genders) > 1 else None


TO_FEMALE = {'anh ấy': 'cô ấy', 'anh ta': 'cô ta', 'ông ấy': 'bà ấy', 'ông ta': 'bà ta', 'cậu ấy': 'cô ấy', 'cậu ta': 'cô ta',
             'hắn': 'cô ta', 'gã': 'ả'}
TO_MALE = {'cô ấy': 'anh ấy', 'cô ta': 'anh ta', 'chị ấy': 'anh ấy', 'chị ta': 'anh ta', 'bà ấy': 'ông ấy', 'bà ta': 'ông ta', 'ả': 'hắn'}


def harmonize_gender(source, result):
    """Last resort when every attempt mixed genders for a single 他/她: follow the Chinese pronoun.

    The draft is wrong somewhere already (one person cannot be both), so aligning it with the
    source's own pronoun cannot make it worse; the model repeats this slip across seeds.
    """
    marks = re.findall('[他她](?!们)', source)
    if len(marks) != 1: return result
    from audio_translate.moderation.address import GENDER_OF, THIRD_RE
    table = TO_FEMALE if marks[0] == '她' else TO_MALE
    wrong = 'male' if marks[0] == '她' else 'female'

    def swap(match):
        token = match.group(1)
        if GENDER_OF.get(token.lower()) != wrong: return token
        new = table[token.lower()]
        return new[:1].upper() + new[1:] if token[:1].isupper() else new
    return THIRD_RE.sub(swap, result)


def output_budget(source, maximum):
    """Hy-MT2 needs about 2-3 tokens per Chinese character; leave a wide margin."""
    return min(maximum, 48 + 6 * len(source))


def attempt_seed(source, recovery, attempt):
    # Depends on the text only, never on slot, completion order or wall clock.
    base = int(hashlib.sha256(source.encode('utf-8')).hexdigest()[:8], 16) % 100000
    return base + recovery * 101 + attempt


def physical_cores():
    import psutil
    return psutil.cpu_count(logical=False) or 4


def default_settings():
    return {
        'backend': 'hy-mt2-gguf',
        'model': os.getenv('HY_MT_MODEL_PATH', str(ROOT / 'models' / MODEL_DIRECTORY / MODEL_NAME)),
        'model_sha256': MODEL_SHA256, 'source_lang': 'zh', 'target_lang': 'vi',
        'device': 'cpu', 'batch_size': int(os.getenv('HY_MT_BATCH_SIZE', '4')),
        'source_tokens': int(os.getenv('HY_MT_SOURCE_TOKENS', '768')),
        'output_tokens': int(os.getenv('HY_MT_OUTPUT_TOKENS', '1536')),
        'context_tokens': 256, 'context_chars': 512,
        # 3072 per slot with q8_0 KV keeps 7B weights + cache near 5.3 GiB; lower to 2048 if RAM is tight.
        'n_ctx': int(os.getenv('HY_MT_CONTEXT_SIZE', '3072')), 'kv_cache_type': os.getenv('HY_MT_KV_CACHE_TYPE', 'q8_0'),
        'n_batch': 128, 'n_gpu_layers': 0,
        'threads': int(os.getenv('AI_NUM_THREADS', '0')) or physical_cores(),
        'cpu_target': float(os.getenv('HY_MT_CPU_TARGET', '85')),
        'min_available_gib': float(os.getenv('HY_MT_MIN_AVAILABLE_GIB', '1')),
        'startup_available_gib': float(os.getenv('HY_MT_STARTUP_AVAILABLE_GIB', '6')),
        'memory_wait_seconds': float(os.getenv('HY_MT_MEMORY_WAIT_SECONDS', '120')),
        'glossary': [], 'prompt': prompt_text(), 'segmentation': 'sentence', 'version': 7,
    }


class TranslationAdapter:
    def __init__(self, settings):
        self.settings = settings
        self.model = None
        self.job_dir = None
        self.runtime = None
        self.names = []
        self.lexicon = []  # genre terminology, set per job; [{source, target}]
        self.gender_check = False  # soft retry of inconsistent pronouns, set per job
        if settings.get('backend') != 'hy-mt2-gguf':
            raise ValueError('Translation requires the hy-mt2-gguf backend')
        for key in ('batch_size', 'source_tokens', 'output_tokens', 'n_ctx', 'n_batch', 'threads', 'context_tokens', 'context_chars'):
            value = settings.get(key)
            if type(value) is not int or value < 1:
                raise ValueError(f'Invalid translation {key}')
        if settings['batch_size'] > 8 or settings['source_tokens'] < 8:
            raise ValueError('Invalid translation batch_size/source_tokens')
        if settings['source_tokens'] + settings['output_tokens'] + settings['context_tokens'] + 512 > settings['n_ctx']:
            raise ValueError('Translation context is too small for input, prompt and output')
        for key in ('cpu_target', 'min_available_gib', 'startup_available_gib', 'memory_wait_seconds'):
            value = settings.get(key)
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
                raise ValueError(f'Invalid translation {key}')
        if settings['cpu_target'] > 100 or type(settings.get('n_gpu_layers')) is not int or settings['n_gpu_layers'] < 0:
            raise ValueError('Invalid translation cpu_target/n_gpu_layers')
        if not isinstance(settings.get('prompt'), str) or not settings['prompt'].strip():
            raise ValueError('Invalid translation prompt')
        if settings.get('segmentation', 'sentence') not in ('sentence', 'row'):
            raise ValueError('Invalid translation segmentation')
        if not isinstance(settings.get('glossary'), list):
            raise ValueError('Invalid translation glossary')
        for item in settings['glossary']:
            if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k] for k in ('source', 'target')):
                raise ValueError('Invalid translation glossary entry')

    def wait_memory(self, minimum, phase):
        import psutil
        from audio_translate.core.memory_policy import commit_available, GIB
        began = time.monotonic()
        job = self.job_dir or os.getenv('AUDIO_ACTIVE_JOB')
        while True:
            check_cancel(job)
            available = psutil.virtual_memory().available
            commit = commit_available()
            needed = minimum * GIB
            from audio_translate.core import lanes
            if available >= minimum * GIB and (commit is None or commit >= needed):
                lanes.waiting(job, 0)
                return
            keep_waiting = lanes.waiting(job, needed)
            waited = time.monotonic() - began
            if job:
                atomic_json(Path(job) / 'working' / 'translation-runtime.json', {
                    'state': 'WAITING_MEMORY', 'backend': 'hy-mt2-gguf', 'phase': phase,
                    'available_gib': round(available / GIB, 2), 'required_available_gib': minimum,
                    'wait_seconds': round(waited, 1),
                    'wait_timeout_seconds': self.settings['memory_wait_seconds'],
                })
            if waited >= self.settings['memory_wait_seconds'] and keep_waiting:
                pass  # later workflows are shrinking or pausing for this one
            elif waited >= self.settings['memory_wait_seconds'] and job and lanes.others_running(job):
                lanes.waiting(job, 0)
                lanes.auto_pause(job, reason='translation_memory_timeout')
                raise Cancelled('Translation paused while other workflows hold memory; it resumes automatically')
            elif waited >= self.settings['memory_wait_seconds']:
                if job:
                    atomic_json(Path(job) / 'working' / 'cancel.signal', {'mode': 'pause', 'reason': 'translation_memory_timeout'})
                    raise Cancelled('Translation paused while waiting for Hy-MT2 memory; checkpoints preserved')
                raise RuntimeError('Hy-MT2 translation memory wait timed out')
            time.sleep(2)

    def load(self):
        if self.model is not None:
            return
        path = Path(self.settings['model'])
        if not path.is_file():
            raise FileNotFoundError('Hy-MT2 GGUF model not found; run worker/tools/download_translation_model.py')
        from audio_translate.translation.translation_server import policy
        self.wait_memory(policy()['start_free_gib'], 'MODEL_LOADING')
        if self.job_dir:
            atomic_json(Path(self.job_dir)/'working'/'translation-runtime.json', {'state':'MODEL_LOADING','device':self.settings.get('device','cpu')})
        from llama_cpp import Llama
        from audio_translate.translation.translation_server import policy, executable, Runtime
        config = policy()
        gpu = self.settings.get('device') == 'gpu'
        if gpu:
            from audio_translate.core.compute_settings import validate
            validate('gpu', ['translation'])
            from audio_translate.translation.translation_server import gpu_memory, GIB
            required = path.stat().st_size + (.4 + config['vram_reserve_gib'] + config['safety_gib']) * GIB
            if gpu_memory(self.settings)['free'] < required:
                if self.job_dir:
                    atomic_json(Path(self.job_dir)/'working'/'translation-runtime.json', {'state':'WAITING_MEMORY', 'phase':'GPU_MODEL_LOADING', 'required_vram_gib':required/GIB})
                    atomic_json(Path(self.job_dir)/'working'/'cancel.signal', {'mode':'pause', 'reason':'translation_vram'})
                raise Cancelled('Translation paused while waiting for GPU memory; checkpoints preserved')
        from audio_translate.translation.translation_server import server_gpu_available
        use_server = config['engine'] != 'embedded' and executable().is_file() and (not gpu or server_gpu_available())
        if use_server:
            self.model = Llama(model_path=str(path), vocab_only=True, verbose=False)
            self.runtime = Runtime(self)
            try: self.runtime.start()
            except BaseException:
                self.close(); raise
            return
        if config['engine'] == 'server':
            raise RuntimeError('Compatible llama-server missing; GPU needs a CUDA-enabled helper (HY_MT_SERVER_PATH)')
        self.model = Llama(
            model_path=str(path), n_ctx=self.settings['n_ctx'], n_batch=self.settings['n_batch'],
            n_threads=self.settings['threads'], n_threads_batch=self.settings['threads'],
            n_gpu_layers=self.settings['n_gpu_layers'], use_mmap=True, use_mlock=False, verbose=False,
        )

    def close(self):
        if self.runtime:
            self.runtime.close(); self.runtime = None
        if self.model and hasattr(self.model, 'close'):
            self.model.close(); self.model = None

    def window_size(self):
        from audio_translate.translation.translation_server import policy
        import psutil
        # Bounded read-ahead supplies enough independent rows for larger machines.
        maximum = min(psutil.cpu_count(logical=False) or 1, policy()['max_slots'] or (psutil.cpu_count(logical=False) or 1))
        return max(self.settings['batch_size'], 2 * maximum)

    def token_count(self, text):
        return len(self.model.tokenize(text.encode('utf-8'), add_bos=False, special=False))

    def parts(self, text):
        # Keep adjacent sentences together; split only when the token budget requires it.
        limit = self.settings['source_tokens']
        while text:
            if len(text) <= limit * 8 and self.token_count(text) <= limit:
                yield text
                return
            low, high, cut = 1, min(len(text) - 1, limit * 8), 0
            while low <= high:
                middle = (low + high) // 2
                if self.token_count(text[:middle]) <= limit:
                    cut = middle
                    low = middle + 1
                else:
                    high = middle - 1
            if not cut:
                raise RuntimeError('Hy-MT2 cannot split oversized input safely')
            boundaries = [m.end() for m in re.finditer(r'[。！？!?；，;,:：\s]+[”’"）)]*', text[:cut])]
            if boundaries and boundaries[-1] >= max(1, cut // 2):
                cut = boundaries[-1]
            yield text[:cut]
            text = text[cut:]

    def name_sources(self):
        return [item['source'] for item in (*self.settings['glossary'], *self.names) if item.get('source')]

    def terms(self, text):
        """Configured glossary first, then the job's detected names, limited to those in `text`."""
        chosen = {}
        for item in list(self.settings['glossary']) + list(getattr(self, 'names', [])):
            if item['source'] in text and item['source'] not in chosen:
                chosen[item['source']] = item['target']
        for item in self.lexicon:
            if item['source'] in text and item['source'] not in chosen:
                chosen[item['source']] = item['target']
        # 倩倩 is redundant inside 张倩倩 unless it also occurs on its own.
        return [(source, target) for source, target in chosen.items()
                if not any(source != other and source in other and source not in text.replace(other, '')
                           for other in chosen)]

    def glossary_block(self, text):
        terms = self.terms(text)
        return '参考下面的翻译：\n' + '\n'.join(f'{source} 翻译成 {target}' for source, target in terms) + '\n\n' if terms else ''

    def prompt(self, source, context='', strategy=0):
        """Official Hy-MT2 single user turn: optional terminology, instruction, source.

        `context` is accepted for checkpoint-key compatibility but deliberately not sent.
        `settings['prompt']` only identifies the job's fingerprint; the template lives here.
        """
        user = self.glossary_block(source) + strategies()[strategy][1] + '\n\n' + source
        user = re.sub(r'<[|｜]([^<>]+)[|｜]>', r'〈\1〉', user)
        return self.wrap(user)

    def group_prompt(self, texts):
        source = ''.join(f'<s{index}>{text}</s{index}>' for index, text in enumerate(texts, 1))
        user = re.sub(r'<[|｜]([^<>]+)[|｜]>', r'〈\1〉', self.glossary_block(''.join(texts)) + group_prompt())
        return self.wrap(user + '\n\n<source>' + source + '</source>')

    def chat(self):
        return CHAT_FORMATS[chat_format(getattr(self.model, 'metadata', None))]

    def wrap(self, user):
        start, end, _ = self.chat()
        return start + user + end

    def complete(self, prompt, slot, budget, seed, temperature):
        """One generation; returns (text, stopped normally)."""
        if self.runtime:
            result, final = self.runtime.server.completion(prompt, slot, budget, lambda: check_cancel(self.job_dir),
                                                           seed=seed, temperature=temperature, stop=self.chat()[2])
            return result, (final.get('stop_type') in ('eos', 'word') and not final.get('stopped_limit')
                            and not final.get('truncated'))
        pieces, reason = [], None
        stream = self.model.create_completion(prompt, max_tokens=budget, temperature=temperature, top_p=.6, top_k=20,
                                              repeat_penalty=1.05, seed=seed, stop=self.chat()[2], stream=True)
        try:
            for chunk in stream:
                check_cancel(self.job_dir)
                choice = chunk['choices'][0]
                pieces.append(choice['text'])
                reason = choice.get('finish_reason') or reason
        finally:
            stream.close()
        text = ''.join(pieces)
        for token in self.chat()[2]: text = text.replace(token, '')
        return text.strip(), reason == 'stop'

    @staticmethod
    def split_group(result, texts):
        """Aligned row translations from `<sN>` markers, or a reason for falling back."""
        body = re.sub(r'^\s*<target>|</target>\s*$', '', result.strip())
        values = []
        for index, text in enumerate(texts, 1):
            found = re.search(fr'<s{index}>(.*?)</s{index}>', body, re.S)
            if not found:
                return None, 'missing segment marker'
            value = ' '.join(found.group(1).split())
            if not value and text.strip():
                return None, 'empty segment'
            if re.search(r'</?s\d+>|</?(source|target)>', value):
                return None, 'nested segment marker'
            problem = output_problem(value, text) if text.strip() else None
            if problem:
                return None, problem
            values.append(value)
        if re.search(fr'<s{len(texts) + 1}>', body):
            return None, 'extra segment marker'
        leftover = re.sub(r'<s(\d+)>.*?</s\1>', '', body, flags=re.S).strip()
        if leftover:
            return None, 'text outside segment markers'
        return values, None

    @complete_task
    def infer_group(self, texts, slot=0):
        """Translate consecutive rows as one sentence; raises GroupFailure to fall back."""
        check_cancel(self.job_dir)
        joined = ''.join(texts)
        budget = min(self.settings['output_tokens'], 64 + 8 * len(joined))
        prompt = self.group_prompt(texts)
        if len(self.model.tokenize(prompt.encode('utf-8'), add_bos=False, special=True)) + budget > self.settings['n_ctx']:
            raise GroupFailure('group exceeds context budget')
        reasons = []
        for attempt, temperature in enumerate(group_temperatures()):
            result, complete = self.complete(prompt, slot, budget, attempt_seed(joined, 0, attempt), temperature)
            values, problem = self.split_group(result, texts) if complete else (None, 'output exceeded the length budget')
            if values is not None:
                if not self.gender_check or not any(gender_problem(t, v, self.name_sources()) for t, v in zip(texts, values)):
                    return values
                problem = 'pronoun genders disagree'  # aligned but inconsistent: retry, then rows one by one
            reasons.append(problem)
        # Row prompts have no neighbours to borrow a wrong subject from, and `infer` itself
        # keeps its first draft when every attempt disagrees, so this never fails a row.
        raise GroupFailure('; '.join(reasons))

    @complete_task
    def infer(self, source, context, slot=0, recovery=0):
        import psutil
        from llama_cpp import llama_set_n_threads
        check_cancel(self.job_dir)
        if not self.runtime:
            from audio_translate.translation.translation_server import policy
            from audio_translate.translation.translation_server import pressure as resource_pressure
            minimum = max(policy()['reserve_gib'], self.settings['min_available_gib'])
            from audio_translate.core.memory_policy import commit_available
            commit = commit_available()
            health = resource_pressure(self.settings)
            if psutil.virtual_memory().available < minimum * 1024**3 or (commit is not None and commit < minimum * 1024**3) or health['low_vram'] or health['hot']:
                self.close()
                if self.job_dir:
                    atomic_json(Path(self.job_dir)/'working'/'translation-runtime.json', {'state':'WAITING_TEMPERATURE' if health['hot'] else 'WAITING_MEMORY', 'required_available_gib':policy()['start_free_gib']})
                    atomic_json(Path(self.job_dir)/'working'/'cancel.signal', {'mode':'pause', 'reason':'translation_temperature' if health['hot'] else 'translation_memory_reserve'})
                raise Cancelled('Translation paused under resource pressure; model released and checkpoints preserved')
        battery = psutil.sensors_battery()
        target = min(self.settings['cpu_target'], 65) if battery and not battery.power_plugged else self.settings['cpu_target']
        pressure = (psutil.cpu_percent(interval=.05) >= target or psutil.virtual_memory().available < self.settings['min_available_gib'] * 1024**3) if not self.runtime else False
        threads = max(1, self.settings['threads'] // 2) if pressure else self.settings['threads']
        if not self.runtime: llama_set_n_threads(self.model.ctx, threads, threads)
        attempts, soft = [], None
        budget = output_budget(source, self.settings['output_tokens'])
        for attempt, (strategy, _, temperature) in enumerate(strategies()):
            seed = attempt_seed(source, recovery, attempt)
            prompt = self.prompt(source, context, attempt)
            input_tokens = len(self.model.tokenize(prompt.encode('utf-8'), add_bos=False, special=True))
            if input_tokens + budget > self.settings['n_ctx']:
                raise RuntimeError('Hy-MT2 prompt/glossary exceeds context budget; reduce source_tokens or glossary')
            if self.job_dir and not self.runtime:
                atomic_json(Path(self.job_dir) / 'working' / 'translation-runtime.json', {
                    'state': 'RUNNING', 'backend': 'hy-mt2-gguf', 'batch_size': 1,
                    'input_tokens': input_tokens, 'threads': threads, 'cpu_target': target,
                    'throttled': pressure, 'repair_attempt': attempt,
                })
            result, complete = self.complete(prompt, slot, budget, seed, temperature)
            # Hitting the length budget means a runaway answer, not a long translation.
            problem = output_problem(result, source) if complete else 'output exceeded the length budget'
            if problem is None:
                if self.gender_check and gender_problem(source, result, self.name_sources()):
                    soft = soft or result
                    continue
                return result
            attempts.append(dict(seed=seed, draft=result[:2000], reason=problem, strategy=strategy))
        if soft is not None:
            return harmonize_gender(source, soft)
        raise TranslationFailure(f'Hy-MT2 returned {problem} after three attempts; checkpoint not saved', attempts)

    def translate_checkpointed(self, texts, lookup=None, save=None, save_row=None, contexts=None):
        if not any(text.strip() for text in texts):
            return ['' for _ in texts]
        self.load()
        contexts = contexts if contexts is not None else [''] * len(texts)
        if len(contexts) != len(texts):
            raise ValueError('Translation context count mismatch')
        if self.runtime:
            return self._parallel(texts, contexts, lookup, save, save_row)
        results = []
        for owner, text in enumerate(texts):
            translated = []
            previous = contexts[owner]
            for part_id, source in enumerate(self.parts(text)):
                check_cancel(self.job_dir)
                value = lookup(owner, part_id, source) if lookup else None
                if value is None:
                    value = self.infer(source, previous) if source.strip() else ''
                    if save:
                        save(owner, part_id, source, value)
                translated.append(value)
                previous = (previous + source)[-self.settings['context_chars']:]
            result = ' '.join(value for value in translated if value)
            if save_row:
                save_row(owner, result)
            results.append(result)
        return results

    def translate_stream(self, entries, lookup, save, save_row, fail_row):
        """Bounded reorder queue. Only the coordinator calls durable callbacks.

        Entries are (row ID, source, context, cached result, recovery generation).
        A completed row occupies its place until the contiguous head is released.
        """
        from collections import deque
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
        from audio_translate.core.control import stop_mode
        import psutil

        entries = iter(entries)
        queue, states, ready, running = deque(), {}, deque(), {}
        exhausted, failure = False, None
        # Rows that exhausted every strategy are set aside so the rest of the file keeps
        # translating; Continue retries only them. Consecutive failures mean the model
        # or runtime is broken, so the stage stops instead of burning through every row.
        quarantined, streak = [], 0
        # Rows collected until the sentence ends; dispatched as one tagged group task.
        pending = []
        grouping = self.settings.get('segmentation', 'sentence') == 'sentence'
        self.group_stats = dict(groups=0, grouped_rows=0, fallbacks=0)

        def flush():
            if len(pending) > 1:
                ready.append((pending[0][0], -1, tuple(text for _, text in pending), tuple(owner for owner, _ in pending), 0))
            elif pending:
                advance(pending[0][0])
            pending.clear()

        def advance(owner):
            state = states[owner]
            while True:
                source = next(state['parts'], None)
                if source is None:
                    result = ' '.join(state['output'])
                    save_row(owner, result)
                    state['done'] = True
                    return
                part = len(state['output'])
                value = lookup(owner, part, source)
                if value is None and source.strip():
                    ready.append((owner, part, source, state['context'], state['recovery']))
                    return
                state['output'].append(value or '')
                state['context'] = (state['context'] + source)[-self.settings['context_chars']:]

        def refill():
            nonlocal exhausted
            while not exhausted:
                slots = self.runtime.slots if self.runtime else 1
                # Read-ahead is counted in rows; a group may finish its sentence past the limit.
                limit = max(2, 2 * slots) * (GROUP_ROWS if grouping else 1)
                if len(queue) >= limit and not pending:
                    break
                entry = next(entries, None)
                if entry is None:
                    exhausted = True
                    flush()
                    break
                owner, text, context, cached, recovery = entry
                queue.append(owner)
                states[owner] = dict(done=cached is not None, context=context, output=[], recovery=recovery)
                if cached is None:
                    self.load()
                    if recovery and self.runtime:
                        self.runtime.slots = 1
                    states[owner]['parts'] = iter(self.parts(text))
                    # Continue retries a failed row on its own; long rows keep token-based parts.
                    if grouping and not recovery and text.strip() and len(text) <= GROUP_ROW_CHARS:
                        pending.append((owner, text))
                        if (text.rstrip()[-1:] in SENTENCE_END or len(pending) >= GROUP_ROWS
                                or sum(len(value) for _, value in pending) >= GROUP_CHARS):
                            flush()
                    else:
                        flush()
                        advance(owner)
                else:
                    flush()
                    save_row(owner, cached, cached=True)
                # Cached prefix can be consumed without growing the queue.
                while queue and states[queue[0]]['done']:
                    del states[queue.popleft()]

        maximum = psutil.cpu_count(logical=False) or 1
        with ThreadPoolExecutor(max_workers=maximum) as executor:
            while True:
                mode = stop_mode(self.job_dir)
                if mode in ('cancel', 'abort'):
                    for future in running: future.cancel()
                    raise Cancelled('Processing cancelled by user')
                if self.runtime and failure is None:
                    self.runtime.observe()
                if not mode and failure is None:
                    refill()
                recovering = any(state['recovery'] and not state['done'] for state in states.values())
                draining = self.runtime and (getattr(self.runtime, 'admission_blocked', False) or
                                              (hasattr(self.runtime, 'needs_drain') and self.runtime.needs_drain()))
                if not running and ready and not mode and failure is None and self.runtime:
                    self.runtime.tune_between_batches(list(ready)[:1] if recovering else list(ready))
                    draining = False
                slots = 1 if recovering else self.runtime.slots if self.runtime else 1
                free = sorted(set(range(slots)) - {item[1] for item in running.values()})
                free = free[:max(0, slots-len(running))]
                while ready and free and not mode and failure is None and not draining:
                    # Continue finishes the failed row before admitting unrelated rows.
                    task = next((item for item in ready if item[4]), ready[0]) if recovering else ready[0]
                    ready.remove(task)
                    slot = free.pop(0)
                    if task[1] == -1:
                        future = executor.submit(self.infer_group, task[2], slot)
                    else:
                        future = executor.submit(self.infer, task[2], task[3], slot, task[4])
                    running[future] = (task, slot)
                if not running:
                    if failure: raise failure
                    if mode: raise Cancelled('Translation paused; completed checkpoints preserved')
                    if exhausted and not queue:
                        if quarantined:
                            rows = '; '.join(f'row {owner}: {reason}' for owner, reason in sorted(quarantined)[:10])
                            raise TranslationFailure(f'{len(quarantined)} row(s) still fail after three attempts '
                                                     f'({rows}); all other rows are saved. Use Continue to retry them.', [])
                        return
                    if not ready:
                        raise RuntimeError('Translation reorder queue stalled')
                    continue
                done, _ = wait(running, timeout=.2, return_when=FIRST_COMPLETED)
                # Observe failures before any callbacks can admit more work.
                successes, fallbacks = [], []
                for future in sorted(done, key=lambda f: running[f][0][:2]):
                    task, slot = running.pop(future)
                    owner, part, source, _, _ = task
                    if part == -1:
                        try:
                            successes.append((task, future.result()))
                        except Cancelled as exc:
                            failure = failure or exc
                        except GroupFailure:
                            fallbacks.append(task)
                        except Exception as exc:
                            fail_row(task[3][0], 0, task[2][0], exc)
                            failure = failure or exc
                        continue
                    try:
                        successes.append((task, future.result()))
                    except Cancelled as exc:
                        failure = failure or exc
                    except TranslationFailure as exc:
                        fail_row(owner, part, source, exc)
                        quarantined.append((owner, exc.attempts[-1]['reason'] if exc.attempts else str(exc))); streak += 1
                        queue.remove(owner); del states[owner]
                        if streak >= QUARANTINE_STREAK: failure = failure or exc
                    except Exception as exc:
                        fail_row(owner, part, source, exc)
                        failure = failure or exc
                if successes: streak = 0
                record = getattr(self.runtime, 'record', None)
                for (owner, part, source, owners, _), value in successes:
                    if record: record(sum(map(len, source)) if part == -1 else len(source))
                    if part == -1:
                        self.group_stats['groups'] += 1
                        self.group_stats['grouped_rows'] += len(owners)
                        for member, text, translated in zip(owners, source, value):
                            save(member, 0, text, translated)
                            state = states[member]
                            next(state['parts'], None)  # a short row is a single part
                            state['output'].append(translated)
                            advance(member)
                        continue
                    save(owner, part, source, value)
                    state = states[owner]
                    state['output'].append(value)
                    state['context'] = (state['context'] + source)[-self.settings['context_chars']:]
                    advance(owner)
                for task in fallbacks:
                    # Unaligned group: each row is translated on its own with the usual 3 attempts.
                    self.group_stats['fallbacks'] += 1
                    for member in task[3]:
                        advance(member)
                while queue and states[queue[0]]['done']:
                    del states[queue.popleft()]

    def _parallel(self, texts, contexts, lookup, save, save_row):
        from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
        from audio_translate.core.control import stop_mode, Cancelled
        # One ready part per source row; later parts depend only on preceding source.
        generators = [iter(self.parts(text)) for text in texts]
        outputs = [[] for _ in texts]
        previous = list(contexts)
        results = [None] * len(texts)
        ready = []
        def advance(owner):
            while True:
                source = next(generators[owner], None)
                if source is None:
                    results[owner] = ' '.join(value for value in outputs[owner] if value)
                    if save_row: save_row(owner, results[owner])
                    return
                part_id = len(outputs[owner])
                cached = lookup(owner, part_id, source) if lookup else None
                if cached is None and source.strip():
                    ready.append((owner, part_id, source, previous[owner])); return
                outputs[owner].append(cached or '')
                previous[owner] = (previous[owner] + source)[-self.settings['context_chars']:]
        for owner in range(len(texts)): advance(owner)
        if not ready: return results
        self.runtime.tune_between_batches(ready)
        running = {}
        failure = None
        import psutil
        with ThreadPoolExecutor(max_workers=psutil.cpu_count(logical=False) or 1) as executor:
            while ready or running:
                self.runtime.observe()
                if not running and ready and getattr(self.runtime, 'admission_blocked', False):
                    self.runtime.tune_between_batches(ready)
                    # Restarting with fewer allocated slots must actually restore the reserve.
                    if getattr(self.runtime, 'admission_blocked', False):
                        self.runtime.pause_memory()
                mode = stop_mode(self.job_dir)
                if mode == 'cancel':
                    for future in running: future.cancel()
                    raise Cancelled('Processing cancelled by user')
                free = sorted(set(range(self.runtime.slots)) - set(item[1] for item in running.values()))
                free = free[:max(0, self.runtime.slots - len(running))]
                while ready and free and not mode and failure is None and not getattr(self.runtime, 'admission_blocked', False):
                    task = ready.pop(0); slot = free.pop(0)
                    future = executor.submit(self.infer, task[2], task[3], slot)
                    running[future] = (task, slot)
                if not running:
                    if mode: raise Cancelled('Translation paused; completed checkpoints preserved')
                    if failure: raise failure
                    break
                done, _ = wait(running, timeout=.2, return_when=FIRST_COMPLETED)
                self.runtime.observe()
                for future in done:
                    (owner, part_id, source, _), _slot = running.pop(future)
                    try: value = future.result()
                    except BaseException as exc:
                        failure = failure or exc; continue
                    if save: save(owner, part_id, source, value)
                    outputs[owner].append(value)
                    previous[owner] = (previous[owner] + source)[-self.settings['context_chars']:]
                    # Record a finished parent even while other slots are draining.
                    advance(owner)
                if failure and not running: raise failure
                if not running and ready and not stop_mode(self.job_dir):
                    self.runtime.tune_between_batches(ready)
        return results

    @complete_task
    def translate(self, texts):
        return self.translate_checkpointed(texts)
